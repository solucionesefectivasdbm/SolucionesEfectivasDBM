"""
tests/test_momentos.py — Tests unitarios para la lógica de momentos m1–m5.

Esta es la lógica más propensa a errores del sistema. El caso crítico
es m2 que cruza el límite de mes: días 1-4 de cualquier mes pertenecen
al m2 del mes ANTERIOR.

Cobertura completa de todos los rangos y casos borde.
"""
from datetime import date, timedelta

import pytest

from app.utils.momentos import (
    get_momento,
    get_mes_momento,
    get_periodo_momento,
    fecha_limite_mora,
    en_mora,
)


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

    # --- Febrero: m1 termina en el último día del mes (28 o 29) ---
    def test_m1_febrero_no_bisiesto(self):
        """Febrero 2027 no tiene día 29: m1 termina el 28 (antes: ValueError)."""
        inicio, fin = get_periodo_momento(2027, 2, "m1")
        assert inicio == date(2027, 2, 25)
        assert fin == date(2027, 2, 28)

    def test_m1_febrero_bisiesto(self):
        inicio, fin = get_periodo_momento(2028, 2, "m1")
        assert inicio == date(2028, 2, 25)
        assert fin == date(2028, 2, 29)

    # --- Febrero: m2 empieza el 1 de marzo (no hay día 30) ---
    def test_m2_febrero_no_bisiesto_empieza_marzo_1(self):
        """m2 de febrero no debe solaparse con m1 (25-28)."""
        inicio, fin = get_periodo_momento(2027, 2, "m2")
        assert inicio == date(2027, 3, 1)
        assert fin == date(2027, 3, 4)

    def test_m2_febrero_bisiesto_empieza_marzo_1(self):
        inicio, fin = get_periodo_momento(2028, 2, "m2")
        assert inicio == date(2028, 3, 1)
        assert fin == date(2028, 3, 4)

    def test_m2_mes_de_30_dias(self):
        """Abril tiene 30 días: m2 empieza el 30 como siempre."""
        inicio, fin = get_periodo_momento(2026, 4, "m2")
        assert inicio == date(2026, 4, 30)
        assert fin == date(2026, 5, 4)

    def test_property_agrees_con_get_momento(self):
        """
        Para CADA día de 2026-01-01..2028-12-31 (incluye febrero bisiesto
        2028): la fecha cae dentro del período que get_periodo_momento()
        devuelve para su (anio, mes, momento) según get_mes_momento() y
        get_momento(); y los rangos m1/m2 de cada mes no se solapan.
        """
        un_dia = timedelta(days=1)
        fecha = date(2026, 1, 1)
        fin = date(2028, 12, 31)
        iteraciones = 0
        while fecha <= fin:
            anio, mes = get_mes_momento(fecha)
            momento = get_momento(fecha)
            inicio, termino = get_periodo_momento(anio, mes, momento)
            assert inicio <= fecha <= termino, (fecha, momento, inicio, termino)
            fecha += un_dia
            iteraciones += 1
        assert iteraciones == 1096

        for anio in (2026, 2027, 2028):
            for mes in range(1, 13):
                _, fin_m1 = get_periodo_momento(anio, mes, "m1")
                inicio_m2, _ = get_periodo_momento(anio, mes, "m2")
                assert fin_m1 < inicio_m2, (anio, mes, fin_m1, inicio_m2)


class TestFechaLimiteMora:
    """
    fecha_limite_mora(hoy) — primer día del momento que contiene `hoy`.
    scheduled-overdue-evaluation: fin/fin+1 por momento (Mar 2026) + casos
    de cruce de mes/año y febrero.
    """

    # --- m5 (19-24): fin=24, fin+1=25 (pasa a m1) ---
    def test_m5_fin(self):
        assert fecha_limite_mora(date(2026, 3, 24)) == date(2026, 3, 19)

    def test_m5_fin_mas_1(self):
        assert fecha_limite_mora(date(2026, 3, 25)) == date(2026, 3, 25)

    # --- m1 (25-29): fin=29, fin+1=30 (pasa a m2) ---
    def test_m1_fin(self):
        assert fecha_limite_mora(date(2026, 3, 29)) == date(2026, 3, 25)

    def test_m1_fin_mas_1(self):
        assert fecha_limite_mora(date(2026, 3, 30)) == date(2026, 3, 30)

    # --- m2 (30..4 del mes siguiente): fin=Apr 4, fin+1=Apr 5 (pasa a m3) ---
    def test_m2_fin(self):
        assert fecha_limite_mora(date(2026, 4, 4)) == date(2026, 3, 30)

    def test_m2_fin_mas_1(self):
        assert fecha_limite_mora(date(2026, 4, 5)) == date(2026, 4, 5)

    # --- m3 (5-13): fin=13, fin+1=14 (pasa a m4) ---
    def test_m3_fin(self):
        assert fecha_limite_mora(date(2026, 3, 13)) == date(2026, 3, 5)

    def test_m3_fin_mas_1(self):
        assert fecha_limite_mora(date(2026, 3, 14)) == date(2026, 3, 14)

    # --- m4 (14-18): fin=18, fin+1=19 (pasa a m5) ---
    def test_m4_fin(self):
        assert fecha_limite_mora(date(2026, 3, 18)) == date(2026, 3, 14)

    def test_m4_fin_mas_1(self):
        assert fecha_limite_mora(date(2026, 3, 19)) == date(2026, 3, 19)

    # --- Cruce diciembre → enero ---
    def test_enero_1_a_4_limite_diciembre_30(self):
        assert fecha_limite_mora(date(2026, 1, 1)) == date(2025, 12, 30)
        assert fecha_limite_mora(date(2026, 1, 4)) == date(2025, 12, 30)

    # --- Marzo 1-4: febrero tiene < 30 días (28 o 29) → límite = día 1 de marzo ---
    def test_marzo_1_a_4_no_bisiesto_limite_marzo_1(self):
        assert fecha_limite_mora(date(2026, 3, 1)) == date(2026, 3, 1)
        assert fecha_limite_mora(date(2026, 3, 4)) == date(2026, 3, 1)

    def test_marzo_1_bisiesto_limite_marzo_1(self):
        assert fecha_limite_mora(date(2028, 3, 1)) == date(2028, 3, 1)

    # --- Febrero (m1 dentro del propio mes) ---
    def test_febrero_28_no_bisiesto(self):
        assert fecha_limite_mora(date(2026, 2, 28)) == date(2026, 2, 25)

    def test_febrero_29_bisiesto(self):
        assert fecha_limite_mora(date(2028, 2, 29)) == date(2028, 2, 25)


class TestEnMora:
    """en_mora(fecha_maxima, hoy) = fecha_maxima < fecha_limite_mora(hoy)."""

    def test_fm_27_hoy_28_no_en_mora(self):
        assert en_mora(date(2026, 3, 27), date(2026, 3, 28)) is False

    def test_fm_27_hoy_29_no_en_mora(self):
        assert en_mora(date(2026, 3, 27), date(2026, 3, 29)) is False

    def test_fm_27_hoy_30_en_mora(self):
        assert en_mora(date(2026, 3, 27), date(2026, 3, 30)) is True

    def test_fm_abril_2_hoy_abril_4_no_en_mora(self):
        assert en_mora(date(2026, 4, 2), date(2026, 4, 4)) is False

    def test_fm_abril_2_hoy_abril_5_en_mora(self):
        assert en_mora(date(2026, 4, 2), date(2026, 4, 5)) is True

    def test_fm_febrero_28_hoy_marzo_1_en_mora(self):
        assert en_mora(date(2026, 2, 28), date(2026, 3, 1)) is True

    def test_fm_diciembre_31_hoy_enero_4_no_en_mora(self):
        assert en_mora(date(2026, 12, 31), date(2027, 1, 4)) is False

    def test_fm_diciembre_31_hoy_enero_5_en_mora(self):
        assert en_mora(date(2026, 12, 31), date(2027, 1, 5)) is True

    def test_property_agrees_con_get_momento(self):
        """
        Para CADA día de 2026-01-01..2028-12-31 (incluye febrero bisiesto
        2028), fecha_limite_mora(hoy):
        (a) cae dentro del mismo momento (m1..m5) y mismo mes-momento que
            `hoy`, según get_momento() y get_mes_momento();
        (b) es el PRIMER día de ese momento: el día anterior pertenece a otro
            momento o a otro mes-momento.
        """
        un_dia = timedelta(days=1)
        hoy = date(2026, 1, 1)
        fin = date(2028, 12, 31)
        iteraciones = 0
        while hoy <= fin:
            limite = fecha_limite_mora(hoy)
            assert limite <= hoy, hoy
            # (a) mismo momento y mismo mes-momento
            assert get_momento(limite) == get_momento(hoy), hoy
            assert get_mes_momento(limite) == get_mes_momento(hoy), hoy
            # (b) primer día del momento
            anterior = limite - un_dia
            assert (
                get_momento(anterior) != get_momento(limite)
                or get_mes_momento(anterior) != get_mes_momento(limite)
            ), f"{limite} no es el primer día de su momento (hoy={hoy})"
            hoy += un_dia
            iteraciones += 1
        assert iteraciones == 1096
