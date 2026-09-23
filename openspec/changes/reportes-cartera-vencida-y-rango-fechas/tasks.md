# Tasks: Reportes — Cartera Vencida + filtro por intervalo de días

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | PR1 ~180-240, PR2 ~200-260, PR3 ~220-300 |
| 400-line budget risk | Low per PR / High if shipped as one PR |
| Chained PRs recommended | Yes |
| Suggested split | PR1: momentos utils + resolver_ventana + `/ingresos` interval → PR2: `/cartera-vencida` endpoint → PR3: frontend |
| Delivery strategy | ask-on-risk |
| Chain strategy | stacked-to-main (resolved; each PR targets the previous PR's branch or main in sequence, PR1 targets main) |

Decision needed before apply: No (resolved)
Chained PRs recommended: Yes
Chain strategy: stacked-to-main
400-line budget risk: Low

### Suggested Work Units

| Unit | Goal | Likely PR | Focused test command | Runtime harness | Rollback boundary |
|------|------|-----------|----------------------|-----------------|-------------------|
| 1 | `fecha_entrada_mora`/`bounds_entrada_mora` + `resolver_ventana` + `/ingresos` interval mode + hidden `/reportes` alias | PR 1 | `backend/venv/Scripts/python.exe -m pytest backend/tests/test_momentos.py backend/tests/test_reportes_intervalo.py -q` | Existing `test_reportes*.py` suite must stay green unedited (regression proof) | Revert PR1; `/reportes` alias and `/ingresos` route disappear, no data touched |
| 2 | `GET /reportes/cartera-vencida` endpoint (SQL range, guards, Decimal totals, por-gestor) | PR 2 | `backend/venv/Scripts/python.exe -m pytest backend/tests/test_reportes_cartera_vencida.py -q` | Manual curl against dev DB with a known overdue cuota | Revert PR2; new route removed, PR1 untouched |
| 3 | Frontend selectors, views, API layer, stale `Reporte` type fix | PR 3 | `npx tsc --noEmit` (frontend) | Manual check: switch report type + filter mode in browser | Revert PR3; backend endpoints remain usable via direct API calls |

## Phase 1: PR1 — Momentos utilities, resolver_ventana, Ingresos interval mode

- [x] 1.1 RED: in `backend/tests/test_momentos.py` add `TestFechaEntradaMora` covering scenarios `Inside m1, closes day after`, `Cross-month m2`, `February non-leap`, `February leap`, `December m2 into January`, plus design's extra cases (m3 day 14, day 31→day 5, Mar day 3→Mar 5, Dec 30→Jan 5, Jan 2→Jan 5).
- [x] 1.2 GREEN: add `fecha_entrada_mora(fecha_maxima)` to `backend/app/utils/momentos.py` per D3 (`get_periodo_momento(*get_mes_momento(fm), get_momento(fm))[1] + 1 day`).
- [x] 1.3 RED: add `TestBoundsEntradaMora` with the exhaustive equivalence loop (2025-01..2028-12) asserting `bounds_entrada_mora(inicio, fin)` predicate == `inicio <= fecha_entrada_mora(fm) <= fin`, per design's D4 equivalence proof.
- [x] 1.4 GREEN: add `bounds_entrada_mora(inicio, fin)` to `backend/app/utils/momentos.py` per the Interfaces contract (`fecha_limite_mora(inicio - 1d), fecha_limite_mora(fin)`).
- [x] 1.5 RED: create `backend/tests/test_reportes_intervalo.py` covering spec scenarios `Momento mode resolves as today`, `Interval mode uses the raw bounds`, `Both modes supplied is rejected`, `Neither mode supplied is rejected` (422, no query runs), plus partial-momento and partial-interval 422 cases from design's Validation rules.
- [x] 1.6 GREEN: add `resolver_ventana(anio, mes, momento, fecha_desde, fecha_hasta) -> (date, date)` to `backend/app/routers/reportes.py`, raising `HTTPException(422)` per D2 and the Validation rules section.
- [x] 1.7 RED: extend `backend/tests/test_reportes_intervalo.py` (or a new test) for spec scenario `Interval mode aggregates the same way` on `/reportes/ingresos`.
- [x] 1.8 GREEN: generalize the `/reportes` handler into `/reportes/ingresos` in `backend/app/routers/reportes.py`, using `resolver_ventana`; keep `anio/mes/momento` `Optional`, add additive `fecha_inicio/fecha_fin` fields per D9.
- [x] 1.9 Add `GET /reportes` as a hidden alias (`include_in_schema=False`) on the same handler per D1.
- [x] 1.10 Verify existing `test_reportes*.py` files pass unmodified (regression proof for D1) — run full backend suite for this module.
- [ ] 1.11 Update `frontend/src/api/index.ts` `reportesApi.ingresos(params: FiltroReporte)` call signature to accept momento-or-interval params (backend-facing only; UI wiring is PR3). — DEFERRED: orchestrator scoped this apply batch as "backend-only" for PR1 (per apply prompt's AGENTS.md-conventions note); moving to PR3 batch alongside the rest of the frontend API/type work (task 3.2) to keep PR1 a clean backend-only diff.

## Phase 2: PR2 — Cartera Vencida endpoint

- [ ] 2.1 RED: create `backend/tests/test_reportes_cartera_vencida.py` covering spec scenarios `Included when entrada-en-mora falls in the window`, `Excluded when entrada-en-mora falls outside the window`, `Paid payments are never included`.
- [ ] 2.2 RED: add scenarios `Totals and gestor breakdown present`, `No receptor breakdown in the response` to the same test file.
- [ ] 2.3 RED: add scenarios `Deferred payment disappears from a past window on re-query`, `Window entirely in the future returns an empty report`, `Window partially in the future is clamped, not rejected` (D5 clamp).
- [ ] 2.4 RED: add coverage for D6 guards — soft-deleted cuota excluded, operationally-closed credit excluded — and D8 gestor-less cuota counted in totals but absent from `por_gestor`.
- [ ] 2.5 GREEN: define `CarteraVencidaGestor` and `CarteraVencidaResponse` Pydantic models in `backend/app/routers/reportes.py` per the Interfaces contract.
- [ ] 2.6 GREEN: implement `GET /reportes/cartera-vencida` — `resolver_ventana` → `fin_efectivo = min(fecha_fin, hoy_bogota())` (D5) → `bounds_entrada_mora` SQL filter (D4) → guards `pagado==False`, `deleted_at IS NULL`, `credito_operativamente_abierto()` (D6) → single `select(Pago, Gestor)` outer join (D8).
- [ ] 2.7 GREEN: accumulate `pendiente = (capital_a_pagar-capital_pagado)+(interes_a_pagar-interes_pagado)` as `Decimal`, convert to `float` only at response build (D7, AGENTS.md Decimal rule).
- [ ] 2.8 GREEN: sort `por_gestor` by `(gestor_nombre, gestor_id)`; verify grand total equals sum of per-gestor subtotals.
- [ ] 2.9 Run full `test_reportes_cartera_vencida.py` and confirm all RED tests from 2.1-2.4 are now GREEN.

## Phase 3: PR3 — Frontend

- [ ] 3.1 Replace stale `Reporte` type in `frontend/src/types/index.ts` with `ReporteIngresos` and `ReporteCarteraVencida` matching the backend response shapes (fixes existing `total_intereses`/missing-pending-fields drift).
- [ ] 3.2 Add `FiltroReporte` union type and `reportesApi.carteraVencida(params)` to `frontend/src/api/index.ts`; finalize `reportesApi.ingresos` typing started in 1.11.
- [ ] 3.3 In `frontend/src/pages/Reportes/ReportesPage.tsx`, add report-type selector (Ingresos / Cartera Vencida) and filter-mode selector (Por momento / Por intervalo), reusing the `MOMENTOS` dropdown for momento mode.
- [ ] 3.4 Add date inputs (`type="date"`, `YYYY-MM-DD` string state) following the `AuditoriaPage` pattern for interval mode.
- [ ] 3.5 Split rendering into `IngresosReporteView` and `CarteraVencidaReporteView` per D10 container/presentational split; clear the current report when report type changes.
- [ ] 3.6 Verify `npx tsc --noEmit` passes with no type errors.
- [ ] 3.7 Manual check: momento mode Ingresos unchanged visually; interval mode both reports; Cartera Vencida shows totals + por-gestor with no por-receptor section.

## Phase 4: Spec/Docs cleanup

- [ ] 4.1 Confirm `openspec/specs/overdue-evaluation/spec.md` delta (already drafted) merges cleanly — no additional action if already applied.
- [ ] 4.2 Confirm `openspec/changes/reportes-cartera-vencida-y-rango-fechas/specs/reportes/spec.md` scenarios are all covered by tasks 1.5, 1.7, 2.1-2.4 (traceability check, no code change).
