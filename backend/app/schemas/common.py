"""Schemas compartidos: paginación, audit log, reportes."""
import uuid
from datetime import datetime
from typing import Generic, Optional, TypeVar
from pydantic import BaseModel

from app.models.audit_log import AccionAudit

T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    """Respuesta paginada estándar para todos los listados."""
    items: list[T]
    total: int
    page: int
    page_size: int
    pages: int


class AuditLogResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    entidad: str
    entidad_id: uuid.UUID
    accion: AccionAudit
    campo_modificado: Optional[str]
    valor_anterior: Optional[str]
    valor_nuevo: Optional[str]
    usuario_id: uuid.UUID
    usuario_username: Optional[str] = None
    fecha_accion: datetime
    ip_origen: str


class ReporteDetalleGestor(BaseModel):
    gestor_id: uuid.UUID
    gestor_nombre: str
    total_recaudado: float
    total_intereses: float
    total_capital: float


class ReporteDetalleCuenta(BaseModel):
    """Sub-desglose por cuenta bancaria dentro de un receptor (PR2b lo puebla)."""
    cuenta_bancaria_id: uuid.UUID
    etiqueta: str
    es_predeterminada: bool
    total_recaudado: float
    total_intereses: float
    total_capital: float


class ReporteDetalleReceptor(BaseModel):
    receptor_id: uuid.UUID
    receptor_nombre: str
    total_recaudado: float
    total_intereses: float
    total_capital: float
    # Poblado a partir de PR2b (receiver-bank-account-assignment); vacío hasta entonces.
    por_cuenta: list[ReporteDetalleCuenta] = []


class ReporteResponse(BaseModel):
    anio: int
    mes: int
    momento: str
    total_recaudado: float
    total_intereses: float
    total_capital: float
    por_gestor: list[ReporteDetalleGestor]
    por_receptor: list[ReporteDetalleReceptor]
