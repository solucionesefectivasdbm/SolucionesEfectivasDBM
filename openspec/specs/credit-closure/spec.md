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
automatic closure path MAY write `saldo_capital` or `saldo_intereses` to force
closure. The ONLY exception is the operator-driven explicit closure with the opt-in
flag (see Explicit Closure Confirmation), which MAY set `saldo_intereses` to
`Decimal("0.00")` on a capital-settled `cuota_fija` credit, atomically with
`activo = False` and with the previous value audited. The four payment-path call
sites and the settled-only closure primitive MUST remain unchanged.
(Previously: no closure path of any kind could write balances.)

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

#### Scenario: Last installment paid partially with balance outstanding

- GIVEN a `cuota_fija` credit at `numero_cuota == numero_cuotas` (base `13600.00`)
- WHEN it is paid partially (e.g. `8000.00`) and capital remains
- THEN `activo` stays `True`, balances reflect the real remaining amounts
- AND the further installment is generated with the SAME base value (`13600.00`),
  carrying no arrastre

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

### Requirement: Closable-with-Interest-Pending Signal

`CreditoResponse` MUST expose `puede_cerrar_con_interes_pendiente: bool`, true if and
only if `activo` AND `tipo_credito == cuota_fija` AND `saldo_capital <= 0` AND
`saldo_intereses > 0`. `pendiente_de_cierre` semantics MUST NOT change; the two flags
are mutually exclusive.

#### Scenario: Capital settled, interest outstanding

- GIVEN an active `cuota_fija` credit with `saldo_capital = 0.00`, `saldo_intereses = 5000.00`
- WHEN the credit is read (list or detail)
- THEN `puede_cerrar_con_interes_pendiente` is true AND `pendiente_de_cierre` is false

#### Scenario: Signal false outside the state

- GIVEN a credit that is closed, OR has `saldo_capital > 0`, OR has both balances at
  zero, OR is `abono_capital`
- WHEN the credit is read
- THEN `puede_cerrar_con_interes_pendiente` is false

### Requirement: Post-payment Closure Prompt

After a successful payment on any of the three payment routes (`registrar`,
`confirmar-excedente`, `no-programado`), the payments UI MUST re-read the credit and,
when `puede_cerrar_con_interes_pendiente` is true, show the prompt
"Crédito con saldo de capital en 0 pero interés pendiente de $X. ¿Desea cerrarlo o
seguir cobrando el interés pendiente?" with buttons "Cerrar crédito" / "Seguir
cobrando". `$X` is `saldo_intereses` formatted as elsewhere in the UI.

#### Scenario: Prompt shown

- GIVEN a payment that leaves a `cuota_fija` credit at capital `0.00` / interest `> 0`
- WHEN the payment succeeds on any of the three routes
- THEN the prompt appears showing the pending interest amount

#### Scenario: Prompt not shown

- GIVEN a payment that leaves capital `> 0`, OR settles both balances, OR fails
- WHEN the request completes
- THEN no prompt appears and the existing flow is unchanged

#### Scenario: Operator closes

- WHEN "Cerrar crédito" is pressed
- THEN the closure endpoint is called with the opt-in flag
- AND on success the credit shows as closed; on error the backend `detail` is rendered
  via the existing toast pattern

#### Scenario: Operator keeps collecting

- WHEN "Seguir cobrando" is pressed
- THEN the prompt closes; no request is sent, nothing is written, no audit entry exists
- AND the credit stays operationally open with its interest-only installment tail

### Requirement: Credit List Badge and Action for Capital-Settled Credits

The credit list MUST render a distinct badge "Capital saldado · interés pendiente" when
`puede_cerrar_con_interes_pendiente` is true, visually distinct from "Saldado —
pendiente de cierre", and MUST offer the close action to `admin`, `recaudador` and
`registrador` for that state. The action MUST call the endpoint with the opt-in flag.

#### Scenario: Badge and action visible

- GIVEN a credit with `puede_cerrar_con_interes_pendiente = true`
- WHEN an `admin`, `recaudador` or `registrador` views the list
- THEN the distinct badge and the close action are shown

#### Scenario: Action hidden for other roles

- GIVEN the same credit
- WHEN a `gestor` views the list
- THEN the badge is shown and the close action is not

### Requirement: Explicit Closure Confirmation

The closure endpoint MUST let `admin`, `recaudador` and `registrador` confirm closure
of a settled credit, writing an audit entry via `audit_service.registrar_*`.
Confirmation is deliberately NON-idempotent. The request body MAY carry an opt-in
flag `cerrar_con_interes_pendiente: bool` (default `false`). Evaluation order and
observable status: unknown credit `404`; already closed `422`; `saldo_capital > 0`
`422` regardless of the flag; then, for `cuota_fija` with `saldo_intereses > 0`:
flag absent/false `422`, flag true → close; settled credit → close regardless of the
flag; forbidden role `403`. Closing with the flag on a capital-settled `cuota_fija`
MUST set `saldo_intereses` to `Decimal("0.00")` and `activo` to `False` in the same
transaction, and audit both changes in a single `registrar_actualizacion_campos`
call (the helper writes one `AuditLog` row per field: `activo` `True → False` and
`saldo_intereses` previous value → `0.00`, both in the same transaction). Without the flag,
behavior MUST be exactly today's. For `abono_capital` the flag MUST be ignored.
(Previously: no request body; `saldo_intereses > 0` was always `422`.)

#### Scenario: Authorized confirmation

- GIVEN a settled credit with `activo = True`
- WHEN an `admin`, `recaudador` or `registrador` confirms closure
- THEN `activo` becomes `False` and an audit entry is written

#### Scenario: Forbidden role

- WHEN a `gestor` calls the endpoint
- THEN the response is `403` and `activo` is unchanged

#### Scenario: Already-closed credit rejected

- GIVEN `activo = False`
- WHEN closure is confirmed again, with or without the flag
- THEN the response is `422`, no state changes, and no audit entry is written

#### Scenario: Not-settled credit rejected

- GIVEN a credit with an outstanding balance
- WHEN closure is confirmed without the flag
- THEN the response is `422` and `activo` stays `True`

#### Scenario: Interest pending without the flag keeps today's behavior

- GIVEN an active `cuota_fija` credit with `saldo_capital = 0.00`, `saldo_intereses = 5000.00`
- WHEN closure is confirmed with the flag absent or `false`
- THEN the response is `422`, balances and `activo` are unchanged, no audit entry

#### Scenario: Interest pending with the flag closes

- GIVEN the same credit
- WHEN an authorized role confirms closure with the flag `true`
- THEN `activo` is `False`, `saldo_intereses` is `Decimal("0.00")`, `saldo_capital` unchanged
- AND the audit log contains two rows from the same call: `activo` `True → False`
  and `saldo_intereses` `5000.00 → 0.00`
- AND the credit no longer appears in portfolio totals or the collection list

#### Scenario: Flag never bypasses capital pending

- GIVEN an active credit with `saldo_capital > 0` (any `saldo_intereses`)
- WHEN closure is confirmed with the flag `true`
- THEN the response is `422`, balances and `activo` are unchanged, no audit entry

#### Scenario: Flag on a fully settled credit

- GIVEN an active credit with both balances at `0.00`
- WHEN closure is confirmed with the flag `true`
- THEN it closes exactly as without the flag; the audit entry records `activo` only

#### Scenario: Flag on an abono_capital credit

- GIVEN an active `abono_capital` credit
- WHEN closure is confirmed with the flag `true`
- THEN the flag is ignored: `saldo_capital <= 0` closes, `saldo_capital > 0` is `422`
- AND `saldo_intereses` is never written

### Requirement: Operator-Readable Rejection Messages

Every rejection introduced or touched by this change MUST return an
`HTTPException` `detail` that states the BUSINESS REASON in Spanish, in terms an
operator recognizes, so the rejection does not read as a platform failure. The
`detail` MUST NOT be only internal field names, tolerances or raw numbers.
The message is written ONCE in the backend; any frontend site that triggers such a
rejection MUST surface `detail` rather than a generic literal.
(Previously: identical text; scenario added for the flag-with-capital-pending case.)

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
