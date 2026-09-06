# Proposal: Carry-over Payment Registration

## Intent

In `cuota_fija` credits with a pending arrastre, `_siguiente_cuota_fija` folds the
carry-over into `monto_a_pagar` but leaves `capital_a_pagar`/`interes_a_pagar` at
base values. `_validar_split` then rejects every exact payment (HTTP 422), so the
collector must refuse money or split it into two records. Live production credits
are affected today.

## Scope

### In Scope
- Distribute the carry-over into the per-component targets of the generated cuota.
- Allocation rule (owner decision): 100% to the component that produced the
  shortfall — `falta_capital = capital_a_pagar - capital_pagado`, likewise interest.
- Correct `_calcular_virtuales` so projections show the arrastre-inclusive amount.
- One-off admin-only POST backfill for pending rows already carrying arrastre.
- Real, unmocked backend tests for the arrastre path (`Decimal` assertions).

### Out of Scope (non-goals)
- `abono_capital` credits; its interest-only arrastre rule is unchanged.
- Surplus handling: the existing `destino_excedente` prompt stays. No
  advance-future-installment logic (item #2).
- Closing-rule / `bloqueador_map` redesign (item #3) and item #8.
- Weakening `_validar_split` caps for ordinary non-arrastre payments.

## Capabilities

### New Capabilities
- `payment-carryover`: how a `cuota_fija` shortfall is disaggregated, carried into
  the next cuota's components, validated, projected, and reported.

### Modified Capabilities
- None (no existing specs).

## Approach

**Recommended: in-process re-derivation, migration-free (approach 1).**
`generar_siguiente_cuota` already receives `cuota_anterior`, whose row persists
`capital_a_pagar/pagado` and `interes_a_pagar/pagado`. Pass it into
`_siguiente_cuota_fija` and add each shortfall to its own component. Because the
inflated components are themselves persisted, chained partials accumulate
correctly with no extra state, and the split is recoverable retroactively for the
backfill.

**Rejected: new persisted arrastre column (approach 2).** The audit trail is
derivable (`monto_a_pagar - base`) and `audit_service` already logs mutations. A
column costs an Alembic revision plus the idempotent `startup_create_tables` hook;
migration failures are logged but do not abort startup, so a live production DB
could silently serve NULL arrastre. Higher blast radius, likely over budget.

**Rejected: loosening the caps (approach 3).** Removes a guardrail for ordinary
payments and leaves the projector wrong.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `backend/app/services/credito_service.py:406-441` | Modified | Component-level carry-over distribution |
| `backend/app/routers/pagos.py:241-439` | Modified | Arrastre-aware virtual projection |
| `backend/app/routers/admin.py` (temp endpoint) | New | One-off backfill, deleted in a later commit |
| `backend/tests/test_credito_service.py`, `test_pago_service.py` | New | Unmocked arrastre coverage |
| `backend/app/services/pago_service.py:57-120` | Unchanged | Caps stay as guardrail |
| `frontend/` | Unchanged | Backend already surfaces amounts and errors |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Shared generation code used by all payment branches | Med | `abono_capital` path untouched; regression tests both types |
| `reportes.py:91-134` pending totals shift (they become correct) | High | Assert new totals in tests; note the change to the owner |
| Backfill mis-imputes historical rows | Low | Split re-derived from the persisted prior row, not guessed |
| Prior `saldo_capital`-reset-on-edit class of bug | Low | Backfill touches only `Pago` targets, never `Credito` saldos |

## Rollback Plan

Revert the commit. Component values are derived at generation time, so no schema
or data rollback is needed. Rows created while the fix was live keep correct
components and remain payable; reverting only restores the old rejection. The
backfill is idempotent (guarded by `monto_a_pagar > capital_a_pagar + interes_a_pagar`).

## Dependencies

- None. Migration-free by design.

## Success Criteria

- [ ] An exact payment of base + full arrastre is accepted for `cuota_fija`.
- [ ] The arrastre lands 100% on the component that produced the shortfall.
- [ ] Chained partials accumulate correctly across three consecutive cuotas.
- [ ] `_calcular_virtuales` shows the arrastre-inclusive amount.
- [ ] `_validar_split` still rejects overpaying a component with no arrastre.
- [ ] Existing pending production rows are corrected by the backfill.
- [ ] `python -m pytest` green; no test mocks `generar_siguiente_cuota` for arrastre.

## Review Budget Forecast

~250-330 changed lines (generation ~40, projector ~60, backfill ~50, tests ~150).
Within the 400-line budget. Excluding the backfill endpoint would shed ~50.

## Proposal question round

Owner decisions 1-4 are recorded and binding. One product unknown remains and is
currently an assumption, not a decision:

1. **Backfill**: existing pending `cuota_fija` rows have a correct
   `monto_a_pagar` but base-level components, so they stay unpayable until
   touched. Assumption: correct them with a one-off admin-only endpoint per
   AGENTS.md. Alternative: skip it and let collectors work around a handful of
   credits. Which do you want?
2. **Report impact**: `reportes.py` pending capital/interest totals will change
   (upward, to the true figure). Confirm this is desired and not a surprise for
   whoever reads those reports.
3. **Frontend**: no change is planned — the UI reads backend-computed values.
   Confirm no additional arrastre indicator is expected in this slice.
