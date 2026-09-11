# Daily Installment Scheduling Specification

## Purpose

Defines due-date rules for `periodicidad = diario` credits: Sunday is never a
collection day, a Sunday start date is rejected, projections match generation,
and pending Sunday-dated rows are corrected once. Dates are calendar `date`
values; weekday semantics follow ISO (Monday..Sunday). Rejection `detail`
strings are backend-owned Spanish UI copy; scenarios fix semantic content,
not exact wording. Scope is `diario` only.

## Requirements

### Requirement: Sunday Is Never a Daily Due Date

For a `diario` credit, the next due date computed from any prior due date MUST
be the next calendar day, and when that day is a Sunday it MUST be the
following Monday instead. Every subsequent installment MUST be computed from
the shifted date, so the shift cascades. The installment count MUST NOT change
and no two installments of one credit MAY share a due date.

#### Scenario: Saturday advances to Monday

- GIVEN a daily installment due on Saturday 2026-01-31
- WHEN the next due date is computed
- THEN it is Monday 2026-02-02 (month boundary crossed, Sunday skipped)

#### Scenario: Non-Sunday day advances by one

- GIVEN a daily installment due on Thursday 2026-01-15
- WHEN the next due date is computed
- THEN it is Friday 2026-01-16

#### Scenario: Cascade preserves count and uniqueness

- GIVEN a daily credit with `numero_cuotas = 10` starting Monday 2026-01-05
- WHEN all ten due dates are generated
- THEN none falls on a Sunday, the last is 2026-01-15, all dates are distinct
- AND exactly ten installments exist

### Requirement: Other Periodicities Unchanged

The Sunday rule MUST apply only to `diario`. `semanal`, `quincenal` and
`mensual` MUST keep their current next-date behavior, including due dates that
fall on a Sunday.

#### Scenario: Weekly credit due on Sunday stays

- GIVEN a `semanal` installment due on Sunday 2026-01-25
- WHEN the next due date is computed
- THEN it is Sunday 2026-02-01

#### Scenario: Anchored periodicities untouched

- GIVEN a `mensual` or `quincenal` credit whose anchor day lands on a Sunday
- WHEN the next due date is computed
- THEN the result equals the current anchor-based behavior

### Requirement: Sunday Start Date Rejected on Creation

Creating a `diario` credit whose `fecha_inicial_pago` is a Sunday MUST be
rejected with HTTP 422 carrying a plain-string `detail` (router-level
check, so the existing frontend toast renders it verbatim).
The system MUST NOT silently move the date. The message MUST state, in
operator terms, that daily credits do not collect on Sunday and another start
date is required.

#### Scenario: Sunday start rejected

- GIVEN a `diario` credit payload with `fecha_inicial_pago = 2026-02-01` (Sunday)
- WHEN the credit is created
- THEN the response is 422, no credit or installment is persisted
- AND the message names Sunday as not a daily collection day

#### Scenario: Non-Sunday start accepted

- GIVEN the same payload with `fecha_inicial_pago = 2026-02-02`
- WHEN the credit is created
- THEN it succeeds and the first installment is due 2026-02-02

#### Scenario: Sunday start allowed for other periodicities

- GIVEN a `semanal` credit with a Sunday `fecha_inicial_pago`
- WHEN the credit is created
- THEN it is accepted as today

### Requirement: Projection Parity

Virtual (non-persisted) daily installments shown by `GET /pagos` and
`GET /pagos/diarios` MUST use the same next-date rule as real generation, so
no projected or persisted daily due date is a Sunday.

#### Scenario: Projected rows skip Sunday

- GIVEN a daily credit whose next real installment is due Saturday
- WHEN its virtual successors are projected
- THEN the first virtual row is due Monday and later rows cascade identically
  to what generation would persist

### Requirement: Independence from Carry-over and Closure

Date shifting MUST NOT alter `numero_cuota`, amounts, shortfall carry-over
(`payment-carryover`) or settlement/closure (`credit-closure`).

#### Scenario: Shortfall carried across a Sunday shift

- GIVEN a daily `cuota_fija` installment due Saturday paid partially
- WHEN the next installment is generated
- THEN it is due Monday, carries the per-component shortfall, and
  `capital_a_pagar + interes_a_pagar == monto_a_pagar`

### Requirement: One-off Pending-Row Backfill

A temporary admin-only POST endpoint MUST recompute due dates of pending
(`pagado = False`, `deleted_at IS NULL`) installments of active `diario`
credits so none is a Sunday, re-walking each credit's pending rows in order
from its earliest pending row. Paid rows and non-`diario` credits MUST NOT be
modified. The endpoint MUST be idempotent and MUST report the corrected credit
IDs, the number of rows changed, and before/after dates per row. It MUST be
removed in a follow-up change.

#### Scenario: Pending Sunday row and successors corrected

- GIVEN an active daily credit with a pending row due Sunday followed by
  pending rows on Monday and Tuesday
- WHEN the backfill runs
- THEN the rows become Monday, Tuesday, Wednesday and the report lists them

#### Scenario: Pending first installment on Sunday corrected

- GIVEN an active daily credit whose only pending row is installment 1 due Sunday
- WHEN the backfill runs
- THEN that row moves to Monday

#### Scenario: Paid and non-daily rows untouched

- GIVEN a paid daily row due Sunday and a pending `semanal` row due Sunday
- WHEN the backfill runs
- THEN both keep their dates

#### Scenario: Idempotent re-run

- WHEN the backfill runs a second time
- THEN it reports zero changed rows and modifies nothing

### Requirement: Edit-Days Guard Unchanged

`PATCH` edit-days for a `diario` credit MUST still return 422 with the existing
message; the backfill MUST NOT be reachable through that route.

#### Scenario: Daily edit-days still rejected

- WHEN edit-days is called on a `diario` credit
- THEN the response is 422 and no dates change

## Non-Goals

- Holidays or Saturday exclusion.
- Rewriting paid rows or historical dates.
- Any Alembic migration or frontend logic change.
