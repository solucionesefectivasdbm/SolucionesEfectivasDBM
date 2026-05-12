import uuid
from datetime import date
from decimal import Decimal
from typing import Optional
from pydantic import BaseModel, field_validator

from app.models.pago import TipoCuota, DestinoExcedente


class PagoResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    credito_id: uuid.UUID
    numero_cuota: int
    tipo_cuota: TipoCuota
    monto_a_pagar: Decimal
    capital_a_pagar: Decimal
    interes_a_pagar: Decimal
    capital_pagado: Decimal
    interes_pagado: Decimal
    momento: str
    fecha_maxima: date
    receptor_id: Optional[uuid.UUID]
    pagado: bool
    validado_recaudador: bool
    fecha_pago_real: Optional[date]
    es_excedente_a: Optional[DestinoExcedente]
    es_ultimo_pago: bool
    tipo_validacion: Optional[str] = None
    cliente_nombre: Optional[str] = None
    numero_credito_cliente: Optional[str] = None
    # Campos virtuales: solo presentes en filas proyectadas (no existen en BD)
    es_proyectada: bool = False
    razon_bloqueo: Optional[str] = None


class RegistrarPagoRequest(BaseModel):
    """Registrar monto pagado de una cuota (Registrador / Admin)."""
    capital_pagado: Decimal
    interes_pagado: Decimal

    @field_validator("capital_pagado", "interes_pagado")
    @classmethod
    def validar_montos(cls, v: Decimal) -> Decimal:
        if v < 0:
            raise ValueError("El monto no puede ser negativo")
        return v


class RegistrarPagoResponse(BaseModel):
    """
    Respuesta al registrar pago. Si hay excedente, el frontend
    muestra el modal de decisión antes de confirmar.
    """
    pago: PagoResponse
    requiere_decision: bool = False
    excedente: Optional[Decimal] = None
    mensaje: str = "Pago registrado correctamente"


class ConfirmarExcedenteRequest(BaseModel):
    destino_excedente: DestinoExcedente


class PagoNoProgramadoRequest(BaseModel):
    monto: Decimal
    destino: DestinoExcedente  # capital o intereses
    fecha_pago: date

    @field_validator("monto")
    @classmethod
    def validar_monto(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("El monto debe ser mayor a cero")
        return v


class ValidarPagoRequest(BaseModel):
    """Recaudador / Admin: validación con tipo declarado."""
    tipo_validacion: Optional[str] = None  # "completo" | "incompleto" | "con_excedente"

    @field_validator("tipo_validacion")
    @classmethod
    def validar_tipo(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in ("completo", "incompleto", "con_excedente"):
            raise ValueError("tipo_validacion debe ser completo, incompleto o con_excedente")
        return v


class ModificarFechaPagoRequest(BaseModel):
    """Recaudador: modifica fecha_maxima de un pago individual."""
    fecha_maxima: date


class ModificarReceptorPagoRequest(BaseModel):
    """Recaudador / Admin: modifica receptor de un pago individual."""
    receptor_id: uuid.UUID


class PagoFiltros(BaseModel):
    """Filtros para el módulo de pagos (año, mes, momento son obligatorios)."""
    anio: int
    mes: int
    momento: str
    gestor_id: Optional[uuid.UUID] = None
    cliente_id: Optional[uuid.UUID] = None
    receptor_id: Optional[uuid.UUID] = None
    busqueda: Optional[str] = None
    page: int = 1
    page_size: int = 50

    @field_validator("momento")
    @classmethod
    def validar_momento(cls, v: str) -> str:
        if v not in ("m1", "m2", "m3", "m4", "m5"):
            raise ValueError("El momento debe ser m1, m2, m3, m4 o m5")
        return v

    @field_validator("mes")
    @classmethod
    def validar_mes(cls, v: int) -> int:
        if not (1 <= v <= 12):
            raise ValueError("El mes debe estar entre 1 y 12")
        return v
