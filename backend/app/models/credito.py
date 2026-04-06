"""
Modelo Crédito.

DECISIÓN TÉCNICA: tasa_interes_mensual usa NUMERIC(5,4) para almacenar
exactamente 0.0300 (3%). Usamos Decimal en Python para evitar errores
de coma flotante en cálculos financieros — un error de 0.01 COP
acumulado en miles de cuotas puede ser problemático.

numero_cuotas es NULLABLE porque en abono_capital no existe plazo fijo.
abono_minimo es NULLABLE porque solo aplica a abono_capital.
"""
import enum
import uuid
from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, Date, Enum, ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base_model import AuditMixin


class TipoCredito(str, enum.Enum):
    cuota_fija = "cuota_fija"
    abono_capital = "abono_capital"


class Periodicidad(str, enum.Enum):
    mensual = "mensual"
    quincenal = "quincenal"
    semanal = "semanal"
    diario = "diario"


class Credito(AuditMixin, Base):
    __tablename__ = "creditos"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    cliente_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clientes.id"), nullable=False
    )
    numero_credito_cliente: Mapped[str] = mapped_column(
        String(20), unique=True, nullable=False,
        comment="Formato: {cedula_cliente}-CR-{secuencial:03d}"
    )
    tipo_credito: Mapped[TipoCredito] = mapped_column(
        Enum(TipoCredito, name="tipo_credito_enum"), nullable=False
    )
    capital_prestado: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    tasa_interes_mensual: Mapped[Decimal] = mapped_column(
        Numeric(5, 4), nullable=False,
        comment="Ej: 0.0300 para 3% mensual"
    )
    fecha_apertura: Mapped[date] = mapped_column(Date, nullable=False)
    fecha_inicial_pago: Mapped[date] = mapped_column(Date, nullable=False)
    periodicidad: Mapped[Periodicidad] = mapped_column(
        Enum(Periodicidad, name="periodicidad_enum"), nullable=False
    )
    saldo_capital: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    saldo_intereses: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False, default=Decimal("0.00")
    )
    abono_minimo: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(15, 2), nullable=True,
        comment="Solo para abono_capital"
    )
    numero_cuotas: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True,
        comment="Requerido para cuota_fija. NULL para abono_capital"
    )
    calcular_interes_dias_corridos: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    activo: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Relaciones
    cliente: Mapped["Cliente"] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "Cliente", back_populates="creditos"
    )
    pagos: Mapped[list["Pago"]] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "Pago", back_populates="credito", order_by="Pago.numero_cuota"
    )
