# Verify Report: payment-multi-recipient (item 10)

**Date**: 2026-09-22
**Verdict**: PASS
**Scope**: PR1 (#51, 846b588), PR2 (#52/#53, e9e26da/36b120e), spec-cleanup (#54, cf58f9d) — all merged to `main`. Working tree clean.

## Test Execution Evidence

- Backend: `cd backend && venv/Scripts/python.exe -m pytest -q` → **624 passed, 0 failed** (11 warnings, all pre-existing/unrelated: deprecated `event_loop` fixture, `AsyncMockMixin` unawaited coroutine in mocked tests, `datetime.utcnow()` deprecation in `jose`).
- Frontend: `cd frontend && npx tsc --noEmit` → **exit 0, no errors**.

## Spec Compliance Matrix

### `specs/pago-repartos/spec.md`

| Requirement | Status | Evidence |
|---|---|---|
| Split Allocation Persistence | PASS | `pago_reparto_service.reemplazar_repartos` persists N rows with mutually-exclusive `cuenta_bancaria_id`/`cliente_id`; `RepartoItem` model_validator enforces exactly-one-id. Covered by `test_pago_reparto_service.py::TestReemplazarRepartos`. |
| Split Integrity Validation (exact `Decimal` equality) | PASS | `reemplazar_repartos` line 192-198: `suma != esperado` exact compare, no TOL. Spec prose fixed in PR4 cleanup (cf58f9d) to state exact equality (was stale TOL wording — correctly flagged in tasks.md Deviations and fixed). |
| Client-Type Split Never Creates Credit | PASS | `reemplazar_repartos` never touches `Credito`; `Cliente` existence/soft-delete checked via id lookup only, no free text accepted (schema requires `cliente_id: UUID`). |
| Direct Split Edit and Delete | PASS | `PUT /pagos/{id}/repartos` replaces the whole set (soft-delete + insert), admin/recaudador only (`require_role`), no correction-record kept — matches design's "no correction flow" decision. |
| Account Inheritance Only From a Single Cuenta Recipient | PASS | `cuenta_heredable`: len!=1 → None; single `cliente` recipient → None (returns None because `cuenta_bancaria_id` is None on that dict). Verified against code directly, matches the corrected spec text (post Judgment-Day-PR2 owner refinement). |
| Revenue Reports Attribute Split Pagos Per Cuenta | PASS | `reportes.py` reads `filas_repartos` (active, `tipo_destinatario=cuenta_bancaria`) joined/grouped by `cuenta_bancaria_id`, prorates capital/interest by each reparto's share; client rows excluded by construction (only `cuenta_bancaria`-typed repartos are queried). |

### `specs/receptor-ledger/spec.md` (delta)

| Requirement | Status | Evidence |
|---|---|---|
| Compute-on-read balance from `pago_repartos` | PASS | `receptor_ledger_service.saldos_por_cuenta`: `SUM(PagoReparto.monto)` joined to `Pago`, filtered `PagoReparto.deleted_at IS NULL`, `Pago.pagado`, `Pago.deleted_at IS NULL`. No persistence/cache. Backfill migration provides historical parity. |

### `specs/receiver-bank-account-assignment/spec.md` (delta)

| Requirement | Status | Evidence |
|---|---|---|
| Cascading Filters via `pago_repartos` (EXISTS, no dupes) | PASS | `pagos.py` `GET /pagos` filter uses `exists(select(PagoReparto.id).where(...))` OR'd with the legacy pending-pago column match — confirmed no JOIN-based duplication. |
| Individual Payment Account Change (legacy PATCH kept) | PASS | `PATCH /pagos/{id}/cuenta-bancaria` still present, calls `_get_pago_con_credito(lock=True)` (Judgment Day PR1 fix), syncs `pago_repartos` via `reemplazar_por_cuenta_unica`. Spec's "REMOVED" section was correctly rewritten as a second MODIFIED requirement in cf58f9d — confirmed the file now documents this as kept, matching shipped code. |

## Design Coherence (`design.md`)

All architecture decisions verified against code: satellite table (not N-Pago-rows), `PUT` replace-whole-set API, soft-delete removal, exact-Decimal sum check, split-only-when-paid, default-100%-reparto-on-registration, legacy-PATCH-kept, corrected inheritance rule, required-FK client recipient, EXISTS-based list filter, migration-embedded backfill. No deviations found beyond the two already self-documented and already fixed in tasks.md (stale TOL wording, stale "REMOVED" PATCH section) — both corrected in commit `cf58f9d`.

## Task Completion (`tasks.md`)

All tasks in Phase 1-4 marked `[x]`, each with runtime evidence (pytest pass counts, RED confirmations before GREEN). 3 Judgment Day rounds documented (PR1: 1 CRITICAL + 2 WARNING + 1 SUGGESTION fixed; PR2: 1 CRITICAL investigated → doc-only fix + 2 WARNING; PR3: 1 WARNING fixed) plus one manually-discovered-and-fixed CRITICAL frontend bug (`totalObjetivo` string concatenation from `Decimal`-as-JSON-string fields) during the PR3 manual smoke test, with a regression re-run confirming the fix. No unchecked tasks.

## Issues

None CRITICAL, none WARNING, none SUGGESTION outstanding — both self-flagged spec staleness items (TOL wording, PATCH "REMOVED" section) were already corrected in the spec-cleanup commit (`cf58f9d`) prior to this verification.

## Residual/Documented Debt (non-blocking, carried forward from design.md Open Questions)

- Migration backfill SQL was not executed against a real Postgres instance in this environment (no Postgres available locally) — verified only by code/SQL review matching design.md verbatim, plus `alembic heads` resolving cleanly. Per design's own Testing Strategy, staging Postgres parity check (Σ ledger before == after) remains a pre-prod-deploy manual step, not yet evidenced here.
- No overdraft check when money moves between cuentas via a split (explicitly accepted parity with item 9 decision 2 — not a gap, a stated design choice).
- Frontend has no automated test runner; PR3 coverage rests on `tsc --noEmit` plus the two Judgment Day rounds' manual code review and one manual browser smoke test (single-recipient path only — multi-recipient split save was exercised up to a 3-row in-progress UI state, not confirmed end-to-end via automation).

## Verdict

**PASS** — All 3 specs (pago-repartos, receptor-ledger delta, receiver-bank-account-assignment delta), design.md, and tasks.md are consistent with the code on `main`. Backend suite green (624/624), frontend typecheck clean. No CRITICAL or WARNING issues found in this independent review. Change is archive-ready; the Postgres-backfill-not-yet-run-in-prod item should be confirmed as an operational step (not a code gap) before/at deploy if not already done.
