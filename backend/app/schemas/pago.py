import uuid
from datetime import date
from decimal import Decimal
from typing import Optional
from pydantic import BaseModel, field_validator

from app.models.credito import TipoCredito
from app.models.pago import TipoCuota, DestinoExcedente
from app.schemas.pago_reparto import RepartoResponse
from app.schemas.receptor import CuentaBancariaResumen


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
    # atraso-pago-aplazado-corte-original: corte de mora inmutable del
    # momento original de este pago (design D2/D3). Se fija al crear el pago
    # y no se mueve ante un aplazamiento puntual de `fecha_maxima` — ver
    # `app.utils.momentos.flags_mora`. Optional/None: filas virtuales de
    # `_calcular_virtuales` y sitios legacy que no lo seleccionan todavía.
    fecha_maxima_original: Optional[date] = None
    cuenta_bancaria_id: Optional[uuid.UUID]
    cuenta_bancaria: Optional[CuentaBancariaResumen] = None
    pagado: bool
    validado_recaudador: bool
    fecha_pago_real: Optional[date]
    es_excedente_a: Optional[DestinoExcedente]
    es_ultimo_pago: bool
    tipo_validacion: Optional[str] = None
    veces_aplazado: int = 0
    cliente_nombre: Optional[str] = None
    numero_credito_cliente: Optional[str] = None
    # Campos virtuales: solo presentes en filas proyectadas (no existen en BD)
    es_proyectada: bool = False
    razon_bloqueo: Optional[str] = None
    # Tipo de crédito del padre — permite al frontend distinguir la cuota de
    # interés `cuota_fija` (capital saldado) de la `abono_capital` (ciclo
    # alternado, capital NO saldado). Optional/None: ver design decision 1,
    # `Pago` no tiene esta columna; solo se completa en filas de listado.
    tipo_credito: Optional[TipoCredito] = None
    # Overdue evaluation (scheduled-overdue-evaluation): computados por el
    # router en el momento de construir la fila (ver `app.utils.momentos.flags_mora`). Default
    # False cubre pagados, proyectados, y cualquier otro sitio de
    # model_validate(ORM) que no recalcula estos flags.
    vencido: bool = False
    en_mora: bool = False
    # payment-multi-recipient (item 10, PR2): destinatarios del reparto de
    # este pago. Vacío por default — cubre filas virtuales/proyectadas (que
    # nunca tienen reparto) y cualquier sitio que no lo cargue explícito
    # (GET /pagos lo carga batched; ver pago_reparto_service.repartos_por_pago).
    repartos: list[RepartoResponse] = []

    @field_validator("veces_aplazado", mode="before")
    @classmethod
    def _veces_aplazado_none_a_cero(cls, v):
        # ORM instances not yet flushed have no Python-side column default
        # applied — treat unset (None) as 0, the same value the DB would
        # assign on INSERT (server_default='0').
        return 0 if v is None else v


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
    es_aplazamiento: bool = False


class ModificarCuentaBancariaPagoRequest(BaseModel):
    """Recaudador / Admin: modifica la cuenta bancaria de un pago individual."""
    cuenta_bancaria_id: uuid.UUID


class PagoFiltros(BaseModel):
    """Filtros para el módulo de pagos (año, mes, momento son obligatorios)."""
    anio: int
    mes: int
    momento: str
    gestor_id: Optional[uuid.UUID] = None
    cliente_id: Optional[uuid.UUID] = None
    receptor_id: Optional[uuid.UUID] = None
    cuenta_bancaria_id: Optional[uuid.UUID] = None
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
