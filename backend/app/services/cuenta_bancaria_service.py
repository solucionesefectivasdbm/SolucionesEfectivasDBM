"""
services/cuenta_bancaria_service.py — Regla de cuenta predeterminada.

DECISIÓN TÉCNICA (design decision 3): la lógica de la cuenta predeterminada
vive aquí porque la reutilizan receptores.py, gestores.py y pagos.py. El
cambio de predeterminada usa dos statements Core explícitos en orden (clear
old -> set new) porque el índice único parcial se valida por statement y el
orden de flush del ORM no está garantizado (decision 2).
"""
import uuid

from fastapi import HTTPException
from sqlalchemy import exists, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.receptor import CuentaBancaria


async def obtener_cuenta_o_404(db: AsyncSession, cuenta_id: uuid.UUID) -> CuentaBancaria:
    result = await db.execute(
        select(CuentaBancaria).where(CuentaBancaria.id == cuenta_id)
        .options(selectinload(CuentaBancaria.receptor))
    )
    cuenta = result.scalar_one_or_none()
    if not cuenta:
        raise HTTPException(status_code=404, detail="Cuenta bancaria no encontrada")
    return cuenta


async def sin_predeterminada(db: AsyncSession, receptor_id: uuid.UUID) -> bool:
    """True si el receptor no tiene ninguna cuenta predeterminada (incluye
    receptores legacy con cuentas anteriores al backfill, todas en False)."""
    existe_default = (await db.execute(
        select(
            exists().where(
                CuentaBancaria.receptor_id == receptor_id,
                CuentaBancaria.es_predeterminada == True,  # noqa: E712
            )
        )
    )).scalar()
    return not existe_default


async def marcar_predeterminada(
    db: AsyncSession, receptor_id: uuid.UUID, cuenta_id: uuid.UUID
) -> CuentaBancaria:
    cuenta = (await db.execute(
        select(CuentaBancaria).where(
            CuentaBancaria.id == cuenta_id,
            CuentaBancaria.receptor_id == receptor_id,
        )
    )).scalar_one_or_none()
    if not cuenta:
        raise HTTPException(status_code=404, detail="Cuenta bancaria no encontrada")

    # Decision 2: dos statements Core explícitos en orden — clear old, set new.
    # Nunca depender del orden de flush del ORM (el índice único parcial se
    # valida por statement, no de forma diferida).
    await db.execute(
        update(CuentaBancaria)
        .where(CuentaBancaria.receptor_id == receptor_id, CuentaBancaria.id != cuenta_id)
        .values(es_predeterminada=False)
    )
    await db.execute(
        update(CuentaBancaria)
        .where(CuentaBancaria.id == cuenta_id)
        .values(es_predeterminada=True)
    )
    await db.flush()
    await db.refresh(cuenta)
    return cuenta


def etiqueta_cuenta(c: CuentaBancaria) -> str:
    return f"{c.entidad_bancaria} · {c.tipo_cuenta.value} · {c.numero_cuenta}"
