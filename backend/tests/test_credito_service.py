"""
tests/test_credito_service.py — Tests para cálculos financieros de créditos.

Cubre:
- Cálculo de cuota fija (amortización francesa)
- Cálculo de interés por días corridos
- Generación de fechas_maxima por periodicidad
- Detección de días corridos aplicables
"""
from datetime import date
from decimal import Decimal

import pytest

import uuid
from datetime import datetime

from app.models.credito import Credito, Periodicidad, TipoCredito
from app.services.credito_service import (
    calcular_cuota_fija,
    calcular_interes_periodo,
)
from app.utils.fechas import (
    calcular_interes_primera_cuota,
    debe_usar_dias_corridos,
    siguiente_fecha_maxima,
)


def _credito_fixture(periodicidad: Periodicidad, anchor_dia_1=None, anchor_dia_2=None) -> Credito:
    """Minimal in-memory Credito for date function tests (no DB required)."""
    return Credito(
        id=uuid.uuid4(),
        cliente_id=uuid.uuid4(),
        numero_credito_cliente="TEST-CR-001",
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


class TestCalcularCuotaFija:
    """Tests de cuota fija con interés simple.

    Fórmula: interes_total = capital * tasa_mensual * (num_cuotas / periodos_por_mes)
             cuota = (capital + interes_total) / num_cuotas
    """

    def test_cuota_ejemplo_basico(self):
        """
        Préstamo: 1,000,000 COP a 3% mensual, 12 cuotas mensuales.
        Interés simple: 1,000,000 * 0.03 * 12 = 360,000 de interés total.
        Cuota = (1,000,000 + 360,000) / 12 = 113,333.33 COP.
        """
        capital = Decimal("1000000")
        tasa = Decimal("0.0300")
        cuota = calcular_cuota_fija(capital, tasa, 12, Periodicidad.mensual)
        # Tolerancia de ±1 COP por redondeo
        assert abs(cuota - Decimal("113333.33")) < Decimal("1.00")

    def test_cuota_tasa_cero(self):
        """Con tasa 0%, la cuota es simplemente capital/n."""
        capital = Decimal("1200000")
        cuota = calcular_cuota_fija(capital, Decimal("0"), 12, Periodicidad.mensual)
        assert cuota == Decimal("100000.00")

    def test_cuota_una_sola_cuota(self):
        """Con 1 cuota, el monto es capital + un período de interés."""
        capital = Decimal("1000000")
        tasa = Decimal("0.0300")
        cuota = calcular_cuota_fija(capital, tasa, 1, Periodicidad.mensual)
        esperada = Decimal("1000000") * (1 + Decimal("0.0300"))
        assert abs(cuota - esperada) < Decimal("0.01")

    def test_cuota_es_decimal_no_float(self):
        """El resultado debe ser Decimal para evitar errores de punto flotante."""
        cuota = calcular_cuota_fija(Decimal("500000"), Decimal("0.0250"), 6, Periodicidad.mensual)
        assert isinstance(cuota, Decimal)

    def test_cuota_dos_decimales(self):
        """El resultado debe tener exactamente 2 decimales."""
        cuota = calcular_cuota_fija(Decimal("750000"), Decimal("0.0350"), 24, Periodicidad.mensual)
        assert cuota == cuota.quantize(Decimal("0.01"))


class TestCalcularInteresPeriodo:
    """Tests de interés de un período completo."""

    def test_interes_basico(self):
        interes = calcular_interes_periodo(Decimal("1000000"), Decimal("0.0300"))
        assert interes == Decimal("30000.00")

    def test_interes_saldo_reducido(self):
        """El interés se recalcula sobre el saldo pendiente."""
        interes = calcular_interes_periodo(Decimal("500000"), Decimal("0.0300"))
        assert interes == Decimal("15000.00")

    def test_interes_redondeo(self):
        """Verifica redondeo correcto a 2 decimales."""
        interes = calcular_interes_periodo(Decimal("333333"), Decimal("0.0300"))
        assert interes == interes.quantize(Decimal("0.01"))


class TestInteresDiasCorridos:
    """Tests para cálculo de interés proporcional a días."""

    def test_30_dias_equivale_a_periodo_completo(self):
        """30 días corridos = 1 período mensual completo."""
        capital = Decimal("1000000")
        tasa = Decimal("0.0300")
        interes = calcular_interes_primera_cuota(
            capital, tasa,
            fecha_apertura=date(2026, 1, 1),
            fecha_inicial_pago=date(2026, 1, 31),
        )
        assert interes == Decimal("30000.00")

    def test_15_dias_es_mitad_del_periodo(self):
        """15 días = 50% del interés mensual."""
        capital = Decimal("1000000")
        tasa = Decimal("0.0300")
        interes = calcular_interes_primera_cuota(
            capital, tasa,
            fecha_apertura=date(2026, 1, 1),
            fecha_inicial_pago=date(2026, 1, 16),
        )
        assert abs(interes - Decimal("15000.00")) < Decimal("0.01")

    def test_dias_corridos_retorna_decimal(self):
        interes = calcular_interes_primera_cuota(
            Decimal("500000"), Decimal("0.0300"),
            fecha_apertura=date(2026, 2, 1),
            fecha_inicial_pago=date(2026, 2, 20),
        )
        assert isinstance(interes, Decimal)


class TestDebUsarDiasCorridos:
    """Tests para detección de si aplica días corridos (diferencia >= 10 días)."""

    def test_diferencia_exacta_10_dias_aplica(self):
        """Exactamente 10 días de diferencia → debe activarse."""
        assert debe_usar_dias_corridos(
            fecha_apertura=date(2026, 1, 1),
            fecha_inicial_pago=date(2026, 1, 21),  # Dictada: 31 enero. Diferencia: |31-21|=10
            periodicidad=Periodicidad.mensual,
        ) is True

    def test_diferencia_menor_10_no_aplica(self):
        """5 días de diferencia → no aplica."""
        assert debe_usar_dias_corridos(
            fecha_apertura=date(2026, 1, 1),
            fecha_inicial_pago=date(2026, 1, 26),  # Dictada: 31 enero. Diferencia: 5
            periodicidad=Periodicidad.mensual,
        ) is False

    def test_periodicidad_quincenal(self):
        """Para quincenal (14 días), fecha dictada = apertura + 14."""
        assert debe_usar_dias_corridos(
            fecha_apertura=date(2026, 1, 1),
            fecha_inicial_pago=date(2026, 1, 25),  # Dictada: 15. Diferencia: |25-15|=10
            periodicidad=Periodicidad.quincenal,
        ) is True


class TestSiguienteFechaMaxima:
    """Tests para generación de fechas según periodicidad (anchor-aware).

    REWRITTEN from old +30/+14 timedelta tests to use the new anchor-aware
    signature: siguiente_fecha_maxima(fecha_anterior, credito).
    Spec: REQ-2.1, REQ-2.2, CAP-4.
    """

    def test_mensual_anchor_mismo_dia_del_mes(self):
        """Scenario 2.1.a: mensual anchor 15, Jan-15 → Feb-15 (same day)."""
        credito = _credito_fixture(Periodicidad.mensual, anchor_dia_1=15)
        resultado = siguiente_fecha_maxima(date(2026, 1, 15), credito)
        assert resultado == date(2026, 2, 15)

    def test_mensual_cruce_anio(self):
        """Scenario 2.2.a: mensual anchor 15, Dec-15 → Jan-15 next year."""
        credito = _credito_fixture(Periodicidad.mensual, anchor_dia_1=15)
        resultado = siguiente_fecha_maxima(date(2026, 12, 15), credito)
        assert resultado == date(2027, 1, 15)

    def test_quincenal_d1_a_d2_mismo_mes(self):
        """Scenario 3.1.a: quincenal 15/30, Mar-15 → Mar-30."""
        credito = _credito_fixture(Periodicidad.quincenal, anchor_dia_1=15, anchor_dia_2=30)
        resultado = siguiente_fecha_maxima(date(2026, 3, 15), credito)
        assert resultado == date(2026, 3, 30)

    def test_quincenal_d2_a_d1_mes_siguiente(self):
        """Scenario 3.1.b: quincenal 15/30, Mar-30 → Apr-15."""
        credito = _credito_fixture(Periodicidad.quincenal, anchor_dia_1=15, anchor_dia_2=30)
        resultado = siguiente_fecha_maxima(date(2026, 3, 30), credito)
        assert resultado == date(2026, 4, 15)

    def test_semanal_suma_7_dias(self):
        """Scenario 4.1.a: semanal advances by +7 days (unchanged semantics)."""
        credito = _credito_fixture(Periodicidad.semanal)
        resultado = siguiente_fecha_maxima(date(2026, 1, 15), credito)
        assert resultado == date(2026, 1, 22)

    def test_diario_suma_1_dia(self):
        """Scenario 4.2.a: diario advances by +1 day (unchanged semantics)."""
        credito = _credito_fixture(Periodicidad.diario)
        resultado = siguiente_fecha_maxima(date(2026, 1, 15), credito)
        assert resultado == date(2026, 1, 16)


# ─────────────────────────────────────────────────────────────────────────────
# GROUP D — recalcular_cuotas_futuras anchor behavior (async DB)
# Spec: CAP-6, REQ-6.1–6.5
# ─────────────────────────────────────────────────────────────────────────────

from app.services.credito_service import recalcular_cuotas_futuras
from app.models.pago import Pago, TipoCuota
from app.utils.momentos import get_momento


async def _credito_db(db_session, periodicidad, anchor_dia_1=None, anchor_dia_2=None, **kwargs):
    """Persist a minimal Credito to the test DB."""
    defaults = dict(
        id=uuid.uuid4(),
        cliente_id=uuid.uuid4(),
        numero_credito_cliente=f"RCALC-{uuid.uuid4().hex[:8]}-CR-001",
        tipo_credito=TipoCredito.cuota_fija,
        capital_prestado=Decimal("1200000.00"),
        tasa_interes_mensual=Decimal("0.0300"),
        fecha_apertura=date(2026, 1, 1),
        fecha_inicial_pago=date(2026, 1, 20),
        periodicidad=periodicidad,
        saldo_capital=Decimal("1200000.00"),
        saldo_intereses=Decimal("0.00"),
        numero_cuotas=12,
        activo=True,
        anchor_dia_1=anchor_dia_1,
        anchor_dia_2=anchor_dia_2,
    )
    defaults.update(kwargs)
    credito = Credito(**defaults)
    db_session.add(credito)
    await db_session.flush()
    return credito


async def _pago_db(db_session, credito, numero, fecha_maxima, pagado=False, capital=None, interes=None):
    """Persist a Pago to the test DB."""
    cap = capital or Decimal("100000.00")
    intr = interes or Decimal("30000.00")
    pago = Pago(
        id=uuid.uuid4(),
        credito_id=credito.id,
        numero_cuota=numero,
        tipo_cuota=TipoCuota.programada,
        monto_a_pagar=cap + intr,
        capital_a_pagar=cap,
        interes_a_pagar=intr,
        capital_pagado=cap if pagado else Decimal("0.00"),
        interes_pagado=intr if pagado else Decimal("0.00"),
        fecha_maxima=fecha_maxima,
        momento=get_momento(fecha_maxima),
        pagado=pagado,
    )
    db_session.add(pago)
    await db_session.flush()
    return pago


class TestRecalcularCuotasFuturasAnchor:
    """CAP-6: recalcular_cuotas_futuras re-anchors pending cuotas; amounts unchanged."""

    @pytest.mark.asyncio
    async def test_6_1_a_mensual_re_anchor_drifted_dates(self, db_session):
        """Scenario 6.1.a: mensual anchor_dia_1=20, drifted dates corrected."""
        credito = await _credito_db(
            db_session, Periodicidad.mensual, anchor_dia_1=20,
            fecha_inicial_pago=date(2026, 1, 20)
        )
        # Paid cuota 1
        await _pago_db(db_session, credito, 1, date(2026, 1, 20), pagado=True)
        # Pending cuotas with drifted dates
        cuota2 = await _pago_db(db_session, credito, 2, date(2026, 2, 19))
        cuota3 = await _pago_db(db_session, credito, 3, date(2026, 3, 21))
        cuota4 = await _pago_db(db_session, credito, 4, date(2026, 4, 20))

        await recalcular_cuotas_futuras(db_session, credito, date(2026, 2, 20))

        assert cuota2.fecha_maxima == date(2026, 2, 20)
        assert cuota3.fecha_maxima == date(2026, 3, 20)
        assert cuota4.fecha_maxima == date(2026, 4, 20)

    @pytest.mark.asyncio
    async def test_6_2_a_quincenal_re_anchor_with_alternation(self, db_session):
        """Scenario 6.2.a: quincenal d1=15 d2=30, drifted pending cuotas corrected."""
        credito = await _credito_db(
            db_session, Periodicidad.quincenal, anchor_dia_1=15, anchor_dia_2=30,
            fecha_inicial_pago=date(2026, 3, 15),
            tipo_credito=TipoCredito.abono_capital, numero_cuotas=None,
        )
        # Last paid: Mar-15
        await _pago_db(db_session, credito, 1, date(2026, 3, 15), pagado=True)
        # Drifted pending cuotas
        cuota2 = await _pago_db(db_session, credito, 2, date(2026, 3, 29))
        cuota3 = await _pago_db(db_session, credito, 3, date(2026, 4, 12))

        await recalcular_cuotas_futuras(db_session, credito, date(2026, 3, 30))

        assert cuota2.fecha_maxima == date(2026, 3, 30)
        assert cuota3.fecha_maxima == date(2026, 4, 15)

    @pytest.mark.asyncio
    async def test_6_3_a_amounts_invariant(self, db_session):
        """Scenario 6.3.a: amounts and saldos unchanged after recalcular."""
        credito = await _credito_db(
            db_session, Periodicidad.mensual, anchor_dia_1=20,
        )
        cuota = await _pago_db(
            db_session, credito, 1, date(2026, 2, 19),
            capital=Decimal("100000.00"), interes=Decimal("30000.00")
        )
        original_capital = cuota.capital_a_pagar
        original_interes = cuota.interes_a_pagar
        original_monto = cuota.monto_a_pagar

        await recalcular_cuotas_futuras(db_session, credito, date(2026, 2, 20))

        # Dates changed
        assert cuota.fecha_maxima == date(2026, 2, 20)
        # Amounts unchanged
        assert cuota.capital_a_pagar == original_capital
        assert cuota.interes_a_pagar == original_interes
        assert cuota.monto_a_pagar == original_monto

    @pytest.mark.asyncio
    async def test_6_4_a_paid_cuotas_untouched(self, db_session):
        """Scenario 6.4.a: paid cuotas keep their historical fecha_maxima."""
        credito = await _credito_db(
            db_session, Periodicidad.mensual, anchor_dia_1=20,
        )
        cuota_pagada = await _pago_db(
            db_session, credito, 1, date(2026, 1, 18), pagado=True
        )
        cuota_pendiente = await _pago_db(
            db_session, credito, 2, date(2026, 2, 19)
        )

        await recalcular_cuotas_futuras(db_session, credito, date(2026, 2, 20))

        # Paid cuota date is historical and must NOT change
        assert cuota_pagada.fecha_maxima == date(2026, 1, 18)
        # Pending cuota date is corrected
        assert cuota_pendiente.fecha_maxima == date(2026, 2, 20)

    @pytest.mark.asyncio
    async def test_6_5_a_momento_recomputed(self, db_session):
        """Scenario 6.5.a: momento is recomputed for corrected fecha_maxima."""
        credito = await _credito_db(
            db_session, Periodicidad.mensual, anchor_dia_1=20,
        )
        cuota = await _pago_db(db_session, credito, 1, date(2026, 2, 19))
        old_momento = cuota.momento

        await recalcular_cuotas_futuras(db_session, credito, date(2026, 2, 20))

        assert cuota.fecha_maxima == date(2026, 2, 20)
        assert cuota.momento == get_momento(date(2026, 2, 20))
