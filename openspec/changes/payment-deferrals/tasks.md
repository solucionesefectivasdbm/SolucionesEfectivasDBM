# Tasks: Payment Deferrals

**Scenario count**: 9 requirements, 22 scenarios total (Deferral Counter: 2; Extended Date Modification: 4; Deferral Rejections: 3; Role Gate: 1; Distinguishable Audit: 2; Cross-Period Deferred Listing: 3; Double Visualization: 1; Deferral Prompt in the UI: 2 `[manual]`; Row Styling and Badge: 3 `[manual]`). All 22 mapped below — see Scenario Coverage Map. Gaps: 0.

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines (code+tests only, openspec excluded) | migration ~35, `models/pago.py` ~6, `schemas/pago.py` ~4, `routers/pagos.py` ~115, `tests/test_aplazamientos.py` ~320 (new), `types/index.ts` ~2, `api/index.ts` ~10, `PagosPage.tsx` ~75, `App.tsx` ~2 ≈ **~570** |
| 800-line budget risk | Low |
| Chained PRs recommended | No |
| Suggested split | Single PR, branch `feature/payment-deferrals` → `main` |
| Delivery strategy | single-pr-default |
| Decision needed before apply | No |

### Suggested Work Units

| Unit | Goal | Likely PR | Focused test command | Runtime harness | Rollback boundary |
|------|------|-----------|----------------------|-----------------|-------------------|
| 1 | Backend: migration + model + schemas + `modificar_fecha_pago` deferral logic + shared listing helper + `/pagos/aplazados` endpoint | PR 1 | `cd backend && python -m pytest tests/test_aplazamientos.py -q` | httpx AsyncClient + aiosqlite integration tests (unmocked) | Revert migration file, `models/pago.py`, `schemas/pago.py`, `routers/pagos.py` diff; delete `test_aplazamientos.py`; `alembic downgrade -1` |
| 2 | Frontend: types + api client + PagosPage modal/row/badge + `aplazados` variant + route + nav | PR 1 (same PR, separable commits) | `cd frontend && npx tsc --noEmit` + manual checklist (Phase 9) | Manual: weekly/daily/aplazados pages, modal checkbox, badge/color precedence | Revert `types/index.ts`, `api/index.ts`, `PagosPage.tsx`, `App.tsx` diff; backend unaffected |

## Phase 1: Foundation — Migration & Model

- [x] 1.1 Create `backend/alembic/versions/b2c3d4e5f6a7_add_veces_aplazado_to_pagos.py`, `down_revision='a1b2c3d4e5f6'`: `add_column('pagos', Column('veces_aplazado', Integer, nullable=False, server_default='0', comment=…))` + `ck_pagos_veces_aplazado_no_negativo` (`veces_aplazado >= 0`); downgrade drops constraint then column
- [x] 1.2 Modify `backend/app/models/pago.py`: `veces_aplazado: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")`
- [x] 1.3 Verify: `cd backend && python -m pytest -q` — 0 failures on existing suite (additive column, no behavior change yet)

## Phase 2: Foundation — Schemas

- [x] 2.1 Modify `backend/app/schemas/pago.py`: `ModificarFechaPagoRequest.es_aplazamiento: bool = False`; `PagoResponse.veces_aplazado: int = 0`
- [x] 2.2 Verify: `cd backend && python -m pytest -q` — 0 failures (schema addition backward-compatible)

## Phase 3: RED — Failing Tests for `modificar_fecha_pago` Deferral Logic (`backend/tests/test_aplazamientos.py`, new file, fixtures copied from `test_desvalidar_pago.py`)

- [x] 3.1 RED: existing rows default to `veces_aplazado = 0` on any listing (Req: Deferral Counter — scenario "Existing rows default to zero")
- [x] 3.2 RED: reversal (`desvalidar`) keeps the counter unchanged on a deferred, validated payment (Req: Deferral Counter — scenario "Reversal keeps the counter")
- [x] 3.3 RED: plain correction (`es_aplazamiento` omitted / `false`) — date changes, `veces_aplazado` stays `0`, existing single audit entry (Req: Extended Date Modification — scenario "Plain correction unchanged")
- [x] 3.4 RED: first deferral — date moves forward with `es_aplazamiento=true` → `fecha_maxima` updated, `veces_aplazado: 0 → 1`, response includes updated counter (Req: Extended Date Modification — scenario "First deferral")
- [x] 3.5 RED: second deferral on the same payment → `veces_aplazado: 1 → 2` (Req: Extended Date Modification — scenario "Second deferral")
- [x] 3.6 RED: correction after deferral (`es_aplazamiento=false` on a payment with `veces_aplazado=1`) — date changes, counter stays `1` (Req: Extended Date Modification — scenario "Correction after deferral")
- [x] 3.7 RED: paid payment + `es_aplazamiento=true` → 422, detail states a paid installment cannot be deferred, no mutation, no audit row (Req: Deferral Rejections — scenario "Paid payment cannot be deferred")
- [x] 3.8 RED: same-date or backward-date deferral (`nueva_fecha <= fecha_maxima actual` + flag) → 422, detail states a deferral must move the date forward, no mutation, no audit row; same date/backward **without** the flag → 200 (unchanged today's behavior) (Req: Deferral Rejections — scenario "Backward or same date is not a deferral")
- [x] 3.9 RED: deferred payment (`veces_aplazado=1`) then paid in full — counter stays `1`; a further deferral attempt on the now-paid payment returns 422 (Req: Deferral Rejections — scenario "Deferred then paid")
- [x] 3.10 RED: role matrix — `registrador`/`gestor` sending `es_aplazamiento=true` → 403, payment unchanged; `admin`/`recaudador` → 200 (Req: Role Gate — scenario "Registrador and gestor forbidden")
- [x] 3.11 RED: projected/virtual row id + any date modification → 404, nothing persisted (Req: Deferral Rejections — "Projected rows... 404" clause)
- [x] 3.12 RED: deferral audit — successful deferral writes audit rows showing `fecha_maxima` old→new AND `veces_aplazado` `"0"→"1"` with the caller's user id (Req: Distinguishable Audit — scenario "Deferral audited")
- [x] 3.13 RED: correction audit — successful plain correction writes only the `fecha_maxima` audit row, no `veces_aplazado` entry (Req: Distinguishable Audit — scenario "Correction audited as today")
- [x] 3.14 Verify RED: `cd backend && python -m pytest tests/test_aplazamientos.py -q` — all tests in 3.1-3.13 fail (endpoint not yet modified)

## Phase 4: GREEN — Implement `modificar_fecha_pago` Deferral Logic (`backend/app/routers/pagos.py`)

- [x] 4.1 Switch payment lookup to `_get_pago_con_credito(db, pago_id, lock=True)` (same lock pattern as `desvalidar_pago`); re-read `pago.pagado` and `pago.fecha_maxima` after acquiring the lock, before any check
- [x] 4.2 Add ordered rejection checks under `es_aplazamiento=true`: (1) `pago.pagado` → 422 "no se puede aplazar" text; (2) `body.fecha_maxima <= pago.fecha_maxima` → 422 "debe mover la fecha hacia adelante" text; raise before any mutation
- [x] 4.3 On accepted call: update `fecha_maxima`; when `es_aplazamiento=true`, increment `veces_aplazado` by one and log `INFO "APLAZAMIENTO OK — pago_id=%s usuario_id=%s veces=%s"`
- [x] 4.4 Build `cambios` dict for `audit_service.registrar_actualizacion_campos`: always `{"fecha_maxima": (old, new)}`; add `{"veces_aplazado": (old, new)}` only when `es_aplazamiento=true`
- [x] 4.5 Verify GREEN: `cd backend && python -m pytest tests/test_aplazamientos.py -q` — tests from 3.1-3.13 pass (3.1/3.2 may already pass from Phase 1-2; confirm here)

## Phase 5: RED — Failing Tests for Cross-Period Deferred Listing

- [x] 5.1 RED: pending deferred payments due in October and December, no filters → both returned, October first (asc `fecha_maxima`) (Req: Cross-Period Deferred Listing — scenario "Spans months")
- [x] 5.2 RED: one pending + one paid deferred payment — default (`incluir_pagados` omitted) returns only the pending one; `incluir_pagados=true` returns both (Req: Cross-Period Deferred Listing — scenario "Paid excluded by default")
- [x] 5.3 RED: deferred payments of two gestores — a `gestor` caller receives only their own clients' payments (Req: Cross-Period Deferred Listing — scenario "Gestor scoping")
- [x] 5.4 RED: `veces_aplazado = 0` rows and soft-deleted rows excluded regardless of filters
- [x] 5.5 RED: pagination/sort contract — `total`/`pages`/`page_size` correct; `sort_dir=desc` reverses order; `page_size > 50` → 422; `busqueda` filters by client name
- [x] 5.6 RED: `listar_pagos` (existing weekly/daily endpoint) — a real deferred row carries its `veces_aplazado`; a virtual/projected row defaults to `0` (Req: Double Visualization — scenario "Present in both views")
- [x] 5.7 Verify RED: `cd backend && python -m pytest tests/test_aplazamientos.py -q` — tests from 5.1-5.6 fail (endpoint/select not yet added)

## Phase 6: GREEN — Implement Listing (`backend/app/routers/pagos.py`)

- [x] 6.1 Extract shared `_aplicar_scope_y_busqueda(query, current_user, gestor_id, cliente_id, busqueda)` from `listar_pagos`, used by both `listar_pagos` and the new endpoint
- [x] 6.2 Add `veces_aplazado` to `listar_pagos` select + `_pago_row_a_dict` (real rows carry the value; virtual/projected dicts default to `0`)
- [x] 6.3 Add `GET /pagos/aplazados` → `PaginatedResponse[PagoResponse]`, `Depends(get_current_user)`; params `incluir_pagados: bool = False`, `sort_dir: "asc"|"desc" = "asc"`, `gestor_id`, `cliente_id`, `busqueda`, `page >= 1`, `page_size 1..50 = 50`; predicate `deleted_at IS NULL AND veces_aplazado > 0 AND (pagado OR credito_operativamente_abierto())`, plus `pagado = false` unless `incluir_pagados`; order `fecha_maxima <dir>, Cliente.nombre, Cliente.apellidos, Pago.id`; `total` via `select(func.count()).select_from(query.subquery())`
- [x] 6.4 Verify GREEN: `cd backend && python -m pytest tests/test_aplazamientos.py -q` — all tests from Phase 3 and Phase 5 pass

## Phase 7: Full Backend Regression

- [x] 7.1 Verify: `cd backend && python -m pytest -q` — 0 failures, count ≥ baseline + all new tests from `test_aplazamientos.py`

## Phase 8: Frontend Types & API Client

- [x] 8.1 Modify `frontend/src/types/index.ts`: `Pago.veces_aplazado: number`
- [x] 8.2 Modify `frontend/src/api/index.ts`: `modificarFecha(pagoId, fecha_maxima, es_aplazamiento = false)`; add `listarAplazados(params)`
- [x] 8.3 Verify: `cd frontend && npx tsc --noEmit` — 0 errors

## Phase 9: Frontend — PagosPage Modal, Row Style, Badge, Aplazados Variant

- [x] 9.1 Modify `frontend/src/pages/Pagos/PagosPage.tsx` date modal: add checkbox "¿Es un aplazamiento solicitado por el cliente?" + helper text, state reset to `false` on open, submit calls `modificarFecha(..., es_aplazamiento)`; toast "Aplazamiento registrado" vs "Fecha actualizada"; backend 4xx `detail` shown verbatim on rejection (Req: Deferral Prompt in the UI — both scenarios)
- [x] 9.2 Add row class precedence: `es_proyectada` gray (unaffected) → `!es_proyectada && isVencido(p)` red → `!es_proyectada && !p.pagado && !isVencido(p) && p.veces_aplazado > 0` violet → zebra; `es_ultimo_pago` border independent of the above (Req: Row Styling and Badge — "Deferred not overdue", "Deferred and overdue again")
- [x] 9.3 Add badge in the Estado cell for `veces_aplazado > 0`: `Aplazado ×{n}` (`bg-violet-100 text-violet-700`, title "Veces aplazado"); no escalated style for `n >= 2`, only the number changes (Req: Row Styling and Badge — "Two deferrals same style")
- [x] 9.4 Add third `variante="aplazados"`: hide Año/Mes/Momento filters, show "Incluir pagados" checkbox (default off), `filtrosCompletos = true`, title "Pagos Aplazados", empty state "No hay pagos aplazados", fetch via `listarAplazados`; default pending-only per spec (Req: Cross-Period Deferred Listing UI surface; Row Styling and Badge — "default to pending-only")
- [x] 9.5 Modify `frontend/src/App.tsx`: `<Route path="pagos/aplazados" element={<PagosPage variante="aplazados" />} />`
- [x] 9.6 Add navigation: header button "Pagos Aplazados" in regular variant; "Volver a Pagos" button in the `aplazados` variant
- [x] 9.7 Verify: `cd frontend && npx tsc --noEmit` — 0 errors

## Phase 10: Manual Verification Checklist (frontend — no test runner)

- [ ] 10.1 Plain correction: answer "No" (or dismiss) on the date modal → date changes, no badge appears (Req: Deferral Prompt in the UI — scenario "Yes increments, No does not", first half)
- [ ] 10.2 First deferral: answer "Yes" on a pending row → date changes, badge `Aplazado ×1` appears, violet row style in weekly, daily, and regular Pagos views (Req: Deferral Prompt in the UI — scenario "Yes increments, No does not", second half; Row Styling and Badge — "Deferred not overdue")
- [ ] 10.3 Second deferral on the same row → badge updates to `×2`, same violet style (no escalation) (Req: Row Styling and Badge — "Two deferrals same style")
- [ ] 10.4 Deferred row whose new date passes into the past → row turns red, badge persists (Req: Row Styling and Badge — "Deferred and overdue again")
- [ ] 10.5 Paid row has no date button: a paid row does not render "Modificar fecha", so no deferral can be requested from the UI (Req: Deferral Prompt in the UI — scenario "Paid row has no date button"; the backend 422 guard is covered by `[pytest]`)
- [ ] 10.6 `/pagos/aplazados`: lists deferred payments across months, pending only by default; "Incluir pagados" toggles paid rows in; pagination and `sort_dir` controls work
- [ ] 10.7 Gestor session: a `gestor` user visiting `/pagos/aplazados` sees only their own clients' deferred payments (Req: Cross-Period Deferred Listing — scenario "Gestor scoping", UI confirmation)
- [ ] 10.8 Navigation: "Pagos Aplazados" button navigates from `/pagos`; "Volver a Pagos" returns from `/pagos/aplazados`

## Phase 11: Docs & Cleanup

- [x] 11.1 Confirm no leftover TODOs/dead code in `routers/pagos.py` deferral branch; confirm migration applies cleanly on a fresh DB (`alembic upgrade head` then `downgrade -1` then `upgrade head`)
- [x] 11.2 Update openspec archive readiness: verify `proposal.md`, `design.md`, `specs/payment-deferral-tracking/spec.md`, `tasks.md` are consistent before requesting sdd-apply → sdd-archive

## Scenario Coverage Map (9 requirements, 22 scenarios — all mapped, 0 gaps)

| Requirement | Scenarios | Task(s) |
|---|---|---|
| Deferral Counter | 2/2 | 3.1, 3.2 |
| Extended Date Modification | 4/4 | 3.3, 3.4, 3.5, 3.6 |
| Deferral Rejections | 3/3 | 3.7, 3.8, 3.9, 3.11 |
| Role Gate | 1/1 | 3.10 |
| Distinguishable Audit | 2/2 | 3.12, 3.13 |
| Cross-Period Deferred Listing | 3/3 | 5.1, 5.2, 5.3, 5.4, 5.5, 10.6, 10.7 |
| Double Visualization | 1/1 | 5.6 |
| Deferral Prompt in the UI | 2/2 | 9.1, 10.1, 10.2, 10.5 |
| Row Styling and Badge | 3/3 | 9.2, 9.3, 9.4, 10.2, 10.3, 10.4 |
