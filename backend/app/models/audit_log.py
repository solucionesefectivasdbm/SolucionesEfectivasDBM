"""
Modelo AuditLog — registro inmutable de todas las operaciones críticas.

DECISIÓN TÉCNICA: audit_log NO hereda AuditMixin porque:
1. No tiene deleted_at (el historial es permanente, nunca se borra)
2. No tiene updated_at (cada registro es inmutable por definición)
Solo tiene fecha_accion que el servicio de auditoría setea explícitamente.

ip_origen es VARCHAR(45) para soportar IPv6 (máx 39 chars + margen).
"""
import enum
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class AccionAudit(str, enum.Enum):
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    DELETE = "DELETE"


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    entidad: Mapped[str] = mapped_column(String(50), nullable=False)
    entidad_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    accion: Mapped[AccionAudit] = mapped_column(
        Enum(AccionAudit, name="accion_audit_enum"), nullable=False
    )
    campo_modificado: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    valor_anterior: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    valor_nuevo: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    usuario_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    fecha_accion: Mapped[datetime] = mapped_column(nullable=False)
    ip_origen: Mapped[str] = mapped_column(String(45), nullable=False)

    # Relaciones
    usuario: Mapped["Usuario"] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "Usuario", back_populates="audit_logs"
    )
