# Delta for abono_capital Carry-over

> Change `carryover-scope-fixes` — Bug A. Delta on
> `openspec/specs/abono-capital-carryover/spec.md`. Amounts are `Decimal`; comparisons
> use `TOL`. `detail` strings are backend-owned Spanish copy; scenarios fix semantic
> content, not wording.

## ADDED Requirements

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

## MODIFIED Requirements

### Requirement: Projection and Frontend Unchanged

Virtual projection (`_calcular_virtuales`) MUST keep projecting base amounts
for `abono_capital`; any pending arrastre is visible only on the persisted
blocking row. The frontend MUST render backend components as-is; the only
frontend behavior tied to this capability is the capital-input scoping defined in
"Interés Installment Is Not Capital-Settled".
(Previously: "No frontend change is required".)

#### Scenario: Virtual successors show base values

- GIVEN a blocking row with arrastre-inclusive components
- WHEN successors are projected
- THEN virtual rows show base components with the sum invariant holding

#### Scenario: Frontend renders backend components

- WHEN the payments page renders a corrected cuota
- THEN it displays `capital_a_pagar` / `interes_a_pagar` from the payload as-is
