# Delta for Overdue Evaluation

> Change `scheduled-overdue-evaluation` — Phase 2 item 08. New capability: one
> system-wide definition of "overdue" (`en_mora`) tied to the close of the momento
> containing `fecha_maxima`, evaluated on the Bogotá calendar date (`hoy_bogota()`),
> computed at read time (no job, no persisted flag, no backfill), and exposed on the
> pago response. "Unpaid" means `pagado = false`. All dates below are Bogotá dates.
> Test tags: `[pytest]` = backend-automatable; `[manual]` = frontend, no runner.

## ADDED Requirements

### Requirement: Momento Instance Boundaries

Every calendar date MUST belong to exactly one momento instance (`year, month, m1..m5`)
using the existing classification: m1 = 25–29, m2 = 30 (and 31) through day 4 of the
next month, m3 = 5–13, m4 = 14–18, m5 = 19–24. Days 1–4 belong to m2 of the PREVIOUS
month (January 1–4 → m2 of December of the previous year). In February, m1 MUST end on
the last day of February (28, or 29 in a leap year) and m2 MUST be March 1–4. A momento
instance is "closed" at `hoy` iff `hoy` is strictly after its last day.

#### Scenario: Cross-month m2 `[pytest]`

- GIVEN `fecha_maxima = 2026-10-02`
- THEN its momento instance is (2026, 9, m2) spanning 2026-09-30 … 2026-10-04

#### Scenario: February non-leap `[pytest]`

- GIVEN `fecha_maxima = 2026-02-27`
- THEN its momento instance is (2026, 2, m1) spanning 2026-02-25 … 2026-02-28

#### Scenario: February leap `[pytest]`

- GIVEN `fecha_maxima = 2028-02-29`
- THEN its momento instance is (2028, 2, m1) spanning 2028-02-25 … 2028-02-29

#### Scenario: December to January `[pytest]`

- GIVEN `fecha_maxima = 2026-12-31`
- THEN its momento instance is (2026, 12, m2) spanning 2026-12-30 … 2027-01-04

### Requirement: Single Overdue Predicate

The system MUST define overdue (`en_mora`) exactly once as a pure function of
`(fecha_maxima, hoy)`: an unpaid payment is `en_mora` iff the momento instance
containing its `fecha_maxima` is closed at `hoy`, i.e. iff `fecha_maxima < first day of
the momento instance containing hoy`. Every consumer that evaluates overdue (alerts,
client status, response fields) MUST use this predicate or its equivalent date bound,
with `hoy = hoy_bogota()`. Server time MUST be injectable in tests as an explicit date.

#### Scenario: Inside the momento, not overdue `[pytest]`

- GIVEN unpaid `fecha_maxima = 2026-09-27` (m1, 25–29)
- WHEN evaluated with `hoy = 2026-09-28` or `hoy = 2026-09-29`
- THEN `en_mora = false`

#### Scenario: Day after the momento ends `[pytest]`

- GIVEN unpaid `fecha_maxima = 2026-09-27`
- WHEN evaluated with `hoy = 2026-09-30`
- THEN `en_mora = true`

#### Scenario: Cross-month m2 closes on the 5th `[pytest]`

- GIVEN unpaid `fecha_maxima = 2026-10-02`
- WHEN evaluated with `hoy = 2026-10-04` THEN `en_mora = false`
- AND WHEN evaluated with `hoy = 2026-10-05` THEN `en_mora = true`

#### Scenario: February non-leap closes on March 1 `[pytest]`

- GIVEN unpaid `fecha_maxima = 2026-02-27`
- WHEN evaluated with `hoy = 2026-02-28` THEN `en_mora = false`
- AND WHEN evaluated with `hoy = 2026-03-01` THEN `en_mora = true`

#### Scenario: February leap closes on March 1 `[pytest]`

- GIVEN unpaid `fecha_maxima = 2028-02-27`
- WHEN evaluated with `hoy = 2028-02-29` THEN `en_mora = false`
- AND WHEN evaluated with `hoy = 2028-03-01` THEN `en_mora = true`

#### Scenario: December m2 closes on January 5 `[pytest]`

- GIVEN unpaid `fecha_maxima = 2026-12-31`
- WHEN evaluated with `hoy = 2027-01-04` THEN `en_mora = false`
- AND WHEN evaluated with `hoy = 2027-01-05` THEN `en_mora = true`

#### Scenario: Far past is overdue `[pytest]`

- GIVEN unpaid `fecha_maxima = 2026-06-10`
- WHEN evaluated with `hoy = 2026-09-15`
- THEN `en_mora = true`

### Requirement: Overdue Fields on the Pago Response

`PagoResponse` MUST expose two server-computed booleans: `vencido` (`pagado = false`
AND `fecha_maxima < hoy_bogota()`, visual alert) and `en_mora` (Single Overdue
Predicate, counts). `en_mora = true` MUST imply `vencido = true`. Paid rows MUST return
both `false`. Projected (non-persisted) rows MUST return both `false`. Both fields MUST
be present on every listing that returns `PagoResponse` (monthly, weekly, daily,
deferred, per-credit).

#### Scenario: Past due inside an open momento `[pytest]`

- GIVEN unpaid `fecha_maxima = 2026-09-27` and `hoy = 2026-09-29`
- WHEN the payment is listed
- THEN `vencido = true` AND `en_mora = false`

#### Scenario: Past due after the momento closed `[pytest]`

- GIVEN the same payment and `hoy = 2026-09-30`
- WHEN listed THEN `vencido = true` AND `en_mora = true`

#### Scenario: Due today or later `[pytest]`

- GIVEN unpaid `fecha_maxima = 2026-09-27` and `hoy = 2026-09-27`
- WHEN listed THEN `vencido = false` AND `en_mora = false`

#### Scenario: Paid and projected rows `[pytest]`

- GIVEN a paid row with `fecha_maxima = 2026-06-10` and a projected row
- WHEN listed with `hoy = 2026-09-15`
- THEN both rows have `vencido = false` AND `en_mora = false`

### Requirement: Overdue Alerts Count Only `en_mora`

`GET /pagos/alertas/vencidos` MUST return only unpaid payments with `en_mora = true`
(momento closed), keeping today's other filters (operationally open credit, visibility,
soft-delete). Payments that are `vencido` but not `en_mora` MUST NOT be included in the
list, the count, or the total amount. Dashboard KPI and header badge consume this
endpoint and therefore MUST agree with it without further client-side filtering.

#### Scenario: Open momento excluded from alerts `[pytest]`

- GIVEN unpaid payments due 2026-09-27 (A) and 2026-09-10 (B) and `hoy = 2026-09-29`
- WHEN alerts are requested
- THEN only B is returned; count and total reflect B only

#### Scenario: Closed momento included `[pytest]`

- GIVEN the same payments and `hoy = 2026-09-30`
- WHEN alerts are requested
- THEN A and B are both returned

### Requirement: Client Status Uses the Same Predicate

A client is "al día" iff none of their payments is `en_mora` per the Single Overdue
Predicate. This definition MUST be applied identically at every site that derives client
status: the `al_dia` list filter on `GET /clientes`, the `al_dia` value returned on each
client in the listing, and the client detail. A `vencido` but not `en_mora` payment MUST
NOT mark the client as "en atraso". The persisted `Cliente.al_dia` column MUST remain
unused for this decision.

#### Scenario: Client stays al día inside the momento `[pytest]`

- GIVEN a client whose only unpaid payment is due 2026-09-27 and `hoy = 2026-09-29`
- WHEN the listing is filtered by `al_dia = true`, listed unfiltered, and the detail is read
- THEN the client is returned by the filter AND `al_dia = true` in all three responses

#### Scenario: Client in atraso after close `[pytest]`

- GIVEN the same client and `hoy = 2026-09-30`
- WHEN the three sites are read
- THEN the client is excluded by `al_dia = true`, returned by `al_dia = false`, and
  `al_dia = false` in listing and detail

### Requirement: Deferred Payments Evaluated on Current Date

A payment with `veces_aplazado > 0` MUST be evaluated by the Single Overdue Predicate
against its current `fecha_maxima` only; the original date and the counter MUST NOT
affect `vencido`, `en_mora`, alerts, or client status.

#### Scenario: Deferral moves the payment out of mora `[pytest]`

- GIVEN a payment originally due 2026-09-10 deferred to 2026-10-02 and `hoy = 2026-09-30`
- WHEN listed and alerts are requested
- THEN `en_mora = false` AND it is absent from alerts

#### Scenario: Deferred and closed again `[pytest]`

- GIVEN the same payment and `hoy = 2026-10-05`
- WHEN listed THEN `en_mora = true` AND it appears in alerts

### Requirement: Partial Payments Are Not Special-Cased

A partially paid installment (`pagado = false` with some `capital_pagado` or
`interes_pagado`) MUST be evaluated exactly like any unpaid payment.

#### Scenario: Partial after close `[pytest]`

- GIVEN a `pagado = false` installment with a partial amount recorded, due 2026-09-27
- WHEN evaluated with `hoy = 2026-09-30`
- THEN `en_mora = true` and it counts in alerts and client status

### Requirement: Frontend Never Derives Overdue from Browser Time

The frontend MUST decide overdue rendering solely from the server-provided `vencido` and
`en_mora` fields. No view MAY compare `fecha_maxima` with the browser clock
(`new Date()`) to decide row color, text style, badge, counts, or client status. In the
shared payments table (all variants) an unpaid row MUST render the red alert style when
`vencido = true`; the "Vencido" badge MUST be shown only when `en_mora = true`.

#### Scenario: Red without badge inside the momento `[manual]`

- GIVEN a row with `vencido = true` and `en_mora = false`
- THEN it renders red AND no "Vencido" badge is shown

#### Scenario: Red with badge after close `[manual]`

- GIVEN a row with `vencido = true` and `en_mora = true`
- THEN it renders red AND the "Vencido" badge is shown

#### Scenario: Badge count matches KPI `[manual]`

- GIVEN the Pagos list and the dashboard on the same Bogotá date
- THEN the number of rows with the "Vencido" badge equals the dashboard overdue count
  for the same scope

#### Scenario: Browser clock is irrelevant `[manual]`

- GIVEN a browser whose local date differs from the Bogotá date
- WHEN the Pagos list is rendered
- THEN row styling and badges follow the server fields, not the local date

## Non-Goals

- Scheduled job, cron, notifications, persisted overdue flag, backfill, report changes,
  changes to momento ranges, closure rules, or deferral semantics.
