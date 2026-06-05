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
    fecha_inicial_pago_2: Optional[date] = None  # segunda fecha de pago, SOLO quincenal
    periodicidad: Periodicidad
    numero_cuotas: Optional[int] = None
    abono_minimo: Optional[Decimal] = None
    calcular_interes_dias_corridos: bool = False

    # Derived anchor fields (populated by model_validator, not from payload)
    anchor_dia_1: Optional[int] = None
    anchor_dia_2: Optional[int] = None

    @field_validator("anchor_dia_1", "anchor_dia_2")
    @classmethod
    def validar_anchor_dia(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and not (1 <= v <= 31):
            raise ValueError("anchor_dia debe estar entre 1 y 31")
        return v

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

        # Quincenal: requires second date, must be distinct day, derive anchors
        if self.periodicidad == Periodicidad.quincenal:
            if self.fecha_inicial_pago_2 is None:
                raise ValueError("quincenal requiere la segunda fecha de pago (fecha_inicial_pago_2)")
            if self.fecha_inicial_pago_2 < self.fecha_apertura:
                raise ValueError("La segunda fecha de pago no puede ser anterior a la apertura")
            if self.fecha_inicial_pago_2.day == self.fecha_inicial_pago.day:
                raise ValueError("Las dos fechas de pago deben caer en dias distintos del mes")
            # Normalize: d1 < d2
            d1, d2 = sorted([self.fecha_inicial_pago.day, self.fecha_inicial_pago_2.day])
            self.anchor_dia_1 = d1
            self.anchor_dia_2 = d2
        elif self.periodicidad == Periodicidad.mensual:
            # Mensual: derive anchor from fecha_inicial_pago.day; ignore fecha_inicial_pago_2
            self.anchor_dia_1 = self.fecha_inicial_pago.day
            self.anchor_dia_2 = None
        else:
            # semanal/diario: no anchors
            self.anchor_dia_1 = None
            self.anchor_dia_2 = None

        return self


class CreditoUpdate(BaseModel):
    """Solo Admin puede modificar estos campos."""
    capital_prestado: Optional[Decimal] = None
    tasa_interes_mensual: Optional[Decimal] = None
    abono_minimo: Optional[Decimal] = None  # Solo aplica a abono_capital
    fecha_pago_activo: Optional[date] = None  # Recalcula todo el ciclo

    @field_validator("abono_minimo")
    @classmethod
    def validar_abono_minimo(cls, v: Optional[Decimal]) -> Optional[Decimal]:
        if v is not None and v < 0:
            raise ValueError("El abono mínimo no puede ser negativo")
        return v


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
