"""add cuenta_bancaria assignment (default flag + gestores/pagos FKs)

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-09-15 00:00:00.000000

DDL only. Adds `cuentas_bancarias.es_predeterminada` plus nullable
`cuenta_bancaria_id` FKs on `gestores`/`pagos`. No data backfill here —
see the temporary admin backfill endpoint (PR1b).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('cuentas_bancarias', sa.Column(
        'es_predeterminada', sa.Boolean(), nullable=False, server_default=sa.false(),
        comment="True si es la cuenta predeterminada del receptor.",
    ))
    op.create_index(
        'uq_cuentas_bancarias_default_por_receptor', 'cuentas_bancarias', ['receptor_id'],
        unique=True, postgresql_where=sa.text('es_predeterminada'), sqlite_where=sa.text('es_predeterminada'),
    )

    op.add_column('gestores', sa.Column('cuenta_bancaria_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        'fk_gestores_cuenta_bancaria', 'gestores', 'cuentas_bancarias', ['cuenta_bancaria_id'], ['id'],
    )

    op.add_column('pagos', sa.Column('cuenta_bancaria_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        'fk_pagos_cuenta_bancaria', 'pagos', 'cuentas_bancarias', ['cuenta_bancaria_id'], ['id'],
    )
    op.create_index('ix_pagos_cuenta_bancaria_id', 'pagos', ['cuenta_bancaria_id'])


def downgrade() -> None:
    op.drop_index('ix_pagos_cuenta_bancaria_id', table_name='pagos')
    op.drop_constraint('fk_pagos_cuenta_bancaria', 'pagos', type_='foreignkey')
    op.drop_column('pagos', 'cuenta_bancaria_id')
    op.drop_constraint('fk_gestores_cuenta_bancaria', 'gestores', type_='foreignkey')
    op.drop_column('gestores', 'cuenta_bancaria_id')
    op.drop_index('uq_cuentas_bancarias_default_por_receptor', table_name='cuentas_bancarias')
    op.drop_column('cuentas_bancarias', 'es_predeterminada')
