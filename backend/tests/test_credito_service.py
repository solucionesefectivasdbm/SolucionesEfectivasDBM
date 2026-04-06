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

from app.models.credito import Periodicidad
from app.services.credito_service import (
    calcular_cuota_fija,
    calcular_interes_periodo,
)
from app.utils.fechas import (
    calcular_interes_primera_cuota,
    debe_usar_dias_corridos,
    siguiente_fecha_maxima,
)


class TestCalcularCuotaFija:
    """Tests de amortización francesa."""

    def test_cuota_ejemplo_basico(self):
        """
        Préstamo: 1,000,000 COP a 3% mensual, 12 cuotas.
        Cuota esperada ≈ 100,462 COP (verificado con calculadora financiera).
        """
        capital = Decimal("1000000")
        tasa = Decimal("0.0300")
        cuota = calcular_cuota_fija(capital, tasa, 12)
        # Tolerancia de ±1 COP por redondeo
        assert abs(cuota - Decimal("100462.13")) < Decimal("1.00")

    def test_cuota_tasa_cero(self):
        """Con tasa 0%, la cuota es simplemente capital/n."""
        capital = Decimal("1200000")
        cuota = calcular_cuota_fija(capital, Decimal("0"), 12)
        assert cuota == Decimal("100000.00")

    def test_cuota_una_sola_cuota(self):
        """Con 1 cuota, el monto es capital + un período de interés."""
        capital = Decimal("1000000")
        tasa = Decimal("0.0300")
        cuota = calcular_cuota_fija(capital, tasa, 1)
        esperada = Decimal("1000000") * (1 + Decimal("0.0300"))
        assert abs(cuota - esperada) < Decimal("0.01")

    def test_cuota_es_decimal_no_float(self):
        """El resultado debe ser Decimal para evitar errores de punto flotante."""
        cuota = calcular_cuota_fija(Decimal("500000"), Decimal("0.0250"), 6)
        assert isinstance(cuota, Decimal)

    def test_cuota_dos_decimales(self):
        """El resultado debe tener exactamente 2 decimales."""
        cuota = calcular_cuota_fija(Decimal("750000"), Decimal("0.0350"), 24)
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
    """Tests para generación de fechas según periodicidad."""

    def test_mensual_suma_30_dias(self):
        fecha = date(2026, 1, 15)
        siguiente = siguiente_fecha_maxima(fecha, Periodicidad.mensual)
        assert siguiente == date(2026, 2, 14)

    def test_quincenal_suma_14_dias(self):
        fecha = date(2026, 1, 15)
        siguiente = siguiente_fecha_maxima(fecha, Periodicidad.quincenal)
        assert siguiente == date(2026, 1, 29)

    def test_semanal_suma_7_dias(self):
        fecha = date(2026, 1, 15)
        siguiente = siguiente_fecha_maxima(fecha, Periodicidad.semanal)
        assert siguiente == date(2026, 1, 22)

    def test_diario_suma_1_dia(self):
        fecha = date(2026, 1, 15)
        siguiente = siguiente_fecha_maxima(fecha, Periodicidad.diario)
        assert siguiente == date(2026, 1, 16)

    def test_mensual_cruce_anio(self):
        """30 de diciembre + 30 días = 29 de enero del año siguiente."""
        fecha = date(2026, 12, 30)
        siguiente = siguiente_fecha_maxima(fecha, Periodicidad.mensual)
        assert siguiente == date(2027, 1, 29)
