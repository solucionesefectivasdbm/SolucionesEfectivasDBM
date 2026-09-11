# Exploration — Zero-balance credit closure

Change: `zero-balance-credit-closure` (quote phase 2, corrective item 2)
Phase: explore
Artifact store: hybrid (this file + Engram topic `sdd/zero-balance-credit-closure/explore`, obs #891)

## Current state

There is no `estado` enum. Closure is represented solely by `Credito.activo: bool`
(`backend/app/models/credito.py:89`), a one-way flag that nothing ever resets to `True`.

Authoritative balances are `saldo_capital` / `saldo_intereses`. The only sanctioned mutator
during payments is `PagoService._aplicar_reduccion_saldos`
(`backend/app/services/pago_service.py:36-55`), which floors both at `0.00` via `max(...)`.
`TOL = Decimal("0.01")` exists but is used only for payment-split validation, never in the
closure check.

The closure decision lives in `PagoService._verificar_cierre_credito`
(`backend/app/services/pago_service.py:337-364`): it closes when `saldo_capital <= 0`, or when
the credit is `cuota_fija` and `numero_cuota >= numero_cuotas`. It is called from all three
scheduled-payment paths, always before the "generate next cuota" guard.
`registrar_pago_no_programado` (`backend/app/services/pago_service.py:367-438`) duplicates a
subset of this logic inline instead of reusing the canonical function.

## Confirmed defects

### 1. Admin capital edit can zero the balance without closing the credit

`PATCH /creditos/{id}` -> `actualizar_credito` (`backend/app/routers/creditos.py:246-264`)
assigns `credito.saldo_capital = max(0, nuevo_saldo)` directly, outside
`_aplicar_reduccion_saldos`, and never calls `_verificar_cierre_credito`.

A capital correction that drops the outstanding balance to `0.00` leaves `activo = True`. The
credit keeps appearing in `/creditos?solo_activos=true`, in the portfolio sum
(`backend/app/routers/creditos.py:101-106`) and in `/pagos/diarios`
(`backend/app/routers/pagos.py:274-279`) until an unrelated future payment retroactively closes
it. This matches the client-reported symptom exactly.

No test in `backend/tests/test_creditos_actualizar.py` asserts `activo` after this edit.

### 2. Partial payment on the last cuota_fija installment force-closes and erases remaining debt

`_pago_parcial` (`backend/app/services/pago_service.py:252`) calls `_verificar_cierre_credito`
unconditionally. Its `numero_cuota >= numero_cuotas` branch fires even on an under-paid final
installment, then forcibly zeroes `saldo_capital`
(`backend/app/services/pago_service.py:364`) — silently forgiving unpaid balance.

This is the same "silent overwrite of derived state" anti-pattern as the historic `recalcular_*`
bugs. `test_cierre_al_alcanzar_ultima_cuota` (`backend/tests/test_pago_service.py:315-336`)
covers only a FULL final payment, so this path is uncovered.

### 3. No tolerance floor for `abono_capital` closure (lower severity)

`abono_capital` has no `numero_cuotas` fallback, so a residual of cents can theoretically keep a
credit open forever. Needs a business tolerance decision.

### 4. Closure is not reversible

No primitive exists to reopen a credit or reverse a registered payment. The existing `revertir`
endpoint in `backend/app/routers/pagos.py` only ungates an unpaid check and explicitly rejects
paid cuotas. This is a hard dependency risk for item 5 of the quote (Recaudo reversal button).

## Testing trap

Both existing closure tests patch `generar_siguiente_cuota` unconditionally and exercise only
full-payment happy paths. Neither covers the admin-edit path nor the last-cuota partial-payment
path — the same blind spot that hid the item-1 carryover bug.

## Approaches

| # | Approach | Pros | Cons | Effort |
|---|----------|------|------|--------|
| 1 | Centralize closure into one canonical function and call it from every balance-mutating path (fix `actualizar_credito`, dedupe `registrar_pago_no_programado`, guard the `numero_cuotas` branch to require full payment) | Fixes both root causes; no schema change; matches the existing "canonical mutator" pattern | Touches 2 files; needs new tests; must not regress the existing full-payment closure test | Medium |
| 2 | Computed "is closed" check on read paths only, leaving `activo` untouched | Zero risk to existing tests and flow | Does not fix actual DB state; treats a symptom, not what the client reported | Low |
| 3 | Reconciliation sweep/backfill for `activo = True AND saldo_capital <= TOL` | Catches any drift source; reuses the existing temporary-backfill-endpoint convention | Masks the root cause if used alone | Low-Medium |

**Recommendation:** approach 1, paired with a one-time backfill endpoint (shape of approach 3)
for credits already stuck open at zero balance in production, per the `AGENTS.md`
temporary-admin-endpoint convention. No Alembic migration needed — `activo` is an existing
column.

## Risks

- Fixing defect 2 must not regress the currently passing full-payment closure test.
- No reopen/reversal primitive exists — blocks item 5 of the quote until designed.
- Backfill tolerance definition needs business sign-off; a wrong tolerance could forgive real debt.
- `registrar_pago_no_programado`'s early-return-on-closure semantics (it skips `saldo_intereses`
  recalculation) must be preserved when centralizing.
- No frontend test infrastructure — display regressions rely on `npx tsc --noEmit` only.

## Open questions for the business owner

1. Should `abono_capital` closure tolerate a small residual (e.g. <= 0.01) or require exact 0.00?
2. Should the admin capital edit auto-close immediately when it zeroes the balance, or require an
   explicit confirmation step?
3. For last-installment underpayment: generate a residual cuota for the shortfall, or close and
   record the unpaid amount for reporting — never silently forgive it?
4. Should the production backfill for stuck-open zero-balance credits require manual per-credit
   review, or run as a blanket sweep?
