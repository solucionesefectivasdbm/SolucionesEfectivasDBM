"""
services/pago_reparto_service.py — Reparto de un Pago entre destinatarios
(payment-multi-recipient, item 10).

DECISIÓN TÉCNICA: satellite ledger, nunca N filas de Pago (ver docstring de
app.models.pago_reparto). Para un pago pagado, la suma de sus repartos
activos es la ÚNICA fuente de verdad de a dónde fue el dinero (invariante
I1); receptor_ledger_service.saldos_por_cuenta lee de acá, siempre on-read.

PR1 cubrió el caso de UN destinatario:
- `crear_reparto_por_defecto` — fila al 100% creada en los 4 paths de
  registro de pago_service.py.
- `reemplazar_por_cuenta_unica` — sync del PATCH legacy
  `/pagos/{id}/cuenta-bancaria` en un pago ya pagado.

PR2 agrega el reparto explícito multi-destinatario:
- `reemplazar_repartos` — valida y reemplaza el set completo de repartos de
  un pago pagado (`PUT /pagos/{id}/repartos`).
- `cuenta_heredable` / `aplicar_herencia` — decisión 'Inheritance' del
  design: con 1 solo destinatario, la cuenta heredable a la siguiente cuota
  no cambia; con 2+ destinatarios de CUALQUIER tipo (cuenta y/o cliente), la
  siguiente cuota pendiente pierde la cuenta heredada — solo si todavía
  conserva el valor previo (una reasignación manual no se pisa).
- `repartos_por_pago` — lectura batched (GET/PUT del router y el listado de
  `GET /pagos`), sin N+1.
"""
import uuid
from decimal import Decimal
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cliente import Cliente
from app.models.pago import Pago
from app.models.pago_reparto import PagoReparto, TipoDestinatario
from app.models.receptor import CuentaBancaria
from app.services.cuenta_bancaria_service import etiqueta_cuenta
from app.utils.tz import ahora_bogota

CERO = Decimal("0.00")


async def crear_reparto_por_defecto(db: AsyncSession, pago: Pago) -> Optional[PagoReparto]:
    """
    Crea la fila de reparto por defecto al registrar un pago: el 100% de lo
    pagado (capital_pagado + interes_pagado) va a `pago.cuenta_bancaria_id`.

    No crea nada si no hay cuenta asignada o el monto es 0 — el CHECK
    ck_pago_repartos_monto_positivo exige monto > 0, y sin cuenta no hay
    destinatario (invariante I1: solo pagos CON cuenta Y monto > 0 tienen
    reparto). El split explícito multi-destinatario se hace después, vía
    PUT /pagos/{id}/repartos (PR2) — igual que hoy funciona "Modificar
    cuenta" sobre un pago ya registrado.
    """
    monto = pago.capital_pagado + pago.interes_pagado
    if pago.cuenta_bancaria_id is None or monto <= CERO:
        return None

    reparto = PagoReparto(
        pago_id=pago.id,
        tipo_destinatario=TipoDestinatario.cuenta_bancaria,
        cuenta_bancaria_id=pago.cuenta_bancaria_id,
        monto=monto,
    )
    db.add(reparto)
    await db.flush()
    return reparto


def _resumen_reparto(reparto: PagoReparto) -> dict:
    return {
        "id": str(reparto.id),
        "cuenta_bancaria_id": str(reparto.cuenta_bancaria_id) if reparto.cuenta_bancaria_id else None,
        "cliente_id": str(reparto.cliente_id) if reparto.cliente_id else None,
        "monto": str(reparto.monto),
    }


async def _soft_delete_repartos_activos(db: AsyncSession, pago_id: uuid.UUID) -> list[dict]:
    """Borrado lógico (statement Core, no loop de ORM) de todas las filas de
    reparto activas de un pago. Devuelve el resumen de lo borrado para
    auditoría. Compartido por `reemplazar_por_cuenta_unica` acá y, en PR2,
    por `reemplazar_repartos`."""
    ahora = ahora_bogota()
    result = await db.execute(
        update(PagoReparto)
        .where(PagoReparto.pago_id == pago_id, PagoReparto.deleted_at == None)  # noqa: E711
        .values(deleted_at=ahora, updated_at=ahora)
        .returning(PagoReparto)
    )
    return [_resumen_reparto(r) for r in result.scalars().all()]


async def reemplazar_por_cuenta_unica(db: AsyncSession, pago: Pago) -> tuple[list[dict], Optional[dict]]:
    """
    Sincroniza pago_repartos con el PATCH legacy `/pagos/{id}/cuenta-bancaria`:
    en un pago YA PAGADO, borra lógicamente el/los reparto(s) activos y crea
    una única fila al 100% hacia la nueva `pago.cuenta_bancaria_id` (ya
    reasignada por el router antes de esta llamada). Preserva el invariante
    I1 sin la validación multi-destinatario de `reemplazar_repartos` (PR2)
    — este PATCH nunca reparte entre N destinatarios.

    No hace nada en un pago pendiente: antes de pagar, `Pago.cuenta_bancaria_id`
    sigue siendo la única fuente de verdad (todavía no existen repartos).

    Devuelve (repartos_antes, repartos_despues) para el audit trail del
    router — no solo el `cuenta_bancaria_id` escalar, también el estado
    real de la tabla satélite que esta llamada mutó.

    Concurrencia: el router adquiere `SELECT ... FOR UPDATE` sobre el
    crédito antes de llamar acá (`_get_pago_con_credito(lock=True)`), igual
    que `registrar_pago`/`confirmar_excedente`. Eso serializa dos PATCH
    concurrentes sobre el mismo pago y evita que ambos dejen una fila de
    reparto activa cada uno (doble conteo en el ledger).
    """
    if not pago.pagado:
        return [], None
    repartos_antes = await _soft_delete_repartos_activos(db, pago.id)
    nuevo = await crear_reparto_por_defecto(db, pago)
    return repartos_antes, (_resumen_reparto(nuevo) if nuevo else None)


# ─── PR2: reparto explícito multi-destinatario ──────────────────────────────


async def reemplazar_repartos(
    db: AsyncSession, pago: Pago, items: list["RepartoItem"]  # noqa: F821
) -> tuple[list[dict], list[dict]]:
    """
    Reemplaza atómicamente el set completo de repartos activos de un pago
    YA PAGADO (`PUT /pagos/{id}/repartos`). Valida TODO antes de mutar nada
    — si cualquier chequeo falla, no se soft-borra ni se inserta ninguna
    fila (design.md 'Split Integrity Validation': una edición inválida deja
    los valores previos intactos).

    Validaciones, en orden:
    1. El pago debe estar pagado (antes de pagar no se conoce el monto real
       a repartir — se sigue usando `Pago.cuenta_bancaria_id`).
    2. Al menos un destinatario.
    3. Sin destinatario repetido (misma cuenta o mismo cliente dos veces).
    4. Toda `cuenta_bancaria_id` referenciada existe (CuentaBancaria no usa
       soft delete, ver su docstring — solo existencia).
    5. Todo `cliente_id` referenciado existe y no está borrado lógicamente.
    6. La suma de `monto` es EXACTAMENTE igual a
       `capital_pagado + interes_pagado` — igualdad exacta de Decimal, no la
       tolerancia TOL=0.01 de `_validar_split` (design.md 'Sum check': acá
       el ledger tiene que cuadrar al centavo, TOL solo existe por floats de
       entrada de usuario).

    Raises:
        ValueError: con mensaje descriptivo si cualquier validación falla.

    Returns:
        (repartos_antes, repartos_despues) — ambos `list[dict]` con la
        forma de `_resumen_reparto`, listos para auditoría.
    """
    if not pago.pagado:
        raise ValueError("Solo se pueden repartir pagos ya pagados")
    if not items:
        raise ValueError("Debe incluir al menos un destinatario en el reparto")

    vistos: set[tuple[TipoDestinatario, uuid.UUID]] = set()
    for item in items:
        identidad = (item.tipo_destinatario, item.cuenta_bancaria_id or item.cliente_id)
        if identidad in vistos:
            raise ValueError(
                f"El destinatario {identidad[1]} está repetido en el reparto"
            )
        vistos.add(identidad)

    cuenta_ids = {i.cuenta_bancaria_id for i in items if i.cuenta_bancaria_id}
    if cuenta_ids:
        encontradas = set((await db.execute(
            select(CuentaBancaria.id).where(CuentaBancaria.id.in_(cuenta_ids))
        )).scalars().all())
        faltantes = cuenta_ids - encontradas
        if faltantes:
            raise ValueError(f"Cuenta bancaria desconocida: {faltantes.pop()}")

    cliente_ids = {i.cliente_id for i in items if i.cliente_id}
    if cliente_ids:
        encontrados = set((await db.execute(
            select(Cliente.id).where(
                Cliente.id.in_(cliente_ids), Cliente.deleted_at == None  # noqa: E711
            )
        )).scalars().all())
        faltantes_cliente = cliente_ids - encontrados
        if faltantes_cliente:
            raise ValueError(f"Cliente desconocido o eliminado: {faltantes_cliente.pop()}")

    esperado = pago.capital_pagado + pago.interes_pagado
    suma = sum((i.monto for i in items), CERO)
    if suma != esperado:
        raise ValueError(
            f"La suma de los repartos ({suma}) debe ser exactamente igual "
            f"a lo pagado ({esperado})"
        )

    repartos_antes = await _soft_delete_repartos_activos(db, pago.id)

    nuevas_filas = [
        PagoReparto(
            pago_id=pago.id,
            tipo_destinatario=item.tipo_destinatario,
            cuenta_bancaria_id=item.cuenta_bancaria_id,
            cliente_id=item.cliente_id,
            monto=item.monto,
        )
        for item in items
    ]
    db.add_all(nuevas_filas)
    await db.flush()

    repartos_despues = [_resumen_reparto(r) for r in nuevas_filas]
    return repartos_antes, repartos_despues


def cuenta_heredable(repartos: list[dict]) -> Optional[uuid.UUID]:
    """
    Design.md decisión 'Inheritance' (owner decision confirmada 2026-09-22,
    Engram #1079/#1081): con exactamente 1 destinatario, la cuenta que se
    hereda a la siguiente cuota es la de ese destinatario (si es tipo
    cuenta_bancaria) o `None` (si es tipo cliente — no hay cuenta que
    heredar). Con 2 o más destinatarios, sin importar el tipo (2 cuentas,
    1 cuenta + 1 cliente, etc.), siempre `None` — la herencia se bloquea
    porque ya no hay una única cuenta "la" heredable.

    `repartos`: lista de dicts con la forma de `_resumen_reparto`
    (`cuenta_bancaria_id`/`cliente_id` como `str` o `None`) — el `despues`
    que devuelve `reemplazar_repartos`.
    """
    if len(repartos) != 1:
        return None
    cuenta_str = repartos[0].get("cuenta_bancaria_id")
    return uuid.UUID(cuenta_str) if cuenta_str else None


async def aplicar_herencia(
    db: AsyncSession, pago: Pago, repartos_despues: list[dict]
) -> tuple[Optional[uuid.UUID], Optional[uuid.UUID], list[uuid.UUID]]:
    """
    Aplica la decisión de `cuenta_heredable` sobre `pago` (el pago recién
    repartido) y, si corresponde, sobre la siguiente cuota pendiente.

    - `pago.cuenta_bancaria_id` se actualiza a `h`: sin cambio para el caso
      de 1 destinatario (h es la misma cuenta que ya tenía, o la nueva si el
      admin reemplazó el único destinatario por otro), `None` para un
      reparto multi-destinatario — ya no hay "la" cuenta de este pago, la
      fuente de verdad son sus repartos activos (invariante I1).
    - Si `h` es `None` y el pago SÍ tenía una cuenta antes de este reparto
      (si nunca tuvo, no hay nada que "desheredar"), se limpia
      `cuenta_bancaria_id` de la siguiente cuota (`numero_cuota + 1`) del
      mismo crédito, pero SOLO si esa cuota sigue pendiente y su cuenta
      todavía es exactamente la que este pago tenía — una reasignación
      manual posterior no se pisa (tasks.md 2.5).

    Returns:
        (cuenta_anterior, h, ids_de_siguientes_cuotas_afectadas) — para que
        el router audite tanto el cambio en `pago` como, si aplica, el
        cambio en la siguiente cuota.
    """
    anterior = pago.cuenta_bancaria_id
    h = cuenta_heredable(repartos_despues)
    pago.cuenta_bancaria_id = h

    afectados: list[uuid.UUID] = []
    if h is None and anterior is not None:
        resultado = await db.execute(
            update(Pago)
            .where(
                Pago.credito_id == pago.credito_id,
                Pago.numero_cuota == pago.numero_cuota + 1,
                Pago.pagado == False,  # noqa: E712
                Pago.cuenta_bancaria_id == anterior,
                Pago.deleted_at == None,  # noqa: E711
            )
            .values(cuenta_bancaria_id=None)
            .returning(Pago.id)
        )
        afectados = [row[0] for row in resultado.all()]
        await db.flush()

    return anterior, h, afectados


async def repartos_por_pago(
    db: AsyncSession, pago_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[dict]]:
    """
    Lectura batched (sin N+1) de los repartos ACTIVOS de varios pagos a la
    vez: una query a `pago_repartos`, una a `cuentas_bancarias`, una a
    `clientes`. La usan `GET`/`PUT /pagos/{id}/repartos` y el batch de
    `GET /pagos` (design.md).

    Devuelve dicts listos para `RepartoResponse.model_validate(...)` — con
    `etiqueta` ya resuelta (`etiqueta_cuenta(...)` para tipo cuenta_bancaria,
    nombre completo del cliente para tipo cliente).
    """
    if not pago_ids:
        return {}

    filas = (await db.execute(
        select(PagoReparto).where(
            PagoReparto.pago_id.in_(pago_ids), PagoReparto.deleted_at == None,  # noqa: E711
        )
    )).scalars().all()
    if not filas:
        return {}

    cuenta_ids = {f.cuenta_bancaria_id for f in filas if f.cuenta_bancaria_id}
    cliente_ids = {f.cliente_id for f in filas if f.cliente_id}

    cuentas_map: dict[uuid.UUID, CuentaBancaria] = {}
    if cuenta_ids:
        cuentas = (await db.execute(
            select(CuentaBancaria).where(CuentaBancaria.id.in_(cuenta_ids))
        )).scalars().all()
        cuentas_map = {c.id: c for c in cuentas}

    clientes_map: dict[uuid.UUID, Cliente] = {}
    if cliente_ids:
        clientes = (await db.execute(
            select(Cliente).where(Cliente.id.in_(cliente_ids))
        )).scalars().all()
        clientes_map = {c.id: c for c in clientes}

    resultado: dict[uuid.UUID, list[dict]] = {}
    for f in filas:
        if f.tipo_destinatario == TipoDestinatario.cuenta_bancaria:
            cuenta = cuentas_map.get(f.cuenta_bancaria_id)
            etiqueta = etiqueta_cuenta(cuenta) if cuenta else "Cuenta bancaria eliminada"
        else:
            cliente = clientes_map.get(f.cliente_id)
            etiqueta = f"{cliente.nombre} {cliente.apellidos}" if cliente else "Cliente eliminado"
        resultado.setdefault(f.pago_id, []).append({
            "id": f.id,
            "tipo_destinatario": f.tipo_destinatario,
            "cuenta_bancaria_id": f.cuenta_bancaria_id,
            "cliente_id": f.cliente_id,
            "monto": f.monto,
            "etiqueta": etiqueta,
        })
    return resultado
