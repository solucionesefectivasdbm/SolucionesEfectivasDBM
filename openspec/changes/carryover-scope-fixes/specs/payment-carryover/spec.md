# Delta for Payment Carry-over

> Change `carryover-scope-fixes` — Bug B, rule 15. Delta on
> `openspec/specs/payment-carryover/spec.md`. Amounts are `Decimal`; comparisons use `TOL`.
> Worked example used below: `capital_prestado 120000.00`, `numero_cuotas 12`,
> base `capital_por_cuota 10000.00`, base `interes 3600.00`, base installment `13600.00`.

## MODIFIED Requirements

### Requirement: Shortfall Disaggregation

When a `cuota_fija` installment is generated after a prior installment left a
shortfall, the system MUST compute the shortfall per component from the persisted
prior row: `falta_capital = capital_a_pagar - capital_pagado` and
`falta_interes = interes_a_pagar - interes_pagado`, each floored at zero. Each
shortfall MUST be added to its own component of the new installment. Distribution
MUST NOT be proportional and MUST NOT default to interest.

EXCEPTION (rule 15): when the installment being generated or recalculated has
`numero_cuota > numero_cuotas` and the credit still has `saldo_capital > 0`, NO
shortfall MUST be carried. The installment MUST equal the full base:
`capital_a_pagar = capital_por_cuota` (derived from `capital_prestado / numero_cuotas`)
and `interes_a_pagar` = base interest on `capital_prestado`, NOT capped to the remaining
balance. Past-term behavior is specified in `credit-closure` ("Past-term Base
Installment"); this requirement only carves it out of carry-over.
(Previously: shortfall was carried unconditionally, with no `numero_cuotas` carve-out.)

#### Scenario: Purely capital shortfall

- GIVEN a prior cuota with `falta_capital = 50.00` and `falta_interes = 0.00`
- WHEN the next cuota is generated with base `capital 100.00` / `interes 20.00`
- THEN `capital_a_pagar = 150.00` AND `interes_a_pagar = 20.00`

#### Scenario: Purely interest shortfall

- GIVEN a prior cuota with `falta_capital = 0.00` and `falta_interes = 15.00`
- WHEN the next cuota is generated with base `capital 100.00` / `interes 20.00`
- THEN `capital_a_pagar = 100.00` AND `interes_a_pagar = 35.00`

#### Scenario: Mixed shortfall

- GIVEN `falta_capital = 30.00` and `falta_interes = 10.00`
- WHEN the next cuota is generated
- THEN each component grows by its own shortfall
- AND `capital_a_pagar + interes_a_pagar == monto_a_pagar`

#### Scenario: Zero arrastre regression guard

- GIVEN the prior cuota was paid in full
- WHEN the next cuota is generated
- THEN components equal base values, unchanged from current behavior

#### Scenario: Chained partials accumulate without double counting

- GIVEN three consecutive partial payments, each leaving a further shortfall
- WHEN each next cuota is generated from the already-inflated prior row
- THEN cuota N's components equal base plus the full outstanding shortfall of
  cuota N-1 only
- AND no shortfall is counted twice across the chain

#### Scenario: Shortfall on the last regular installment is not carried past term

- GIVEN cuota `12` of `12` (base `13600.00`) is paid partially with `8000.00`,
  leaving `saldo_capital > 0`
- WHEN cuota `13` is generated
- THEN `capital_a_pagar = 10000.00`, `interes_a_pagar = 3600.00`, `monto_a_pagar = 13600.00`
- AND no `falta_capital` / `falta_interes` from cuota 12 is added

#### Scenario: Shortfall between past-term installments is not carried either

- GIVEN cuota `13` of `12` (base `13600.00`) is paid partially, leaving `saldo_capital > 0`
- WHEN cuota `14` is generated
- THEN its components equal the same base values as cuota 13

#### Scenario: Carry-over within term is unaffected

- GIVEN cuota `11` of `12` is paid partially
- WHEN cuota `12` is generated
- THEN the per-component shortfall IS carried exactly as in the scenarios above
