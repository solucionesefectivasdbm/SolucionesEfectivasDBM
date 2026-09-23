# Delta for Overdue Evaluation

## ADDED Requirements

### Requirement: Derived Entrada-en-Mora Date

The system MUST provide a pure function `fecha_entrada_mora(fecha_maxima) -> date` in
`backend/app/utils/momentos.py`, defined as the day immediately after the last day of the
momento instance containing `fecha_maxima` (i.e. `fecha_maxima`'s momento's close date +
1 day). It MUST be built on the same momento classification as the Momento Instance
Boundaries requirement (`get_momento`/`get_mes_momento`/`get_periodo_momento`), not a
separate date computation, so it stays consistent with `en_mora` at every boundary.

#### Scenario: Inside m1, closes day after `[pytest]`

- GIVEN `fecha_maxima = 2026-09-27` (m1, 25–29, closes 2026-09-29)
- THEN `fecha_entrada_mora(2026-09-27) = 2026-09-30`

#### Scenario: Cross-month m2 `[pytest]`

- GIVEN `fecha_maxima = 2026-10-02` (momento (2026, 9, m2), spans 2026-09-30 … 2026-10-04)
- THEN `fecha_entrada_mora(2026-10-02) = 2026-10-05`

#### Scenario: February non-leap `[pytest]`

- GIVEN `fecha_maxima = 2026-02-27` (m1, closes 2026-02-28)
- THEN `fecha_entrada_mora(2026-02-27) = 2026-03-01`

#### Scenario: February leap `[pytest]`

- GIVEN `fecha_maxima = 2028-02-29` (m1, closes 2028-02-29)
- THEN `fecha_entrada_mora(2028-02-29) = 2028-03-01`

#### Scenario: December m2 into January `[pytest]`

- GIVEN `fecha_maxima = 2026-12-31` (momento (2026, 12, m2), closes 2027-01-04)
- THEN `fecha_entrada_mora(2026-12-31) = 2027-01-05`

#### Scenario: Consistency with `en_mora` `[pytest]`

- GIVEN any unpaid `fecha_maxima` and any `hoy`
- WHEN `hoy >= fecha_entrada_mora(fecha_maxima)`
- THEN `en_mora(fecha_maxima, hoy) = true`, and for `hoy < fecha_entrada_mora(fecha_maxima)`
  THEN `en_mora(fecha_maxima, hoy) = false`

## MODIFIED Requirements

### Requirement: Reporting Is a Documented Consumer of Overdue Data

(Previously covered by the "report changes" item in Non-Goals, which excluded any
reporting use of overdue/mora data from this capability's scope.)

Reporting MAY consume `fecha_entrada_mora` to build event-based overdue reports (see the
`reportes` capability). This capability still MUST NOT itself schedule jobs, send
notifications, persist an overdue flag, or backfill historical data; those exclusions
remain unchanged. This requirement narrows the prior blanket "no report changes"
exclusion to apply only to those unchanged items, not to reporting's read-only
consumption of `fecha_entrada_mora` or the existing `en_mora`/`vencido` fields.

#### Scenario: Reporting reads mora data without mutating this capability `[pytest]`

- GIVEN the `reportes` capability calls `fecha_entrada_mora(fecha_maxima)` for a set of
  unpaid payments
- WHEN it aggregates them into a report
- THEN no job, notification, persisted flag, or backfill is introduced by this capability
  as a result

## Non-Goals (Updated)

- Scheduled job, cron, notifications, persisted overdue flag, backfill, changes to
  momento ranges, closure rules, or deferral semantics.
- (Previously also excluded "report changes" outright; superseded above — reporting may
  now read `fecha_entrada_mora`, `en_mora`, and `vencido` as inputs, but this capability
  still does not own or implement any report itself.)
