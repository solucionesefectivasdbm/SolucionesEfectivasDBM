# abono_capital Carry-over Specification

## Purpose

Defines how an INTEREST shortfall (arrastre) on an `abono_capital` credit is
carried into the next interest-bearing installment, preserved across
recalculation, validated and backfilled. Amounts are `Decimal` quantized to
`0.01` (ROUND_HALF_UP); comparisons use the existing tolerance `TOL`.

## Requirements

### Requirement: Interest-only Shortfall Carry

When an `abono_capital` installment that can hold interest is generated, the
system MUST take `falta_interes = max(0, interes_a_pagar - interes_pagado)`
from the persisted last paid interest-bearing cuota and add 100% of it to
`interes_a_pagar`. `capital_a_pagar` MUST NOT absorb any shortfall. Shortfalls
left on `abono`-type cuotas MUST NOT carry. If the paid cuota was settled in
full (`capital_pagado + interes_pagado >= monto_a_pagar`) the carry MUST be
`0.00` regardless of how the split was recorded.

#### Scenario: Fully settled cuota with skewed split carries nothing

- GIVEN a paid `interes` cuota with `monto_a_pagar 50000.00`,
  `interes_a_pagar 50000.00`, `interes_pagado 30000.00`,
  `capital_pagado 20000.00` (settled via excedente applied to capital)
- WHEN the next interest-bearing cuota is generated
- THEN the carry is `0.00`

#### Scenario: Mensual combined cuota folds arrastre into interest

- GIVEN a mensual credit with base `interes 50000.00`, `abono_minimo 100000.00`
  and a prior combined cuota with `falta_interes = 20000.00`
- WHEN the next cuota is generated
- THEN `capital_a_pagar = 100000.00`, `interes_a_pagar = 70000.00`,
  `monto_a_pagar = 170000.00`

#### Scenario: Alternating interés successor carries the shortfall

- GIVEN a quincenal credit whose last paid `interes` cuota had
  `interes_a_pagar 50000.00` / `interes_pagado 30000.00`
- WHEN the next `interes` cuota is generated with base `interes 50000.00`
- THEN `interes_a_pagar = 70000.00`, `capital_a_pagar = 0.00`,
  `monto_a_pagar = 70000.00`

#### Scenario: Abono cuota never carries nor absorbs

- GIVEN any pending interest arrastre
- WHEN an `abono` cuota is generated or recalculated
- THEN `interes_a_pagar = 0.00` AND `monto_a_pagar = capital_a_pagar = abono_minimo`
- AND a shortfall on that abono cuota does not inflate any later cuota

#### Scenario: Zero arrastre regression guard

- GIVEN the last paid interest-bearing cuota was paid in full
- WHEN the next cuota is generated
- THEN components equal base values

### Requirement: Interés Installment Is Not Capital-Settled

An `abono_capital` `interes` installment (`capital_a_pagar = 0.00`) is a structural
half of the alternating cycle, not evidence that capital is settled. The system MUST NOT
treat it as the `cuota_fija` interest-only tail:

- Payment payloads (`PagoResponse`, including regular, deferred and virtual rows) MUST
  expose `tipo_credito` so consumers can distinguish the two cases.
- The payments UI (both `/pagos` and `/pagos/diarios`) MUST disable the capital input
  and show the "capital ya está saldado" notice ONLY when `tipo_credito == cuota_fija`
  AND `tipo_cuota == interes`. On an `abono_capital` `interes` installment the capital
  input MUST stay enabled.
- Split validation caps are unchanged. When capital above `TOL` is sent as an EXACT
  payment against an `abono_capital` `interes` installment, the response MUST be `422`
  with a `detail` stating that this installment of the alternating cycle charges
  interest only and capital is collected on the abono installment; it MUST NOT state
  that the capital is settled.
- The existing free component split on a PARTIAL payment MUST remain accepted on an
  `abono_capital` `interes` installment.

#### Scenario: Quincenal interés installment with carryover keeps capital input enabled (prod case)

- GIVEN a quincenal `abono_capital` credit whose current `interes` cuota has
  `capital_a_pagar 0.00`, `interes_a_pagar 70000.00` (base 50000.00 + 20000.00 arrastre)
- WHEN the operator opens the payment form for that cuota
- THEN the capital input is enabled AND no "capital ya está saldado" notice is shown

#### Scenario: Partial free split accepted on an interés installment

- GIVEN the same cuota
- WHEN a partial payment of `30000.00` is registered as `capital 10000.00` /
  `interes 20000.00`
- THEN it is accepted as `parcial` with no HTTP 422
- AND the recorded components match the split sent

#### Scenario: Exact payment targeting capital on an interés installment

- GIVEN the same cuota
- WHEN an exact payment of `70000.00` is registered as `capital 10000.00` /
  `interes 60000.00`
- THEN the response is `422`
- AND `detail` names the alternating-cycle reason and MUST NOT claim the capital is
  settled

#### Scenario: cuota_fija interest-only tail keeps today's behavior

- GIVEN a `cuota_fija` credit with `saldo_capital <= 0` and a pending `interes` cuota
- WHEN the operator opens the payment form
- THEN the capital input is disabled AND the "capital ya está saldado" notice is shown
- AND sending capital above `TOL` yields `422` with the existing settled-capital `detail`

#### Scenario: tipo_credito present on every payment row

- WHEN `GET /pagos`, the deferred list, or virtual rows are read
- THEN each row carries `tipo_credito` equal to its credit's `tipo_credito`

### Requirement: Shortfall Survives an Intervening Abono Cuota

In alternating periodicities the interest shortfall of a partially paid
`interes` cuota MUST land on the next `interes` cuota even though an `abono`
cuota is generated in between. The source MUST be the last paid `interes`
cuota with `numero_cuota` lower than the cuota being generated; the
intervening abono row MUST NOT be used as the source.

#### Scenario: Partial interés, abono, then interés

- GIVEN cuota N (`interes`, target 50000.00) paid 30000.00 and cuota N+1
  (`abono`) paid in full
- WHEN cuota N+2 (`interes`, base 50000.00) is generated
- THEN `interes_a_pagar = 70000.00`

#### Scenario: Chained partials do not double count

- GIVEN cuota N+2 above is then paid 60000.00
- WHEN cuota N+4 (`interes`) is generated after abono N+3
- THEN its `interes_a_pagar` equals base plus `10000.00` only

### Requirement: Recalculation Preserves Pending Arrastre

`recalcular_cuota_actual_si_no_pagada` on an unpaid `abono_capital` cuota MUST
re-derive the pending interest shortfall from prior rows and keep it in
`interes_a_pagar`, both after a `pago no programado` and after admin edits
(capital, tasa, abono_minimo).

#### Scenario: Pago no programado keeps the arrastre

- GIVEN a current mensual cuota with `interes_a_pagar = 70000.00`
  (base 50000.00 + 20000.00 arrastre)
- WHEN a pago no programado reduces `saldo_capital` so base becomes 45000.00
- THEN `interes_a_pagar = 65000.00` AND the sum invariant holds

#### Scenario: Admin edit keeps the arrastre on an interés cuota

- GIVEN a current alternating `interes` cuota carrying 20000.00
- WHEN the admin edits `tasa_interes_mensual`
- THEN `interes_a_pagar` equals the new base plus 20000.00

#### Scenario: Recalculated abono cuota stays interest-free

- WHEN the current cuota is `abono` and is recalculated
- THEN `interes_a_pagar = 0.00` and `monto_a_pagar = abono_minimo`

### Requirement: Prior-Row Selection Correctness

The source row for the carry MUST be selected only among rows with
`pagado = True` and `deleted_at IS NULL`, ordered by `numero_cuota`.

#### Scenario: Unpaid interés row is not a source

- GIVEN an interés cuota N with `pagado = False` and zero paid amounts (constructed directly in the test fixture; `desvalidar_pago` only acts on rows that are not yet paid, so no endpoint un-pays a row)
- WHEN the next interés cuota is generated or recalculated
- THEN cuota N is ignored and no arrastre from it is carried

#### Scenario: Deferral does not alter the carry

- GIVEN a pending arrastre and a deferral that changes only `fecha_maxima`
- WHEN the cuota is regenerated or recalculated
- THEN the carried amount is unchanged

#### Scenario: Soft-deleted row skipped

- GIVEN the most recent paid `interes` row has `deleted_at` set
- WHEN the source is selected
- THEN the previous non-deleted paid `interes` row is used

### Requirement: Arrastre-inclusive Payment Acceptance

Split validation caps MUST remain unchanged; targets move to the
arrastre-inclusive components.

#### Scenario: Exact payment accepted

- GIVEN an `abono_capital` cuota with `interes_a_pagar = 70000.00`
- WHEN a payment of exactly `capital_a_pagar + 70000.00` is registered
- THEN it is accepted as `exacto` with no HTTP 422

#### Scenario: Partial and surplus flows unchanged

- WHEN the paid total is below or above the arrastre-inclusive total
- THEN the existing `parcial` and `destino_excedente` flows apply unchanged

### Requirement: Component Sum Invariant

Every generated or recalculated `abono_capital` row MUST satisfy
`capital_a_pagar + interes_a_pagar == monto_a_pagar` within `TOL`.

#### Scenario: Invariant on all branches

- WHEN a mensual, `interes` or `abono` cuota is generated or recalculated
- THEN the component sum equals `monto_a_pagar`

### Requirement: One-off Backfill Correction (fulfilled, historical)

This requirement was fulfilled and retired: the endpoint shipped in PR #31,
its production dry-run on 2026-09-14 found zero qualifying rows, and it was
removed in PR #32. No implementation or tests remain by design. The original
requirement is kept for traceability.

A temporary admin-only endpoint MUST correct unpaid `abono_capital` rows where
`monto_a_pagar > capital_a_pagar + interes_a_pagar + TOL` by raising
`interes_a_pagar` by the difference. It MUST support dry-run and apply, be
idempotent, log via the audit service, and MUST be removed after one prod run.

#### Scenario: Qualifying row corrected

- GIVEN an unpaid row with `monto_a_pagar 170000.00`, `capital 100000.00`,
  `interes 50000.00`
- WHEN the backfill applies
- THEN `interes_a_pagar = 70000.00` and `monto_a_pagar` is unchanged

#### Scenario: Dry-run reports without writing

- WHEN the backfill runs in dry-run mode
- THEN qualifying rows are listed and no row is modified

#### Scenario: Idempotent re-run

- WHEN the backfill applies a second time
- THEN zero rows qualify and none are modified

#### Scenario: Out-of-scope rows untouched

- GIVEN paid rows, `cuota_fija` rows, credit balances, and arrastres already
  written off by earlier data loss
- WHEN the backfill runs
- THEN none are modified or reconstructed

### Requirement: Projection and Frontend Unchanged

Virtual projection (`_calcular_virtuales`) MUST keep projecting base amounts
for `abono_capital`; any pending arrastre is visible only on the persisted
blocking row. The frontend MUST render backend components as-is; the only
frontend behavior tied to this capability is the capital-input scoping defined in
"Interés Installment Is Not Capital-Settled".

#### Scenario: Virtual successors show base values

- GIVEN a blocking row with arrastre-inclusive components
- WHEN successors are projected
- THEN virtual rows show base components with the sum invariant holding

#### Scenario: Frontend renders backend components

- WHEN the payments page renders a corrected cuota
- THEN it displays `capital_a_pagar` / `interes_a_pagar` from the payload as-is

## Non-Goals

- Recovering arrastre already written off in production.
- Changes to `_validar_split` caps, closing rules, reversal or deferral logic.
- `cuota_fija` behavior (see `payment-carryover`).
