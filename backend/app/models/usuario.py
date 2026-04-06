"""
Modelo Usuario — representa a las personas que operan el sistema.

DECISIÓN TÉCNICA: El campo tipo_usuario usa un Enum de Python (no solo string)
para que SQLAlchemy valide los valores tanto en Python como en la DB.
El campo activo permite deshabilitar usuarios sin borrarlos.
"""
import enum
import uuid

from sqlalchemy import Boolean, Enum, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base_model import AuditMixin


class TipoUsuario(str, enum.Enum):
    admin = "admin"
    registrador = "registrador"
    recaudador = "recaudador"
    gestor = "gestor"


class Usuario(AuditMixin, Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    telefono: Mapped[str] = mapped_column(String(20), nullable=False)
    tipo_usuario: Mapped[TipoUsuario] = mapped_column(
        Enum(TipoUsuario, name="tipo_usuario_enum"), nullable=False
    )
    activo: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    must_change_password: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False,
        comment="True cuando el Admin asignó contraseña temporal"
    )

    # Relaciones
    gestor_perfil: Mapped["Gestor"] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "Gestor", back_populates="usuario", uselist=False
    )
    audit_logs: Mapped[list["AuditLog"]] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "AuditLog", back_populates="usuario"
    )
