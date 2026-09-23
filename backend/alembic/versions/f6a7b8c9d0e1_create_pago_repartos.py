"""create pago_repartos (PR1, payment-multi-recipient foundation)

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-09-22 00:00:00.000000

Creates the `pago_repartos` satellite ledger table (payment-multi-recipient,
item 10) and backfills one 100%-allocation row per already-paid `Pago` that
has a `cuenta_bancaria_id` and a positive total — establishing invariant I1
("every paid pago with a cuenta has repartos summing exactly to its total")
for existing data before `receptor_ledger_service.saldos_por_cuenta` starts
reading from this table instead of `Pago.cuenta_bancaria_id` directly.

The `capital_pagado + interes_pagado > 0` filter is required by the
`ck_pago_repartos_monto_positivo` CHECK constraint (monto > 0) — zero-amount
paid pagos contribute nothing to the ledger either way, so parity holds
without a row for them. `deleted_at IS NULL` on `pagos` matches the same
filter `receptor_ledger_service.saldos_por_cuenta` applies on read — a
soft-deleted pago must not get a reparto row. The backfill INSERT is
idempotent (`NOT EXISTS` against `pago_repartos`), so re-running this
upgrade never duplicates rows.

`gen_random_uuid()` requires Postgres >= 13 (built in via pgcrypto-less
core as of 13). Confirmed 2026-09-22: prod runs PostgreSQL 18 (Railway).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'f6a7b8c9d0e1'
down_revision: Union[str, None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'pago_repartos',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('pago_id', sa.UUID(), nullable=False),
        sa.Column(
            'tipo_destinatario',
            sa.Enum('cuenta_bancaria', 'cliente', name='tipo_destinatario_reparto_enum'),
            nullable=False,
        ),
        sa.Column('cuenta_bancaria_id', sa.UUID(), nullable=True),
        sa.Column('cliente_id', sa.UUID(), nullable=True),
        sa.Column('monto', sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.CheckConstraint('monto > 0', name='ck_pago_repartos_monto_positivo'),
        sa.CheckConstraint(
            "(tipo_destinatario = 'cuenta_bancaria' AND cuenta_bancaria_id IS NOT NULL AND cliente_id IS NULL) "
            "OR (tipo_destinatario = 'cliente' AND cliente_id IS NOT NULL AND cuenta_bancaria_id IS NULL)",
            name='ck_pago_repartos_destinatario',
        ),
        sa.ForeignKeyConstraint(['pago_id'], ['pagos.id'], ),
        sa.ForeignKeyConstraint(['cuenta_bancaria_id'], ['cuentas_bancarias.id'], ),
        sa.ForeignKeyConstraint(['cliente_id'], ['clientes.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_pago_repartos_pago_id', 'pago_repartos', ['pago_id'],
    )
    op.create_index(
        'ix_pago_repartos_cuenta_bancaria_id', 'pago_repartos', ['cuenta_bancaria_id'],
    )

    # Backfill: una fila al 100% por cada Pago ya pagado (no borrado) con
    # cuenta asignada. `deleted_at IS NULL` iguala el filtro que
    # receptor_ledger_service.saldos_por_cuenta aplica en el lado de
    # lectura — un pago borrado lógicamente no debe generar reparto.
    # `NOT EXISTS` hace el backfill idempotente: re-ejecutar este upgrade
    # (p.ej. un replay manual) no duplica filas.
    # `now() - interval '5 hours'` iguala ahora_bogota() (UTC-5, ver
    # app/utils/tz.py) — las filas creadas en runtime por
    # crear_reparto_por_defecto usan ese mismo helper vía AuditMixin.
    op.execute(
        """
        INSERT INTO pago_repartos (id, pago_id, tipo_destinatario, cuenta_bancaria_id, monto, created_at, updated_at)
        SELECT gen_random_uuid(), pagos.id, 'cuenta_bancaria', pagos.cuenta_bancaria_id,
               pagos.capital_pagado + pagos.interes_pagado,
               now() - interval '5 hours', now() - interval '5 hours'
        FROM pagos
        WHERE pagos.pagado
          AND pagos.deleted_at IS NULL
          AND pagos.cuenta_bancaria_id IS NOT NULL
          AND pagos.capital_pagado + pagos.interes_pagado > 0
          AND NOT EXISTS (
              SELECT 1 FROM pago_repartos WHERE pago_repartos.pago_id = pagos.id
          )
        """
    )


def downgrade() -> None:
    op.drop_index('ix_pago_repartos_cuenta_bancaria_id', table_name='pago_repartos')
    op.drop_index('ix_pago_repartos_pago_id', table_name='pago_repartos')
    op.drop_table('pago_repartos')
    # Postgres NO elimina el tipo ENUM al hacer drop_table — hay que hacerlo
    # explícito o un upgrade() posterior choca con "type already exists".
    sa.Enum(name='tipo_destinatario_reparto_enum').drop(op.get_bind())
