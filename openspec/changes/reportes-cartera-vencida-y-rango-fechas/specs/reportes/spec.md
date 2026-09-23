# Reportes Specification

## Purpose

Defines the reporting capability: `GET /reportes/ingresos` (existing structure,
generalized) and `GET /reportes/cartera-vencida` (new). Both support two mutually
exclusive filter modes — "por momento" (`anio`/`mes`/`momento`) or "por intervalo"
(`fecha_desde`/`fecha_hasta`). Cartera Vencida is event-based on
`fecha_entrada_mora` (see `overdue-evaluation`) and always live-recomputed, never a
historical snapshot.

## Requirements

### Requirement: Two Mutually Exclusive Filter Modes

Both `GET /reportes/ingresos` and `GET /reportes/cartera-vencida` MUST accept either
momento params (`anio`, `mes`, `momento`, all required together) or interval params
(`fecha_desde`, `fecha_hasta`, both required together), never a mix. Supplying params
from both modes, or from neither mode, MUST be rejected with HTTP 422 before any query
runs. When momento mode is used, the resolved window MUST be identical to today's
`get_periodo_momento(anio, mes, momento)` result.

#### Scenario: Momento mode resolves as today `[pytest]`

- GIVEN `anio=2026, mes=9, momento=m1`
- WHEN either endpoint is called
- THEN the window is `2026-09-25 … 2026-09-29`, matching `get_periodo_momento` today

#### Scenario: Interval mode uses the raw bounds `[pytest]`

- GIVEN `fecha_desde=2026-09-01, fecha_hasta=2026-09-15`
- WHEN either endpoint is called
- THEN the window is exactly `2026-09-01 … 2026-09-15`

#### Scenario: Both modes supplied is rejected `[pytest]`

- GIVEN `anio=2026, mes=9, momento=m1, fecha_desde=2026-09-01, fecha_hasta=2026-09-15`
- WHEN either endpoint is called
- THEN the response is HTTP 422 and no data is queried

#### Scenario: Neither mode supplied is rejected `[pytest]`

- GIVEN no momento params and no interval params
- WHEN either endpoint is called
- THEN the response is HTTP 422 and no data is queried

### Requirement: Ingresos Report Structure Unchanged

`GET /reportes/ingresos` MUST produce the same response shape and aggregation logic as
today's `GET /reportes` for momento mode (per-window totals, paid/pending split), with
only the window source changed to accept interval mode as an alternative.

#### Scenario: Momento mode output matches today's endpoint `[pytest]`

- GIVEN identical data and identical `anio, mes, momento` params
- WHEN `GET /reportes/ingresos` is called
- THEN the response body matches what today's `GET /reportes` returns for the same
  params

#### Scenario: Interval mode aggregates the same way `[pytest]`

- GIVEN payments due inside `2026-09-01 … 2026-09-15`, some paid and some pending
- WHEN `GET /reportes/ingresos` is called with that interval
- THEN totals and the paid/pending split reflect only payments due inside that window,
  using the same aggregation fields as momento mode

### Requirement: Cartera Vencida Is Event-Based on Entrada en Mora

`GET /reportes/cartera-vencida` MUST include an unpaid payment iff
`fecha_entrada_mora(fecha_maxima)` falls inside the resolved window
(`fecha_inicio <= fecha_entrada_mora < fecha_fin_exclusive`, or the window's inclusive
end per the same convention as `get_periodo_momento`). It MUST NOT use `hoy_bogota()` or
any "as of today" cutoff — inclusion depends only on the window and the payment's
current `fecha_maxima`.

#### Scenario: Included when entrada-en-mora falls in the window `[pytest]`

- GIVEN an unpaid payment with `fecha_maxima = 2026-09-27` (`fecha_entrada_mora =
  2026-09-30`)
- WHEN the window is `2026-09-30 … 2026-10-04`
- THEN the payment is included in Cartera Vencida

#### Scenario: Excluded when entrada-en-mora falls outside the window `[pytest]`

- GIVEN the same payment (`fecha_entrada_mora = 2026-09-30`)
- WHEN the window is `2026-09-25 … 2026-09-29`
- THEN the payment is excluded from Cartera Vencida

#### Scenario: Paid payments are never included `[pytest]`

- GIVEN a payment with `pagado = true` and `fecha_entrada_mora` inside the window
- WHEN Cartera Vencida is requested for that window
- THEN the payment is excluded

### Requirement: Cartera Vencida Totals and Por-Gestor Breakdown Only

The response MUST include a total overdue amount and a breakdown per gestor (same
aggregation style as Ingresos' existing breakdowns), and MUST NOT include a
per-receptor breakdown, since these are unreceived (unpaid) payments.

#### Scenario: Totals and gestor breakdown present `[pytest]`

- GIVEN overdue payments belonging to two different gestores inside the window
- WHEN Cartera Vencida is requested
- THEN the response includes a grand total and one entry per gestor with that gestor's
  subtotal, summing to the grand total

#### Scenario: No receptor breakdown in the response `[pytest]`

- GIVEN overdue payments in the window
- WHEN Cartera Vencida is requested
- THEN the response body contains no per-receptor field or section

### Requirement: Cartera Vencida Is Live, Not a Historical Snapshot

Cartera Vencida MUST be recomputed at read time from each payment's current
`fecha_maxima`; it MUST NOT persist or reconstruct `fecha_entrada_mora` as it existed
at an earlier point in time. A payment deferred (`payment-deferral-tracking`) to a new
`fecha_maxima` whose `fecha_entrada_mora` no longer falls in a previously-queried past
window MUST NOT reappear when that window is re-queried later.

#### Scenario: Deferred payment disappears from a past window on re-query `[pytest]`

- GIVEN an unpaid payment originally due 2026-09-10 (`fecha_entrada_mora = 2026-09-14`,
  inside window `2026-09-01 … 2026-09-30`) that is later deferred to 2026-10-12
  (`fecha_entrada_mora` recomputed from the new `fecha_maxima`, now outside that window)
- WHEN Cartera Vencida is re-queried for `2026-09-01 … 2026-09-30` after the deferral
- THEN the payment is absent from the result and from the gestor total it previously
  contributed to

#### Scenario: Window entirely in the future returns an empty report `[pytest]`

- GIVEN today is `2026-09-23` and the requested window is `2026-10-01 … 2026-10-31`
  (entirely after today)
- WHEN Cartera Vencida is requested for that window
- THEN the effective query window is clamped to end at today, so no payment can have
  `fecha_entrada_mora` inside the future portion, and the response has zero total and
  an empty per-gestor breakdown

#### Scenario: Window partially in the future is clamped, not rejected `[pytest]`

- GIVEN today is `2026-09-23` and the requested window is `2026-09-15 … 2026-10-15`
  (straddles today)
- WHEN Cartera Vencida is requested for that window
- THEN payments are evaluated only against the `2026-09-15 … 2026-09-23` portion of the
  window (clamped to today), not the full requested range
