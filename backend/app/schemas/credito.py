import uuid
from datetime import date
from decimal import Decimal
from typing import Optional
from pydantic import BaseModel, field_validator, model_validator

from app.models.credito import TipoCredito, Periodicidad


class CreditoCreate(BaseModel):
    cliente_id: uuid.UUID
    tipo_credito: TipoCredito
    capital_prestado: Decimal
    tasa_interes_mensual: Decimal
    fecha_apertura: date
    fecha_inicial_pago: date
    periodicidad: Periodicidad
    numero_cuotas: Optional[int] = None
    abono_minimo: Optional[Decimal] = None
    calcular_interes_dias_corridos: bool = False

    @field_validator("capital_prestado")
    @classmethod
    def validar_capital(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("El capital prestado debe ser mayor a cero")
        return v

    @field_validator("tasa_interes_mensual")
    @classmethod
    def validar_tasa(cls, v: Decimal) -> Decimal:
        if v <= 0 or v >= 1:
            raise ValueError("La tasa debe ser un valor entre 0 y 1 (ej: 0.0300 para 3%)")
        return v

    @model_validator(mode="after")
    def validar_reglas_negocio(self) -> "CreditoCreate":
        # cuota_fija requiere numero_cuotas
        if self.tipo_credito == TipoCredito.cuota_fija and not self.numero_cuotas:
            raise ValueError("numero_cuotas es obligatorio para crédito de cuota fija")

        # abono_capital solo acepta mensual o quincenal
        if self.tipo_credito == TipoCredito.abono_capital and self.periodicidad not in (
            Periodicidad.mensual, Periodicidad.quincenal
        ):
            raise ValueError("Abono a capital solo permite periodicidad mensual o quincenal")

        # fecha_inicial_pago no puede ser anterior a fecha_apertura
        if self.fecha_inicial_pago < self.fecha_apertura:
            raise ValueError("La fecha inicial de pago no puede ser anterior a la fecha de apertura")

        return self


class CreditoUpdate(BaseModel):
    """Solo Admin puede modificar estos campos."""
    capital_prestado: Optional[Decimal] = None
    tasa_interes_mensual: Optional[Decimal] = None
    fecha_pago_activo: Optional[date] = None  # Recalcula todo el ciclo


class CreditoResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    cliente_id: uuid.UUID
    numero_credito_cliente: str
    tipo_credito: TipoCredito
    capital_prestado: Decimal
    tasa_interes_mensual: Decimal
    fecha_apertura: date
    fecha_inicial_pago: date
    periodicidad: Periodicidad
    saldo_capital: Decimal
    saldo_intereses: Decimal
    abono_minimo: Optional[Decimal]
    numero_cuotas: Optional[int]
    calcular_interes_dias_corridos: bool
    activo: bool
