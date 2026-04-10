"""
base_model.py — Mixin de auditoría compartido por todos los modelos.

DECISIÓN TÉCNICA: AuditMixin usa mapped_column de SQLAlchemy 2.x (estilo moderno
con type hints). Todos los modelos heredan estos campos para tener trazabilidad
completa. deleted_at implementa el borrado lógico — nunca hacemos DELETE físico.

Las fechas usan ahora_bogota() (UTC-5) en lugar de func.now() de PostgreSQL
(que retorna UTC) para que coincidan con la hora real de operación en Colombia.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Mapped, mapped_column

from app.utils.tz import ahora_bogota


class AuditMixin:
    """Campos de auditoría presentes en todas las entidades del sistema."""

    created_at: Mapped[datetime] = mapped_column(
        default=ahora_bogota,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        default=ahora_bogota,
        onupdate=ahora_bogota,
        nullable=False,
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        nullable=True,
        default=None,
    )
