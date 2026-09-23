"""
Modelo PagoReparto — reparto de un Pago entre N destinatarios (cuentas
bancarias y/o clientes), payment-multi-recipient (item 10).

DECISIÓN TÉCNICA: satellite table, nunca N filas de Pago — el invariante
"1 Pago = 1 cuota" que usan mora, cierre de crédito y generar_siguiente_cuota
se mantiene intacto (ver design.md, evita la clase de regresión de
PRs #30-#39). Para un Pago pagado, la suma de sus repartos activos es la
ÚNICA fuente de verdad de a dónde fue el dinero (invariante I1); el ledger
de item 9 (receptor_ledger_service.saldos_por_cuenta) lee de acá, siempre
on-read — nunca un total cacheado.

A diferencia de MovimientoReceptor (inmutable/append-only), PagoReparto SÍ
usa AuditMixin: el owner decidió que los repartos son directamente
editables/borrables sin flujo de corrección tipo receptor_movimientos
(design decision 2) — el borrado es lógico (`deleted_at`), nunca físico.

El CHECK constraint fuerza en la propia DB que monto > 0 y que exactamente
uno de cuenta_bancaria_id/cliente_id esté presente, según tipo_destinatario
— un destinatario tipo cliente NUNCA crea un Credito (informativo/contable
solamente, ver proposal.md).
"""
import enum
import uuid
from decimal import Decimal
from typing import Optional

from sqlalchemy import CheckConstraint, Enum, ForeignKey, Index, Numeric
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base_model import AuditMixin


class TipoDestinatario(str, enum.Enum):
    cuenta_bancaria = "cuenta_bancaria"
    cliente = "cliente"


class PagoReparto(AuditMixin, Base):
    __tablename__ = "pago_repartos"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    pago_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pagos.id"), nullable=False
    )
    tipo_destinatario: Mapped[TipoDestinatario] = mapped_column(
        Enum(TipoDestinatario, name="tipo_destinatario_reparto_enum"), nullable=False
    )
    cuenta_bancaria_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cuentas_bancarias.id"), nullable=True
    )
    cliente_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clientes.id"), nullable=True
    )
    monto: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)

    __table_args__ = (
        CheckConstraint("monto > 0", name="ck_pago_repartos_monto_positivo"),
        CheckConstraint(
            "(tipo_destinatario = 'cuenta_bancaria' AND cuenta_bancaria_id IS NOT NULL AND cliente_id IS NULL) "
            "OR (tipo_destinatario = 'cliente' AND cliente_id IS NOT NULL AND cuenta_bancaria_id IS NULL)",
            name="ck_pago_repartos_destinatario",
        ),
        Index("ix_pago_repartos_pago_id", "pago_id"),
        Index("ix_pago_repartos_cuenta_bancaria_id", "cuenta_bancaria_id"),
    )

    # Relaciones
    pago: Mapped["Pago"] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "Pago", back_populates="repartos"
    )
