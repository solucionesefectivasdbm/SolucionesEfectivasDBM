# Payment Validation Reversal Specification

## Purpose

Defines the rules for reverting the recaudador validation ("check") of an
installment via `POST /pagos/{pago_id}/desvalidar`, plus the traceability
and UI feedback that make every failed attempt explainable. Business rules
are the current ones: no time window, no same-user restriction, no
`credito.activo` guard. Rejection `detail` strings are backend-owned Spanish
UI copy; scenarios fix semantic content, not exact wording.

Test tags: `[pytest]` = backend-automatable; `[manual]` = frontend, no runner.

## Requirements

### Requirement: Successful Reversal

Reverting a validated installment that is unpaid and has no recorded amounts
MUST clear `validado_recaudador` and `tipo_validacion`, return HTTP 200 with
the updated payment, and record one audit call attributed to the caller that
tracks `validado_recaudador` True→False, plus a `tipo_validacion` entry
recording its prior value → `None` when `tipo_validacion` was set (no
`tipo_validacion` entry is written when it was already null, since nothing
changed).

#### Scenario: Validated unpaid installment is reverted `[pytest]`

- GIVEN an installment with `validado_recaudador = True`, `pagado = False`,
  `capital_pagado = 0` and `interes_pagado = 0`
- WHEN an `admin` or `recaudador` calls `desvalidar`
- THEN the response is 200, `validado_recaudador` is `False` and
  `tipo_validacion` is null
- AND an audit entry exists for `validado_recaudador` with the caller's id
- AND, if `tipo_validacion` had a value before the call, a second audit entry
  exists recording that prior value being cleared to `None`

### Requirement: Reversal Rejections

The endpoint MUST reject with HTTP 422 and a plain-string `detail`, checked in
this order: (1) `pagado = True`; (2) `capital_pagado > 0` or
`interes_pagado > 0`; (3) `validado_recaudador = False`. A rejected call MUST
NOT modify the payment or write an audit entry.

#### Scenario: Paid installment `[pytest]`

- GIVEN an installment with `pagado = True`
- WHEN `desvalidar` is called
- THEN the response is 422 and the message states the payment was already
  registered with amounts, and nothing changes

#### Scenario: Amounts recorded `[pytest]`

- GIVEN an unpaid installment with `capital_pagado > 0` or `interes_pagado > 0`
- WHEN `desvalidar` is called
- THEN the response is 422 and the message states amounts are recorded

#### Scenario: Not validated `[pytest]`

- GIVEN an unpaid installment with `validado_recaudador = False` and no amounts
- WHEN `desvalidar` is called
- THEN the response is 422 and the message states it was not validated

### Requirement: Role Matrix

Only `admin` and `recaudador` MAY revert. Any other role MUST receive HTTP 403
before any payment state is read or logged as a business rejection.

#### Scenario: Registrador and gestor forbidden `[pytest]`

- GIVEN a validated installment and a `registrador` or `gestor` user
- WHEN `desvalidar` is called
- THEN the response is 403 and the installment stays validated

#### Scenario: Admin and recaudador allowed `[pytest]`

- GIVEN two validated installments
- WHEN an `admin` reverts one and a `recaudador` reverts the other
- THEN both responses are 200

### Requirement: Concurrent and Repeated Calls

The credit row MUST be locked (`SELECT ... FOR UPDATE` on the credit, same as
`registrar_pago`) for the duration of the request so that two concurrent
reversals of the same payment serialize. A second call on an already-reverted
payment MUST return 422 (not-validated message); the system MUST NOT return a
silent success.

#### Scenario: Double call `[pytest]`

- GIVEN a validated installment
- WHEN `desvalidar` is called twice in sequence by the same user
- THEN the first response is 200, the second is 422 with the not-validated
  message, and the second call adds no new audit entry (only the entries
  written by the first, successful call exist)

### Requirement: Attempt Logging

Every call that passes the role check MUST emit exactly one application log
line containing `pago_id`, `usuario_id`, and the outcome: `DESVALIDAR OK` on
success or the rejection reason (`pagado`, `montos_registrados`,
`no_validado`) on failure. Logging MUST NOT add audit rows or change the
schema.

#### Scenario: Success logged `[pytest]`

- WHEN a reversal succeeds
- THEN one log line records `DESVALIDAR OK` with `pago_id` and `usuario_id`

#### Scenario: Each rejection logged `[pytest]`

- GIVEN one installment per rejection cause (paid, amounts, not validated)
- WHEN `desvalidar` is called on each
- THEN each produces one log line with the matching reason and no audit entry

### Requirement: Frontend Submit Guard

While a reversal request is in flight, the "Reversar" control for that row
MUST be disabled and further clicks MUST NOT issue additional requests.

#### Scenario: Double-click yields one request `[manual]`

- GIVEN the Pagos list with a validated row and a throttled network
- WHEN the user double-clicks "Reversar" and confirms
- THEN exactly one `desvalidar` request is sent and the button re-enables
  after the response

### Requirement: Error Message Mapping

The UI MUST never show the literal `Error`. Failures MUST map as: backend
4xx with `detail` → show `detail` verbatim; no HTTP response (network) →
a specific network-failure message; expired session → handled by
`session-expiry-feedback`. After a 422 the list MUST be refetched so the row
reflects server state, except when the error is the session-expiry rejection
(the page is already navigating to `/login`; refetching there would re-enter
the refresh flow and produce a stray toast).

#### Scenario: Backend rejection shown and list refreshed `[manual]`

- GIVEN another user already reverted the same row
- WHEN this user clicks "Reversar"
- THEN the toast shows the backend not-validated message
- AND the row no longer offers "Reversar" after refetch

#### Scenario: Network failure `[manual]`

- GIVEN the API is unreachable
- WHEN the user clicks "Reversar"
- THEN the toast shows the network-failure message, not `Error`

## Non-Goals

- Reversal on closed credits (`credit-closure` non-goal); time windows;
  same-user restriction; changes to `registrar_pago` or `validar`.
