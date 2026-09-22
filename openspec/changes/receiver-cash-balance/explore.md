# Exploration: Receiver Cash Balance (item 9, `receiver-cash-balance`, quoted $620,000 COP)

## Current State

**Receptor model** (`backend/app/models/receptor.py`): `id, nombre, cedula(unique), telefono` + AuditMixin (created_at/updated_at/deleted_at soft delete). 1:N to `CuentaBancaria` (entidad_bancaria, tipo_cuenta, numero_cuenta, es_predeterminada with partial-unique-index enforcing one default per receptor). No balance/ledger field exists today.

**Pago model** (`backend/app/models/pago.py`): has `cuenta_bancaria_id` (nullable FK, indexed) — NOT a direct `receptor_id`. `Pago.receptor_id` was dropped in migration `d4e5f6a7b8c9_drop_receptor_id_from_gestores_pagos.py` (2026-09-20) after item 11's clean-prod-week backfill/cutover. So: **money is attributed to a receptor only via `Pago.cuenta_bancaria_id -> CuentaBancaria.receptor_id`**.

Payment lifecycle: `pagado` (bool, set by registrador when payment recorded — `pago_service.py`), `validado_recaudador` (separate QA confirmation by recaudador/admin via `POST /pagos/{id}/validar`/`desvalidar` in `routers/pagos.py` — orthogonal to money custody, do not conflate with "collected"). Signal for money physically collected under a receptor = `pagado=True` + `cuenta_bancaria_id` set.

**Existing aggregation precedent** — `backend/app/routers/reportes.py` (`GET /reportes`, admin-only): computes `por_receptor`/`por_cuenta` totals per año/mes/momento, entirely **compute-on-read**: loads all `Pago` rows in period, joins in-memory to `CuentaBancaria→Receptor`, accumulates dicts, sorts deterministically (explicit comment about byte-identical float sums). No persisted total anywhere. Closest structural precedent — but strictly period-scoped, not all-time/running.

**Denormalized-field bug history**: `Cliente.al_dia` is intentionally denormalized but manually-set (safe, not computed). By contrast, `Credito.saldo_capital`/`saldo_intereses` are persisted running balances that caused TWO separate multi-PR bug-fix efforts (project memory: "Fix arrastre abono_capital" PRs #30-#33, "Fix bugs arrastre Mattos/Sanabria" PRs #36-#39) plus prod backfills, from drifting out of sync with `Pago` history under carryover edge cases. Strong local evidence against persisted running balances for money tracking; `reportes.py`'s compute-on-read pattern has no equivalent incident history.

**Roles** (`backend/app/models/usuario.py`): `admin`, `registrador`, `recaudador`, `gestor`. Current `receptores.py`: list allows `admin`+`recaudador`; all other receptor/cuenta endpoints are `admin`-only. `reportes.py` is `admin`-only. Payment registration (`pagado=True`) done by `registrador`; QA validation (`validado_recaudador`) by `recaudador`/`admin`.

**Audit pattern**: `AuditLog` (`backend/app/models/audit_log.py`) is a generic flat immutable field-diff log (entidad, entidad_id, accion, campo_modificado, valor_anterior/nuevo, usuario_id, fecha_accion, ip_origen) via `audit_service.registrar_creacion/actualizacion_campos/eliminacion`. It does NOT model debit/credit ledger semantics or "salidas" — a receptor ledger needs a purpose-built table.

**Migration conventions**: ALL `op.create_table` calls live in the single `d9144df95951_initial.py` migration; every later migration (`a1b2c3d4e5f6`, `b2c3d4e5f6a7`, `c3d4e5f6a7b8`, `d4e5f6a7b8c9`) only adds/drops columns/indexes/FKs. **There is no precedent in this repo for a new-table migration post-initial** — item 9 would be the first. Conventions to replicate: `postgresql.UUID(as_uuid=True)` PK + `default=uuid.uuid4`, AuditMixin with `ahora_bogota()`-based timestamps (or no `deleted_at` if append-only, per `AuditLog`), `Numeric(15,2)` for currency, explicit named FK/index constraints (see `es_predeterminada` partial-unique-index pattern).

**Frontend**: `frontend/src/pages/Receptores/ReceptoresPage.tsx` is CRUD+modals (list/search/paginate, create/edit/delete receptor, nested "Cuentas" modal for bank accounts with add/edit/mark-default). No balance/ledger UI exists. Natural extension: balance badge in the table (new `GET /receptores/{id}/saldo`), plus a "Movimientos" modal mirroring the "Cuentas" modal pattern, using the existing `ConfirmarCreacion` confirm-step pattern for registering a salida.

**Tests**: `test_reportes_por_cuenta.py`, `test_pagos_cuenta_bancaria.py`, `test_pagos_router.py`, `test_desvalidar_pago.py`, `test_reportes_arrastre.py` establish the pattern — router-level async FastAPI tests with role-scoped auth, plus exhaustive edge-case service tests for arrastre/carryover math. Ledger correction math should follow `test_reportes_arrastre.py`'s exhaustiveness given the carryover-bug history.

## Affected Areas

- `backend/app/models/receptor.py` — new ledger/movement model
- `backend/app/routers/receptores.py` — new salida/correction/balance endpoints
- `backend/app/routers/reportes.py` — do not duplicate its aggregation logic; item 13 may extend it later
- `backend/app/services/` — new `receptor_ledger_service.py` (or similar)
- `backend/alembic/versions/` — first post-initial `create_table` migration, needs extra review care
- `frontend/src/pages/Receptores/ReceptoresPage.tsx` — balance + salida/correction UI
- `frontend/src/api`, `frontend/src/types` — new types/API client methods
- `backend/tests/` — new ledger correctness tests patterned on `test_reportes_arrastre.py`

## Approaches

1. **Compute-on-read (extend reportes.py pattern), no persisted balance** — sum collected `Pago` amounts via `cuenta_bancaria_id → Receptor` minus a new lightweight `salidas` table.
   - Pros: matches the only existing precedent; avoids drift risk (directly avoids the arrastre bug class); no backfill needed for the collected side.
   - Cons: all-time aggregation over the full `Pago` table could need index tuning as data grows (existing `ix_pagos_cuenta_bancaria_id` helps but a receptor has 1..N cuentas).
   - Effort: Medium.

2. **Persisted running balance field on `Receptor`** (wallet-style).
   - Pros: O(1) reads, simple UI badge.
   - Cons: this exact pattern (persisted balance drifting from ledger) has caused two separate multi-PR bug-fix efforts in this codebase (`saldo_capital`/`saldo_intereses`). High long-term risk given direct local precedent of failure.
   - Effort: Medium build, High risk.

3. **Full dedicated ledger table recording recaudo + salida + correccion as rows.**
   - Pros: single source of truth, audit-friendly, cleanly supports item 13's daily report via date-filtered ledger rows, corrections as offsetting rows (never mutate history).
   - Cons: requires backfilling a `recaudo` row for every historical `pago` (non-trivial, idempotency risk), duplicates data already on `Pago` (two sources of truth unless strictly derived/read-only).
   - Effort: High.

## Recommendation

**Hybrid of 1 and 3**: new `receptor_movimientos` ledger table restricted to `salida` and `correccion` rows only (these have no other source of truth) — do NOT duplicate `recaudo` rows. Balance = `SUM(collected Pago via cuenta_bancaria join, pagado=True) - SUM(salidas) +/- corrections`, computed on read like `reportes.py`. Gets ledger traceability for outflows/corrections and item-13 readiness, while avoiding backfill risk and the proven persisted-balance drift bug class.

## Permission Proposal

- Register `salida`: likely `admin`-only initially (mirrors current receptor CRUD), but recaudador may be the more natural cash-handling role — **needs owner decision**.
- Register `correccion`: recommend `admin`-only, no exceptions.
- Read balance/ledger: `admin` + `recaudador` (mirrors current receptor-list split); item 13 may need recaudador read access too.

## UI Surface

- "Saldo" badge/column on `ReceptoresPage.tsx` table (new `GET /receptores/{id}/saldo`).
- New "Movimientos" modal (mirrors existing "Cuentas" modal) listing salidas/correcciones with running balance, plus a salida registration form using the existing `ConfirmarCreacion` confirm-step pattern.
- Corrections likely need a separate, more restricted form (admin-only, justification text required).

## Open Business Questions (must be answered before proposal)

1. Reassignment timing: when `Pago.cuenta_bancaria_id` changes after `pagado=True`, does the balance move retroactively? (Naturally yes under the compute-on-read hybrid — confirm this is desired.)
2. Who can register salidas — admin only, or also recaudador?
3. Can corrections subtract as well as add? Do they need a justification field / approval step?
4. Balance scope: all-time running, or period-scoped like `reportes.py`'s año/mes/momento? Item 13 (daily report) suggests date filtering matters.
5. Overdraft protection: can a salida exceed the current computed balance — reject, warn, or purely informational?
6. Do ledger entries survive receptor soft-delete? (Recommend yes, like `AuditLog`.)
7. Should salidas be scoped to a specific `cuenta_bancaria_id`, or receptor-level only?
8. Should the model anticipate item 10 (clients as receivers), or is that explicitly deferred?

## Risks

- No precedent for a new-table migration post-initial — treat the migration as its own carefully reviewed PR slice (cf. item 11's PR1a-PR4 split).
- Pressure to cache the balance as a `Receptor` field for UI performance — this repo has two prior incidents from exactly that shortcut; any future cached field must be reconciled/tested against the compute-on-read source of truth.
- Reassignment semantics ambiguity (open question 1) could produce surprising balance jumps if not decided and tested up front.
- Item 13 coupling: ledger date/period fields need item 13 in mind now, or item 13 forces a later schema change.
- Backfill scope for the new `salidas`/`correcciones` table is zero (empty at launch) — risk-reducer vs. option 3, opposite profile from item 11's backfill-heavy migrations.

## Estimated Changed-Lines Forecast vs 400-line Budget

Slice 1 (model + migration + service + read-only balance endpoint + tests): ~250-350 lines. Slice 2 (salida/correction write endpoints + frontend UI): ~300-400 lines. **Recommend at least 2 PR slices** to stay under the 400-line budget, following item 11's precedent of small sequential slices.

## Readiness Assessment

**Not ready for proposal** — the 8 open business questions above must be answered first, especially #1 (reassignment semantics), #2 (who registers salidas), #3 (correction rules), #4 (balance scope). Once answered, the hybrid data-model recommendation gives enough clarity to move to `sdd-propose`.
