"""
Modelo MovimientoReceptor — ledger inmutable de salidas y correcciones de
efectivo por cuenta bancaria (receiver-cash-balance, item 9).

DECISIÓN TÉCNICA: Sin AuditMixin, igual que AuditLog — no tiene updated_at
ni deleted_at porque la fila es inmutable (append-only). Un error se corrige
con una correccion compensatoria, nunca editando o borrando la fila
original. El saldo NUNCA se persiste aquí ni en Receptor/CuentaBancaria:
se calcula on-read en receptor_ledger_service. Esto es un invariante
obligatorio — lección directa de los incidentes de drift de
saldo_capital/saldo_intereses (PRs #30-#33, #36-#39): un total cacheado
eventualmente se desincroniza de su fuente.

El CHECK constraint fuerza el signo de `monto` según `tipo` en la propia DB:
salida siempre > 0, correccion siempre != 0 (positiva o negativa).
"""
import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import CheckConstraint, Enum, ForeignKey, Index, Numeric, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.utils.tz import ahora_bogota


class TipoMovimiento(str, enum.Enum):
    salida = "salida"
    correccion = "correccion"


class MovimientoReceptor(Base):
    """Sin AuditMixin: fila inmutable, append-only (ver docstring del módulo)."""

    __tablename__ = "receptor_movimientos"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    cuenta_bancaria_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cuentas_bancarias.id"), nullable=False
    )
    tipo: Mapped[TipoMovimiento] = mapped_column(
        Enum(TipoMovimiento, name="tipo_movimiento_receptor_enum"), nullable=False
    )
    monto: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    nota: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    usuario_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(default=ahora_bogota, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "(tipo = 'salida' AND monto > 0) OR (tipo = 'correccion' AND monto <> 0)",
            name="ck_receptor_movimientos_monto_por_tipo",
        ),
        Index("ix_receptor_movimientos_cuenta_bancaria_id", "cuenta_bancaria_id"),
        Index("ix_receptor_movimientos_created_at", "created_at"),
    )

    # Relaciones
    usuario: Mapped["Usuario"] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "Usuario", back_populates="movimientos_receptor"
    )
