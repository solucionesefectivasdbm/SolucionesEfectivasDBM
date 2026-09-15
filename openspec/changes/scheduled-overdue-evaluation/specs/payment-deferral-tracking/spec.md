# Delta for Payment Deferral Tracking

> Change `scheduled-overdue-evaluation`. Delta on
> `openspec/specs/payment-deferral-tracking/spec.md`: the row-styling requirement stops
> hard-coding the naive `fecha_maxima < today` predicate and consumes the
> server-computed `vencido` / `en_mora` fields defined in `overdue-evaluation`.

## MODIFIED Requirements

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
