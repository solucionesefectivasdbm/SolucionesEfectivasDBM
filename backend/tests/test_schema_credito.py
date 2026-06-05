"""
tests/test_schema_credito.py — Pydantic schema tests for CreditoCreate.

RED phase: tests covering CAP-7 (API/schema contract) and REQ-1.1/1.2/1.3.
These fail before C2 (fecha_inicial_pago_2 field + model_validator) is applied.
"""
import uuid
from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.models.credito import Periodicidad, TipoCredito
from app.schemas.credito import CreditoCreate


def _base_payload(**kwargs) -> dict:
    """Minimal valid mensual cuota_fija payload."""
    defaults = {
        "cliente_id": str(uuid.uuid4()),
        "tipo_credito": "cuota_fija",
        "capital_prestado": "1000000.00",
        "tasa_interes_mensual": "0.0300",
        "fecha_apertura": "2026-01-01",
        "fecha_inicial_pago": "2026-01-20",
        "periodicidad": "mensual",
        "numero_cuotas": 12,
    }
    defaults.update(kwargs)
    return defaults


class TestMensualBackwardCompat:
    """REQ-7.1: mensual contract unchanged — no new required field."""

    def test_mensual_no_second_date_required(self):
        """Scenario 7.1.a: mensual payload with single fecha_inicial_pago succeeds."""
        payload = _base_payload()
        credito = CreditoCreate(**payload)
        assert credito.periodicidad == Periodicidad.mensual
        assert credito.fecha_inicial_pago == date(2026, 1, 20)

    def test_mensual_derives_anchor_dia_1_from_fecha_day(self):
        """Scenario 1.1.a: after parsing, anchor_dia_1 == fecha_inicial_pago.day."""
        payload = _base_payload(fecha_inicial_pago="2026-01-20")
        credito = CreditoCreate(**payload)
        assert credito.anchor_dia_1 == 20
        assert credito.anchor_dia_2 is None

    def test_mensual_anchor_dia_1_day_5(self):
        """anchor_dia_1 derived from day 5."""
        payload = _base_payload(fecha_inicial_pago="2026-01-05")
        credito = CreditoCreate(**payload)
        assert credito.anchor_dia_1 == 5
        assert credito.anchor_dia_2 is None

    def test_mensual_extra_second_date_ignored_or_rejected(self):
        """Scenario 7.3.c: mensual with a second date — backend ignores it or rejects cleanly.
        Mensual MUST NOT silently become quincenal. anchor_dia_2 stays None."""
        payload = _base_payload(fecha_inicial_pago_2="2026-01-30")
        credito = CreditoCreate(**payload)
        # mensual: second date must be ignored; anchor_dia_2 stays None
        assert credito.anchor_dia_2 is None
        assert credito.anchor_dia_1 == 20


class TestQuincenalTwoDates:
    """REQ-7.2: quincenal accepts two initial dates; REQ-1.2 normalization."""

    def _quincenal_payload(self, d1_str: str, d2_str: str) -> dict:
        return _base_payload(
            periodicidad="quincenal",
            tipo_credito="abono_capital",
            numero_cuotas=None,
            fecha_inicial_pago=d1_str,
            fecha_inicial_pago_2=d2_str,
        )

    def test_7_2_a_quincenal_two_dates_accepted(self):
        """Scenario 7.2.a: quincenal with days 15 and 30 → anchor_dia_1=15, anchor_dia_2=30."""
        payload = self._quincenal_payload("2026-01-15", "2026-01-30")
        credito = CreditoCreate(**payload)
        assert credito.anchor_dia_1 == 15
        assert credito.anchor_dia_2 == 30

    def test_7_2_b_out_of_order_normalized(self):
        """Scenario 7.2.b: reversed input (30 then 15) → normalized anchor_dia_1=15, anchor_dia_2=30."""
        payload = self._quincenal_payload("2026-01-30", "2026-01-15")
        credito = CreditoCreate(**payload)
        assert credito.anchor_dia_1 == 15
        assert credito.anchor_dia_2 == 30

    def test_1_2_a_normalization_in_order(self):
        """Scenario 1.2.a: (10, 25) → anchor_dia_1=10, anchor_dia_2=25."""
        payload = self._quincenal_payload("2026-01-10", "2026-01-25")
        credito = CreditoCreate(**payload)
        assert credito.anchor_dia_1 == 10
        assert credito.anchor_dia_2 == 25

    def test_1_2_b_normalization_reversed(self):
        """Scenario 1.2.b: reversed input (30, 15) → normalized anchor_dia_1=15, anchor_dia_2=30."""
        payload = self._quincenal_payload("2026-01-30", "2026-01-15")
        credito = CreditoCreate(**payload)
        assert credito.anchor_dia_1 == 15
        assert credito.anchor_dia_2 == 30


class TestQuincenalValidationErrors:
    """REQ-7.3 and REQ-1.2.c: invalid/missing anchor scenarios raise errors."""

    def test_7_3_a_quincenal_missing_second_date_raises(self):
        """Scenario 7.3.a: quincenal with only one date → validation error (422)."""
        payload = _base_payload(
            periodicidad="quincenal",
            tipo_credito="abono_capital",
            numero_cuotas=None,
        )
        with pytest.raises(ValidationError):
            CreditoCreate(**payload)

    def test_7_3_b_quincenal_equal_days_raises(self):
        """Scenario 7.3.b: quincenal two dates with same day → validation error."""
        payload = _base_payload(
            periodicidad="quincenal",
            tipo_credito="abono_capital",
            numero_cuotas=None,
            fecha_inicial_pago="2026-01-15",
            fecha_inicial_pago_2="2026-02-15",  # same day (15) in different months
        )
        with pytest.raises(ValidationError):
            CreditoCreate(**payload)

    def test_1_2_c_equal_days_rejected(self):
        """Scenario 1.2.c: (15, 15) same day → validation error."""
        payload = _base_payload(
            periodicidad="quincenal",
            tipo_credito="abono_capital",
            numero_cuotas=None,
            fecha_inicial_pago="2026-01-15",
            fecha_inicial_pago_2="2026-03-15",  # same day number 15
        )
        with pytest.raises(ValidationError):
            CreditoCreate(**payload)


class TestSemanalDiarioAnchorNull:
    """REQ-1.1.c, REQ-1.1.d: semanal and diario derive no anchors (both NULL)."""

    def test_semanal_anchor_both_null(self):
        """Scenario 1.1.c: semanal leaves both anchors NULL."""
        payload = _base_payload(
            periodicidad="semanal",
            tipo_credito="cuota_fija",
            numero_cuotas=52,
        )
        credito = CreditoCreate(**payload)
        assert credito.anchor_dia_1 is None
        assert credito.anchor_dia_2 is None

    def test_diario_anchor_both_null(self):
        """Scenario 1.1.d: diario leaves both anchors NULL."""
        payload = _base_payload(
            periodicidad="diario",
            tipo_credito="cuota_fija",
            numero_cuotas=365,
        )
        credito = CreditoCreate(**payload)
        assert credito.anchor_dia_1 is None
        assert credito.anchor_dia_2 is None
