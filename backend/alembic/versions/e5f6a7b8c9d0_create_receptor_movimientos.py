"""create receptor_movimientos (PR1, ledger foundation)

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-09-22 00:00:00.000000

First post-initial `create_table` migration in this repo (receiver-cash-
balance, item 9). Creates the append-only `receptor_movimientos` ledger
table (`salida` and `correccion` rows only — `recaudo` stays derived from
`Pago`, no backfill needed either direction). No cached/persisted balance
column anywhere; the balance is always computed on read (see
receptor_ledger_service.py). Table ships empty: zero data loss risk.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'receptor_movimientos',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('cuenta_bancaria_id', sa.UUID(), nullable=False),
        sa.Column('tipo', sa.Enum('salida', 'correccion', name='tipo_movimiento_receptor_enum'), nullable=False),
        sa.Column('monto', sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column('nota', sa.Text(), nullable=True),
        sa.Column('usuario_id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "(tipo = 'salida' AND monto > 0) OR (tipo = 'correccion' AND monto <> 0)",
            name='ck_receptor_movimientos_monto_por_tipo',
        ),
        sa.ForeignKeyConstraint(['cuenta_bancaria_id'], ['cuentas_bancarias.id'], ),
        sa.ForeignKeyConstraint(['usuario_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_receptor_movimientos_cuenta_bancaria_id', 'receptor_movimientos', ['cuenta_bancaria_id'],
    )
    op.create_index(
        'ix_receptor_movimientos_created_at', 'receptor_movimientos', ['created_at'],
    )


def downgrade() -> None:
    op.drop_index('ix_receptor_movimientos_created_at', table_name='receptor_movimientos')
    op.drop_index('ix_receptor_movimientos_cuenta_bancaria_id', table_name='receptor_movimientos')
    op.drop_table('receptor_movimientos')
    # Postgres NO elimina el tipo ENUM al hacer drop_table — hay que hacerlo
    # explícito o un upgrade() posterior choca con "type already exists".
    sa.Enum(name='tipo_movimiento_receptor_enum').drop(op.get_bind())
