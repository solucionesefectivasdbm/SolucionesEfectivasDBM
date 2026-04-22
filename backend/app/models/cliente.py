"""
Modelo Cliente.

DECISIÓN TÉCNICA: El campo al_dia es desnormalizado (podría calcularse
desde los pagos) pero los requerimientos lo piden explícito para que
el Registrador lo pueda marcar manualmente sin depender del cálculo
automático. Esto da flexibilidad operativa al negocio.
"""
import uuid
from typing import Optional

from sqlalchemy import Boolean, ForeignKey, Index, String, Text, text as sa_text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base_model import AuditMixin


class Cliente(AuditMixin, Base):
    __tablename__ = "clientes"
    __table_args__ = (
        Index(
            "uq_clientes_cedula_active",
            "cedula",
            unique=True,
            postgresql_where=sa_text("deleted_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    gestor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("gestores.id"),
        nullable=False,
    )
    nombre: Mapped[str] = mapped_column(String(100), nullable=False)
    apellidos: Mapped[str] = mapped_column(String(100), nullable=False)
    cedula: Mapped[str] = mapped_column(String(20), nullable=False)
    telefono: Mapped[str] = mapped_column(String(20), nullable=False)
    direccion: Mapped[str] = mapped_column(Text, nullable=False)
    correo_electronico: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    afiliacion_militar: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    al_dia: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Relaciones
    gestor: Mapped["Gestor"] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "Gestor", back_populates="clientes"
    )
    creditos: Mapped[list["Credito"]] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "Credito", back_populates="cliente"
    )
