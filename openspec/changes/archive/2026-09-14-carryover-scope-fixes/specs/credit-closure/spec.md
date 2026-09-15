# Delta for Credit Closure

> Change `carryover-scope-fixes` — Bug B (rule 15) and Bug A message scoping. Delta on
> `openspec/specs/credit-closure/spec.md`. Amounts are `Decimal`; comparisons use `TOL`.
> Worked example: `capital_prestado 120000.00`, `numero_cuotas 12`, base
> `capital_por_cuota 10000.00`, base `interes 3600.00`, base installment `13600.00`.
> Message-copy note unchanged: `detail` is backend-owned Spanish copy; scenarios fix
> semantic content, not wording.

## ADDED Requirements

### Requirement: Past-term Base Installment

While a `cuota_fija` credit has `saldo_capital > 0` and the installment being generated
or recalculated has `numero_cuota > numero_cuotas`, that installment MUST equal the full
base installment: `capital_a_pagar = capital_por_cuota` (from `capital_prestado /
numero_cuotas`) and `interes_a_pagar` = base interest computed on `capital_prestado`,
with `monto_a_pagar` their sum. It MUST carry no arrastre and MUST NOT be capped to the
remaining `saldo_capital`. This MUST hold on both the generation path
(`generar_siguiente_cuota`) and the recalculation path
(`recalcular_cuota_actual_si_no_pagada`). Past-term installments MUST repeat until
`saldo_capital = 0`; from then on the Interest-only Installment Tail (rule 14) applies.

#### Scenario: Partial payment of the last regular installment (prod case)

- GIVEN cuota `12` of `12` with `monto_a_pagar 13600.00` and `saldo_capital 10000.00`
- WHEN it is paid partially with `8000.00`
- THEN cuota `13` is generated with `capital_a_pagar 10000.00`, `interes_a_pagar 3600.00`,
  `monto_a_pagar 13600.00`
- AND `activo` stays `True`, balances reflect the real remaining amounts

#### Scenario: Past-term installment is not capped to remaining capital

- GIVEN a past-term credit with `saldo_capital 2000.00` and base `capital_por_cuota 10000.00`
- WHEN the next installment is generated
- THEN `capital_a_pagar = 10000.00` (not `2000.00`) AND `interes_a_pagar = 3600.00`

#### Scenario: Admin edit on a past-term unpaid installment keeps base values

- GIVEN an unpaid cuota `13` of `12` and a prior partially paid cuota `12`
- WHEN the credit is edited (capital or tasa) and the installment is recalculated
- THEN its components equal the base values derived from the edited credit
- AND no shortfall from cuota 12 is re-added

#### Scenario: Past-term sequence ends in the interest-only tail

- GIVEN a past-term credit whose payment brings `saldo_capital` to `0.00` with
  `saldo_intereses > 0`
- WHEN the next installment is generated
- THEN it is interest-only per the Interest-only Installment Tail requirement

#### Scenario: Component sum invariant holds past term

- WHEN any past-term installment is generated or recalculated
- THEN `capital_a_pagar + interes_a_pagar == monto_a_pagar` within `TOL`

### Requirement: One-off Past-term Arrastre Backfill

A temporary admin-only endpoint MUST correct unpaid `cuota_fija` rows with
`numero_cuota > numero_cuotas`, `capital_pagado = 0` and `interes_pagado = 0`, whose
`capital_a_pagar` or `interes_a_pagar` exceeds (beyond `TOL`) the base recomputed from
`capital_prestado` / `numero_cuotas`. It MUST reset both components to base, recompute
`monto_a_pagar`, and audit previous values via `audit_service`. It MUST support dry-run
and apply, scan all credits (no hard-coded IDs), be idempotent, and be removed after one
production run.

#### Scenario: Dry-run lists without writing

- GIVEN one qualifying inflated past-term row
- WHEN the backfill runs in dry-run mode
- THEN the row (credit, `numero_cuota`, current and base components) is reported
- AND no row is modified and no audit entry is written

#### Scenario: Apply corrects the row

- GIVEN cuota `13` of `12` with `capital_a_pagar 12000.00`, `interes_a_pagar 5200.00`
- WHEN the backfill applies
- THEN `capital_a_pagar = 10000.00`, `interes_a_pagar = 3600.00`, `monto_a_pagar = 13600.00`
- AND previous values are audited

#### Scenario: Idempotent re-run

- WHEN the backfill applies a second time
- THEN zero rows qualify and nothing is modified

#### Scenario: Out-of-scope rows untouched

- GIVEN rows with any payment recorded, rows within term, `abono_capital` rows,
  interest-only tail rows, and credit balances
- WHEN the backfill runs
- THEN none of them are modified

## MODIFIED Requirements

### Requirement: Closure by Settled State Only

A credit MUST close when and only when it becomes settled on a balance-mutating
path (`_pago_exacto`, `_pago_parcial`, the excess path,
`registrar_pago_no_programado`). Installment count MUST NOT trigger closure. No
automatic closure path MAY write `saldo_capital` or `saldo_intereses` to force
closure. The ONLY exception is the operator-driven explicit closure with the opt-in
flag (see Explicit Closure Confirmation), which MAY set `saldo_intereses` to
`Decimal("0.00")` on a capital-settled `cuota_fija` credit, atomically with
`activo = False` and with the previous value audited. The four payment-path call
sites and the settled-only closure primitive MUST remain unchanged.
(Previously: identical text; PARTIAL last-installment scenario added — the exact-payment
scenario alone left the carry-over gap untested.)

#### Scenario: Payment settles the credit

- GIVEN an open credit one payment away from settled
- WHEN that payment is registered on any of the four paths
- THEN `activo` becomes `False` AND no further installment is generated

#### Scenario: Last installment reached with balance outstanding

- GIVEN a `cuota_fija` credit at `numero_cuota == numero_cuotas`
- WHEN it is paid in full but capital remains
- THEN `activo` stays `True`, balances are unchanged
- AND a further installment is generated with the SAME value, carrying no
  arrastre

#### Scenario: Last installment paid partially with balance outstanding

- GIVEN a `cuota_fija` credit at `numero_cuota == numero_cuotas` (base `13600.00`)
- WHEN it is paid partially (e.g. `8000.00`) and capital remains
- THEN `activo` stays `True`, balances reflect the real remaining amounts
- AND the further installment is generated with the SAME base value (`13600.00`),
  carrying no arrastre

#### Scenario: Under-paid final installment never forgives debt

- WHEN the final installment is only partly paid
- THEN both balances retain their real remaining amounts and `activo` stays `True`

#### Scenario: Real path without mocking

- WHEN the scenarios above are exercised without patching
  `generar_siguiente_cuota`
- THEN the observed installment generation matches the assertions

#### Scenario: Payment leaving interest pending never auto-closes

- GIVEN a `cuota_fija` credit whose payment brings `saldo_capital` to `0.00` with
  `saldo_intereses > 0`
- WHEN the payment is registered on any of the four paths
- THEN `activo` stays `True`, `saldo_intereses` is unchanged
- AND the next generated installment is interest-only (rule 10 default)

#### Scenario: Settled-only primitive never writes balances

- GIVEN any credit
- WHEN the settled-only closure primitive runs
- THEN `saldo_capital` and `saldo_intereses` are byte-identical before and after

### Requirement: Operator-Readable Rejection Messages

Every rejection introduced or touched by this change MUST return an
`HTTPException` `detail` that states the BUSINESS REASON in Spanish, in terms an
operator recognizes, so the rejection does not read as a platform failure. The
`detail` MUST NOT be only internal field names, tolerances or raw numbers.
The message is written ONCE in the backend; any frontend site that triggers such a
rejection MUST surface `detail` rather than a generic literal. A `detail` MUST be
factually true for the credit it is issued on: the "capital already settled" reason
MUST be issued only for `cuota_fija` credits.
(Previously: the interest-only rejection scenario did not distinguish `tipo_credito`,
so the settled-capital reason leaked onto `abono_capital` interés installments.)

#### Scenario: Already-closed message

- WHEN closure is confirmed on a closed credit
- THEN `detail` states that the credit is already closed and that closure cannot
  be confirmed twice

#### Scenario: Not-settled message names the outstanding component

- GIVEN an unsettled credit
- WHEN closure is confirmed
- THEN `detail` names WHICH balance is still owed — capital, interest, or both —
  and its amount

#### Scenario: Capital sent against an interest-only installment

- GIVEN a pending `cuota_fija` installment with `capital_a_pagar = 0` (interest-only tail)
- WHEN a payment with capital above tolerance is registered
- THEN the response is `422`
- AND `detail` explains that the installment charges interest only because the
  capital is already settled, instead of reporting a bare component-exceeded error

#### Scenario: Settled-capital reason never issued for abono_capital

- GIVEN a pending `abono_capital` `interes` installment with `capital_a_pagar = 0`
- WHEN a payment with capital above tolerance is registered as an exact payment
- THEN the response is `422`
- AND `detail` MUST NOT state that the capital is settled (see
  `abono-capital-carryover`, "Interés Installment Is Not Capital-Settled")

#### Scenario: Frontend surfaces the reason

- GIVEN a frontend site that invokes a rejection path from this change
- THEN it renders the backend `detail`
- AND MUST NOT swallow it behind a generic literal such as `'Error'`

#### Scenario: Flag rejected because capital is pending

- GIVEN an active credit with `saldo_capital > 0`
- WHEN closure is confirmed with the flag `true`
- THEN `detail` states in Spanish that a credit cannot be closed while capital is
  still owed, names the capital amount, and MUST NOT use the word "condonar"

#### Scenario: Interest pending without the flag

- GIVEN an active `cuota_fija` credit with capital `0.00` and interest `> 0`
- WHEN closure is confirmed without the flag
- THEN `detail` is the existing message naming the pending interest and its amount
