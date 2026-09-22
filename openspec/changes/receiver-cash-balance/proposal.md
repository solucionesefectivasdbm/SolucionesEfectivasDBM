# Proposal: Receiver Cash Balance (item 9)

## Intent

Receptores (money custodians) have no visible cash balance today. Admins cannot see how much a `cuenta_bancaria` currently holds, register cash taken out (`salida`), or correct manual discrepancies. This creates operational blind spots for reconciling physical/bank cash against collected `Pago` history. Goal: give admins a reliable, per-bank-account balance view plus controlled outflow/correction tracking, without repeating the two prior persisted-running-balance drift incidents (`saldo_capital`/`saldo_intereses`).

## Scope

### In Scope
- New `receptor_movimientos` ledger table (append-only) recording only `salida` and `correccion` rows, scoped to `cuenta_bancaria_id`.
- Compute-on-read balance per `cuenta_bancaria_id` = collected `Pago` sum (via existing `cuenta_bancaria_id` join, `pagado=True`) − salidas + corrections (following `reportes.py`'s pattern).
- `salida` registration: `admin`-only, blocked if it would exceed current computed balance (hard reject, not a warning). Permission check must not hardcode `admin` in a way that blocks adding `registrador` later.
- `correccion` registration: `admin`-only, positive or negative, optional free-text note.
- Read endpoints: balance per cuenta_bancaria, movement history.
- UI: balance badge/column on `ReceptoresPage.tsx`, "Movimientos" modal (salida/correction forms + history), following the existing "Cuentas" modal and `ConfirmarCreacion` confirm-step pattern.
- Tests patterned on `test_reportes_arrastre.py`'s exhaustiveness given carryover-bug history.

### Out of Scope
- No periodic reset/cierre of balances — running total forever (mandatory, non-negotiable).
- No date-range filtering UI for movements in this change (stretch goal only if trivial; otherwise deferred to item 13, daily collection/distribution report).
- No `registrador` permission for salidas (future change, item 13-adjacent).
- No anticipation of item 10 (clients as receivers) — deferred, flagged as assumption below.
- No persisted/cached balance field on `Receptor`/`CuentaBancaria`.

## Capabilities

### New Capabilities
- `receptor-ledger`: salida/correction ledger entries and compute-on-read balance per cuenta_bancaria.

### Modified Capabilities
- None.

## Approach

Hybrid of compute-on-read + minimal ledger (per exploration recommendation): balance is never persisted. `salida`/`correccion` are the only two row types stored — `recaudo` stays derived from `Pago`, no backfill needed. Balance scope is `cuenta_bancaria_id`, not `receptor_id` — a receptor's cuentas are independent wallets. `Pago.cuenta_bancaria_id` reassignment after `pagado=True` moves balance retroactively by design (accepted, not a bug). Migration is the first post-initial `create_table` in this repo — treat as its own reviewed PR slice, following `AuditMixin` conventions (UUID PK, `Numeric(15,2)`, explicit constraints).

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `backend/app/models/receptor.py` | New | `MovimientoReceptor` ledger model |
| `backend/alembic/versions/` | New | First post-initial `create_table` migration |
| `backend/app/services/receptor_ledger_service.py` | New | Balance calc, overdraft check, salida/correccion writes |
| `backend/app/routers/receptores.py` | Modified | New salida/correction/balance/history endpoints |
| `frontend/src/pages/Receptores/ReceptoresPage.tsx` | Modified | Balance badge + Movimientos modal |
| `backend/tests/` | New | Ledger correctness + overdraft tests |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| New-table migration has no repo precedent | Medium | Isolate as its own reviewed PR slice |
| Pressure to cache balance later, repeating drift bug | Medium | Document compute-on-read as mandatory invariant in design |
| >400-line PR budget | High | Split into 2 PRs: (1) model+migration+read balance+tests, (2) write endpoints+UI |
| Reassignment causing surprising balance jumps if untested | Low | Explicit test case for retroactive move |

## Rollback Plan

Both PR slices are additive (new table, new endpoints, new UI section) with no changes to existing `Pago`/`CuentaBancaria` read paths. Revert via standard PR revert; migration has a clean `downgrade()` dropping the new table only.

## Dependencies

- None blocking. Item 13 (daily report) may later read this ledger's date fields.

## Success Criteria

- [ ] Admin can view current balance per `cuenta_bancaria_id`, matching `SUM(Pago) - SUM(salidas) +/- corrections`.
- [ ] Salida rejected with clear error when it would exceed current balance.
- [ ] Correction supports positive/negative with optional note, admin-only.
- [ ] Reassigning `Pago.cuenta_bancaria_id` after `pagado=True` moves balance correctly (test-covered).
- [ ] Both PR slices stay under 400 changed lines each.

## Proposal question round

Not run in this session (auto mode; owner already answered the 6 binding decisions listed by the orchestrator). Two exploration questions remain open and are carried as assumptions, not blockers:

1. **Ledger entries surviving receptor soft-delete**: assumed **yes** (mirrors `AuditLog`'s immutability) — confirm during design.
2. **Anticipating item 10 (clients as receivers)**: assumed **no** — explicitly deferred, schema should not be contorted to pre-support it.
