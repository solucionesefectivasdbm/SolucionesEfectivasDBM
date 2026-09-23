# Archive Report: Reportes — Cartera Vencida + Filtro por Intervalo de Días

**Change**: `reportes-cartera-vencida-y-rango-fechas` (items 13+14 fused)
**Archived**: 2026-09-23
**Status**: COMPLETE AND MERGED

## Executive Summary

Three stacked PRs (#55, #56, #57) successfully implemented interval-filter mode for the existing Ingresos report and added a new Cartera Vencida report endpoint, both filtering over momento or arbitrary date ranges. All implementation verified with passing tests; both features deployed to production.

## Deliverables

### Code Changes (3 Stacked PRs)

| PR | Branch | Title | Status |
|---|---|---|---|
| #55 | `feat/reportes-rango-fechas` | PR1: momentos utilities + resolver_ventana + Ingresos interval | MERGED |
| #56 | `feat/reportes-cartera-vencida` | PR2: Cartera Vencida endpoint | MERGED |
| #57 | `feat/reportes-frontend-tipo-y-rango` | PR3: Frontend selectors + type fixes | MERGED |

### Backend Deliverables

1. **`backend/app/utils/momentos.py`**
   - Added `fecha_entrada_mora(fecha_maxima) -> date`: pure function computing entry-into-overdue date, reusing existing momento boundaries.
   - Added `bounds_entrada_mora(inicio, fin) -> (date, date)`: SQL-friendly bounds for the date range where entrada-en-mora falls.
   - Full coverage: m2 cross-month, February leap/non-leap, December year boundary.

2. **`backend/app/routers/reportes.py`**
   - Added `resolver_ventana()`: unified window-resolution helper accepting either momento or interval params, returning 422 for invalid combinations.
   - Generalized `GET /reportes/ingresos` (formerly `/reportes`): accepts both filter modes, response shape unchanged.
   - Added hidden `GET /reportes` alias: backward compatibility for existing clients.
   - New `GET /reportes/cartera-vencida` endpoint: filters unpaid payments by entrada-en-mora window, returns totals + per-gestor breakdown (no per-receptor).
   - All guards applied: soft-deleted excluded, operationally-closed credits excluded, `pagado==False` filter, Decimal arithmetic.

3. **Backend Tests**
   - `backend/tests/test_momentos.py`: 11 new tests for `fecha_entrada_mora` covering spec + design boundary cases + consistency with `en_mora`.
   - `backend/tests/test_momentos.py`: ~40 new assertions for `bounds_entrada_mora` equivalence proof (4-year sweep, all critical moments).
   - `backend/tests/test_reportes_intervalo.py`: 9 tests covering both filter modes, 422 validation, aggregation equivalence.
   - `backend/tests/test_reportes_cartera_vencida.py`: 13 tests covering membership, totals, gestor breakdown, deferral handling, future-window clamping, soft-delete/closed-credit guards.
   - **Regression proof**: 10 existing `test_reportes*.py` tests pass unmodified against hidden `/reportes` alias (D1).

### Frontend Deliverables

1. **`frontend/src/types/index.ts`**
   - Replaced stale `Reporte` type with `ReporteIngresos` (13 fields, optional `anio`/`mes`/`momento`, required `fecha_inicio`/`fecha_fin`).
   - New `ReporteCarteraVencida` type matching backend response.
   - New `FiltroReporte` union enforcing mutually-exclusive momento/interval modes at TypeScript level.

2. **`frontend/src/api/index.ts`**
   - `reportesApi.ingresos(params: FiltroReporte)`: typed call for Ingresos with both filter modes.
   - `reportesApi.carteraVencida(params: FiltroReporte)`: new endpoint call.

3. **`frontend/src/pages/Reportes/ReportesPage.tsx`**
   - Report-type selector (Ingresos / Cartera Vencida).
   - Filter-mode selector (Por momento / Por intervalo).
   - Momento mode reuses existing `MOMENTOS`, `MESES`, `aniosDisponibles` dropdowns.
   - Interval mode uses date inputs (`type="date"`, `YYYY-MM-DD` pattern) following `AuditoriaPage` style.
   - Report cleared when report type changes (D10 container/presentational split).

4. **`frontend/src/pages/Reportes/IngresosReporteView.tsx` (new)**
   - Extracted view component for Ingresos report (totals cards + por-gestor table).

5. **`frontend/src/pages/Reportes/CarteraVencidaReporteView.tsx` (new)**
   - New view component for Cartera Vencida report (totals card + per-gestor table, no per-receptor).

### Spec Updates

1. **`openspec/specs/overdue-evaluation/spec.md`** (main spec)
   - ADDED: "Derived Entrada-en-Mora Date" requirement with 6 scenarios (m1/m2/Feb/Dec boundaries + consistency with `en_mora`).
   - MODIFIED: "Reporting Is a Documented Consumer of Overdue Data" requirement (narrows "no report changes" Non-Goal to allow read-only reporting consumption).
   - UPDATED Non-Goals: removed blanket "report changes" exclusion; clarified remaining non-goals.

2. **`openspec/specs/reportes/spec.md`** (new main spec)
   - Five requirements: Two Mutually Exclusive Filter Modes, Ingresos Structure Unchanged, Cartera Vencida Event-Based, Totals/Por-Gestor Only, Live Not Historical.
   - 14 scenarios covering filter modes, response shapes, membership, deferral, future-window handling.
   - All scenarios traced to 22+ implementation tests (full traceability).

## Verification Status

**All three PRs verified with PASS WITH WARNINGS:**
- PR1 (momentos + resolver + Ingresos interval): 645/645 backend tests passing; 10/10 regression tests (backward compatibility verified).
- PR2 (Cartera Vencida endpoint): 658/658 backend tests (645 baseline + 13 new); spec date-arithmetic typo fixed (2026-09-15 → 2026-09-14, verified via hand computation).
- PR3 (Frontend): `npx tsc --noEmit` passed zero type errors; type drift analysis clean; no scope leakage detected.

**Non-blocking observations:**
- TestBoundsEntradaMora uses 4-year boundary-sweep (5844 assertions) instead of literal cross-product (sound mathematical equivalence).
- Spec THEN-clauses for future-window scenarios could explicitly state `fecha_fin` clamping (currently only in design and code docstrings).
- Manual browser check (task 3.7) confirmed working: all 4 combos (Ingresos/Cartera Vencida × momento/intervalo) functional; no receptor section in Cartera Vencida; network requests confirmed 200.

## Architecture Decisions Confirmed

| # | Decision | Impact |
|---|----------|--------|
| D1 | Hidden `/reportes` alias for backward compatibility | Zero breaking changes; existing clients unaffected |
| D2 | `resolver_ventana` in router (not utils/momentos) | Clean separation: pure date logic vs HTTP validation |
| D3 | `fecha_entrada_mora` reuses existing momento utilities | Guaranteed consistency with `en_mora` at all boundaries |
| D4 | Cartera Vencida filtered in SQL by bounds | Single-query efficiency; no N+1; matches `/alertas/vencidos` pattern |
| D5 | Future-window clamping to today | Natural empty-set result for entirely-future windows; consistent with `en_mora` semantics |
| D6 | Same guards as `/alertas/vencidos` | Collectable cartera logic aligned across codebase |
| D7 | Decimal arithmetic for money (per AGENTS.md) | Frontend gets typed numbers; backend maintains precision |
| D8 | Single outer-join query for per-gestor breakdown | Deterministic order; no redundant queries |
| D9 | Optional momento fields in Ingresos response | Backward compatible; interval mode transparently slots in |
| D10 | Separate view components for report types | Container/presentational split; type safety; no response shape mixing |

## Compliance & Conventions

- **SQLAlchemy 2.x async**: `await db.execute()` on AsyncSession (standard codebase pattern).
- **Decimal for money**: Cumulative accounting done as Decimal; float conversion only at response serialization (AGENTS.md rule observed).
- **Soft delete**: `deleted_at IS NULL` guard on all queries.
- **No N+1**: Single query with outer joins, not per-row loops.
- **Spanish commit messages**: 3 conventional-commit messages merged to main (following repo history).
- **Read-only endpoints**: No audit_service calls; no data mutations; no backfill (per design + Non-Goals).

## Known Limitations & Future Work

1. **Performance on wide intervals**: Same load-all-then-aggregate pattern as existing `/alertas/vencidos` and `/reportes`. Acceptable at current scale; flagged for optimization if data volume grows.
2. **Historical snapshot reconstruction**: Explicitly out of scope (rule 2, business rule). Cartera Vencida is always live-recomputed from current `fecha_maxima`.
3. **Spec doc clarity on clamping**: Future pass could add explicit `fecha_fin` clamping statement to THEN-clauses (currently only in design.md and code).

## Rollback & Migration

- **No migration required**: No schema changes, no persisted derived state.
- **No audit implications**: Read-only endpoints do not touch audit_service.
- **Backward compatibility**: Hidden `/reportes` alias keeps old clients working unchanged.
- **Rollback boundary**: Revert the three PRs in reverse order (PR3 → PR2 → PR1); no data loss, no cleanup needed.

## Artifact Traceability

**Change artifacts archived in `openspec/changes/archive/2026-09-23-reportes-cartera-vencida-y-rango-fechas/`:**
- proposal.md ✓
- explore.md ✓
- design.md ✓
- tasks.md ✓ (all 4 phases completed: 1 + 2 + 3 + cleanup)
- verify-report.md ✓ (3-part report: PR1, PR2, PR3)
- specs/overdue-evaluation/spec.md ✓ (delta, merged to main)
- specs/reportes/spec.md ✓ (new spec, created in main)

**Engram memory observations (if applicable):**
- `sdd/reportes-cartera-vencida-y-rango-fechas/proposal` — captured intent, business rules, dependencies.
- `sdd/reportes-cartera-vencida-y-rango-fechas/design` — architecture decisions D1–D10.
- `sdd/reportes-cartera-vencida-y-rango-fechas/tasks` — 4 phases with 40+ tasks, all checkbox-completed.
- `sdd/reportes-cartera-vencida-y-rango-fechas/verify-report` — multi-part verification (PR1+PR2+PR3).

## Next Steps

**None. This change is COMPLETE and CLOSED.**

All requirements met, all specs synced to main, all PRs merged to production, all tests passing, all verifications complete. The Reportes capability now supports both momento-based and interval-based filtering for Ingresos (unchanged structure) and provides a new live-recomputed Cartera Vencida report, breaking down overdue balance by gestor and optionally by arbitrary date range.

The overdue-evaluation capability now formally documents that reporting may consume `fecha_entrada_mora` as a read-only input, with no impact on its own non-goals (no jobs, no notifications, no backfill, no persistence).

---

**Archived by**: SDD Archive Executor
**Date**: 2026-09-23
**Archive location**: `openspec/changes/archive/2026-09-23-reportes-cartera-vencida-y-rango-fechas/`
**Git commit**: Prepared for staging and commit by orchestrator.
