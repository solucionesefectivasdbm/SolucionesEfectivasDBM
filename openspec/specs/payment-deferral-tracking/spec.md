# Payment Deferral Tracking Specification

## Purpose

Defines how a client-requested deferral of one installment is recorded,
distinguished from a clerical date correction, exposed to the UI, and listed
across periods. The single source of truth is the per-payment counter
`veces_aplazado`; a payment is "deferred" iff `veces_aplazado > 0`. No reason
field, no history table, no backfill. Rejection `detail` strings are
backend-owned Spanish UI copy; scenarios fix semantic content, not wording.

Test tags: `[pytest]` = backend-automatable; `[manual]` = frontend, no runner.

## Requirements

### Requirement: Deferral Counter

Every persisted payment MUST carry `veces_aplazado` (integer, `>= 0`, default
`0`, never null). Existing rows MUST read `0` after migration. In v1 the
counter MUST only increase; no endpoint decrements or resets it. `PagoResponse`
MUST expose `veces_aplazado` for real rows and `0` for projected rows.

#### Scenario: Existing rows default to zero `[pytest]`

- GIVEN payments created before this change
- WHEN any listing returns them
- THEN each has `veces_aplazado = 0`

#### Scenario: Reversal keeps the counter `[pytest]`

- GIVEN a validated, deferred payment (`veces_aplazado = 2`)
- WHEN `desvalidar` succeeds
- THEN `veces_aplazado` is still `2`

### Requirement: Extended Date Modification

`PATCH /pagos/{id}/fecha` MUST accept an optional `es_aplazamiento` boolean
defaulting to `false`. With `false` the behavior MUST be identical to today
(date overwritten, counter untouched, existing audit entry). With `true` the
system MUST set `fecha_maxima`, increment `veces_aplazado` by one, and return
the updated payment. `momento` and later installments MUST NOT change.

#### Scenario: Plain correction unchanged `[pytest]`

- GIVEN a pending payment with `veces_aplazado = 0`
- WHEN the date is modified without `es_aplazamiento`
- THEN the date changes and `veces_aplazado` stays `0`

#### Scenario: First deferral `[pytest]`

- GIVEN a pending payment due 2026-10-05
- WHEN the date is moved to 2026-10-12 with `es_aplazamiento = true`
- THEN `fecha_maxima = 2026-10-12` and `veces_aplazado = 1`

#### Scenario: Second deferral `[pytest]`

- GIVEN the payment above
- WHEN it is deferred again to 2026-10-19
- THEN `veces_aplazado = 2`

#### Scenario: Correction after deferral `[pytest]`

- GIVEN a payment with `veces_aplazado = 1`
- WHEN the date is modified with `es_aplazamiento = false`
- THEN the date changes and `veces_aplazado` stays `1`

### Requirement: Deferral Rejections

A call with `es_aplazamiento = true` MUST be rejected with HTTP 422 and a
plain-string `detail`, checked in this order: (1) `pagado = true`; (2) the new
`fecha_maxima` is not strictly later than the current one. A rejected call
MUST NOT modify the payment or write an audit entry. Plain corrections
(`es_aplazamiento = false`) on paid payments and backward moves MUST remain
allowed as today. Projected rows have no persisted id, so any date
modification on them MUST fail with 404 and persist nothing.

#### Scenario: Paid payment cannot be deferred `[pytest]`

- GIVEN a payment with `pagado = true`
- WHEN it is deferred
- THEN the response is 422 stating a paid installment cannot be deferred,
  and date and counter are unchanged

#### Scenario: Backward or same date is not a deferral `[pytest]`

- GIVEN a pending payment due 2026-10-12
- WHEN it is "deferred" to 2026-10-12 or 2026-10-05
- THEN the response is 422 stating a deferral must move the date forward,
  and nothing changes

#### Scenario: Deferred then paid `[pytest]`

- GIVEN a payment with `veces_aplazado = 1`
- WHEN it is paid in full
- THEN `veces_aplazado` stays `1` and a further deferral returns 422

### Requirement: Role Gate

The role gate MUST be the current one for `modificar_fecha_pago`: `admin` and
`recaudador` only; any other role MUST receive 403 regardless of
`es_aplazamiento`.

#### Scenario: Registrador and gestor forbidden `[pytest]`

- WHEN a `registrador` or `gestor` sends `es_aplazamiento = true`
- THEN the response is 403 and the payment is unchanged

### Requirement: Distinguishable Audit

A successful deferral MUST write an audit entry attributed to the caller that
records the `fecha_maxima` transition AND is distinguishable from a plain
correction (for example, an additional tracked change on `veces_aplazado`
old → new). A plain correction MUST NOT write that deferral marker.

#### Scenario: Deferral audited `[pytest]`

- WHEN a deferral succeeds
- THEN the audit shows `fecha_maxima` old → new and `veces_aplazado` `0` → `1`
  with the caller's id

#### Scenario: Correction audited as today `[pytest]`

- WHEN a plain correction succeeds
- THEN only the `fecha_maxima` change is audited

### Requirement: Cross-Period Deferred Listing

The system MUST provide a listing of real (non-projected) payments with
`veces_aplazado > 0` with no year/month bound. By default it MUST return only
pending (`pagado = false`) rows; `incluir_pagados = true` MUST add paid ones.
Rows MUST be sorted by `fecha_maxima` ascending. Visibility rules of
`listar_pagos` MUST apply: any authenticated user may call it, a `gestor`
sees only their own clients' payments, soft-deleted rows are excluded, and
pending rows of operationally closed credits are excluded.

#### Scenario: Spans months `[pytest]`

- GIVEN pending deferred payments due in October and December
- WHEN the deferred listing is requested without filters
- THEN both are returned, October first

#### Scenario: Paid excluded by default `[pytest]`

- GIVEN one pending and one paid deferred payment
- WHEN listed without `incluir_pagados`
- THEN only the pending one is returned
- AND with `incluir_pagados = true` both are returned

#### Scenario: Gestor scoping `[pytest]`

- GIVEN deferred payments of two gestores
- WHEN a `gestor` requests the listing
- THEN only their clients' payments are returned

### Requirement: Double Visualization

A deferred payment MUST still appear in the weekly and daily listings for the
period of its current `fecha_maxima`, with `veces_aplazado` populated.

#### Scenario: Present in both views `[pytest]`

- GIVEN a payment deferred into November
- WHEN November is listed via `GET /pagos` and the deferred listing is requested
- THEN the payment is in both with `veces_aplazado = 1`

### Requirement: Deferral Prompt in the UI

The existing "Modificar fecha" action MUST ask whether the change is a
client-requested deferral before submitting. "Yes" MUST send
`es_aplazamiento = true`; "No" or dismiss MUST send a plain correction or
nothing. Backend 4xx `detail` MUST be shown verbatim (as in
`payment-validation-reversal`).

#### Scenario: Yes increments, No does not `[manual]`

- GIVEN the Pagos list and a pending row
- WHEN the user changes the date and answers "Yes", then on another row
  answers "No"
- THEN the first row shows a badge with `1` and the second shows none

#### Scenario: Paid row has no date button `[manual]`

- GIVEN a paid row
- THEN the "Modificar fecha" button is not rendered, so no deferral can
  be requested from the UI
- (the backend 422 guard for `es_aplazamiento` on a paid row is covered
  by the `[pytest]` scenario, not reachable from this UI path)

### Requirement: Row Styling and Badge

In the shared payments table (weekly, daily, and deferred variants) a row with
`veces_aplazado > 0` MUST use one dedicated deferred style and show a badge
with the counter. Precedence MUST be: projected (gray) unaffected; overdue red
(server field `vencido = true`) wins over the deferred style; otherwise deferred
style. The "Vencido" badge MUST be shown only when the server field `en_mora = true`
(see `overdue-evaluation`); the deferral counter badge MUST remain visible in every
case. The frontend MUST NOT compare `fecha_maxima` with the browser clock to decide
any of these styles. There MUST be no escalated style for `>= 2`; only the badge
number changes. The `/pagos/aplazados` page MUST default to pending-only and offer a
control to include paid rows.
(Previously: overdue red was defined as `pagado = false` and `fecha_maxima < today`
evaluated in the browser, and the "Vencido" badge followed the same condition.)

#### Scenario: Deferred not overdue `[manual]`

- GIVEN a pending row deferred to a future date (`vencido = false`)
- THEN it renders with the deferred style and badge `1`

#### Scenario: Deferred and past due inside the open momento `[manual]`

- GIVEN a row deferred to 2026-09-27 rendered on Bogotá date 2026-09-29
  (`vencido = true`, `en_mora = false`)
- THEN it renders red with the counter badge `1` visible and no "Vencido" badge

#### Scenario: Deferred and overdue again `[manual]`

- GIVEN a row deferred to 2026-09-27 rendered on Bogotá date 2026-09-30
  (`vencido = true`, `en_mora = true`)
- THEN it renders red with the counter badge still visible and the "Vencido" badge shown

#### Scenario: Two deferrals same style `[manual]`

- GIVEN rows with counters `1` and `3`
- THEN both share the same deferred style and differ only in badge number

## Non-Goals

- Reason/motivo field, deferral history, decrement or undo of the counter,
  backfill of past deferrals, changes to `PATCH /creditos/{id}/dias-pago`,
  new roles or permissions.
