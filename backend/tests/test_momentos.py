"""
tests/test_momentos.py — Tests unitarios para la lógica de momentos m1–m5.

Esta es la lógica más propensa a errores del sistema. El caso crítico
es m2 que cruza el límite de mes: días 1-4 de cualquier mes pertenecen
al m2 del mes ANTERIOR.

Cobertura completa de todos los rangos y casos borde.
"""
from datetime import date

import pytest

from app.utils.momentos import get_momento, get_mes_momento, get_periodo_momento


class TestGetMomento:
    """Tests para la función get_momento()."""

    # --- m1: días 25-29 ---
    def test_m1_dia_25(self):
        assert get_momento(date(2026, 3, 25)) == "m1"

    def test_m1_dia_27(self):
        assert get_momento(date(2026, 3, 27)) == "m1"

    def test_m1_dia_29(self):
        assert get_momento(date(2026, 3, 29)) == "m1"

    # --- m2: día 30 al 4 del siguiente mes ---
    def test_m2_dia_30(self):
        assert get_momento(date(2026, 3, 30)) == "m2"

    def test_m2_dia_31(self):
        """Meses con 31 días."""
        assert get_momento(date(2026, 3, 31)) == "m2"

    def test_m2_dia_1_es_m2_del_mes_anterior(self):
        """CRÍTICO: día 1 de marzo pertenece al m2 de FEBRERO."""
        assert get_momento(date(2026, 3, 1)) == "m2"

    def test_m2_dia_2(self):
        assert get_momento(date(2026, 4, 2)) == "m2"

    def test_m2_dia_3(self):
        assert get_momento(date(2026, 5, 3)) == "m2"

    def test_m2_dia_4(self):
        assert get_momento(date(2026, 6, 4)) == "m2"

    def test_m2_enero_dia_1(self):
        """Enero 1 → m2 de diciembre del año anterior."""
        assert get_momento(date(2026, 1, 1)) == "m2"

    def test_m2_enero_dia_4(self):
        assert get_momento(date(2026, 1, 4)) == "m2"

    # --- m3: días 5-13 ---
    def test_m3_dia_5(self):
        assert get_momento(date(2026, 3, 5)) == "m3"

    def test_m3_dia_9(self):
        assert get_momento(date(2026, 3, 9)) == "m3"

    def test_m3_dia_13(self):
        assert get_momento(date(2026, 3, 13)) == "m3"

    # --- m4: días 14-18 ---
    def test_m4_dia_14(self):
        assert get_momento(date(2026, 3, 14)) == "m4"

    def test_m4_dia_16(self):
        assert get_momento(date(2026, 3, 16)) == "m4"

    def test_m4_dia_18(self):
        assert get_momento(date(2026, 3, 18)) == "m4"

    # --- m5: días 19-24 ---
    def test_m5_dia_19(self):
        assert get_momento(date(2026, 3, 19)) == "m5"

    def test_m5_dia_22(self):
        assert get_momento(date(2026, 3, 22)) == "m5"

    def test_m5_dia_24(self):
        assert get_momento(date(2026, 3, 24)) == "m5"

    # --- Límites entre momentos ---
    def test_limite_m5_m1(self):
        """Día 24 es m5, día 25 es m1."""
        assert get_momento(date(2026, 3, 24)) == "m5"
        assert get_momento(date(2026, 3, 25)) == "m1"

    def test_limite_m1_m2(self):
        """Día 29 es m1, día 30 es m2."""
        assert get_momento(date(2026, 3, 29)) == "m1"
        assert get_momento(date(2026, 3, 30)) == "m2"

    def test_limite_m2_m3(self):
        """Día 4 es m2, día 5 es m3."""
        assert get_momento(date(2026, 3, 4)) == "m2"
        assert get_momento(date(2026, 3, 5)) == "m3"

    def test_limite_m3_m4(self):
        """Día 13 es m3, día 14 es m4."""
        assert get_momento(date(2026, 3, 13)) == "m3"
        assert get_momento(date(2026, 3, 14)) == "m4"

    def test_limite_m4_m5(self):
        """Día 18 es m4, día 19 es m5."""
        assert get_momento(date(2026, 3, 18)) == "m4"
        assert get_momento(date(2026, 3, 19)) == "m5"

    def test_febrero_28_m1(self):
        """Febrero 28 en año no bisiesto."""
        assert get_momento(date(2026, 2, 28)) == "m1"

    def test_febrero_29_bisiesto_m1(self):
        """Febrero 29 en año bisiesto."""
        assert get_momento(date(2028, 2, 29)) == "m1"

    def test_diciembre_30_m2(self):
        """30 de diciembre es m2 de diciembre."""
        assert get_momento(date(2026, 12, 30)) == "m2"

    def test_diciembre_31_m2(self):
        """31 de diciembre es m2 de diciembre."""
        assert get_momento(date(2026, 12, 31)) == "m2"


class TestGetMesMomento:
    """
    Tests para get_mes_momento() — determina a qué mes/año PERTENECE
    el momento, considerando el cruce de mes en m2.
    """

    def test_marzo_15_pertenece_a_marzo(self):
        anio, mes = get_mes_momento(date(2026, 3, 15))
        assert anio == 2026
        assert mes == 3

    def test_marzo_1_pertenece_a_febrero(self):
        """CRÍTICO: 1 de marzo → m2 de FEBRERO."""
        anio, mes = get_mes_momento(date(2026, 3, 1))
        assert anio == 2026
        assert mes == 2

    def test_enero_3_pertenece_a_diciembre_anio_anterior(self):
        """3 de enero → m2 de DICIEMBRE del año anterior."""
        anio, mes = get_mes_momento(date(2026, 1, 3))
        assert anio == 2025
        assert mes == 12

    def test_marzo_30_pertenece_a_marzo(self):
        """30 de marzo → m2 de MARZO (no de abril)."""
        anio, mes = get_mes_momento(date(2026, 3, 30))
        assert anio == 2026
        assert mes == 3

    def test_marzo_5_pertenece_a_marzo(self):
        anio, mes = get_mes_momento(date(2026, 3, 5))
        assert anio == 2026
        assert mes == 3


class TestGetPeriodoMomento:
    """Tests para get_periodo_momento() — rango de fechas de un período."""

    def test_m1_rango(self):
        inicio, fin = get_periodo_momento(2026, 3, "m1")
        assert inicio == date(2026, 3, 25)
        assert fin == date(2026, 3, 29)

    def test_m2_rango(self):
        inicio, fin = get_periodo_momento(2026, 3, "m2")
        assert inicio == date(2026, 3, 30)
        assert fin == date(2026, 4, 4)

    def test_m2_diciembre_cruce_anio(self):
        """m2 de diciembre termina el 4 de enero del año siguiente."""
        inicio, fin = get_periodo_momento(2026, 12, "m2")
        assert inicio == date(2026, 12, 30)
        assert fin == date(2027, 1, 4)

    def test_m3_rango(self):
        inicio, fin = get_periodo_momento(2026, 3, "m3")
        assert inicio == date(2026, 3, 5)
        assert fin == date(2026, 3, 13)

    def test_m4_rango(self):
        inicio, fin = get_periodo_momento(2026, 3, "m4")
        assert inicio == date(2026, 3, 14)
        assert fin == date(2026, 3, 18)

    def test_m5_rango(self):
        inicio, fin = get_periodo_momento(2026, 3, "m5")
        assert inicio == date(2026, 3, 19)
        assert fin == date(2026, 3, 24)

    def test_momento_invalido(self):
        with pytest.raises(ValueError, match="Momento inválido"):
            get_periodo_momento(2026, 3, "m6")
