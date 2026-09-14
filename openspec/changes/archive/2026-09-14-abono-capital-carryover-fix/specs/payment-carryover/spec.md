# Delta for Payment Carry-over

## MODIFIED Requirements

### Requirement: Component Sum Invariant

For every generated or recalculated installment row, regardless of
`tipo_credito` (`cuota_fija` or `abono_capital`) or `tipo_cuota`, the system
MUST satisfy `capital_a_pagar + interes_a_pagar == monto_a_pagar` within `TOL`.
(Previously: scoped to generated `cuota_fija` rows only.)

#### Scenario: Invariant with arrastre

- GIVEN any generated cuota with a pending arrastre
- WHEN the row is persisted
- THEN the component sum equals `monto_a_pagar`

#### Scenario: Invariant after recalculation

- GIVEN a current unpaid cuota of either credit type
- WHEN `recalcular_cuota_actual_si_no_pagada` runs
- THEN the component sum equals `monto_a_pagar`

## MODIFIED Non-Goals

Replace the line "`abono_capital` behavior is unchanged; it has no
`saldo_intereses`." with:

- `abono_capital` carry-over is specified in `abono-capital-carryover`
  (interest-only carry); it still has no `saldo_intereses`.

All other Non-Goals and all `cuota_fija` requirements and scenarios remain
unchanged.
