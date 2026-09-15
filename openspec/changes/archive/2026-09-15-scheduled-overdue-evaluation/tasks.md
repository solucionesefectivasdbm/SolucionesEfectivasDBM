# Tasks: Overdue evaluation at momento close

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~150-200 (design estimate); backend ~110, frontend ~40 |
| 400-line budget risk | Low |
| Chained PRs recommended | No |
| Suggested split | Single PR |
| Delivery strategy | single-pr |
| Chain strategy | size-exception |

Decision needed before apply: Yes
Chained PRs recommended: No
Chain strategy: size-exception
400-line budget risk: Low

### Suggested Work Units

| Unit | Goal | Likely PR | Focused test command | Runtime harness | Rollback boundary |
|------|------|-----------|----------------------|-----------------|-------------------|
| 1 | Predicate + fixture + all consumers + frontend | PR 1 (single, size:exception) | `backend/venv/Scripts/python.exe -m pytest backend/tests/test_momentos.py backend/tests/test_mora_momento_cerrado.py backend/tests/test_clientes.py backend/tests/test_pagos_listado.py` then `cd frontend && npx tsc --noEmit` | Full suite: `backend/venv/Scripts/python.exe -m pytest`; manual QA per Phase 7 | Revert the PR; new response fields are additive, ignored by older frontend |

## Phase 1: Predicate (RED → GREEN)

- [x] 1.1 RED `backend/tests/test_momentos.py` `TestFechaLimiteMora`: fin/fin+1 per momento (m5 19-24, m1 25-29, m2 30..4, m3 5-13, m4 14-18) using Mar 2026; Apr 5→Apr 5; Jan 1-4 2026→Dec 30 2025; Mar 1-4 2026→Mar 1; Mar 1 2028→Mar 1 (leap); Feb 28 2026/Feb 29 2028→Feb 25 (design decisions 1)
- [x] 1.2 RED same file `TestEnMora`: fm 27 vs hoy 28/29 False, 30 True; fm Apr 2 vs Apr 4 False/Apr 5 True; fm Feb 28 vs Mar 1 True; fm Dec 31 vs Jan 4 False/Jan 5 True (spec req 2)
- [x] 1.3 RED same file: property test — for every day in 2026-2028, `fecha_limite_mora(d)` agrees pairwise with `get_momento`/`get_mes_momento`
- [x] 1.4 GREEN `backend/app/utils/momentos.py`: add `fecha_limite_mora(hoy: date) -> date` and `en_mora(fecha_maxima: date, hoy: date) -> bool` per design decision 1
- [x] 1.5 `pytest backend/tests/test_momentos.py` green

## Phase 2: Test Fixture

- [x] 2.1 `backend/tests/conftest.py`: add `fijar_hoy` monkeypatch fixture patching `app.routers.pagos.hoy_bogota` and `app.routers.clientes.hoy_bogota` (design decision 4)

## Phase 3: `/pagos/alertas/vencidos` (RED → GREEN)

- [x] 3.1 RED `backend/tests/test_mora_momento_cerrado.py` (new, `client_factory` pattern): fm Mar 27 pending; `fijar_hoy(Mar 29)`→empty, `total_pagos_vencidos==0`; `fijar_hoy(Mar 30)`→listed, `en_mora`/`vencido` True; fm Apr 2, hoy Apr 4 empty/Apr 5 listed (spec req 4)
- [x] 3.2 RED same file: re-pin `test_alerta_vencidos_excluye_credito_saldado` with `fijar_hoy` so exclusion stays meaningful
- [x] 3.3 GREEN `backend/app/routers/pagos.py:954`: compute `limite = fecha_limite_mora(hoy)`, swap predicate `fecha_maxima < hoy` → `< limite`; add `_flags_mora` merge via `model_copy` (design decision 2, 3)

## Phase 4: `clientes.py` Three Sites (RED → GREEN)

- [x] 4.1 RED `backend/tests/test_mora_momento_cerrado.py`: `GET /clientes?al_dia=` and `GET /clientes/{id}` — `al_dia` True on the 29th, False on the 30th; list filter and detail agree (spec req 5)
- [x] 4.2 GREEN `backend/app/routers/clientes.py`: import `fecha_limite_mora`; shared `limite` at line 48 for list filter (:56) and response override (:110); own `limite` at :190 for detail (:199) (design decision 2)

## Phase 5: `PagoResponse` Flags (RED → GREEN)

- [x] 5.1 RED `backend/tests/test_mora_momento_cerrado.py`: `GET /pagos` hoy Mar 28 → `vencido` True, `en_mora` False; projected virtual row both False; deferred row (veces_aplazado>0, fm Apr 10) hoy Apr 13 not listed/Apr 14 listed (spec reqs 3, 6)
- [x] 5.2 RED same file: partial payment (`capital_pagado>0`, `pagado=False`, fm Mar 27) hoy Mar 30 listed with `en_mora` True (spec req 7)
- [x] 5.3 GREEN `backend/app/schemas/pago.py`: add `vencido: bool = False`, `en_mora: bool = False` to `PagoResponse`
- [x] 5.4 GREEN `backend/app/routers/pagos.py`: add `_flags_mora(fecha_maxima, pagado, hoy) -> dict`; add `hoy` param to `_pago_row_a_dict(row, hoy)`, update call sites (202, 308); virtual dict rows add both `False` (design decision 3)
- [x] 5.5 `pytest backend/tests/test_mora_momento_cerrado.py backend/tests/test_pagos_listado.py` green

## Phase 6: Frontend

- [x] 6.1 `frontend/src/types/index.ts`: `Pago.vencido: boolean; en_mora: boolean` (required)
- [x] 6.2 `frontend/src/pages/Pagos/PagosPage.tsx`: delete `isVencido` (131); line 532 → `!p.vencido`; 533 → `p.vencido && 'bg-red-50'`; 628 → `p.vencido && 'text-danger font-bold'`; 656 → `p.en_mora && <span ...>Vencido</span>` (design decision 5)
- [x] 6.3 Delete `MoraBadge` (`frontend/src/components/ui/index.tsx:43-49`) and its unused import in `frontend/src/pages/Dashboard/DashboardPage.tsx:4`
- [x] 6.4 `cd frontend && npx tsc --noEmit` clean

## Phase 7: Manual QA (not automated)

- [ ] 7.1 MANUAL: unpaid row inside its open momento shows red row, no "Vencido" badge (vencido=T, en_mora=F)
- [ ] 7.2 MANUAL: same row after momento closes shows red row + "Vencido" badge (vencido=T, en_mora=T)
- [ ] 7.3 MANUAL: dashboard KPI and header badge count match `/pagos/alertas/vencidos` total, unaffected by browser local date
- [ ] 7.4 MANUAL: deferred row not overdue → deferred style + counter badge; deferred row overdue after close → red style wins, counter badge stays, "Vencido" badge appears (payment-deferral-tracking precedence)

## Phase 8: Close-out

- [x] 8.1 `backend/venv/Scripts/python.exe -m pytest` full suite green (441 passed; main has 404)
- [x] 8.2 `cd frontend && npx tsc --noEmit` clean
- [ ] 8.3 Open single PR (size:exception — actual diff ~640 authored lines, see apply report) off `main` — OUT OF SCOPE for sdd-apply, orchestrator/owner-driven

## Verification Commands

- Backend: `backend/venv/Scripts/python.exe -m pytest` (Windows) / `cd backend && python -m pytest` (POSIX)
- Frontend: `cd frontend && npx tsc --noEmit`
