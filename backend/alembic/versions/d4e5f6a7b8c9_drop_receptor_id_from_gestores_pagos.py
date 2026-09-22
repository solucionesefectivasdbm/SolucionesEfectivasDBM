"""drop receptor_id from gestores/pagos (PR4 cleanup)

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-09-20 00:00:00.000000

DDL only. Drops the deprecated `receptor_id` FKs/columns on `gestores` and
`pagos` now that `cuenta_bancaria_id` fully replaces them (receiver-bank-
account-assignment, decision 7). Requires a clean prod week after the
backfill (PR1b) and cutover (PR2a/PR2b) with `pendientes` == 0 before this
runs — see OPS-9/OPS-10 in tasks.md.

Downgrade re-adds the nullable columns + FKs and repopulates them from
`cuentas_bancarias.receptor_id` via the current `cuenta_bancaria_id`.
Rows whose `cuenta_bancaria_id IS NULL` cannot recover their original
`receptor_id` (it is lost on upgrade), which is why OPS-10 requires that
count to be 0 on `gestores` and `pagos` before this upgrade runs.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint('pagos_receptor_id_fkey', 'pagos', type_='foreignkey')
    op.drop_column('pagos', 'receptor_id')

    op.drop_constraint('gestores_receptor_id_fkey', 'gestores', type_='foreignkey')
    op.drop_column('gestores', 'receptor_id')


def downgrade() -> None:
    op.add_column('gestores', sa.Column('receptor_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        'gestores_receptor_id_fkey', 'gestores', 'receptores', ['receptor_id'], ['id'],
    )

    op.add_column('pagos', sa.Column('receptor_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        'pagos_receptor_id_fkey', 'pagos', 'receptores', ['receptor_id'], ['id'],
    )

    op.execute(
        """
        UPDATE gestores
        SET receptor_id = (
            SELECT cuentas_bancarias.receptor_id
            FROM cuentas_bancarias
            WHERE cuentas_bancarias.id = gestores.cuenta_bancaria_id
        )
        WHERE gestores.cuenta_bancaria_id IS NOT NULL
        """
    )
    op.execute(
        """
        UPDATE pagos
        SET receptor_id = (
            SELECT cuentas_bancarias.receptor_id
            FROM cuentas_bancarias
            WHERE cuentas_bancarias.id = pagos.cuenta_bancaria_id
        )
        WHERE pagos.cuenta_bancaria_id IS NOT NULL
        """
    )
