# Tasks: Daily Payments Skip Sunday

**Scenario count note**: spec.md's `## Purpose` line references 17 scenarios in an
earlier draft summary; the authoritative file `specs/daily-installment-scheduling/spec.md`
(read directly for this task breakdown) contains **15 scenarios across 7 requirements**.
All 15 are mapped below — see Scenario Coverage Map.

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~345 (fechas.py ~20, creditos.py ~65, pagos.py ~10, tests ~250) |
| 400-line budget risk | Medium |
| Chained PRs recommended | No |
| Suggested split | Single PR (fallback seam available: PR1 rule+rejection+resync+tests / PR2 backfill) |
| Delivery strategy | ask-on-risk |
| Chain strategy | pending |

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: pending
400-line budget risk: Medium

### Suggested Work Units

| Unit | Goal | Likely PR | Focused test command | Runtime harness | Rollback boundary |
|------|------|-----------|----------------------|-----------------|-------------------|
| 1 | Sunday-skip rule, creation rejection, projection resync, carryover regression | PR 1 | `cd backend && python -m pytest tests/test_fechas_ancla.py tests/test_creditos_router.py tests/test_pagos_listado.py tests/test_credito_service_arrastre.py` | httpx AsyncClient + aiosqlite integration tests (unmocked) | Revert `fechas.py`, `creditos.py` guard, `pagos.py` resync diff — backfill endpoint untouched |
| 2 | Backfill endpoint (temporary) | PR 1 (or PR 2 if unit 1 alone nears 400 lines) | `cd backend && python -m pytest tests/test_backfill_domingos_diario.py` | httpx AsyncClient + aiosqlite integration tests (unmocked) | Revert new endpoint/schema + its test file; core Sunday-skip rule stays intact |
| 3 | Cleanup: remove temporary backfill endpoint | Follow-up PR (post-deploy) | `cd backend && python -m pytest` (full suite) | Manual: prod backfill already ran, audit SQL confirms zero pending Sunday rows | Revert removal commit; endpoint code still in git history |

## Phase 1: Sunday-Skip Date Helper (fechas.py)

- [x] 1.1 RED (`backend/tests/test_fechas_ancla.py`): flip `test_4_2_b` — Saturday 2026-01-31 → Monday 2026-02-02 (month boundary); Thursday 2026-01-15 → Friday 2026-01-16; 10-cuota cascade from Monday 2026-01-05 (no Sunday, last 2026-01-15, exactly 10 distinct dates); `semanal` Sunday 2026-01-25 → 2026-02-01 unchanged; `mensual`/`quincenal` Sunday-anchor unchanged (Req: Sunday Is Never a Daily Due Date — 3 scenarios; Other Periodicities Unchanged — 2 scenarios)
- [x] 1.2 GREEN: add `es_domingo(fecha)` and `_siguiente_diario(fecha_anterior)` to `backend/app/utils/fechas.py`; wire only into `siguiente_fecha_maxima`'s diario branch; `semanal` `+7` stays verbatim
- [x] 1.3 Verify: `cd backend && python -m pytest tests/test_fechas_ancla.py` — 0 failures (31 passed)

## Phase 2: Creation Validation (creditos.py)

- [x] 2.1 RED (`backend/tests/test_creditos_router.py`): diario `fecha_inicial_pago` Sunday 2026-02-01 → 422, nothing persisted, `detail` names Sunday; diario 2026-02-02 → 201, first cuota due 2026-02-02; `semanal` Sunday start → 201 accepted (Req: Sunday Start Date Rejected on Creation — 3 scenarios)
- [x] 2.2 GREEN: add `es_domingo` guard raising `HTTPException(422, detail=...)` in `crear_credito` (`creditos.py:159`), before client lookup; message: "Los créditos diarios no pueden iniciar un domingo (el domingo no es día de cobro). Seleccione otra fecha inicial de pago."
- [x] 2.3 Regression lock (pre-existing `backend/tests/test_dias_pago_endpoint.py::TestDiasPagoValidacion::test_diario_rejected`): PATCH edit-days on diario still returns 422, no dates change (Req: Edit-Days Guard Unchanged — 1 scenario). No new test needed — this path is untouched by Phase 1/2 changes and the existing test already covers it; re-verified green in the full-suite run.
- [x] 2.4 Verify: `cd backend && python -m pytest tests/test_creditos_router.py` — 0 failures (23 passed)

## Phase 3: Projection Parity (pagos.py)

- [x] 3.1 RED (`backend/tests/test_pagos_listado.py`): daily credit whose next real cuota is Saturday → first virtual row Monday, cascade identical to generation; assert no regression on non-Sunday-adjacent daily virtual rows (Req: Projection Parity — 1 scenario). Implemented as `TestProyeccionDiariaResyncDomingo` with a legacy-Sunday-history fixture that proves resync (drift bug reproduced pre-fix: virtual cuota #4 computed as 2026-01-07 instead of correct 2026-01-06).
- [x] 3.2 GREEN: resync `fecha_proy` in `_calcular_virtuales` (`pagos.py:460`) to the persisted `fecha_maxima` whenever `n` is an existing row (select `Pago.fecha_maxima`, map `credito_id -> {numero_cuota: fecha}`)
- [x] 3.3 Verify: `cd backend && python -m pytest tests/test_pagos_listado.py` — 0 failures, no regression on existing parity tests (19 passed)

## Phase 4: Carry-over and Closure Independence

- [x] 4.1 RED (`backend/tests/test_credito_service_arrastre.py`): daily `cuota_fija` installment due Saturday paid partially → next due Monday, per-component shortfall carried, `capital_a_pagar + interes_a_pagar == monto_a_pagar` (Req: Independence from Carry-over and Closure — 1 scenario). Written as a characterization/regression test calling `generar_siguiente_cuota` directly — passed immediately (Phase 1 wiring already composes correctly with carry-over), confirming no drift.
- [x] 4.2 GREEN: none needed beyond Phase 1 wiring — confirmed, no drift surfaced.
- [x] 4.3 Verify: `cd backend && python -m pytest tests/test_credito_service_arrastre.py` — 0 failures (11 passed)

## STOP — Review Workload Guard (2026-09-11 apply session)

Authored diff after Phase 4 (excluding `openspec/`): **367 lines** (`git diff main --stat`), approaching the 400-line budget explicitly flagged in this task file's session preflight. Per the mandatory guard, apply STOPPED after Phase 4 and did NOT start Phase 5 (backfill endpoint), which per this file's own "Suggested Work Units" table and design.md's fallback seam is PR2-sized work (new endpoint + new `test_backfill_domingos_diario.py` file with 4+ scenarios, RBAC test, idempotency test — realistically 150+ more lines).

Phases 1-4 are a complete, independently mergeable, independently revertible PR (PR1 per the fallback seam: rule + rejection + projection resync + tests). Full backend suite: 304 passed (baseline 290 on `main` prior to this session + 14 new tests across phases 1-4; note the session preflight referenced a 241-test baseline, but `main` already had 290 passing tests at session start — see apply-progress artifact for detail).

Phase 5 (backfill endpoint), Phase 6 (full-suite + post-deploy prod audit/backfill run), and Phase 7 (cleanup follow-up PR) remain **not started** and are recommended as a separate `sdd-apply` batch / separate PR.

## Phase 5: One-off Backfill Endpoint (temporary)

- [x] 5.1 RED (`backend/tests/test_backfill_domingos_diario.py`, create): pending Sun,Mon,Tue → Mon,Tue,Wed and reported; only pending row is cuota 1 on Sunday → moves to Monday; paid daily Sunday row + pending `semanal` Sunday row → both unchanged; second run → zero changes reported, nothing modified; `gestor` role → 403 (Req: One-off Pending-Row Backfill — 4 scenarios, + RBAC per threat matrix)
- [x] 5.2 GREEN: implement `POST /creditos/admin/backfill-domingos-diario` (`require_role("admin")`) in `creditos.py`, reusing `recalcular_cuotas_futuras`; selection = `periodicidad=diario AND activo AND deleted_at IS NULL AND EXISTS pending Pago (pagado=False, deleted_at IS NULL)`; `desde_fecha` = `siguiente_fecha_maxima(max paid fecha_maxima)` or shifted `fecha_inicial_pago` when no paid rows exist; audit each corrected credit via `audit_service.registrar_actualizacion_campos`; response includes `revisados, creditos_corregidos, cuotas_corregidas, ids[], cambios[]`
- [x] 5.3 Verify: `cd backend && python -m pytest tests/test_backfill_domingos_diario.py` — 0 failures (6 passed)

## Phase 6: Full Suite Verification + Post-Deploy

- [ ] 6.1 Verify: `cd backend && python -m pytest` (full suite) — 0 failures, count ≥ current baseline + new tests
- [ ] 6.2 Note for apply: run `gh auth switch -u solucionesefectivasdbm` before any push, PR, or other `gh` operation
- [ ] 6.3 Post-deploy: run the read-only audit SQL from design.md against prod, record pending Sunday-dated `diario` rows before backfill
- [ ] 6.4 Post-deploy: call `POST /creditos/admin/backfill-domingos-diario` once as admin in prod; record the JSON response (`revisados, creditos_corregidos, cuotas_corregidas, ids, cambios`)
- [ ] 6.5 Post-deploy: re-run the audit SQL, confirm zero pending Sunday-dated `diario` rows remain

## Phase 7: Cleanup (separate follow-up PR, per AGENTS.md temporary-migration convention)

- [ ] 7.1 In a dedicated follow-up PR, after Phase 6.5 confirms zero: remove `POST /creditos/admin/backfill-domingos-diario`, its response schema, and `backend/tests/test_backfill_domingos_diario.py`

## Scenario Coverage Map (spec.md, 7 requirements, 15 scenarios — all mapped, 0 gaps)

| Requirement | Scenarios | Task(s) |
|---|---|---|
| Sunday Is Never a Daily Due Date | 3/3 | 1.1 |
| Other Periodicities Unchanged | 2/2 | 1.1 |
| Sunday Start Date Rejected on Creation | 3/3 | 2.1 |
| Projection Parity | 1/1 | 3.1 |
| Independence from Carry-over and Closure | 1/1 | 4.1 |
| One-off Pending-Row Backfill | 4/4 | 5.1 |
| Edit-Days Guard Unchanged | 1/1 | 2.3 |
