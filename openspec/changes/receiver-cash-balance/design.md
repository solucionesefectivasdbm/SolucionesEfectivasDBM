# Design: Receiver Cash Balance (item 9)

## Technical Approach

Compute-on-read balance per `cuenta_bancaria_id` (never persisted), plus one append-only
`receptor_movimientos` table holding only `salida` and `correccion` rows. `recaudo` stays derived
from `Pago` — no backfill, no second source of truth. Aggregation style follows `reportes.py`
(join `Pago → CuentaBancaria → Receptor` via `cuenta_bancaria_id`), but uses grouped SQL
`SUM` + `Decimal` instead of in-memory float loops, because the overdraft check must be exact.

**Mandatory invariant**: no cached/persisted balance column on `Receptor`/`CuentaBancaria`, ever.
This is the direct lesson of the `saldo_capital`/`saldo_intereses` drift incidents (PRs #30-#33, #36-#39).

## Architecture Decisions

| Decision | Choice | Rejected | Rationale |
|---|---|---|---|
| Balance storage | Compute-on-read | Persisted running total | Two prior multi-PR drift incidents in this repo |
| Ledger rows | `salida` + `correccion` only | Also mirror `recaudo` rows | Avoids backfill + dual truth for `Pago` |
| Scope key | `cuenta_bancaria_id` | `receptor_id` | Owner decision 1; cuentas are independent wallets |
| Money type | `Decimal` (`Numeric(15,2)`) | `float` like `reportes.py` | Overdraft rejection must be exact; `reportes.py` keeps float only for byte-identical legacy sums |
| Correction sign | Signed `monto` on one row type | Separate `correccion_positiva`/`negativa` enums | Owner decision 4; one CHECK covers both |
| Overdraft race | `SELECT … FOR UPDATE` on the parent `cuentas_bancarias` row | Optimistic retry / DB CHECK | Ledger has no single row to lock; parent-row lock serializes per cuenta; repo already handles races at DB level (partial unique index) |
| Immutability | No `deleted_at`, no `updated_at`, no UPDATE/DELETE endpoints | `AuditMixin` | Mirrors `AuditLog`; errors are fixed by an offsetting `correccion`. Ledger rows survive receptor soft-delete (proposal assumption 1 → confirmed) |
| Permissions | Module-level role tuples | Literals inside `require_role(...)` | Owner decision 3: adding `registrador` becomes a one-line diff |
| Date filtering | Deferred to item 13 | Stretch goal now | Owner decision 5; `created_at` is already indexed for it |

## Data Model

`backend/app/models/receptor_movimiento.py` (new module; `receptor.py` keeps Receptor+CuentaBancaria):

```python
class TipoMovimiento(str, enum.Enum):
    salida = "salida"
    correccion = "correccion"

class MovimientoReceptor(Base):          # no AuditMixin — immutable, like AuditLog
    __tablename__ = "receptor_movimientos"
    id: UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    cuenta_bancaria_id: UUID FK("cuentas_bancarias.id"), nullable=False
    tipo: Enum(TipoMovimiento, name="tipo_movimiento_receptor_enum"), nullable=False
    monto: Numeric(15, 2), nullable=False        # salida > 0; correccion != 0, any sign
    nota: Text, nullable=True                    # optional free text (decision 4)
    usuario_id: UUID FK("users.id"), nullable=False
    created_at: DateTime, nullable=False, default=ahora_bogota
    __table_args__ = (
        CheckConstraint(
            "(tipo = 'salida' AND monto > 0) OR (tipo = 'correccion' AND monto <> 0)",
            name="ck_receptor_movimientos_monto_por_tipo"),
        Index("ix_receptor_movimientos_cuenta_bancaria_id", "cuenta_bancaria_id"),
        Index("ix_receptor_movimientos_created_at", "created_at"),   # item 13 readiness
    )
```

`Usuario` gets `movimientos_receptor` backref (mirrors `audit_logs`).

## Migration Plan

`backend/alembic/versions/e5f6a7b8c9d0_create_receptor_movimientos.py`,
`down_revision = 'd4e5f6a7b8c9'`. **First post-initial `create_table` in this repo** — ships alone
in slice 1 and is reviewed as such.

- `upgrade()`: `op.create_table('receptor_movimientos', …)` copying the `audit_log` block style from
  `d9144df95951_initial.py` (`sa.UUID()`, `sa.Enum(..., name='tipo_movimiento_receptor_enum')`,
  `sa.Numeric(15, 2)`, explicit `sa.ForeignKeyConstraint`, `sa.PrimaryKeyConstraint`,
  `sa.CheckConstraint`), then the two `op.create_index` calls.
- `downgrade()`: `op.drop_index` ×2, `op.drop_table`, then
  `sa.Enum(name='tipo_movimiento_receptor_enum').drop(op.get_bind())` — Postgres does not drop the
  enum type with the table. Zero data loss risk: the table is empty at launch.
- No backfill, no data migration. Deploy auto-runs `alembic upgrade head` (per the 2026-06-06 incident fix).

## Balance Computation

`backend/app/services/receptor_ledger_service.py`:

```
saldo(cuenta) = recaudado − salidas + correcciones

recaudado  = SUM(Pago.capital_pagado + Pago.interes_pagado)
             WHERE Pago.cuenta_bancaria_id = cuenta
               AND Pago.pagado IS TRUE AND Pago.deleted_at IS NULL
salidas    = SUM(monto) WHERE tipo = 'salida'      AND cuenta_bancaria_id = cuenta
correcciones = SUM(monto) WHERE tipo = 'correccion' AND cuenta_bancaria_id = cuenta   # signed
```

Two grouped queries (`GROUP BY cuenta_bancaria_id`, `.in_(cuenta_ids)`), `COALESCE → Decimal("0.00")`,
never a per-row Python loop and never N+1. Public functions:

```python
async def saldos_por_cuenta(db, cuenta_ids: list[UUID]) -> dict[UUID, SaldoCuenta]
async def saldos_por_receptor(db, receptor_ids: list[UUID]) -> dict[UUID, SaldoReceptor]
async def listar_movimientos(db, receptor_id, cuenta_bancaria_id=None, page, page_size)
async def registrar_movimiento(db, cuenta_id, tipo, monto, nota, usuario_id) -> MovimientoReceptor
```

Deleted `Pago` rows and `pagado=False` rows are excluded; reassigning `Pago.cuenta_bancaria_id`
after `pagado=True` therefore moves balance retroactively — intended (owner decision 2), test-covered.

## Overdraft Check (race-safe)

Inside `registrar_movimiento`, before any read of the sums:

```python
await db.execute(select(CuentaBancaria.id)
                 .where(CuentaBancaria.id == cuenta_id)
                 .with_for_update())          # serializes concurrent salidas per cuenta
saldo = (await saldos_por_cuenta(db, [cuenta_id]))[cuenta_id].saldo
if tipo is TipoMovimiento.salida and monto > saldo:
    raise HTTPException(409, f"La salida excede el saldo disponible ({saldo})")
db.add(MovimientoReceptor(...)); await db.flush()
```

The lock is held until `get_db()` commits at end of request, so two concurrent salidas against the
same `cuenta_bancaria_id` serialize and the second re-reads the post-insert balance. Corrections skip
the overdraft check (decision 4) but take the same lock for consistent ordering. Note: SQLite
(test DB) ignores `FOR UPDATE`, so the race itself is Postgres-only behavior — covered by a statement
-compilation assertion test plus manual staging verification, not by a concurrent pytest.

## Schemas

`backend/app/schemas/receptor_movimiento.py`:

| Schema | Fields |
|---|---|
| `MovimientoCreate` | `monto: Decimal` (`gt=0` for salida route), `nota: str \| None` (max 500) |
| `CorreccionCreate` | `monto: Decimal` (validator: `!= 0`), `nota: str \| None` |
| `MovimientoResponse` | `id, cuenta_bancaria_id, tipo, monto, nota, usuario_id, usuario_nombre, created_at` |
| `SaldoCuentaResponse` | `cuenta_bancaria_id, etiqueta, es_predeterminada, recaudado, salidas, correcciones, saldo` |
| `SaldoReceptorResponse` | `receptor_id, saldo_total, por_cuenta: list[SaldoCuentaResponse]` |

`etiqueta` reuses `cuenta_bancaria_service.etiqueta_cuenta`.

## Endpoints (`backend/app/routers/receptores.py`)

```python
ROLES_LECTURA_SALDO = ("admin", "recaudador")   # matches listar_receptores
ROLES_SALIDA        = ("admin",)                # add "registrador" here later — 1-line diff
ROLES_CORRECCION    = ("admin",)
```

| Method | Path | Roles | Slice |
|---|---|---|---|
| GET | `/receptores/saldos?receptor_ids=a,b,c` | `ROLES_LECTURA_SALDO` | 1 |
| GET | `/receptores/{receptor_id}/saldo` | `ROLES_LECTURA_SALDO` | 1 |
| GET | `/receptores/{receptor_id}/movimientos?cuenta_bancaria_id&page&page_size` → `PaginatedResponse[MovimientoResponse]` | `ROLES_LECTURA_SALDO` | 1 |
| POST | `/receptores/{receptor_id}/cuentas/{cuenta_id}/salidas` → 201 `MovimientoResponse` | `ROLES_SALIDA` | 2 |
| POST | `/receptores/{receptor_id}/cuentas/{cuenta_id}/correcciones` → 201 `MovimientoResponse` | `ROLES_CORRECCION` | 2 |

Write routes validate that `cuenta_id` belongs to `receptor_id` (404 otherwise), and call
`audit_service.registrar_creacion(entidad="receptor_movimientos", …)` with `get_client_ip(request)`,
matching every other write in this router. Overdraft → `409` with a Spanish detail message.
Routes are declared after the existing `/cuentas` block; `/receptores/saldos` is registered **before**
`/receptores/{receptor_id}` to avoid the UUID path-param shadowing it.

## Data Flow

    POST .../salidas ──→ require_role(*ROLES_SALIDA)
             │
             ↓
    receptor_ledger_service.registrar_movimiento
             │  1. SELECT cuentas_bancarias FOR UPDATE
             │  2. SUM(Pago) − SUM(salida) + SUM(correccion)   [Decimal]
             │  3. reject if monto > saldo (409)
             │  4. INSERT receptor_movimientos  + audit_log
             ↓
    get_db() COMMIT (lock released) ──→ MovimientoResponse

    GET /receptores/saldos ──→ 2 grouped SUM queries ──→ badge on ReceptoresPage

## File Changes

| File | Action | Slice |
|---|---|---|
| `backend/app/models/receptor_movimiento.py` | Create | 1 |
| `backend/app/models/usuario.py` | Modify (backref) | 1 |
| `backend/alembic/versions/e5f6a7b8c9d0_create_receptor_movimientos.py` | Create | 1 |
| `backend/app/schemas/receptor_movimiento.py` | Create | 1 |
| `backend/app/services/receptor_ledger_service.py` | Create | 1 |
| `backend/app/routers/receptores.py` | Modify (read endpoints) | 1 |
| `backend/tests/test_receptor_ledger_service.py` | Create | 1 |
| `backend/tests/test_receptores_saldo_router.py` | Create | 1 |
| `backend/app/routers/receptores.py` | Modify (write endpoints) | 2 |
| `backend/tests/test_receptores_movimientos_router.py` | Create | 2 |
| `frontend/src/types/index.ts` | Modify | 2 |
| `frontend/src/api/index.ts` | Modify | 2 |
| `frontend/src/pages/Receptores/ReceptoresPage.tsx` | Modify | 2 |

## PR Slice Boundary

**Slice 1 — "ledger foundation" (~250-350 lines, backend only, no user-visible behavior change)**
model + migration (its own scrutiny focus) + schemas + service (balance, pagination, `registrar_movimiento`
incl. lock and overdraft guard) + the three GET endpoints + tests. Ships and is mergeable alone: read-only,
always returns `recaudado` with zero movements.

**Slice 2 — "movements + UI" (~300-400 lines)** two POST endpoints wired to the already-tested service,
router tests (201, 403 per role, 409 overdraft, 404 cuenta-mismatch, negative correction), plus the
entire frontend surface. Targets slice 1's branch (Feature Branch Chain) to keep the diff clean.

## Frontend Surface (slice 2, high level)

- `frontend/src/types/index.ts`: `TipoMovimiento`, `MovimientoReceptor`, `SaldoCuenta`, `SaldoReceptor`.
- `frontend/src/api/index.ts`, on `receptoresApi`: `saldos(receptorIds)`, `saldo(id)`,
  `movimientos(id, params)`, `registrarSalida(receptorId, cuentaId, data)`,
  `registrarCorreccion(receptorId, cuentaId, data)`.
- `ReceptoresPage.tsx`: after `cargar()` resolves the page, one `saldos(ids)` call fills a
  `saldosMap` state → "Saldo" badge column (green ≥ 0, amber 0, formatted COP). New
  `modalMovimientos` mirroring `modalCuentas`: per-cuenta saldo breakdown + paginated history +
  "Registrar salida" / "Registrar corrección" forms (admin-only, hidden for `recaudador`) reusing
  `FormField` and the `ConfirmarCreacion` two-step confirm already used by `modalConfirmarCuenta`.
  Overdraft 409 surfaces via the existing `toast.error(detail)` path.

## Testing Strategy

| Layer | What | How |
|---|---|---|
| Unit (service) | Balance math: no pagos; `pagado=False` ignored; soft-deleted `Pago` ignored; salida subtracts; positive/negative correccion; multi-cuenta isolation (one receptor, two cuentas); `Decimal` cent precision | `test_receptor_ledger_service.py`, exhaustive in the style of `test_reportes_arrastre.py` |
| Unit | Reassigning `Pago.cuenta_bancaria_id` after `pagado=True` moves the balance from cuenta A to cuenta B | Explicit named test (proposal success criterion) |
| Unit | Overdraft statement compiles with `FOR UPDATE` | Assert on the compiled Postgres statement (SQLite ignores it) |
| Integration | GET saldo/saldos/movimientos: roles 200/403, 404 unknown receptor, pagination shape | Router tests like `test_reportes_por_cuenta.py` |
| Integration | POST salida 201; 409 exactly-over-balance; 200 at exactly-equal balance; 403 `registrador`/`recaudador`; 404 cuenta of another receptor; correccion negative allowed, zero rejected; `audit_log` row written | `test_receptores_movimientos_router.py` (slice 2) |
| Manual | Two concurrent salidas on staging Postgres both attempting to drain the same cuenta → exactly one succeeds | OPS check before slice 2 release |

## Threat Matrix

N/A — no routing changes, shell commands, subprocesses, VCS/PR automation, executable-file
classification, or process integration. The only adversarial surface is authorization plus the
overdraft race, both handled as explicit design requirements and RED tests above.

## Migration / Rollout

Additive only. Slice 1 deploys the empty table (auto `alembic upgrade head`); no behavior change for
existing users. Slice 2 enables writes and UI. Rollback: revert the PR; `downgrade()` drops the table
and its enum type. No backfill in either direction.

## Open Questions

- [ ] None blocking. Proposal assumption 1 (ledger survives receptor soft-delete) is resolved **yes** —
      `receptor_movimientos` has no `deleted_at` and is never cascaded from `Receptor`. Assumption 2
      (item 10 anticipation) remains explicitly deferred: schema stays keyed to `cuenta_bancaria_id` only.
