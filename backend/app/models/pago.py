"""
Modelo Pago (cuota).

DECISIÓN TÉCNICA: momento usa VARCHAR(5) en lugar de Enum porque m1..m5
son simples etiquetas de período — no necesitan validación de DB y
son fáciles de extender. El campo es calculado al crear el pago según
la fecha_maxima.

es_excedente_a registra qué saldo se redujo cuando el cliente pagó
más de lo esperado. Esto es necesario para el historial de auditoría.
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


class TipoCuota(str, enum.Enum):
    programada = "programada"
    no_programada = "no_programada"
    # Para abono_capital:
    interes = "interes"
    abono = "abono"


class DestinoExcedente(str, enum.Enum):
    capital = "capital"
    intereses = "intereses"


class Pago(AuditMixin, Base):
    __tablename__ = "pagos"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    credito_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("creditos.id"), nullable=False
    )
    numero_cuota: Mapped[int] = mapped_column(Integer, nullable=False)
    tipo_cuota: Mapped[TipoCuota] = mapped_column(
        Enum(TipoCuota, name="tipo_cuota_enum"), nullable=False
    )
    monto_a_pagar: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    capital_a_pagar: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False, default=Decimal("0.00")
    )
    interes_a_pagar: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False, default=Decimal("0.00")
    )
    capital_pagado: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False, default=Decimal("0.00")
    )
    interes_pagado: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False, default=Decimal("0.00")
    )
    momento: Mapped[str] = mapped_column(String(5), nullable=False)
    fecha_maxima: Mapped[date] = mapped_column(Date, nullable=False)
    receptor_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("receptores.id"), nullable=True
    )
    pagado: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    validado_recaudador: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    fecha_pago_real: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    es_excedente_a: Mapped[Optional[DestinoExcedente]] = mapped_column(
        Enum(DestinoExcedente, name="destino_excedente_enum"), nullable=True
    )
    es_ultimo_pago: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False,
        comment="True cuando es la última cuota de un crédito cuota_fija"
    )

    # Relaciones
    credito: Mapped["Credito"] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "Credito", back_populates="pagos"
    )
    receptor: Mapped[Optional["Receptor"]] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "Receptor", back_populates="pagos"
    )
