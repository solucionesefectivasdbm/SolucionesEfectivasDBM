"""
tests/test_models.py — Tests for ORM model fields.

RED phase: these tests verify the Credito model exposes anchor_dia_1 and
anchor_dia_2 as nullable integer attributes. They fail before A2 is applied.
"""
import uuid
from datetime import date, datetime
from decimal import Decimal

import pytest

from app.models.credito import Credito, Periodicidad, TipoCredito


def _make_credito(**kwargs) -> Credito:
    """Minimal Credito instance for ORM-level attribute checks (no DB)."""
    defaults = dict(
        id=uuid.uuid4(),
        cliente_id=uuid.uuid4(),
        numero_credito_cliente="TEST-CR-001",
        tipo_credito=TipoCredito.cuota_fija,
        capital_prestado=Decimal("1000000.00"),
        tasa_interes_mensual=Decimal("0.0300"),
        fecha_apertura=date(2026, 1, 1),
        fecha_inicial_pago=date(2026, 1, 20),
        periodicidad=Periodicidad.mensual,
        saldo_capital=Decimal("1000000.00"),
        saldo_intereses=Decimal("0.00"),
        numero_cuotas=12,
        calcular_interes_dias_corridos=False,
        activo=True,
        created_at=datetime(2026, 1, 1),
        updated_at=datetime(2026, 1, 1),
    )
    defaults.update(kwargs)
    return Credito(**defaults)


class TestCreditoAnchorColumns:
    """REQ-1.1: Credito model exposes anchor_dia_1 and anchor_dia_2."""

    def test_mensual_anchor_dia_1_equals_fecha_day(self):
        """Scenario 1.1.a: mensual with fecha_inicial_pago day 20 → anchor_dia_1 == 20, anchor_dia_2 is None."""
        credito = _make_credito(
            periodicidad=Periodicidad.mensual,
            fecha_inicial_pago=date(2026, 1, 20),
            anchor_dia_1=20,
            anchor_dia_2=None,
        )
        assert credito.anchor_dia_1 == 20
        assert credito.anchor_dia_2 is None

    def test_quincenal_anchor_both_set(self):
        """Scenario 1.1.b: quincenal with anchor days 15 and 30."""
        credito = _make_credito(
            periodicidad=Periodicidad.quincenal,
            anchor_dia_1=15,
            anchor_dia_2=30,
        )
        assert credito.anchor_dia_1 == 15
        assert credito.anchor_dia_2 == 30

    def test_semanal_anchor_both_null(self):
        """Scenario 1.1.c: semanal leaves both anchors NULL."""
        credito = _make_credito(
            periodicidad=Periodicidad.semanal,
            numero_cuotas=None,
            anchor_dia_1=None,
            anchor_dia_2=None,
        )
        assert credito.anchor_dia_1 is None
        assert credito.anchor_dia_2 is None

    def test_diario_anchor_both_null(self):
        """Scenario 1.1.d: diario leaves both anchors NULL."""
        credito = _make_credito(
            periodicidad=Periodicidad.diario,
            numero_cuotas=None,
            anchor_dia_1=None,
            anchor_dia_2=None,
        )
        assert credito.anchor_dia_1 is None
        assert credito.anchor_dia_2 is None

    def test_model_has_anchor_dia_1_attribute(self):
        """Credito model exposes anchor_dia_1 as an attribute (hasattr check)."""
        credito = _make_credito(anchor_dia_1=None, anchor_dia_2=None)
        assert hasattr(credito, "anchor_dia_1")

    def test_model_has_anchor_dia_2_attribute(self):
        """Credito model exposes anchor_dia_2 as an attribute (hasattr check)."""
        credito = _make_credito(anchor_dia_1=None, anchor_dia_2=None)
        assert hasattr(credito, "anchor_dia_2")
