"""
utils/momentos.py — Lógica de cálculo de momentos m1–m5.

DECISIÓN TÉCNICA: Esta es la lógica más propensa a errores del sistema.
El caso crítico es m2: los días 1–4 de cualquier mes pertenecen al m2
del MES ANTERIOR. Esto significa que si un pago vence el 3 de marzo,
su momento es m2 de febrero (no de marzo).

Esto tiene implicaciones en los reportes: al filtrar por "febrero m2"
aparecerán pagos con fecha_maxima entre el 30 de enero y el 4 de febrero.

Los tests unitarios de este módulo son OBLIGATORIOS.
"""
from datetime import date


def get_momento(fecha: date) -> str:
    """
    Determina el momento (m1..m5) al que pertenece una fecha.

    Rangos:
        m1: días 25-29 del mes
        m2: día 30 del mes hasta día 4 del mes siguiente
            (días 1-4 de cualquier mes → m2 del mes anterior)
        m3: días 5-13 del mes
        m4: días 14-18 del mes
        m5: días 19-24 del mes

    Args:
        fecha: La fecha a clasificar.

    Returns:
        String "m1", "m2", "m3", "m4" o "m5".
    """
    dia = fecha.day

    # CRÍTICO: días 1-4 siempre pertenecen al m2 del mes anterior
    if dia <= 4:
        return "m2"

    if 5 <= dia <= 13:
        return "m3"

    if 14 <= dia <= 18:
        return "m4"

    if 19 <= dia <= 24:
        return "m5"

    if 25 <= dia <= 29:
        return "m1"

    # día 30 (y 31 si existe, aunque los reqs no lo mencionan)
    if dia >= 30:
        return "m2"

    # No debería llegar aquí
    raise ValueError(f"Fecha inválida: {fecha}")


def get_mes_momento(fecha: date) -> tuple[int, int]:
    """
    Retorna (año, mes) al que PERTENECE el momento de la fecha.

    Esto es distinto al mes calendario de la fecha. Los días 1-4
    de un mes pertenecen al m2 del mes anterior.

    Ejemplo: fecha 2026-03-03 → momento m2, pero pertenece a febrero 2026
             → retorna (2026, 2)

    Ejemplo: fecha 2026-02-28 → momento m1 de febrero
             → retorna (2026, 2)

    Ejemplo: fecha 2026-03-30 → momento m2, pertenece a marzo 2026
             → retorna (2026, 3)
    """
    dia = fecha.day

    # Los días 1-4 pertenecen al mes anterior
    if dia <= 4:
        if fecha.month == 1:
            return (fecha.year - 1, 12)
        return (fecha.year, fecha.month - 1)

    return (fecha.year, fecha.month)


def get_periodo_momento(anio: int, mes: int, momento: str) -> tuple[date, date]:
    """
    Retorna el rango de fechas (inicio, fin) que corresponde a un
    momento específico en un mes/año dado.

    Útil para filtrar pagos en el módulo de reportes y pagos.

    Args:
        anio: Año (ej: 2026)
        mes: Mes calendario (1-12)
        momento: "m1", "m2", "m3", "m4" o "m5"

    Returns:
        Tupla (fecha_inicio, fecha_fin) inclusive.
    """
    import calendar

    if momento == "m1":
        # días 25-29 del mes
        inicio = date(anio, mes, 25)
        fin = date(anio, mes, 29)
        return (inicio, fin)

    elif momento == "m2":
        # día 30 del mes hasta día 4 del mes siguiente
        # Manejo especial: algunos meses no tienen día 30
        ultimo_dia = calendar.monthrange(anio, mes)[1]
        if ultimo_dia >= 30:
            inicio = date(anio, mes, 30)
        else:
            # Febrero: empieza en día 1 del mes siguiente
            inicio = date(anio, mes, ultimo_dia)

        # fin: día 4 del mes siguiente
        if mes == 12:
            fin = date(anio + 1, 1, 4)
        else:
            fin = date(anio, mes + 1, 4)
        return (inicio, fin)

    elif momento == "m3":
        inicio = date(anio, mes, 5)
        fin = date(anio, mes, 13)
        return (inicio, fin)

    elif momento == "m4":
        inicio = date(anio, mes, 14)
        fin = date(anio, mes, 18)
        return (inicio, fin)

    elif momento == "m5":
        inicio = date(anio, mes, 19)
        fin = date(anio, mes, 24)
        return (inicio, fin)

    else:
        raise ValueError(f"Momento inválido: {momento}. Debe ser m1..m5")
