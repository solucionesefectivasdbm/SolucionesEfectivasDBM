"""
base_model.py — Mixin de auditoría compartido por todos los modelos.

DECISIÓN TÉCNICA: AuditMixin usa mapped_column de SQLAlchemy 2.x (estilo moderno
con type hints). Todos los modelos heredan estos campos para tener trazabilidad
completa. deleted_at implementa el borrado lógico — nunca hacemos DELETE físico.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Mapped, mapped_column


class AuditMixin:
    """Campos de auditoría presentes en todas las entidades del sistema."""

    created_at: Mapped[datetime] = mapped_column(
        default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        nullable=True,
        default=None,
    )
