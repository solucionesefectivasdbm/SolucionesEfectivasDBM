"""
services/receptor_ledger_service.py — Saldo por cuenta bancaria (item 9).

DECISIÓN TÉCNICA: el saldo NUNCA se persiste — se calcula on-read a partir
de `Pago` (recaudo) + `receptor_movimientos` (salidas/correcciones). Esto es
un invariante obligatorio, lección directa de los incidentes de drift de
saldo_capital/saldo_intereses (PRs #30-#33, #36-#39): un total cacheado
eventualmente se desincroniza de su fuente.

`saldos_por_cuenta` hace 2 queries agrupadas (recaudado desde Pago; salidas
+ correcciones desde MovimientoReceptor agrupado también por tipo) — nunca
un loop Python por fila, nunca N+1. `registrar_movimiento` toma un lock de
fila (`SELECT ... FOR UPDATE` sobre `cuentas_bancarias`) antes de leer el
saldo, para serializar salidas concurrentes sobre la misma cuenta. El
statement del lock está extraído en `_select_cuenta_for_update` (función
pura, sin `db`) para poder verificar en un test que compila con `FOR UPDATE`
contra Postgres sin depender de una DB Postgres real — SQLite (la DB de
test) ignora `FOR UPDATE` silenciosamente y daría un falso verde si solo se
probara por ejecución.
"""
import uuid
from decimal import Decimal
from typing import NamedTuple, Optional

from fastapi import HTTPException
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pago import Pago
from app.models.receptor import CuentaBancaria
from app.models.receptor_movimiento import MovimientoReceptor, TipoMovimiento
from app.models.usuario import Usuario
from app.schemas.receptor_movimiento import MovimientoResponse, SaldoCuentaResponse, SaldoReceptorResponse
from app.services.cuenta_bancaria_service import etiqueta_cuenta

CERO = Decimal("0.00")


class SaldoCuenta(NamedTuple):
    """Cómputo puro de saldo para UNA cuenta — sin metadata de presentación
    (etiqueta/es_predeterminada). La usan tanto `saldos_por_receptor` como
    `registrar_movimiento` (chequeo de sobregiro), que no necesitan esa
    metadata."""
    recaudado: Decimal
    salidas: Decimal
    correcciones: Decimal
    saldo: Decimal


def _as_decimal(valor) -> Decimal:
    """Convierte defensivamente el resultado crudo de una agregación SQL a
    Decimal. Nunca `Decimal(float)` directo (artefactos binarios) — ver
    AGENTS.md: todo cálculo financiero usa Decimal, nunca float."""
    if isinstance(valor, Decimal):
        return valor
    return Decimal(str(valor))


async def saldos_por_cuenta(db: AsyncSession, cuenta_ids: list[uuid.UUID]) -> dict[uuid.UUID, SaldoCuenta]:
    """saldo(cuenta) = recaudado - salidas + correcciones. Dos queries
    agrupadas por cuenta_bancaria_id; cuentas sin ningún movimiento no
    aparecen en ninguna de las dos y se completan en 0.00 abajo."""
    if not cuenta_ids:
        return {}

    recaudado_rows = (await db.execute(
        select(
            Pago.cuenta_bancaria_id,
            func.coalesce(func.sum(Pago.capital_pagado + Pago.interes_pagado), CERO),
        )
        .where(
            Pago.cuenta_bancaria_id.in_(cuenta_ids),
            Pago.pagado == True,  # noqa: E712
            Pago.deleted_at == None,  # noqa: E711
        )
        .group_by(Pago.cuenta_bancaria_id)
    )).all()
    recaudado_map = {cid: _as_decimal(total) for cid, total in recaudado_rows}

    movimientos_rows = (await db.execute(
        select(
            MovimientoReceptor.cuenta_bancaria_id,
            MovimientoReceptor.tipo,
            func.coalesce(func.sum(MovimientoReceptor.monto), CERO),
        )
        .where(MovimientoReceptor.cuenta_bancaria_id.in_(cuenta_ids))
        .group_by(MovimientoReceptor.cuenta_bancaria_id, MovimientoReceptor.tipo)
    )).all()
    salidas_map: dict[uuid.UUID, Decimal] = {}
    correcciones_map: dict[uuid.UUID, Decimal] = {}
    for cid, tipo, total in movimientos_rows:
        destino = salidas_map if tipo == TipoMovimiento.salida else correcciones_map
        destino[cid] = _as_decimal(total)

    resultado: dict[uuid.UUID, SaldoCuenta] = {}
    for cid in cuenta_ids:
        recaudado = recaudado_map.get(cid, CERO)
        salidas = salidas_map.get(cid, CERO)
        correcciones = correcciones_map.get(cid, CERO)
        resultado[cid] = SaldoCuenta(
            recaudado=recaudado, salidas=salidas, correcciones=correcciones,
            saldo=recaudado - salidas + correcciones,
        )
    return resultado


async def saldos_por_receptor(
    db: AsyncSession, receptor_ids: list[uuid.UUID]
) -> dict[uuid.UUID, SaldoReceptorResponse]:
    """Resuelve receptor -> cuentas (1 query), delega el cómputo a
    `saldos_por_cuenta`, y arma la respuesta completa (con etiqueta y
    es_predeterminada) agrupada por receptor_id."""
    if not receptor_ids:
        return {}

    cuentas = (await db.execute(
        select(CuentaBancaria).where(CuentaBancaria.receptor_id.in_(receptor_ids))
    )).scalars().all()

    por_receptor: dict[uuid.UUID, list[SaldoCuentaResponse]] = {rid: [] for rid in receptor_ids}
    if cuentas:
        saldos = await saldos_por_cuenta(db, [c.id for c in cuentas])
        for cuenta in cuentas:
            calculo = saldos[cuenta.id]
            por_receptor.setdefault(cuenta.receptor_id, []).append(
                SaldoCuentaResponse(
                    cuenta_bancaria_id=cuenta.id,
                    etiqueta=etiqueta_cuenta(cuenta),
                    es_predeterminada=cuenta.es_predeterminada,
                    recaudado=calculo.recaudado,
                    salidas=calculo.salidas,
                    correcciones=calculo.correcciones,
                    saldo=calculo.saldo,
                )
            )

    return {
        rid: SaldoReceptorResponse(
            receptor_id=rid,
            saldo_total=sum((c.saldo for c in cuentas_receptor), CERO),
            por_cuenta=sorted(cuentas_receptor, key=lambda c: (c.etiqueta, str(c.cuenta_bancaria_id))),
        )
        for rid, cuentas_receptor in por_receptor.items()
    }


async def listar_movimientos(
    db: AsyncSession,
    receptor_id: uuid.UUID,
    cuenta_bancaria_id: Optional[uuid.UUID] = None,
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[MovimientoResponse], int]:
    """Historial paginado, más reciente primero (`created_at DESC`), con
    `id` como tiebreaker único (AGENTS.md: todo ORDER BY paginado termina
    en una columna única). Sigue el patrón de `routers/auditoria.py`."""
    query = (
        select(MovimientoReceptor)
        .join(CuentaBancaria, MovimientoReceptor.cuenta_bancaria_id == CuentaBancaria.id)
        .where(CuentaBancaria.receptor_id == receptor_id)
    )
    if cuenta_bancaria_id:
        query = query.where(MovimientoReceptor.cuenta_bancaria_id == cuenta_bancaria_id)

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar() or 0

    rows = (await db.execute(
        query.add_columns(Usuario.username.label("usuario_username"))
        .join(Usuario, MovimientoReceptor.usuario_id == Usuario.id, isouter=True)
        .order_by(MovimientoReceptor.created_at.desc(), MovimientoReceptor.id)
        .offset((page - 1) * page_size).limit(page_size)
    )).all()

    items = [
        MovimientoResponse(
            id=m.id, cuenta_bancaria_id=m.cuenta_bancaria_id, tipo=m.tipo, monto=m.monto,
            nota=m.nota, usuario_id=m.usuario_id, usuario_nombre=usuario_username, created_at=m.created_at,
        )
        for m, usuario_username in rows
    ]
    return items, total


def _select_cuenta_for_update(cuenta_id: uuid.UUID) -> Select:
    """Extraída como función pura (sin `db`) para poder compilarla en un
    test contra el dialecto Postgres y verificar que `FOR UPDATE` está
    presente — ver docstring del módulo."""
    return select(CuentaBancaria.id).where(CuentaBancaria.id == cuenta_id).with_for_update()


async def registrar_movimiento(
    db: AsyncSession,
    cuenta_id: uuid.UUID,
    tipo: TipoMovimiento,
    monto: Decimal,
    nota: Optional[str],
    usuario_id: uuid.UUID,
) -> MovimientoReceptor:
    """Bloquea la fila de `cuentas_bancarias` (serializa salidas concurrentes
    sobre la misma cuenta), recalcula el saldo bajo el lock, y rechaza la
    salida si excede el saldo disponible. El lock se libera al COMMIT de
    get_db() al final del request. Las correcciones no tienen chequeo de
    sobregiro (decision 4 del design) pero toman el mismo lock para un
    orden consistente."""
    bloqueada = (await db.execute(_select_cuenta_for_update(cuenta_id))).scalar_one_or_none()
    if bloqueada is None:
        raise HTTPException(status_code=404, detail="Cuenta bancaria no encontrada")

    saldo_actual = (await saldos_por_cuenta(db, [cuenta_id]))[cuenta_id].saldo
    if tipo == TipoMovimiento.salida and monto > saldo_actual:
        raise HTTPException(
            status_code=409,
            detail=f"La salida excede el saldo disponible ({saldo_actual})",
        )

    movimiento = MovimientoReceptor(
        cuenta_bancaria_id=cuenta_id, tipo=tipo, monto=monto, nota=nota, usuario_id=usuario_id,
    )
    db.add(movimiento)
    await db.flush()
    return movimiento
