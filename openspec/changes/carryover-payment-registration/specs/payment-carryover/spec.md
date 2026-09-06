# Payment Carry-over Specification

## Purpose

Defines how a `cuota_fija` shortfall (arrastre) is disaggregated per component,
folded into the next installment's targets, validated, projected and backfilled.
All amounts are `Decimal`; comparisons use the existing tolerance `TOL`.

## Requirements

### Requirement: Shortfall Disaggregation

When a `cuota_fija` installment is generated after a prior installment left a
shortfall, the system MUST compute the shortfall per component from the persisted
prior row: `falta_capital = capital_a_pagar - capital_pagado` and
`falta_interes = interes_a_pagar - interes_pagado`, each floored at zero. Each
shortfall MUST be added to its own component of the new installment. Distribution
MUST NOT be proportional and MUST NOT default to interest.

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

### Requirement: Component Sum Invariant

For every generated `cuota_fija` row the system MUST satisfy
`capital_a_pagar + interes_a_pagar == monto_a_pagar` within `TOL`.

#### Scenario: Invariant with arrastre

- GIVEN any generated cuota with a pending arrastre
- WHEN the row is persisted
- THEN the component sum equals `monto_a_pagar`

### Requirement: Arrastre-inclusive Payment Acceptance

Split validation caps MUST remain in force; the ceiling moves to the
arrastre-inclusive component targets rather than being removed.

#### Scenario: Exact payment of base plus full arrastre

- GIVEN a cuota with arrastre-inclusive components
- WHEN a payment matching those components exactly is registered
- THEN it is accepted as `exacto` with no HTTP 422

#### Scenario: Payment below base

- WHEN the paid total is below the base installment
- THEN the existing `parcial` flow applies and a new shortfall is carried

#### Scenario: Payment between base and base plus arrastre

- WHEN the paid total falls between base and arrastre-inclusive total
- THEN it is accepted as `parcial` and the remaining shortfall is carried per
  component

#### Scenario: Payment above base plus arrastre

- WHEN the paid total exceeds the arrastre-inclusive total
- THEN the existing `destino_excedente` flow handles the surplus, unchanged

#### Scenario: Non-arrastre overpayment still rejected

- GIVEN a cuota with zero arrastre
- WHEN a component is overpaid beyond its target
- THEN validation MUST reject it exactly as today

### Requirement: Arrastre-aware Projection

Virtual (non-persisted) future installment projection MUST display the
arrastre-inclusive amount and components, matching what generation would produce.

#### Scenario: Projection matches generation

- GIVEN a credit with a pending arrastre
- WHEN virtual installments are projected
- THEN the first projected row shows the arrastre-inclusive `monto_a_pagar` and
  components

### Requirement: One-off Backfill Correction

An admin-only endpoint MUST correct pending `cuota_fija` rows whose components
are still at base level while `monto_a_pagar` already includes arrastre.

#### Scenario: Qualifying row corrected

- GIVEN a pending `cuota_fija` row with
  `monto_a_pagar > capital_a_pagar + interes_a_pagar`
- WHEN the backfill runs
- THEN components are raised using the disaggregation rule and the sum invariant
  holds

#### Scenario: Idempotent re-run

- WHEN the backfill runs a second time
- THEN already-corrected rows no longer qualify and are left untouched

#### Scenario: Out-of-scope rows untouched

- GIVEN registered/historical payments, `abono_capital` rows, or credit
  `saldo_capital` / `saldo_intereses` balances
- WHEN the backfill runs
- THEN none of them are modified

### Requirement: Reported Pending Totals Reflect True Amounts

Pending capital/interest report totals derived from
`capital_a_pagar - capital_pagado` MUST rise for affected credits. This increase
is intended correctness, not a regression.

#### Scenario: Totals rise after correction

- GIVEN a credit with a corrected arrastre-inclusive cuota
- WHEN pending totals are computed
- THEN they include the arrastre and MUST NOT be clamped to base values

## Non-Goals

- Surplus MUST NOT advance future installments (corrective #2).
- Closing-rule / blocker redesign is out of scope (corrective #3).
- No Alembic migration and no new arrastre column (corrective #8); the split is
  derived from persisted prior-row fields.
- `abono_capital` behavior is unchanged; it has no `saldo_intereses`.
- No frontend changes and no visual arrastre indicator in this slice.
