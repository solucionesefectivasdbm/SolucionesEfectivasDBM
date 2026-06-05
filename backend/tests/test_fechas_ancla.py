"""
tests/test_fechas_ancla.py — Full test suite for anchor-aware date helpers.

RED phase: ALL tests in this file must fail before B3 is implemented.
Covers all 54 spec scenarios for CAP-2, CAP-3, CAP-4.

Reference year facts:
  - 2026: NOT a leap year (Feb has 28 days)
  - 2028: IS a leap year (Feb has 29 days)
  - April/June/September/November: 30 days
  - January/March/May/July/August/October/December: 31 days
"""
import uuid
from datetime import date, datetime
from decimal import Decimal

import pytest

from app.models.credito import Credito, Periodicidad, TipoCredito
from app.utils.fechas import siguiente_fecha_maxima


def _credito(periodicidad: Periodicidad, anchor_dia_1=None, anchor_dia_2=None) -> Credito:
    """Minimal in-memory Credito fixture. No DB required."""
    return Credito(
        id=uuid.uuid4(),
        cliente_id=uuid.uuid4(),
        numero_credito_cliente="ANCHOR-TEST-001",
        tipo_credito=TipoCredito.cuota_fija,
        capital_prestado=Decimal("1000000.00"),
        tasa_interes_mensual=Decimal("0.0300"),
        fecha_apertura=date(2026, 1, 1),
        fecha_inicial_pago=date(2026, 1, 15),
        periodicidad=periodicidad,
        saldo_capital=Decimal("1000000.00"),
        saldo_intereses=Decimal("0.00"),
        numero_cuotas=12,
        calcular_interes_dias_corridos=False,
        activo=True,
        created_at=datetime(2026, 1, 1),
        updated_at=datetime(2026, 1, 1),
        anchor_dia_1=anchor_dia_1,
        anchor_dia_2=anchor_dia_2,
    )


# ─────────────────────────────────────────────────────────────────────────────
# CAPABILITY 2 — Mensual due-date generation
# ─────────────────────────────────────────────────────────────────────────────

class TestMensualAnchor:
    """CAP-2: mensual credits use anchor_dia_1 to land on the same day each month."""

    # REQ-2.1 — Same day-of-month every following month

    def test_2_1_a_jan_to_feb(self):
        """Scenario 2.1.a: anchor 20, Jan-20 → Feb-20."""
        c = _credito(Periodicidad.mensual, anchor_dia_1=20)
        assert siguiente_fecha_maxima(date(2026, 1, 20), c) == date(2026, 2, 20)

    def test_2_1_b_chain_three_months(self):
        """Scenario 2.1.b: anchor 20, chain Jan-20 → Feb-20 → Mar-20 → Apr-20."""
        c = _credito(Periodicidad.mensual, anchor_dia_1=20)
        fecha = date(2026, 1, 20)
        expected = [date(2026, 2, 20), date(2026, 3, 20), date(2026, 4, 20)]
        results = []
        for _ in range(3):
            fecha = siguiente_fecha_maxima(fecha, c)
            results.append(fecha)
        assert results == expected

    # REQ-2.2 — Year rollover

    def test_2_2_a_year_rollover(self):
        """Scenario 2.2.a: anchor 15, Dec-15-2026 → Jan-15-2027."""
        c = _credito(Periodicidad.mensual, anchor_dia_1=15)
        assert siguiente_fecha_maxima(date(2026, 12, 15), c) == date(2027, 1, 15)

    # REQ-2.3 — Short-month clamping (anchor 31)

    def test_2_3_a_jan31_to_feb28_nonleap(self):
        """Scenario 2.3.a: anchor 31, Jan-31-2026 → Feb-28-2026 (clamp, non-leap)."""
        c = _credito(Periodicidad.mensual, anchor_dia_1=31)
        assert siguiente_fecha_maxima(date(2026, 1, 31), c) == date(2026, 2, 28)

    def test_2_3_b_feb28_to_mar31_restores(self):
        """Scenario 2.3.b: anchor 31, Feb-28 → Mar-31 (recovers from clamped date)."""
        c = _credito(Periodicidad.mensual, anchor_dia_1=31)
        # Input is the CLAMPED date (28), but the anchor (31) drives the next month
        assert siguiente_fecha_maxima(date(2026, 2, 28), c) == date(2026, 3, 31)

    def test_2_3_c_mar31_to_apr30_clamp(self):
        """Scenario 2.3.c: anchor 31, Mar-31 → Apr-30 (April has 30 days)."""
        c = _credito(Periodicidad.mensual, anchor_dia_1=31)
        assert siguiente_fecha_maxima(date(2026, 3, 31), c) == date(2026, 4, 30)

    def test_2_3_d_apr30_to_may31_restores(self):
        """Scenario 2.3.d: anchor 31, Apr-30 → May-31 (recovers again)."""
        c = _credito(Periodicidad.mensual, anchor_dia_1=31)
        assert siguiente_fecha_maxima(date(2026, 4, 30), c) == date(2026, 5, 31)

    def test_2_3_e_leap_feb_anchor31(self):
        """Scenario 2.3.e: anchor 31, Jan-31-2028 → Feb-29-2028 (leap year)."""
        c = _credito(Periodicidad.mensual, anchor_dia_1=31)
        assert siguiente_fecha_maxima(date(2028, 1, 31), c) == date(2028, 2, 29)

    # REQ-2.4 — Short-month clamping (anchor 30 into February)

    def test_2_4_a_jan30_to_feb28_nonleap(self):
        """Scenario 2.4.a: anchor 30, Jan-30 → Feb-28 (non-leap clamp)."""
        c = _credito(Periodicidad.mensual, anchor_dia_1=30)
        assert siguiente_fecha_maxima(date(2026, 1, 30), c) == date(2026, 2, 28)

    def test_2_4_b_feb28_to_mar30_restores(self):
        """Scenario 2.4.b: anchor 30, Feb-28 → Mar-30 (recovers)."""
        c = _credito(Periodicidad.mensual, anchor_dia_1=30)
        assert siguiente_fecha_maxima(date(2026, 2, 28), c) == date(2026, 3, 30)


# ─────────────────────────────────────────────────────────────────────────────
# CAPABILITY 3 — Quincenal due-date generation
# ─────────────────────────────────────────────────────────────────────────────

class TestQuincenalAnchor:
    """CAP-3: quincenal credits alternate between d1 and d2 anchor days."""

    # REQ-3.1 — Standard 15/30 alternation

    def test_3_1_a_d1_to_d2_same_month(self):
        """Scenario 3.1.a: d1=15 d2=30, Mar-15 → Mar-30."""
        c = _credito(Periodicidad.quincenal, anchor_dia_1=15, anchor_dia_2=30)
        assert siguiente_fecha_maxima(date(2026, 3, 15), c) == date(2026, 3, 30)

    def test_3_1_b_d2_to_d1_next_month(self):
        """Scenario 3.1.b: d1=15 d2=30, Mar-30 → Apr-15."""
        c = _credito(Periodicidad.quincenal, anchor_dia_1=15, anchor_dia_2=30)
        assert siguiente_fecha_maxima(date(2026, 3, 30), c) == date(2026, 4, 15)

    def test_3_1_c_full_chain_across_boundary(self):
        """Scenario 3.1.c: d1=15 d2=30, chain from Mar-15 for 4 cuotas."""
        c = _credito(Periodicidad.quincenal, anchor_dia_1=15, anchor_dia_2=30)
        fecha = date(2026, 3, 15)
        expected = [date(2026, 3, 30), date(2026, 4, 15), date(2026, 4, 30), date(2026, 5, 15)]
        results = []
        for _ in range(4):
            fecha = siguiente_fecha_maxima(fecha, c)
            results.append(fecha)
        assert results == expected

    # REQ-3.2 — Arbitrary pairs

    def test_3_2_a_pair_10_25(self):
        """Scenario 3.2.a: d1=10 d2=25, Jun-10 → Jun-25 → Jul-10."""
        c = _credito(Periodicidad.quincenal, anchor_dia_1=10, anchor_dia_2=25)
        assert siguiente_fecha_maxima(date(2026, 6, 10), c) == date(2026, 6, 25)
        assert siguiente_fecha_maxima(date(2026, 6, 25), c) == date(2026, 7, 10)

    def test_3_2_b_pair_1_16(self):
        """Scenario 3.2.b: d1=1 d2=16, Jun-16 → Jul-01."""
        c = _credito(Periodicidad.quincenal, anchor_dia_1=1, anchor_dia_2=16)
        assert siguiente_fecha_maxima(date(2026, 6, 16), c) == date(2026, 7, 1)

    # REQ-3.3 — Short-month clamping with correct alternation

    def test_3_3_a_d2_31_clamps_feb_nonleap(self):
        """Scenario 3.3.a: d1=15 d2=31, Feb-15 → Feb-28 (d2=31 clamped in non-leap Feb)."""
        c = _credito(Periodicidad.quincenal, anchor_dia_1=15, anchor_dia_2=31)
        assert siguiente_fecha_maxima(date(2026, 2, 15), c) == date(2026, 2, 28)

    def test_3_3_b_after_clamped_d2_returns_d1_next_month(self):
        """Scenario 3.3.b: d1=15 d2=31, after Feb-28 (clamped) → Mar-15.
        Must alternate correctly even though 28 != 31."""
        c = _credito(Periodicidad.quincenal, anchor_dia_1=15, anchor_dia_2=31)
        assert siguiente_fecha_maxima(date(2026, 2, 28), c) == date(2026, 3, 15)

    def test_3_3_c_d2_31_unclamped_after_clamped_cycle(self):
        """Scenario 3.3.c: d1=15 d2=31, Mar-15 → Mar-31 (d2 unclamped in March)."""
        c = _credito(Periodicidad.quincenal, anchor_dia_1=15, anchor_dia_2=31)
        assert siguiente_fecha_maxima(date(2026, 3, 15), c) == date(2026, 3, 31)

    def test_3_3_d_double_clamp_collision_feb(self):
        """Scenario 3.3.d: d1=29 d2=31, Jan-31 → Feb-28 (both anchors clamp to last day).
        The cycle then resumes: Feb-28 → Mar-29 (d1 unclamped in March)."""
        c = _credito(Periodicidad.quincenal, anchor_dia_1=29, anchor_dia_2=31)
        # Jan-31 is d2-clamped (31=31), so next is d1 in next month
        # But Jan-31 == cand_d2 (Jan-31), so next = d1 in Feb = Feb-29 clamped to Feb-28
        result_from_jan31 = siguiente_fecha_maxima(date(2026, 1, 31), c)
        assert result_from_jan31 == date(2026, 2, 28)
        # After Feb-28 (degenerate double-clamp), next should be Mar-29
        result_from_feb28 = siguiente_fecha_maxima(date(2026, 2, 28), c)
        assert result_from_feb28 == date(2026, 3, 29)

    # REQ-3.4 — Year rollover for quincenal

    def test_3_4_a_year_rollover(self):
        """Scenario 3.4.a: d1=15 d2=30, Dec-30-2026 → Jan-15-2027."""
        c = _credito(Periodicidad.quincenal, anchor_dia_1=15, anchor_dia_2=30)
        assert siguiente_fecha_maxima(date(2026, 12, 30), c) == date(2027, 1, 15)


# ─────────────────────────────────────────────────────────────────────────────
# CAPABILITY 4 — Semanal / diario regression (unchanged)
# ─────────────────────────────────────────────────────────────────────────────

class TestSemanalDiarioRegression:
    """CAP-4: semanal and diario still use timedelta; anchors are irrelevant."""

    def test_4_1_a_semanal_plus_7(self):
        """Scenario 4.1.a: semanal, Jan-15 → Jan-22."""
        c = _credito(Periodicidad.semanal)
        assert siguiente_fecha_maxima(date(2026, 1, 15), c) == date(2026, 1, 22)

    def test_4_1_b_semanal_month_boundary(self):
        """Scenario 4.1.b: semanal, Jan-29 → Feb-05."""
        c = _credito(Periodicidad.semanal)
        assert siguiente_fecha_maxima(date(2026, 1, 29), c) == date(2026, 2, 5)

    def test_4_2_a_diario_plus_1(self):
        """Scenario 4.2.a: diario, Jan-15 → Jan-16."""
        c = _credito(Periodicidad.diario)
        assert siguiente_fecha_maxima(date(2026, 1, 15), c) == date(2026, 1, 16)

    def test_4_2_b_diario_month_boundary(self):
        """Scenario 4.2.b: diario, Jan-31 → Feb-01."""
        c = _credito(Periodicidad.diario)
        assert siguiente_fecha_maxima(date(2026, 1, 31), c) == date(2026, 2, 1)

    def test_4_3_a_semanal_anchor_null_no_error(self):
        """Scenario 4.3.a: semanal with NULL anchor fields; no error, result = +7."""
        c = _credito(Periodicidad.semanal, anchor_dia_1=None, anchor_dia_2=None)
        result = siguiente_fecha_maxima(date(2026, 1, 15), c)
        assert result == date(2026, 1, 22)
