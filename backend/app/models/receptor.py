"""
Modelo Receptor y CuentaBancaria.

DECISIÓN TÉCNICA: Receptor y CuentaBancaria están en el mismo archivo porque
CuentaBancaria solo existe en contexto de un Receptor (no tiene sentido
independiente). La relación es 1:N — un receptor puede tener múltiples cuentas.
"""
import enum
import uuid

from sqlalchemy import Enum, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base_model import AuditMixin


class TipoCuenta(str, enum.Enum):
    ahorros = "Ahorros"
    corriente = "Corriente"


class Receptor(AuditMixin, Base):
    __tablename__ = "receptores"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    nombre: Mapped[str] = mapped_column(String(100), nullable=False)
    cedula: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    telefono: Mapped[str] = mapped_column(String(20), nullable=False)

    # Relaciones
    cuentas_bancarias: Mapped[list["CuentaBancaria"]] = relationship(
        "CuentaBancaria", back_populates="receptor", cascade="all, delete-orphan"
    )
    gestores: Mapped[list["Gestor"]] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "Gestor", back_populates="receptor"
    )
    pagos: Mapped[list["Pago"]] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "Pago", back_populates="receptor"
    )


class CuentaBancaria(Base):
    """Sin AuditMixin porque no requiere borrado lógico según los reqs."""
    __tablename__ = "cuentas_bancarias"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    receptor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("receptores.id"), nullable=False
    )
    entidad_bancaria: Mapped[str] = mapped_column(String(100), nullable=False)
    tipo_cuenta: Mapped[TipoCuenta] = mapped_column(
        Enum(TipoCuenta, name="tipo_cuenta_enum"), nullable=False
    )
    numero_cuenta: Mapped[str] = mapped_column(String(30), nullable=False)

    # Relaciones
    receptor: Mapped["Receptor"] = relationship("Receptor", back_populates="cuentas_bancarias")
