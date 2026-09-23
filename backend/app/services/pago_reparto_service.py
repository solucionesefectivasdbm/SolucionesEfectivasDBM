"""
services/pago_reparto_service.py — Reparto de un Pago entre destinatarios
(payment-multi-recipient, item 10).

DECISIÓN TÉCNICA: satellite ledger, nunca N filas de Pago (ver docstring de
app.models.pago_reparto). Para un pago pagado, la suma de sus repartos
activos es la ÚNICA fuente de verdad de a dónde fue el dinero (invariante
I1); receptor_ledger_service.saldos_por_cuenta lee de acá, siempre on-read.

PR1 solo cubre el caso de UN destinatario:
- `crear_reparto_por_defecto` — fila al 100% creada en los 4 paths de
  registro de pago_service.py.
- `reemplazar_por_cuenta_unica` — sync del PATCH legacy
  `/pagos/{id}/cuenta-bancaria` en un pago ya pagado.

El reparto explícito multi-destinatario, con validación completa de suma
exacta / duplicados / existencia (`reemplazar_repartos`), y la lectura
batched (`repartos_por_pago`) llegan en PR2 — ver design.md.
"""
import uuid
from decimal import Decimal
from typing import Optional

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pago import Pago
from app.models.pago_reparto import PagoReparto, TipoDestinatario
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
