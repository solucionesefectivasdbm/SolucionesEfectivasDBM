"""
tests/test_credito_service_arrastre.py — Carry-over (arrastre) disaggregation.

Covers:
- `desglosar_arrastre`: pure Decimal helper, single source of truth for
  splitting a pending shortfall into capital/interest components.
- `_siguiente_cuota_fija`: distributes the shortfall to the correct
  component when generating the next `cuota_fija` installment.
- `recalcular_cuota_actual_si_no_pagada`: must preserve a pending arrastre
  instead of overwriting it with base values (adjacent defect fix).
"""
import uuid
from datetime import date, datetime
from decimal import Decimal

import pytest

from app.models.credito import Credito, Periodicidad, TipoCredito
from app.models.pago import Pago, TipoCuota
from app.services.credito_service import (
    _siguiente_cuota_fija,
    desglosar_arrastre,
    recalcular_cuota_actual_si_no_pagada,
)


def _mk_pago_anterior(
    capital_a_pagar: Decimal,
    capital_pagado: Decimal,
    interes_a_pagar: Decimal = Decimal("20.00"),
    interes_pagado: Decimal = Decimal("0.00"),
) -> Pago:
    p = Pago()
    p.id = uuid.uuid4()
    p.credito_id = uuid.uuid4()
    p.numero_cuota = 1
    p.tipo_cuota = TipoCuota.programada
    p.capital_a_pagar = capital_a_pagar
    p.interes_a_pagar = interes_a_pagar
    p.capital_pagado = capital_pagado
    p.interes_pagado = interes_pagado
    p.monto_a_pagar = capital_a_pagar + interes_a_pagar
    p.pagado = True
    return p


class TestDesglosarArrastre:
    """Unit tests for the pure helper — no DB required."""

    def test_falta_capital_pura(self):
        """Purely capital shortfall: entire arrastre lands on capital."""
        cuota_anterior = _mk_pago_anterior(
            capital_a_pagar=Decimal("100.00"), capital_pagado=Decimal("50.00")
        )
        arr_cap, arr_int = desglosar_arrastre(cuota_anterior, Decimal("50.00"))
        assert arr_cap == Decimal("50.00")
        assert arr_int == Decimal("0.00")

    def test_falta_interes_pura(self):
        """Prior capital fully paid: entire arrastre lands on interest."""
        cuota_anterior = _mk_pago_anterior(
            capital_a_pagar=Decimal("100.00"), capital_pagado=Decimal("100.00")
        )
        arr_cap, arr_int = desglosar_arrastre(cuota_anterior, Decimal("15.00"))
        assert arr_cap == Decimal("0.00")
        assert arr_int == Decimal("15.00")

    def test_falta_mixta(self):
        """Mixed shortfall: capital gets exactly its own falta, rest is interest."""
        cuota_anterior = _mk_pago_anterior(
            capital_a_pagar=Decimal("100.00"), capital_pagado=Decimal("70.00")
        )
        arr_cap, arr_int = desglosar_arrastre(cuota_anterior, Decimal("40.00"))
        assert arr_cap == Decimal("30.00")
        assert arr_int == Decimal("10.00")
        assert arr_cap + arr_int == Decimal("40.00")

    def test_total_cero_retorna_cero_cero(self):
        """No pending shortfall → no arrastre, regardless of the prior row."""
        cuota_anterior = _mk_pago_anterior(
            capital_a_pagar=Decimal("100.00"), capital_pagado=Decimal("40.00")
        )
        arr_cap, arr_int = desglosar_arrastre(cuota_anterior, Decimal("0.00"))
        assert arr_cap == Decimal("0.00")
        assert arr_int == Decimal("0.00")

    def test_cuota_anterior_none_retorna_cero_cero(self):
        """No prior row (e.g. first cuota) → no arrastre even with a positive total."""
        arr_cap, arr_int = desglosar_arrastre(None, Decimal("50.00"))
        assert arr_cap == Decimal("0.00")
        assert arr_int == Decimal("0.00")

    def test_component_overpay_clamp(self):
        """
        Component-overpay edge: capital was paid beyond its target in a free
        partial split (falta_cap negative) → clamp to 0, arrastre becomes 100%
        interest.
        """
        cuota_anterior = _mk_pago_anterior(
            capital_a_pagar=Decimal("150.00"), capital_pagado=Decimal("160.00")
        )
        arr_cap, arr_int = desglosar_arrastre(cuota_anterior, Decimal("20.00"))
        assert arr_cap == Decimal("0.00")
        assert arr_int == Decimal("20.00")


def _credito_cuota_fija(
    capital_prestado=Decimal("1000.00"),
    tasa=Decimal("0.0200"),
    numero_cuotas=10,
    saldo_capital=Decimal("1000.00"),
) -> Credito:
    return Credito(
        id=uuid.uuid4(),
        cliente_id=uuid.uuid4(),
        numero_credito_cliente="TEST-ARR-001",
        tipo_credito=TipoCredito.cuota_fija,
        capital_prestado=capital_prestado,
        tasa_interes_mensual=tasa,
        fecha_apertura=date(2026, 1, 1),
        fecha_inicial_pago=date(2026, 1, 10),
        periodicidad=Periodicidad.mensual,
        saldo_capital=saldo_capital,
        saldo_intereses=Decimal("0.00"),
        numero_cuotas=numero_cuotas,
        calcular_interes_dias_corridos=False,
        activo=True,
        created_at=datetime(2026, 1, 1),
        updated_at=datetime(2026, 1, 1),
    )


class TestSiguienteCuotaFijaArrastre:
    """`_siguiente_cuota_fija` distributes the shortfall per component."""

    def test_distribuye_al_componente_correcto(self):
        """Base 100/20/120 with a purely-capital shortfall of 50 → capital grows,
        interest stays at base, and cap+int == monto."""
        credito = _credito_cuota_fija()
        cuota_anterior = _mk_pago_anterior(
            capital_a_pagar=Decimal("100.00"), capital_pagado=Decimal("50.00"),
            interes_a_pagar=Decimal("20.00"), interes_pagado=Decimal("10.00"),
        )
        nueva = _siguiente_cuota_fija(
            credito, cuota_anterior, 2, date(2026, 2, 10), "m3", None, Decimal("50.00"),
        )
        assert nueva.capital_a_pagar == Decimal("150.00")
        assert nueva.interes_a_pagar == Decimal("20.00")
        assert nueva.capital_a_pagar + nueva.interes_a_pagar == nueva.monto_a_pagar

    def test_regresion_arrastre_cero_componentes_iguales_a_base(self):
        """Zero-arrastre regression guard: fully-paid prior cuota → base values,
        identical to current (pre-fix) behavior."""
        credito = _credito_cuota_fija()
        cuota_anterior = _mk_pago_anterior(
            capital_a_pagar=Decimal("100.00"), capital_pagado=Decimal("100.00"),
            interes_a_pagar=Decimal("20.00"), interes_pagado=Decimal("20.00"),
        )
        nueva = _siguiente_cuota_fija(
            credito, cuota_anterior, 2, date(2026, 2, 10), "m3", None, Decimal("0.00"),
        )
        assert nueva.capital_a_pagar == Decimal("100.00")
        assert nueva.interes_a_pagar == Decimal("20.00")
        assert nueva.monto_a_pagar == Decimal("120.00")


class TestRecalcularCuotaActualPreservaArrastre:
    """`recalcular_cuota_actual_si_no_pagada` must not erase a pending arrastre."""

    @pytest.mark.asyncio
    async def test_preserva_arrastre_pendiente_tras_edicion_admin(self, db_session):
        """
        A previous cuota was paid partially, leaving a shortfall that got
        carried into the current (unpaid) cuota. When the Admin edits the
        credit (triggering a recalculation), the current cuota's components
        must still include the arrastre — not just the freshly-recalculated
        base values.
        """
        credito = _credito_cuota_fija()
        db_session.add(credito)
        await db_session.flush()

        cuota_pagada = Pago(
            id=uuid.uuid4(), credito_id=credito.id, numero_cuota=1,
            tipo_cuota=TipoCuota.programada,
            monto_a_pagar=Decimal("120.00"),
            capital_a_pagar=Decimal("100.00"), interes_a_pagar=Decimal("20.00"),
            capital_pagado=Decimal("50.00"), interes_pagado=Decimal("10.00"),
            momento="m3", fecha_maxima=date(2026, 1, 10),
            pagado=True, validado_recaudador=True, es_ultimo_pago=False,
        )
        cuota_actual = Pago(
            id=uuid.uuid4(), credito_id=credito.id, numero_cuota=2,
            tipo_cuota=TipoCuota.programada,
            monto_a_pagar=Decimal("180.00"),
            capital_a_pagar=Decimal("150.00"), interes_a_pagar=Decimal("30.00"),
            capital_pagado=Decimal("0.00"), interes_pagado=Decimal("0.00"),
            momento="m3", fecha_maxima=date(2026, 2, 10),
            pagado=False, validado_recaudador=False, es_ultimo_pago=False,
        )
        db_session.add_all([cuota_pagada, cuota_actual])
        await db_session.flush()

        ok = await recalcular_cuota_actual_si_no_pagada(db_session, credito)

        assert ok is True
        # Base is still 100/20, but the pending arrastre (50 capital / 10 interest,
        # from monto 120 - paid 60 = 60) must be preserved, not dropped.
        assert cuota_actual.capital_a_pagar == Decimal("150.00")
        assert cuota_actual.interes_a_pagar == Decimal("30.00")
        assert cuota_actual.monto_a_pagar == Decimal("180.00")
        assert cuota_actual.capital_a_pagar + cuota_actual.interes_a_pagar == cuota_actual.monto_a_pagar
        # Registered payments, capital_pagado/interes_pagado, are never touched.
        assert cuota_pagada.capital_pagado == Decimal("50.00")
        assert cuota_pagada.interes_pagado == Decimal("10.00")

    @pytest.mark.asyncio
    async def test_sin_arrastre_previo_usa_solo_valores_base(self, db_session):
        """No previous paid cuota exists (current cuota is #1) → no arrastre to
        preserve, base values only (existing behavior unaffected)."""
        credito = _credito_cuota_fija()
        db_session.add(credito)
        await db_session.flush()

        cuota_actual = Pago(
            id=uuid.uuid4(), credito_id=credito.id, numero_cuota=1,
            tipo_cuota=TipoCuota.programada,
            monto_a_pagar=Decimal("120.00"),
            capital_a_pagar=Decimal("100.00"), interes_a_pagar=Decimal("20.00"),
            capital_pagado=Decimal("0.00"), interes_pagado=Decimal("0.00"),
            momento="m3", fecha_maxima=date(2026, 1, 10),
            pagado=False, validado_recaudador=False, es_ultimo_pago=False,
        )
        db_session.add(cuota_actual)
        await db_session.flush()

        ok = await recalcular_cuota_actual_si_no_pagada(db_session, credito)

        assert ok is True
        assert cuota_actual.capital_a_pagar == Decimal("100.00")
        assert cuota_actual.interes_a_pagar == Decimal("20.00")
        assert cuota_actual.monto_a_pagar == Decimal("120.00")
