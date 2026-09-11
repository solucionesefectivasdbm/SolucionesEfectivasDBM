# Credit Closure Specification

## Purpose

Defines when a credit is settled, how it is closed, who confirms closure, and how
rejections are explained to the operator. All amounts are `Decimal`. Closure state
is `Credito.activo`.

Message-copy note: rejection `detail` strings are backend-owned and rendered
verbatim by the frontend. Spec prose is English; the `detail` text is Spanish UI
copy. Scenarios below fix the required SEMANTIC CONTENT, not exact wording.

## Requirements

### Requirement: Settled Definition

A `cuota_fija` credit is settled only when `saldo_capital <= 0` AND
`saldo_intereses <= 0`. An `abono_capital` credit is settled when
`saldo_capital <= 0`; it has no `saldo_intereses`. Zero capital alone MUST NOT
mean settled for `cuota_fija`.

#### Scenario: Capital settled, interest outstanding

- GIVEN a `cuota_fija` credit with `saldo_capital = 0.00` and `saldo_intereses > 0`
- THEN it is NOT settled and MUST remain open

#### Scenario: Both components settled

- GIVEN a `cuota_fija` credit with both balances at `0.00`
- THEN it is settled

### Requirement: Closure by Settled State Only

A credit MUST close when and only when it becomes settled on a balance-mutating
path (`_pago_exacto`, `_pago_parcial`, the excess path,
`registrar_pago_no_programado`). Installment count MUST NOT trigger closure. No
closure path MAY write `saldo_capital` or `saldo_intereses` to force closure.

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

#### Scenario: Under-paid final installment never forgives debt

- WHEN the final installment is only partly paid
- THEN both balances retain their real remaining amounts and `activo` stays `True`

#### Scenario: Real path without mocking

- WHEN the scenarios above are exercised without patching
  `generar_siguiente_cuota`
- THEN the observed installment generation matches the assertions

### Requirement: Interest-only Installment Tail

While `saldo_capital <= 0 < saldo_intereses` on a `cuota_fija` credit, generation
MUST continue with installments charging interest only: `capital_a_pagar = 0`,
`interes_a_pagar = min(interes_base, saldo_intereses)`, `tipo_cuota` = the
existing `interes` member, no arrastre. Generation MUST stop when settled.

#### Scenario: Tail generated

- GIVEN capital settled and `saldo_intereses = 5000.00`
- WHEN the next installment is generated
- THEN it charges interest only and never more than `saldo_intereses`

#### Scenario: Tail terminates

- WHEN each interest-only installment is paid in full
- THEN `saldo_intereses` strictly decreases and the credit closes on reaching zero

#### Scenario: No overcharge on the final installment

- GIVEN `saldo_intereses` below `interes_base`
- THEN the installment charges `saldo_intereses`, not `interes_base`

### Requirement: Abono Capital Closure and Interest Rounding

An `abono_capital` credit MUST close when `saldo_capital` reaches `0.00`. Paid
interest MUST be rounded `ROUND_HALF_UP` to 2 decimals.

#### Scenario: Settled abono capital credit

- WHEN a payment brings `saldo_capital` to `0.00`
- THEN `activo` becomes `False`

#### Scenario: Interest rounding

- GIVEN computed interest with more than 2 decimals
- THEN the persisted value equals the `ROUND_HALF_UP` 2-decimal amount

### Requirement: Operationally Open Credits Only on Read Paths

Portfolio totals and the collection list MUST include only operationally open
credits: `activo AND (saldo_capital > 0 OR (cuota_fija AND saldo_intereses > 0))`.
A settled but unconfirmed credit MUST disappear from both while `activo` is still
`True`. The collection list covers BOTH the real-row query of `GET /pagos` and its
virtual rows.

#### Scenario: Settled unconfirmed credit leaves read paths

- GIVEN a settled credit with `activo = True`
- THEN it appears in neither the portfolio total nor `GET /pagos` (real or virtual
  rows)

#### Scenario: Capital settled with interest outstanding stays visible

- GIVEN a `cuota_fija` credit with capital at zero and interest outstanding
- THEN it REMAINS in the portfolio total and the collection list

### Requirement: Admin Capital Edit Does Not Auto-Close

`PATCH /creditos/{id}` MUST NOT change `activo`. When the edit leaves the credit
settled, the response MUST expose a pending-closure signal.

#### Scenario: Edit settles the credit

- WHEN an admin lowers `capital_prestado` to at or below the capital already paid
- THEN balances update, `activo` stays `True`, and the response carries the
  pending-closure signal

#### Scenario: Interest-only installment preserved across an edit

- GIVEN a pending interest-only installment
- WHEN the credit is edited and the installment is recalculated
- THEN it stays interest-only and is not converted back into a capital installment

### Requirement: Explicit Closure Confirmation

A new endpoint MUST let `admin`, `recaudador` and `registrador` confirm closure of
a settled credit, writing an audit entry via `audit_service.registrar_*`.
Confirmation is deliberately NON-idempotent. Evaluation order and observable
status: unknown credit `404`; already closed `422`; not settled `422`; forbidden
role `403`.

#### Scenario: Authorized confirmation

- GIVEN a settled credit with `activo = True`
- WHEN an `admin`, `recaudador` or `registrador` confirms closure
- THEN `activo` becomes `False` and an audit entry is written

#### Scenario: Forbidden role

- WHEN a `gestor` calls the endpoint
- THEN the response is `403` and `activo` is unchanged

#### Scenario: Already-closed credit rejected

- GIVEN `activo = False`
- WHEN closure is confirmed again
- THEN the response is `422`, no state changes, and no audit entry is written

#### Scenario: Not-settled credit rejected

- GIVEN a credit with an outstanding balance
- WHEN closure is confirmed
- THEN the response is `422` and `activo` stays `True`

### Requirement: Operator-Readable Rejection Messages

Every rejection introduced or touched by this change MUST return an
`HTTPException` `detail` that states the BUSINESS REASON in Spanish, in terms an
operator recognizes, so the rejection does not read as a platform failure. The
`detail` MUST NOT be only internal field names, tolerances or raw numbers.
The message is written ONCE in the backend; any frontend site that triggers such a
rejection MUST surface `detail` rather than a generic literal.

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

- GIVEN a pending installment with `capital_a_pagar = 0`
- WHEN a payment with capital above tolerance is registered
- THEN the response is `422`
- AND `detail` explains that the installment charges interest only because the
  capital is already settled, instead of reporting a bare component-exceeded error

#### Scenario: Frontend surfaces the reason

- GIVEN a frontend site that invokes a rejection path from this change
- THEN it renders the backend `detail`
- AND MUST NOT swallow it behind a generic literal such as `'Error'`

### Requirement: Past-term Installments Are Explainable

When installments continue past `numero_cuotas`, the operator MUST be able to tell
from the payment data why installment 13 of 12 exists. The last-installment
indicator MUST be true only when the installment actually settles the credit, so
it is never stamped on an installment followed by more.

#### Scenario: Installment beyond the agreed term is identifiable

- GIVEN a credit past `numero_cuotas` with a balance outstanding
- WHEN its installment is read
- THEN the payload distinguishes it as beyond the agreed term, with its
  `numero_cuota` exceeding `numero_cuotas`

#### Scenario: Last-installment indicator not stamped before the tail

- GIVEN a final capital installment followed by interest-only installments
- THEN the last-installment indicator is false on it and true only on the
  installment that settles the credit

### Requirement: One-off Closure Backfill

A temporary admin-only endpoint MUST close every credit that is `activo = True`
and settled, report the closed IDs, and deliberately bypass the confirmation
requirement as a one-time historic correction.

#### Scenario: Qualifying credits closed

- WHEN the backfill runs
- THEN each settled `activo = True` credit becomes `activo = False` and its ID is
  reported

#### Scenario: Capital-only settled cuota_fija untouched

- GIVEN a `cuota_fija` credit with capital at zero and interest outstanding
- THEN the backfill leaves it open

#### Scenario: Idempotent re-run

- WHEN the backfill runs a second time
- THEN it reports zero corrections and changes nothing

## Non-Goals

- Reopening or reversing a closed credit (quote item 5) — no inverse of closure
  exists.
- Any Alembic migration; reuse the existing `tipo_cuota` enum members.
- Frontend automated tests; the frontend gate is `npx tsc --noEmit` only.
