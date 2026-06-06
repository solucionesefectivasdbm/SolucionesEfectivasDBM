"""
utils/fechas.py — Generación de fechas_maxima según periodicidad.

DECISIÓN TÉCNICA (original): Usamos timedelta simple para semanal/diario.
DECISIÓN TÉCNICA (anchor): mensual y quincenal usan anchor_dia_1/anchor_dia_2
del crédito para anclar la cuota al mismo día del mes cada período, con clamp
via calendar.monthrange para meses cortos (Febrero, Abril, etc.).
stdlib only — no dateutil.

Zona horaria: todas las funciones de "ahora" usan America/Bogota (UTC-5).
Railway y la BD corren en UTC, pero el negocio opera en hora colombiana.
"""
import calendar
import logging
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

from app.models.credito import Periodicidad
from app.utils.tz import TZ_BOGOTA, ahora_bogota, hoy_bogota  # re-exportar

if TYPE_CHECKING:
    from app.models.credito import Credito


def _fecha_en_dia_ancla(anio: int, mes: int, dia_ancla: int) -> date:
    """Returns date(anio, mes, dia_ancla) clamped to the last day of the month."""
    ultimo_dia = calendar.monthrange(anio, mes)[1]
    return date(anio, mes, min(dia_ancla, ultimo_dia))


def _avanzar_mes(anio: int, mes: int) -> tuple[int, int]:
    """Advances (anio, mes) by one calendar month, rolling over December→January."""
    mes += 1
    if mes > 12:
        mes = 1
        anio += 1
    return anio, mes


def _siguiente_mensual(fecha_anterior: date, dia_ancla: int) -> date:
    """Next mensual due date: one month forward, clamped to dia_ancla."""
    anio, mes = _avanzar_mes(fecha_anterior.year, fecha_anterior.month)
    return _fecha_en_dia_ancla(anio, mes, dia_ancla)


def _siguiente_quincenal(fecha_anterior: date, d1: int, d2: int) -> date:
    """Next quincenal due date using anchor alternation.

    d1 < d2. The next date is the smallest anchor-date strictly greater than
    fecha_anterior. Comparison uses the CLAMPED candidate date (not .day ==
    d2) so that short-month clamps alternate correctly.
    """
    cand_d2 = _fecha_en_dia_ancla(fecha_anterior.year, fecha_anterior.month, d2)
    if fecha_anterior < cand_d2:
        return cand_d2  # d2 anchor still in the future this month
    # fecha_anterior >= cand_d2 → move to d1 in the next month
    anio, mes = _avanzar_mes(fecha_anterior.year, fecha_anterior.month)
    return _fecha_en_dia_ancla(anio, mes, d1)


def siguiente_fecha_maxima(fecha_anterior: date, credito: "Credito") -> date:
    """
    Calcula la próxima fecha_maxima dado la fecha anterior y el crédito.

    DECISIÓN TÉCNICA: mensual y quincenal usan anchor_dia_1/anchor_dia_2 del
    crédito para anclar la fecha al día correcto del mes. semanal/diario siguen
    usando timedelta fijo (+7, +1) y no consultan los campos anchor.

    Retrocompatibilidad: si un crédito mensual/quincenal aún no tiene anchors
    asignados (NULL — créditos legacy pre-migración), se usa el comportamiento
    anterior (+30/+14 días) como fallback seguro. Los anchors se asignan al
    crear/editar el crédito o vía la ventana de edición de días de pago.

    Args:
        fecha_anterior: La fecha_maxima de la cuota anterior
                        (o fecha_inicial_pago para la primera cuota).
        credito: El objeto Credito con periodicidad y campos anchor.

    Returns:
        La fecha_maxima de la siguiente cuota.
    """
    p = credito.periodicidad
    if p == Periodicidad.mensual:
        if credito.anchor_dia_1 is not None:
            return _siguiente_mensual(fecha_anterior, credito.anchor_dia_1)
        # Legacy fallback: no anchor yet — warn so ops can track backfill progress
        credito_id = getattr(credito, "id", None)
        logger.warning(
            "siguiente_fecha_maxima: anchor NULL para credito_id=%s periodicidad=%s — usando fallback +30d",
            credito_id,
            p.value,
        )
        return fecha_anterior + timedelta(days=30)
    if p == Periodicidad.quincenal:
        if credito.anchor_dia_1 is not None and credito.anchor_dia_2 is not None:
            return _siguiente_quincenal(fecha_anterior, credito.anchor_dia_1, credito.anchor_dia_2)
        # Legacy fallback: no anchor yet — warn so ops can track backfill progress
        credito_id = getattr(credito, "id", None)
        logger.warning(
            "siguiente_fecha_maxima: anchor NULL para credito_id=%s periodicidad=%s — usando fallback +14d",
            credito_id,
            p.value,
        )
        return fecha_anterior + timedelta(days=14)
    # semanal/diario: timedelta fixo, anchors ignorados
    dias = 7 if p == Periodicidad.semanal else 1
    return fecha_anterior + timedelta(days=dias)


def calcular_interes_primera_cuota(
    saldo_capital: "Decimal",  # type: ignore[name-defined]
    tasa_mensual: "Decimal",   # type: ignore[name-defined]
    fecha_apertura: date,
    fecha_inicial_pago: date,
) -> "Decimal":
    """
    Calcula el interés de la primera cuota cuando se usa días corridos.

    Fórmula: interes = saldo_capital * tasa_mensual * (dias / 30)

    Se activa cuando la diferencia entre fecha_inicial_pago y la fecha
    que dictaría la periodicidad desde fecha_apertura es >= 10 días.

    Args:
        saldo_capital: Capital del crédito.
        tasa_mensual: Tasa de interés mensual (ej: Decimal("0.0300")).
        fecha_apertura: Fecha de apertura del crédito.
        fecha_inicial_pago: Fecha del primer pago.

    Returns:
        Decimal con el interés proporcional.
    """
    from decimal import Decimal, ROUND_HALF_UP

    dias = (fecha_inicial_pago - fecha_apertura).days
    interes = saldo_capital * tasa_mensual * (Decimal(dias) / Decimal(30))
    return interes.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def debe_usar_dias_corridos(
    fecha_apertura: date,
    fecha_inicial_pago: date,
    periodicidad: Periodicidad,
) -> bool:
    """
    Determina si aplica el cálculo de interés por días corridos.

    Se habilita cuando la diferencia entre fecha_inicial_pago y la fecha
    que dictaría la periodicidad a partir de fecha_apertura es >= 10 días.

    Args:
        fecha_apertura: Fecha de apertura.
        fecha_inicial_pago: Fecha del primer pago seleccionada por el usuario.
        periodicidad: Periodicidad del crédito.

    Returns:
        True si la opción debe estar disponible para activar.
    """
    delta_map = {
        Periodicidad.mensual: 30,
        Periodicidad.quincenal: 14,
        Periodicidad.semanal: 7,
        Periodicidad.diario: 1,
    }
    dias_periodo = delta_map[periodicidad]
    fecha_dictada = fecha_apertura + timedelta(days=dias_periodo)
    diferencia = abs((fecha_inicial_pago - fecha_dictada).days)
    return diferencia >= 10
