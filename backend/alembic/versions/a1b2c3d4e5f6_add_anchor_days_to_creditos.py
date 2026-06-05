"""add anchor days to creditos

Revision ID: a1b2c3d4e5f6
Revises: d9144df95951
Create Date: 2026-06-05 23:00:00.000000

DDL only — no data backfill. Data derivation is handled by the
idempotent admin endpoint POST /admin/migracion/anclar-fechas.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'd9144df95951'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'creditos',
        sa.Column(
            'anchor_dia_1',
            sa.Integer(),
            nullable=True,
            comment="Dia-del-mes ancla (1-31). mensual: el dia unico. "
                    "quincenal: el dia mas temprano (d1<d2). NULL para semanal/diario y legacy.",
        ),
    )
    op.add_column(
        'creditos',
        sa.Column(
            'anchor_dia_2',
            sa.Integer(),
            nullable=True,
            comment="Segundo dia-del-mes ancla (1-31), solo quincenal (d1<d2). NULL en el resto.",
        ),
    )
    op.create_check_constraint(
        'ck_creditos_anchor_dia_1_rango',
        'creditos',
        'anchor_dia_1 IS NULL OR (anchor_dia_1 BETWEEN 1 AND 31)',
    )
    op.create_check_constraint(
        'ck_creditos_anchor_dia_2_rango',
        'creditos',
        'anchor_dia_2 IS NULL OR (anchor_dia_2 BETWEEN 1 AND 31)',
    )


def downgrade() -> None:
    op.drop_constraint('ck_creditos_anchor_dia_2_rango', 'creditos', type_='check')
    op.drop_constraint('ck_creditos_anchor_dia_1_rango', 'creditos', type_='check')
    op.drop_column('creditos', 'anchor_dia_2')
    op.drop_column('creditos', 'anchor_dia_1')
