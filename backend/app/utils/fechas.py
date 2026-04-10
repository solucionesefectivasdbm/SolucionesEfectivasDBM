"""
utils/fechas.py — Generación de fechas_maxima según periodicidad.

DECISIÓN TÉCNICA: Usamos timedelta simple (no relativedelta de dateutil)
porque los requerimientos definen períodos fijos en días (30, 14, 7, 1),
no "1 mes calendario". Esto es intencional: evita ambigüedad en meses
cortos (febrero) y garantiza consistencia en todos los cálculos.

Zona horaria: todas las funciones de "ahora" usan America/Bogota (UTC-5).
Railway y la BD corren en UTC, pero el negocio opera en hora colombiana.
"""
from datetime import date, datetime, timedelta, timezone

from app.models.credito import Periodicidad
from app.utils.tz import TZ_BOGOTA, ahora_bogota, hoy_bogota  # re-exportar


def siguiente_fecha_maxima(fecha_anterior: date, periodicidad: Periodicidad) -> date:
    """
    Calcula la próxima fecha_maxima dado la fecha anterior y la periodicidad.

    Args:
        fecha_anterior: La fecha_maxima de la cuota anterior
                        (o fecha_inicial_pago para la primera cuota).
        periodicidad: mensual/quincenal/semanal/diario

    Returns:
        La fecha_maxima de la siguiente cuota.
    """
    delta_map = {
        Periodicidad.mensual: 30,
        Periodicidad.quincenal: 14,
        Periodicidad.semanal: 7,
        Periodicidad.diario: 1,
    }
    dias = delta_map[periodicidad]
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
