# Proposal: abono_capital Carry-over Fix

## Intent

`abono_capital` credits mishandle the interest carry-over (arrastre) in four
places. Two produce the same HTTP 422 the `cuota_fija` fix (73f8c79) removed:
`monto_a_pagar` includes the arrastre but `interes_a_pagar` stays at base, so
`_validar_split` rejects the exact payment. Two silently discard the arrastre:
the alternating abono successor ignores `saldo_pendiente`, and
`recalcular_cuota_actual_si_no_pagada` rewrites base values on every
`pago no programado` or admin edit. Production runs `b46505f`, quincenal
`abono_capital` credits exist, and collectors are working around the 422 by
paying without arrastre plus a `pago no programado` -- which triggers the
write-off. Money is being lost today.

## Owner decisions (binding)

- All four cases in scope. Only the INTEREST shortfall carries; abono cuotas
  never carry; the carried shortfall lands 100% in `interes_a_pagar` of the
  next interés cuota, surviving an intervening abono cuota.
- Invariant: `capital_a_pagar + interes_a_pagar == monto_a_pagar` (within
  `TOL`) for every generated or recalculated cuota.
- `desglosar_arrastre` is NOT reused as-is (capital-first is wrong for the
  mensual combined cuota).
- Backfill via the same temporary admin endpoint pattern; rows already written
  off are accepted residual risk, no manual reconciliation.
- `_validar_split` caps stay. Frontend unchanged.

## Scope

### In Scope
- Case 1: mensual combined cuota -- fold interest arrastre into `interes_a_pagar`.
- Case 2: alternating interés successor -- same.
- Case 3: alternating abono successor -- shortfall must reach the next interés cuota.
- Case 4: `recalcular_cuota_actual_si_no_pagada` abono_capital branch re-derives
  pending interest arrastre instead of dropping it.
- Interest-only carry helper (or `tipo_credito`-aware branch).
- Unmocked RED->GREEN tests for mensual, alternating and recalculation paths.
- One-off admin backfill for unpaid `abono_capital` rows with
  `monto_a_pagar > capital_a_pagar + interes_a_pagar + TOL`, then a cleanup PR.
- Message at pago_service.py:105-109 only if the fix is a one-line
  `tipo_credito` guard; otherwise deferred.

### Out of Scope
- `cuota_fija` behavior and the existing `payment-carryover` requirements.
- Recovering arrastre already written off in prod.
- Virtual projection (`_calcular_virtuales`) -- verify only, no change expected.
- Surplus/`destino_excedente`, closing rules, reversal, deferrals.

## Capabilities

### New Capabilities
- `abono-capital-carryover`: interest-only shortfall carry for `abono_capital`
  (mensual and alternating), recalculation re-derivation, backfill.

### Modified Capabilities
- `payment-carryover`: relax the Non-Goal "`abono_capital` behavior is
  unchanged" and generalize the Component Sum Invariant wording; cuota_fija
  scenarios unchanged.

## Approach

Cases 1, 2, 4: mirror the shipped cuota_fija pattern (re-derive from the
persisted prior `Pago`, migration-free) but through an interest-only helper:
`falta_interes = max(0, interes_a_pagar - interes_pagado)` of the last paid
interés-bearing cuota, added to `interes_a_pagar`; `monto_a_pagar` becomes the
component sum.

Case 3 -- two options, design phase finalizes:

| | (a) Re-derive from prior rows | (b) Persist pending arrastre (Credito/Pago column) |
|---|---|---|
| Mechanism | When generating the interés successor of an abono cuota, walk back to the last paid `tipo_cuota == interes` row (`numero_cuota <` abono's, `deleted_at IS NULL`) and take its `falta_interes` | Store shortfall on the credit at pay time; consume at the next interés cuota |
| Double counting | None: the prior interés row already carries its own inflated `interes_a_pagar` | Needs explicit zeroing after consumption |
| Migration | None | Alembic + `startup_create_tables` hook; failures do not abort boot |
| Audit trail | Derivable from existing rows | New state to log |
| Reversal/deferral interplay | Filters on `pagado`/`deleted_at` already used at lines 782-789 | Must be kept in sync by reversal (#26) and deferral (#28) code |
| Budget | ~30 lines + tests | Likely exceeds 400 alone |

**Recommendation: (a).** It matches the prior change's rejection of a persisted
column, needs no schema change, and the walk-back query is the same shape as
`recalcular_cuota_actual_si_no_pagada` already uses. `generar_siguiente_cuota`
already holds `db`, so the abono_capital branch can become async or receive the
prior interés row from the caller.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `backend/app/services/credito_service.py:596-668` | Modified | Three abono_capital generation branches |
| `backend/app/services/credito_service.py:813-841` | Modified | Recalculation re-derives interest arrastre |
| `backend/app/services/credito_service.py` (near 156-176) | New | Interest-only carry helper |
| `backend/app/routers/admin.py` (temp) | New, then Removed | One-off backfill endpoint |
| `backend/tests/test_credito_service_arrastre_abono_capital.py`, `test_pago_service_arrastre.py` | New | Unmocked coverage |
| `backend/app/services/pago_service.py:96-119` | Unchanged | Caps as guardrail |
| `backend/app/routers/pagos.py:509-529`, `frontend/` | Unchanged | Verify only |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Collectors' workaround starts surfacing real arrastre (visible change) | High | Communicate before deploy; it is the intended correction |
| `reportes.py` pending totals rise for abono_capital | High | Assert in tests; note to owner |
| Walk-back picks a wrong prior row (reversed/deferred/soft-deleted) | Med | Reuse `pagado`/`deleted_at` filters; scenario tests for reversal and deferral |
| Backfill misses case-3/4 write-offs | Certain | Documented as accepted residual risk |
| Diff exceeds 400 lines | Med | Chained slices below |

## Rollback Plan

Revert the fix commit; components are derived at generation time, no schema
change. Backfill is idempotent (guard predicate) and touches only `Pago`
targets, never `Credito` saldos. Rows generated while the fix was live stay
correct and payable.

## Dependencies

- None (migration-free under recommendation (a)).

## Success Criteria

- [ ] Exact payment of base + interest arrastre accepted on mensual and interés cuotas.
- [ ] Alternating: partial interés -> abono -> next interés carries the full interest shortfall.
- [ ] Abono cuotas never carry and never absorb interest.
- [ ] `pago no programado` and admin edits preserve pending arrastre.
- [ ] Invariant holds for every generated/recalculated abono_capital row.
- [ ] Backfill corrects qualifying prod rows once; second run is a no-op.
- [ ] `backend/venv/Scripts/python.exe -m pytest` green; cuota_fija tests untouched.

## Review Budget Forecast

Estimate ~420-500 lines (helper+generation ~70, recalculation ~40, tests ~220,
backfill endpoint+tests ~110). **400-line budget risk: High.** Proposed
slices, same shape as the previous change:
1. PR-1 fix + tests (~330).
2. PR-2 backfill endpoint + tests (~110), run once in prod.
3. PR-3 cleanup (delete endpoint).

## Proposal question round

Owner decisions above are binding; no open product question remains. The only
undecided item is the case-3 mechanism, handed to `sdd-design` with
recommendation (a).
