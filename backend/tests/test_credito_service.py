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
