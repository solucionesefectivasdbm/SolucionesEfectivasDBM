# Exploration: carryover-payment-registration

Corrective item #1 of the phase-2 package. Status: complete. All findings are
code-verified against `main` @ `ae2d774`.

## Business problem

In `cuota_fija` credits, when a previous payment was partial and left a
carry-over (`arrastre`) pending, the system rejects any attempt to register a
payment for the correct arrastre-inclusive amount. The collector must either
refuse the client's money or split the payment into two records.

## Root cause (verified)

The block is a deterministic defect, not a soft UX limit.

1. `backend/app/services/credito_service.py:406-441` — `_siguiente_cuota_fija`
   sets `monto_total = cuota_base + saldo_pendiente` (line 427), but leaves
   `capital_a_pagar` and `interes_a_pagar` (lines 435-436) at BASE values. The
   carry-over is never distributed into the per-component targets.
2. `backend/app/services/pago_service.py:57-120` — `_validar_split`, `exacto`
   branch, rejects when `capital_pagado > pago.capital_a_pagar + TOL` or
   `interes_pagado > pago.interes_a_pagar + TOL` (lines 99-108).

Whenever `saldo_pendiente > 0`, `capital_a_pagar + interes_a_pagar` is strictly
less than `monto_a_pagar`. No split can both sum to `monto_a_pagar` and stay
under the per-component caps. Every exact payment raises `ValueError`, surfaced
as HTTP 422 at `backend/app/routers/pagos.py:478-479`.

The collector is pushed into either the `parcial` branch (which re-carries an
even larger arrastre) or the two-step `confirmar_excedente` flow
(`pago_service.py:271-335`), which dumps the whole excess into a single bucket.

## Carry-over representation

There is no dedicated column. The carry-over is a transient value
(`faltante` / `saldo_a_arrastrar`, `pago_service.py:223-250`) passed as
`saldo_pendiente` into `generar_siguiente_cuota`, and folded only into
`monto_a_pagar` of the next `Pago` row. No `Pago.arrastre` field exists.

## Frontend

`frontend/src/pages/Pagos/PagosPage.tsx:585-593` uses a plain
`<input type="number">` with `useState` — no react-hook-form/zod here, despite
that being the project's usual stack. The limit is NOT duplicated client-side;
the backend error is surfaced verbatim through
`toast.error(e.response?.data?.detail ...)` (line 151).

## Secondary discrepancy

`backend/app/routers/pagos.py:241-439` — `_calcular_virtuales` is a separate,
duplicated projection for future rows that are not yet persisted. Its formula
(lines 372-379) never accounts for pending arrastre and always displays the pure
base amount, reinforcing the collector's impression that the base is the maximum
payable. This projector and its `bloqueador_map` blocking logic overlap with
corrective item #3 (closing-rule redesign).

## Test coverage gap

Every `exacto` / `parcial` / `excedente` test in
`backend/tests/test_pago_service.py` mocks `generar_siguiente_cuota` with
`return_value=None` (lines 106, 125, 142, 162, 179, 239, 273, 308, 333). None
exercise real arrastre folding. `backend/tests/test_credito_service.py` has no
`saldo_pendiente` or `_siguiente_cuota_fija` tests at all. This gap is why the
defect shipped unnoticed.

## Candidate approaches (selection deferred to the proposal phase)

| # | Approach | Effort | Tradeoff |
|---|----------|--------|----------|
| 1 | Inflate `capital_a_pagar` / `interes_a_pagar` at generation time | Medium | Smallest structural change; requires a business allocation rule; must also fix the `_calcular_virtuales` duplication |
| 2 | Persist arrastre explicitly as a new column | Medium-High | Needs an Alembic migration plus the idempotent `startup_create_tables` hook per AGENTS.md; gives an audit trail and cleanly fixes the projector |
| 3 | Loosen the `exacto` per-component caps when the total matches `monto_a_pagar` | Low | Smallest diff, but removes a guardrail for ordinary non-arrastre payments and leaves the projector display gap |

## Open questions for the product owner

1. When a payment exceeds base installment plus full pending carry-over, does
   the surplus advance future installments, reduce capital immediately (today's
   excedente flow), or still require the current `destino_excedente` decision?
2. How should the carry-over be split between `capital_a_pagar` and
   `interes_a_pagar` once folded into a new cuota — proportional to the base
   ratio, 100% to interest, or 100% to whichever bucket produced the shortfall?
3. Does the fix also cover `abono_capital` credits, or is it scoped strictly to
   `cuota_fija`? (`abono_capital` carry-over is interest-only by design.)
4. Should `_calcular_virtuales` be corrected in this change, or deferred to
   item #3?
5. Is a schema/migration change (approach 2) acceptable for this item's scope
   and timeline, or must it stay migration-free?

## Risks

- The fix touches shared generation code (`_siguiente_cuota_fija`,
  `_siguiente_cuota_abono_capital`) used by every payment branch.
- The duplicated projector `_calcular_virtuales` will silently keep showing
  wrong amounts if it is not updated in step.
- Zero existing test scaffolding for this path: new tests must be built from
  scratch, not extended.
