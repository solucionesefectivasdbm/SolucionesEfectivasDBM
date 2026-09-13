"""add veces_aplazado to pagos

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-09-12 00:00:00.000000

DDL only. Additive column with server_default='0' — existing rows read 0
with no backfill and no downtime.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'pagos',
        sa.Column(
            'veces_aplazado',
            sa.Integer(),
            nullable=False,
            server_default='0',
            comment="Cantidad de veces que la fecha máxima fue aplazada a "
                    "solicitud del cliente. Solo aumenta; 0 = nunca aplazado.",
        ),
    )
    op.create_check_constraint(
        'ck_pagos_veces_aplazado_no_negativo',
        'pagos',
        'veces_aplazado >= 0',
    )


def downgrade() -> None:
    op.drop_constraint('ck_pagos_veces_aplazado_no_negativo', 'pagos', type_='check')
    op.drop_column('pagos', 'veces_aplazado')
