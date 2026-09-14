# Delta for Credit Closure

> Change `zero-balance-explicit-closure` — rule 14. Delta on `openspec/specs/credit-closure/spec.md`.
> Scope: `cuota_fija` only. `abono_capital` never carries `saldo_intereses` (rule 3).
> Message-copy note unchanged: rejection `detail` is backend-owned Spanish copy rendered
> verbatim; scenarios fix semantic content, not wording. Quoted UI copy below is binding.

## ADDED Requirements

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

- GIVEN a pending installment with `capital_a_pagar = 0`
- WHEN a payment with capital above tolerance is registered
- THEN the response is `422`
- AND `detail` explains that the installment charges interest only because the
  capital is already settled, instead of reporting a bare component-exceeded error

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

## Non-Goals (delta)

- Automatic closure on any payment path; reopening a closed credit; backfills;
  Alembic migrations; enriching payment response schemas with credit state.
