# Exploration: Scheduled overdue ("mora") evaluation at momento close

Change: `scheduled-overdue-evaluation` — Phase 2 quote item 08 ("Nueva lógica de conteo de atrasos").
Engram: topic `sdd/scheduled-overdue-evaluation/explore` (observation #1004).

## Current State

**"momento" is NOT a stored entity.** It is a pure date-math label (m1..m5) computed by
`backend/app/utils/momentos.py::get_momento(fecha)` from a payment's `fecha_maxima`.
Ranges: m1 = days 25-29; m2 = day 30 through day 4 of next month (cross-month case, tested in
`test_momentos.py`); m3 = 5-13; m4 = 14-18; m5 = 19-24. `get_periodo_momento(anio, mes, momento)`
returns the (inicio, fin) date range for a momento instance. There is no DB row, no "momento
closed" event, no scheduler — "close" is implicit: the day after `fin`. `Pago.momento`
(VARCHAR(5)) is a label set once at creation.

**Overdue is 100% computed at read time, never persisted**, in these places that must move together:
- Backend `GET /pagos/alertas/vencidos` (`backend/app/routers/pagos.py:939-973`):
  `Pago.pagado == False AND Pago.fecha_maxima < hoy_bogota() AND credito_operativamente_abierto()`.
- Backend `clientes.py` "al día" computation (~36-64, ~186-204): not al día if any unpaid pago has
  `fecha_maxima < hoy`. The persisted `Cliente.al_dia` column was deliberately abandoned in favor
  of live computation ("El campo persistido en BD ya no se usa para filtrar").
- Frontend `PagosPage.tsx:131`: `isVencido = (p) => !p.pagado && new Date(p.fecha_maxima) < new Date()`
  — row color (`bg-red-50`), text styling, "Vencido" badge. Shared by all 4 route variants
  (`regular`, `semanal`, `diario`, `aplazados`; `App.tsx:59-62`).
- Frontend `components/ui/index.tsx::MoraBadge` (43-49) — duplicate naive predicate.
- Frontend `DashboardPage.tsx` — KPI "Atrasados" + total mora, from `pagosApi.alertasVencidos()`.
- Frontend `Header.tsx` — alert count badge, same source.
- Frontend `ClientesPage.tsx` (~194-297) — "Al día / En atraso" filter via `al_dia` query param.

No `reportes.py` endpoint references vencido/mora — reports are not a consumer today.

**No scheduling infrastructure exists.** No APScheduler/Celery/cron/`@repeat_every`/background
task. `backend/start.sh` runs Alembic then `exec uvicorn`. Deploy is Railway (`openspec/config.yaml`).
Only "run once" precedent: temporary admin-only POST backfill endpoint (create → run once → delete).
The project has never shipped a recurring background job.

**Timezone**: `backend/app/utils/tz.py` — `TZ_BOGOTA = timezone(timedelta(hours=-5))` (fixed
offset), `hoy_bogota()` / `ahora_bogota()`. Backend uses `hoy_bogota()`; frontend uses browser
`new Date()` — pre-existing inconsistency; new logic should centralize on server time.

**Test infrastructure**: backend `pytest` + `pytest-asyncio` (asyncio_mode=auto), httpx
`AsyncClient` + aiosqlite in-memory DB (`tests/conftest.py`). No `freezegun`; date tests pass
explicit `date` objects. Frontend has no test runner (`strict_tdd.frontend: false`):
`npx tsc --noEmit` + manual QA.

## Affected Areas
- `backend/app/utils/momentos.py` — new `momento_cerrado(fecha_maxima, hoy)`-style predicate.
- `backend/app/routers/pagos.py:939-973` (`/alertas/vencidos`).
- `backend/app/routers/clientes.py:36-64, 186-204` ("al día" subquery).
- `backend/app/services/credito_service.py` — `credito_operativamente_abierto()` / rule 14-15
  closure logic; scoped check needed in design.
- `frontend/src/pages/Pagos/PagosPage.tsx:131,529-533,628,656` — `isVencido`, red styling, badge.
- `frontend/src/components/ui/index.tsx:43-49` — `MoraBadge`.
- `frontend/src/pages/Dashboard/DashboardPage.tsx`, `frontend/src/components/layout/Header.tsx`.
- `frontend/src/pages/Clientes/ClientesPage.tsx:194-297`.
- `openspec/specs/payment-deferral-tracking/spec.md` — "Row Styling and Badge" requirement
  hard-codes the naive overdue predicate; needs a spec delta.
- `backend/start.sh` / deploy config — only if a literal job is chosen.
- `backend/tests/conftest.py` — time-mocking fixture or injectable `hoy`.

## Approaches

1. **Persisted `estado_atraso` set by a scheduled job at momento close.**
   - Pros: literal match to the quote wording; cheap boolean reads; hook for future notifications.
   - Cons: first recurring-job dependency; missed-run/idempotency risk; backfill on rollout; must
     reconcile with deferrals; duplicates derivable state (the pattern already abandoned for
     `Cliente.al_dia`).
   - Effort: High.

2. **Computed-at-read "momento closed?" predicate, no stored job.** Replace `fecha_maxima < hoy`
   with `hoy > fin` of the momento range containing `fecha_maxima` everywhere overdue is read.
   - Pros: zero new infra, no missed runs, single source of truth, pure-function tests, retroactive
     for free (no backfill), code-only rollback.
   - Cons: not literally a "scheduled process"; no event trigger for future notifications; frontend
     "red inside momento" condition needs careful rewording.
   - Effort: Low-Medium.

3. **Hybrid**: Approach 2 as source of truth for reads + lightweight daily job for side effects
   only (audit/notifications/reporting read-model).
   - Pros: satisfies literal wording for future extensibility; job failures non-critical.
   - Cons: more moving parts than the item's scope; no concrete consumer defined yet.
   - Effort: Medium.

## Recommendation
Approach 2. Reuses the project's own pattern (compute live, never persist derived state) with zero
infra, backfill or idempotency handling. Confirm with the owner whether "scheduled process" is a
literal infra requirement or a description of business behavior; if a real job is needed later
(notifications), scope Approach 3's job as a separate follow-up change.

## Risks
- Business-rule ambiguity: (a) exact close-of-momento instant; (b) partial payments inside the
  window once closed; (c) which momento a deferred payment (`veces_aplazado > 0`) is evaluated
  against; (d) per-cuota vs per-credit/client counting for dashboard; (e) whether `Cliente.al_dia`
  shares the new predicate.
- `payment-deferral-tracking` spec "Row Styling and Badge" contradicts the new rule without a delta.
- Persisted state (1/3) would need a catch-up strategy for missed runs.
- No time-mocking in backend tests — design must choose `freezegun` vs injectable `hoy`.
- Frontend verification is manual only.

## Ready for Proposal
Yes, pending the owner's answers to the business questions above. Capture them as
"Business rules (binding)" in the proposal, as in `carryover-scope-fixes/proposal.md`.
