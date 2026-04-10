"""
utils/tz.py — Zona horaria centralizada para Colombia.

Archivo separado sin imports de modelos para evitar dependencias circulares.
Usado por base_model.py (AuditMixin) y cualquier módulo que necesite
la hora de Bogotá.
"""
from datetime import datetime, date, timezone, timedelta

# Colombia: UTC-5, sin horario de verano
TZ_BOGOTA = timezone(timedelta(hours=-5))


def ahora_bogota() -> datetime:
    """Retorna el datetime actual en hora de Bogotá (naive, sin tzinfo).

    Se retorna sin tzinfo porque asyncpg rechaza datetimes con zona horaria
    cuando la columna es TIMESTAMP WITHOUT TIME ZONE.
    """
    return datetime.now(TZ_BOGOTA).replace(tzinfo=None)


def hoy_bogota() -> date:
    """Retorna la fecha (date) actual en hora de Bogotá."""
    return ahora_bogota().date()
