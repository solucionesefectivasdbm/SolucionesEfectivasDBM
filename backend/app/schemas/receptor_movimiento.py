"""schemas/receptor_movimiento.py — Ledger de salidas/correcciones (item 9)."""
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.models.receptor_movimiento import TipoMovimiento


class MovimientoCreate(BaseModel):
    """Payload para registrar una `salida`. `monto` debe ser estrictamente
    positivo — el rechazo por sobregiro (monto > saldo) ocurre en el
    service, no aquí."""

    monto: Decimal = Field(gt=0)
    nota: Optional[str] = Field(default=None, max_length=500)


class CorreccionCreate(BaseModel):
    """Payload para registrar una `correccion`. Signo libre (positivo o
    negativo), pero nunca cero — un ajuste de cero no tiene efecto y no
    debe ensuciar el historial."""

    monto: Decimal
    nota: Optional[str] = Field(default=None, max_length=500)

    @field_validator("monto")
    @classmethod
    def monto_no_cero(cls, v: Decimal) -> Decimal:
        if v == 0:
            raise ValueError("El monto de la corrección no puede ser cero")
        return v


class MovimientoResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    cuenta_bancaria_id: uuid.UUID
    tipo: TipoMovimiento
    monto: Decimal
    nota: Optional[str] = None
    usuario_id: uuid.UUID
    usuario_nombre: Optional[str] = None
    created_at: datetime


class SaldoCuentaResponse(BaseModel):
    model_config = {"from_attributes": True}

    cuenta_bancaria_id: uuid.UUID
    etiqueta: str
    es_predeterminada: bool
    recaudado: Decimal
    salidas: Decimal
    correcciones: Decimal
    saldo: Decimal


class SaldoReceptorResponse(BaseModel):
    receptor_id: uuid.UUID
    saldo_total: Decimal
    por_cuenta: list[SaldoCuentaResponse] = []
