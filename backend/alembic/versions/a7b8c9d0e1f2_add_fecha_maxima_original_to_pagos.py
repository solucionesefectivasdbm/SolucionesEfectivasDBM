"""add fecha_maxima_original to pagos (mora cutoff by original momento)

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-09-25 00:00:00.000000

Nullable at the DB level on purpose (design.md decision D2): the temporary
admin backfill (PR4, `POST /admin/migracion/fecha-maxima-original`) still
needs to distinguish "never touched" from "resolved" while it rebuilds
deferred rows from `audit_log`. New rows get the column filled by the
`before_insert` mapper listener on `Pago` (PR1, `app/models/pago.py`), not
by a DB-level default, so it stays in sync with the exact `fecha_maxima`
passed at construction time.

The backfill UPDATE here only covers what this migration can prove clean
without `audit_log`: every existing row gets its current `fecha_maxima`
copied in. Rows that were deferred BEFORE this deploy will show the wrong
(deferred) value here — the temporary admin endpoint corrects those from
`audit_log` in a later step of the rollout, per design.md's "Backfill
Algorithm". `WHERE fecha_maxima_original IS NULL` makes the UPDATE
idempotent — replaying this upgrade never overwrites an already-set value.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'a7b8c9d0e1f2'
down_revision: Union[str, None] = 'f6a7b8c9d0e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'pagos',
        sa.Column(
            'fecha_maxima_original', sa.Date(), nullable=True,
            comment="Corte de mora inmutable del momento original del pago. "
                    "Se fija una sola vez al crear el pago (before_insert "
                    "listener) y no cambia con aplazamientos puntuales.",
        ),
    )
    op.execute(
        "UPDATE pagos SET fecha_maxima_original = fecha_maxima "
        "WHERE fecha_maxima_original IS NULL"
    )
    op.create_index(
        'ix_pagos_fecha_maxima_original', 'pagos', ['fecha_maxima_original'],
    )


def downgrade() -> None:
    op.drop_index('ix_pagos_fecha_maxima_original', table_name='pagos')
    op.drop_column('pagos', 'fecha_maxima_original')
