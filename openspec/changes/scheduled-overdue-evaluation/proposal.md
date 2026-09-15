# Proposal: Overdue evaluation at momento close (quote item 08)

> Exploration: `explore.md` / Engram `sdd/scheduled-overdue-evaluation/explore` (#1004).
> Owner decisions: business rules below are binding. Execution mode: interactive.

## Intent

Phase 2 item 08 "Nueva lógica de conteo de atrasos" ($400.000 COP). Today an unpaid
installment counts as overdue the day after `fecha_maxima`, while the collector is still
on route inside the same momento. Dashboard KPI, header badge, `/alertas/vencidos` and
the "Al día / En atraso" client filter inflate for days. Success: an installment counts
as overdue only once its momento has closed; inside the momento it stays red as an
alert; one predicate defines "overdue" for the whole system.

## Business rules (binding)

1. Approach: computed-at-read. NO cron, NO persisted overdue flag, NO backfill.
   Introduce a pure predicate `momento_cerrado(fecha_maxima, hoy)` (name may be
   adjusted to project conventions) built on `get_periodo_momento` in
   `backend/app/utils/momentos.py`, and use it everywhere overdue is evaluated.
2. Close-of-momento: an unpaid payment counts as overdue starting the day AFTER the
   `fin` of the momento containing its `fecha_maxima`, Bogotá time (`hoy_bogota()`).
   Example: fecha_maxima 27 (m1 = 25–29) → overdue from the 30th. Inside the momento
   it renders red as a visual alert but does NOT count in indicators (dashboard KPI,
   header badge, /alertas/vencidos, clientes al_dia filter). Cover the cross-month m2
   case (30 → 4 of next month) explicitly.
3. Deferred payments (`veces_aplazado > 0`): evaluated against their current (new)
   `fecha_maxima`, same as any payment.
4. Clientes "Al día / En atraso" uses the SAME new predicate. One definition of
   overdue system-wide.
5. Partial payments: a cuota with `pagado=false` is subject to the rule exactly as
   today; no special casing.
6. Visual red inside the momento: unchanged from today (rendered once `fecha_maxima`
   has passed). What changes is only when it COUNTS as overdue. Decide and state
   whether the "Vencido" badge/text should distinguish "past due, momento open"
   (alert) from "overdue, momento closed" — propose the simplest UX consistent with
   the quote ("conserving red inside the momento").
7. Frontend must stop deciding overdue with browser `new Date()`; the backend should
   expose the overdue state (e.g. a computed field on the pago response such as
   `en_mora: bool` / `vencido`) so all views use server-side Bogotá time. Weigh this
   against the 400-line budget and state the decision.

### Decisions on rules 6 and 7

- **Rule 7 — decided: expose two server-computed booleans on `PagoResponse`**:
  `vencido` (`fecha_maxima < hoy_bogota()`, visual alert) and `en_mora` (momento of
  `fecha_maxima` closed, counts). Cost ~15 backend lines (schema default `False`,
  row-dict builder, projected rows `False`). Frontend deletes `isVencido` and the
  `MoraBadge` date math and reads the fields. Fits the budget; removes the browser
  clock from every overdue decision.
- **Rule 6 — decided: minimal distinction via the existing badge**. Row background
  and red amount text follow `vencido` (unchanged look). The "Vencido" badge is shown
  only when `en_mora`. Inside an open momento the row is red without the badge, so
  the badge count matches the KPI. Rejected: a second badge/text ("Por cerrar") —
  extra copy and styling for no quoted value.

## Scope

### In Scope
- `momentos.py`: pure `en_mora(fecha_maxima, hoy)` plus SQL-friendly
  `fecha_limite_mora(hoy)` (first day of the momento containing `hoy`; a payment is
  overdue iff `fecha_maxima < limite`). Unit tests incl. m2 cross-month, Feb, Dec→Jan.
- Replace `Pago.fecha_maxima < hoy` with `< fecha_limite_mora(hoy)` in
  `pagos.py` (`/alertas/vencidos`) and `clientes.py` (3 sites: list filter, response
  override, detail).
- `PagoResponse.vencido` / `en_mora` on real rows; `False` on projected rows.
- Frontend: `PagosPage.tsx` (row style, text, badge), `ui/index.tsx::MoraBadge`
  (prop `enMora`), `types/index.ts`. Dashboard/Header/Clientes need no logic change
  (they consume backend results).
- New spec `overdue-evaluation`; delta to `payment-deferral-tracking`.

### Out of Scope (non-goals)
- Scheduled job, cron, background worker; notifications.
- Persisted overdue flag, `Cliente.al_dia` column revival, backfill.
- Report changes (`reportes.py` does not consume overdue).
- Closure rules 14/15, carryover logic, momento ranges, deferral semantics.

## Capabilities

### New Capabilities
- `overdue-evaluation`: single system-wide definition of overdue (momento closed,
  Bogotá date), its exposure on `PagoResponse`, and its consumers (alerts, client
  status). Scenarios: inside momento not overdue; day after `fin` overdue; m2
  cross-month; deferred uses new date; partial unpaid; projected rows `False`.

### Modified Capabilities
- `payment-deferral-tracking`: "Row Styling and Badge" replaces the hard-coded
  `fecha_maxima < today` with backend `vencido` (red) / `en_mora` (badge); scenario
  "Deferred and overdue again" reworded accordingly.

## Approach

Exploration approach 2. Momentos are contiguous, non-overlapping calendar ranges, so
"momento of `fecha_maxima` is closed at `hoy`" is equivalent to
`fecha_maxima < inicio(momento(hoy))`. One date bound keeps the three SQL filters
index-friendly and identical. The pure predicate is unit-tested; endpoints get
integration tests with explicit dates (`hoy` injectable, no freezegun).

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `backend/app/utils/momentos.py` | Modified | `en_mora`, `fecha_limite_mora` |
| `backend/app/routers/pagos.py:60-91, 939-973` | Modified | fields in row dict; bound in `/alertas/vencidos` |
| `backend/app/routers/clientes.py:48-57, ~110, ~190-199` | Modified | same bound in 3 subqueries |
| `backend/app/schemas/pago.py` | Modified | `vencido`, `en_mora` (default `False`) |
| `frontend/src/pages/Pagos/PagosPage.tsx:131,532-533,628,656` | Modified | use fields; badge on `en_mora` |
| `frontend/src/components/ui/index.tsx:43-49`, `types/index.ts` | Modified | `MoraBadge` prop; types |
| `openspec/specs/overdue-evaluation`, `payment-deferral-tracking` | New / Delta | specs |
| `backend/tests/` | New | momentos unit, alertas, clientes al_dia |

## Size estimate vs 400-line budget

Backend ~120 (incl. tests ~70), frontend ~30, specs excluded. Roughly 150–200
changed lines. Single PR. `Chained PRs recommended: No`. Budget risk: Low.

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| `get_periodo_momento(anio, 2, "m1")` raises (`date(y,2,29)`) and Feb m2 overlaps m1 | Med | Derive the bound from `get_momento`/`get_mes_momento`, not from `get_periodo_momento`; add Feb tests |
| One consumer left on the old predicate | Low | Grep `fecha_maxima <` in verify; spec lists all consumers |
| Users read red rows without badge as "not counted" confusion | Low | Badge semantics documented; owner accepted rule 6 |
| KPI drops abruptly on deploy | Certain | Intended; note to owner |

## Rollback

Revert the single PR. No schema change, no data change, no job.

## Dependencies

None.

## Success Criteria

- [ ] fecha_maxima 27 (m1): `en_mora=False` on the 28th–29th, `True` on the 30th.
- [ ] fecha_maxima 2 (m2 of previous month): `en_mora=False` on the 4th, `True` on the 5th.
- [ ] Deferred row evaluated on its new `fecha_maxima`.
- [ ] `/alertas/vencidos`, dashboard KPI, header badge, `al_dia` filter agree.
- [ ] Inside momento: red row, no "Vencido" badge; after close: red + badge.
- [ ] No `new Date()` overdue logic remains in the frontend; `tsc --noEmit` clean; pytest green.

## Proposal question round

Owner decisions cover the product questions. Two assumptions need confirmation
(silence = accepted):
1. Rule 6: red row without badge inside the momento, badge only once it counts.
2. Rule 7: two fields (`vencido`, `en_mora`) instead of one, to remove all browser
   date logic.
