"""
Modelo Gestor — perfil extendido de un Usuario con rol 'gestor'.

DECISIÓN TÉCNICA: Gestor está separado de Usuario porque tiene atributos
propios de negocio (cédula, dirección, receptor asignado) que no aplican
a otros roles. La relación Usuario→Gestor es 1:1 (uselist=False).
El campo receptor_id es NULLABLE porque un gestor puede existir sin
receptor asignado todavía.
"""
import uuid
from typing import Optional

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base_model import AuditMixin


class Gestor(AuditMixin, Base):
    __tablename__ = "gestores"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        unique=True,
        nullable=False,
    )
    cedula: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    nombre: Mapped[str] = mapped_column(String(100), nullable=False)
    apellidos: Mapped[str] = mapped_column(String(100), nullable=False)
    telefono: Mapped[str] = mapped_column(String(20), nullable=False)
    direccion: Mapped[str] = mapped_column(Text, nullable=False)
    correo_electronico: Mapped[str] = mapped_column(String(150), unique=True, nullable=False)
    receptor_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("receptores.id"),
        nullable=True,
    )

    # Relaciones
    usuario: Mapped["Usuario"] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "Usuario", back_populates="gestor_perfil"
    )
    receptor: Mapped[Optional["Receptor"]] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "Receptor", back_populates="gestores"
    )
    clientes: Mapped[list["Cliente"]] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "Cliente", back_populates="gestor"
    )
