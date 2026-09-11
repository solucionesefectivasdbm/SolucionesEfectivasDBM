# Verify Report -- daily-payments-skip-sunday

## PR1 -- Phases 1-4

**Change**: daily-payments-skip-sunday
**Mode**: Strict TDD (backend), hybrid artifact store
**Scope of this verify**: Phases 1-4 only. Phase 5 (backfill) and Phases 6-7 are DEFERRED to PR2.
**Verdict**: PASS

## Test Execution Evidence

Command: backend/venv/Scripts/python.exe -m pytest -q backend/tests
Exit code: 0
304 passed, 7 warnings in 1.52s

Matches expected 304 = 290 baseline (main) + 14 new tests.

## Scenario to Test Matrix

| Requirement | Scenario | Test | Verified assertion |
|---|---|---|---|
| Sunday Is Never a Daily Due Date | Saturday advances to Monday | test_fechas_ancla.py::test_4_2_b_diario_month_boundary | 2026-01-31 to 2026-02-02 |
| Sunday Is Never a Daily Due Date | Non-Sunday advances by one | test_4_2_a_diario_plus_1, test_4_2_c_diario_thu_to_fri | Jan-15 to Jan-16 |
| Sunday Is Never a Daily Due Date | Cascade preserves count | test_4_2_g_diario_cascade_ten_cuotas_no_sunday | 10 dates distinct, none Sunday, last 2026-01-15 |
| Other Periodicities Unchanged | Weekly Sunday stays | test_4_1_c_semanal_sunday_unchanged | 2026-01-25 to 2026-02-01 both Sunday |
| Other Periodicities Unchanged | Anchored untouched | pre-existing TestMensualAnchor and TestQuincenalAnchor | regression evidence, still green |
| Sunday Start Rejected | Sunday start rejected | test_diario_domingo_rechazado_nombra_domingo | 422, domingo in detail, zero rows persisted |
| Sunday Start Rejected | Non-Sunday accepted | test_diario_sabado_aceptado, test_diario_lunes_aceptado | 201 for Sat and Mon |
| Sunday Start Rejected | Other periodicities allowed | test_semanal_domingo_aceptado, test_mensual_domingo_aceptado | 201 |
| Projection Parity | Projected rows skip Sunday | test_virtual_nunca_cae_en_domingo | all virtual weekday not 6 |
| Projection Parity | Resync correctness | test_virtual_resincroniza_a_fecha_persistida | cuota 4 chains from real cuota 3 date, 2026-01-06 |
| Independence Carry-over | Shortfall across shift | test_sabado_parcial_arrastra_a_lunes_invariante_monto | numero_cuota 2, 2026-01-05, invariant holds, exact amounts |
| Edit-Days Guard | Still rejected | pre-existing test_diario_rejected | 422, unchanged |

Backfill (4 scenarios) DEFERRED to PR2 -- test file and endpoint not implemented in this slice, per documented PR1/PR2 seam.

Total Phases 1-4 scenarios: 11 covered, 0 gaps.

## Design Conformance

| Design decision | Code evidence | Status |
|---|---|---|
| es_domingo and _siguiente_diario wired only into diario branch | fechas.py lines 48-62, 126-127; semanal unchanged at line 129 | Match |
| Router-level 422 plain string in crear_credito before client lookup | creditos.py lines 167-174, guard before lookup at 177 | Match |
| Message names Sunday, requires another start date | detail text confirmed | Match |
| Resync to persisted fecha_maxima in _calcular_virtuales | pagos.py lines 461-469 | Match |
| No frontend changes | diff stat shows zero frontend files | Match |
| No Alembic migration | no alembic/versions files in diff | Match |

## TDD Compliance

TDD Evidence table present in apply-progress obs 920. 4/4 tasks have RED test files, all cross-referenced above. GREEN confirmed: 304/304 passed. Triangulation: Phase1 7 cases, Phase2 5 cases, Phase3 2 cases, Phase4 1 case matching spec. Safety net: pre-existing suites for each modified file re-verified green.

TDD Compliance: 6/6 checks passed.

## Assertion Quality Audit

Read all 4 new/modified test files directly. No tautologies, no ghost loops, no assertion without production code call, no smoke-test-only patterns. All assertions are exact-value checks or HTTP-status plus persistence checks.

Assertion quality: all assertions verify real behavior. 0 CRITICAL, 0 WARNING.

## Review Workload and Diff Size

git diff main --stat excluding openspec: 367 authored lines across 7 files, under the 400-line budget, matching apply-progress own count.

Six commits on the branch: SDD artifacts, fechas.py rule plus tests, creditos.py rejection plus tests, pagos.py resync plus tests, arrastre independence test, tasks.md status update. No untracked junk files (gga, atl dir, test_all.py, deleted docx) appear in any commit, confirmed via name-status check on the commit range.

## Regression Risk Scan

No remaining plus-one-day timedelta usage for diario dates outside the helper function itself. PATCH edit-days endpoint still rejects diario and semanal with 422, unchanged, confirmed by re-reading the router and the still-green pre-existing regression test.

## Findings

No CRITICAL or WARNING findings for Phases 1-4.

SUGGESTION non-blocking: pre-existing frontend gap (CreditosPage does not flatten list-shaped Pydantic detail) correctly stays out of scope, deferred as separate follow-up per design decision obs 918.

## Deferred to PR2

Phase 5 backfill (test file and admin endpoint, 4 spec scenarios), Phase 6 full-suite plus prod audit and one-time backfill run, Phase 7 follow-up PR removing the temporary endpoint and its test file.

## Artifacts

openspec/changes/daily-payments-skip-sunday/verify-report.md
Engram sdd/daily-payments-skip-sunday/verify-report

---

## PR2 -- Phase 5 (Backfill)

**Change**: daily-payments-skip-sunday
**Branch**: feature/daily-payments-skip-sunday-pr2 (based on feature/daily-payments-skip-sunday @ 854211f)
**Mode**: Strict TDD (backend), hybrid artifact store
**Scope of this verify**: Phase 5 only (temporary admin backfill endpoint). Phases 6-7 (prod audit run, cleanup PR) remain PENDING/DEFERRED, not evaluated as failures.
**Verdict**: PASS WITH WARNINGS (0 CRITICAL, 0 blocking WARNING, 2 non-blocking SUGGESTIONs)

## Test Execution Evidence

Command: backend/venv/Scripts/python.exe -m pytest -q backend/tests
Exit code: 0
310 passed, 7 warnings, 1.63s

Matches expected 310 = 304 baseline (PR1) + 6 new tests. Warnings are pre-existing (asyncio event_loop fixture deprecation, jose utcnow deprecation, one AsyncMockMixin RuntimeWarning in an unrelated pre-existing test) -- none introduced by this change.

## Scenario to Test Matrix (Backfill requirement, 4 spec scenarios)

| Scenario | Test | Verified assertion (body read directly) |
|---|---|---|
| Pending Sun,Mon,Tue -> Mon,Tue,Wed, reported | test_cascada_domingo_lunes_martes_a_lunes_martes_miercoles | 3 pending rows on legacy Sun/Mon/Tue re-chain to Mon/Tue/Wed; creditos_corregidos==1, cuotas_corregidas==3, credit id in ids |
| Only pending row is cuota 1 on Sunday -> moves to Monday | test_solo_cuota_1_pendiente_en_domingo_se_mueve_a_lunes | single pending cuota 1 on Sunday (fecha_inicial_pago itself) shifts to the following Monday |
| Paid daily Sunday row + pending semanal Sunday row -> unchanged | test_cuota_pagada_domingo_y_semanal_pendiente_domingo_no_se_tocan | diario credit paid Sunday row untouched; semanal credit pending Sunday row untouched; neither id appears in ids |
| Second run -> zero changes | test_segunda_corrida_es_idempotente | first run corrects greater than 0 rows; identical second run returns creditos_corregidos==0, cuotas_corregidas==0, ids==[] |

Plus 2 non-spec-scenario tests covering design/RBAC requirements: test_gestor_403 (RBAC: require_role(admin) -- gestor gets 403), test_registra_auditoria_por_credito_corregido (design decision: one audit entry per corrected credit, asserted via a real AuditLog row query).

Total backfill scenarios: 4/4 covered, 0 gaps. Combined with PR1 (11/11), full spec coverage is 15/15, 0 gaps -- matches the tasks.md scenario-count correction (7 requirements / 15 scenarios).

All 6 tests in test_backfill_domingos_diario.py are unmocked integration tests per project convention: real FastAPI app via httpx.AsyncClient with ASGITransport, real aiosqlite db_session injected through get_db override. The only MagicMock used is spec=Usuario for the auth-stub identity (get_current_user override), not for any business logic, DB call, or the endpoint under test -- consistent with test_creditos_router.py and test_dias_pago_endpoint.py conventions.

## Code Review Against Design (backend/app/routers/creditos.py:479-588)

| Design point | Code evidence | Status |
|---|---|---|
| require_role(admin) | line 482 | Match |
| Selection: active diario credits with 1+ pending Pago | lines 511-524, correlated subquery on Pago.credito_id where pagado=False, deleted_at IS NULL | Match |
| desde_fecha from siguiente_fecha_maxima(max paid fecha_maxima) when a paid row exists | lines 542-555, ultima_pagada via func.max(Pago.fecha_maxima) filtered pagado=True; else branch shifts fecha_inicial_pago +1 day if Sunday | Match |
| Reuse of recalcular_cuotas_futuras | line 557 | Match |
| Paid rows never modified | query at 531-539 only selects pagado=False rows into cuotas_pendientes; recalcular_cuotas_futuras itself also only queries pagado=False (credito_service.py:856-864) -- double-enforced | Match |
| Non-diario excluded | line 514 Credito.periodicidad == Periodicidad.diario | Match |
| Only actually-changed rows reported | lines 560-572, comparison pago.fecha_maxima != fecha_antes | Match |
| One audit entry per corrected credit | lines 574-580, single audit_service.registrar_actualizacion_campos call inside the if cambios_credito block, outside the inner pago loop | Match |
| Response shape revisados/creditos_corregidos/cuotas_corregidas/ids/cambios | lines 582-588 | Match |
| TEMPORARY marker present | docstring line 486: TEMPORAL -- correccion historica unica | Match |
| credito.fecha_inicial_pago not rewritten (design decision 7) | no assignment to that field anywhere in the endpoint | Match |
| PATCH /dias-pago guard untouched | line 335 (router.patch dias-pago) is outside the PR2 diff range (479-588); confirmed via git log feature/daily-payments-skip-sunday..HEAD --name-status showing only additions to creditos.py, no modification near line 335 | Match |

### No paid row, first cuota on Sunday branch -- traced explicitly

Read recalcular_cuotas_futuras (credito_service.py:845-871): fecha_actual = desde_fecha, then for the first row in cuotas_futuras (ordered by numero_cuota), cuota.fecha_maxima = fecha_actual is assigned directly -- desde_fecha becomes cuota 1 date itself, not a previous date fed into siguiente_fecha_maxima first. Confirmed against test_solo_cuota_1_pendiente_en_domingo_se_mueve_a_lunes: fecha_inicial_pago=2026-03-01 (Sunday) -> endpoint computes desde_fecha = 2026-03-02 (Monday, +1 day shift) -> recalcular_cuotas_futuras assigns p1.fecha_maxima = 2026-03-02 directly (no further +1). Test asserts exactly date(2026, 3, 2). No double-shift bug.

## Edge Cases Reasoned About

- Credit with ALL rows paid: excluded by construction -- the candidate query (lines 511-524) requires EXISTS a pending Pago; a fully-paid credit has none, so it is never in creditos_candidatos and never counted in revisados. This matches design decision 6 (all active diario credits with 1+ pending row), not all diario credits. revisados therefore means candidates with pending rows, not every diario credit in the system -- see SUGGESTION below on naming clarity.
- Pending rows already correct (not on Sunday) but a Sunday-dated paid row precedes them: desde_fecha = siguiente_fecha_maxima(ultima_pagada=Sunday, credito). Since the rule always advances by 1+ day and only shifts forward when the resulting date lands on Sunday, Sunday plus 1 day equals Monday, which requires no further shift -- the recomputed chain matches the already-correct pending dates, so no spurious changes are reported. This exact recompute-an-already-correct-chain-to-zero-diff path is exercised by test_segunda_corrida_es_idempotente (second run over an already-corrected credit). No separate test needed; reasoning confirmed against the idempotency test actual code path.
- Transaction atomicity (one failure -> whole run rolled back or per-credit?): the endpoint loops over all candidate credits inside a single request using the shared db session with no per-credit commit or flush boundary and no try/except. A failure partway through (e.g. a recalcular_cuotas_futuras exception on credit N) would raise out of the endpoint; FastAPI get_db dependency (project convention) performs the commit/rollback at the request boundary, so the entire run is one atomic transaction, not per-credit. This is untested (no test forces a mid-loop failure) and undocumented in this endpoint docstring, but it mirrors the same reuse-recalcular_cuotas_futuras-in-a-loop pattern used by the already-archived cierre-saldo-cero and arrastre backfills referenced in the docstring itself (mismo patron que los backfills de arrastre y cierre-saldo-cero ya archivados) -- not a new risk introduced by this PR. Flagged as non-blocking SUGGESTION, not CRITICAL or WARNING.

## TDD Compliance

TDD Evidence table present in apply-progress obs #920 (PR2 section). 1/1 task batch (5.1-5.3) has a RED test file (test_backfill_domingos_diario.py, 6 tests, all failed 404 before the endpoint existed) and GREEN confirmed against actual execution: 6/6 pass standalone (pytest -q backend/tests/test_backfill_domingos_diario.py) and remain 6/6 inside the full 310-test run. Triangulation: 6 distinct cases (cascade, lone-Sunday-cuota-1, paid+semanal-untouched, idempotent, RBAC-403, audit-count) against 4 spec scenarios -- adequate, exceeds minimum. Safety net: 304/304 pre-existing tests reported passing before this task per apply-progress; reconfirmed here since the full 310-test run subsumes all 304.

TDD Compliance: 6/6 checks passed.

## Assertion Quality Audit

Read test_backfill_domingos_diario.py in full (299 lines, 6 test methods). No tautologies, no ghost loops (no for/forEach over query results), no assertion-without-production-code-call, no smoke-test-only patterns. All assertions are exact-value date/int/list checks (equality, membership) directly against ORM object state or JSON response body after a real HTTP POST through the real app. Mock/assertion ratio: 1 MagicMock (auth stub, not business logic) across 6 tests vs about 30 assert statements -- well under the 2x threshold, and the one mock is an identity stub, not a business-logic mock.

Assertion quality: all assertions verify real behavior. 0 CRITICAL, 0 WARNING.

## Review Workload and Diff Size

git diff feature/daily-payments-skip-sunday --stat -- . (excluding openspec): 412 insertions, 2 deletions across backend/app/routers/creditos.py (+116/-2) and backend/tests/test_backfill_domingos_diario.py (+298 new file) -- matches apply-progress own count exactly. This is 12 lines over the nominal 400-line budget; per session preflight this PR2 slice was pre-accepted as size:exception (chained-PR review budget applies per-PR, not cumulative against PR1), so this is not a fresh finding, only a confirmation of the already-accepted risk.

Note: the same stat command also shows an unrelated binary entry for the deleted docx lock file (Bin 162 to 0 bytes) -- this is the pre-existing untracked working-tree deletion visible in git status at session start, NOT part of either PR2 commit. Confirmed via git log feature/daily-payments-skip-sunday..HEAD --name-status, which lists only M backend/app/routers/creditos.py and A backend/tests/test_backfill_domingos_diario.py in commit fc120eb, and M openspec/changes/daily-payments-skip-sunday/tasks.md in commit 62728e7. No junk files (.gga, .atl dir, test_all.py, the docx) are present in any commit.

## Regression Risk Scan

PATCH /creditos/{id}/dias-pago (line 335, require_role admin/registrador/recaudador) is untouched by this PR diff range and remains outside the new endpoint code (lines 479-588); the backfill endpoint is not reachable via that route and does not alter its guard. RBAC on the new endpoint is require_role(admin) only, confirmed by test_gestor_403 returning 403 for a gestor user.

## Findings

CRITICAL: none.

WARNING: none blocking.

SUGGESTION (non-blocking, x2):
1. revisados in the response counts only diario credits that already have 1+ pending row (the candidate-query result), not every active diario credit in the system. This matches design decision 6 exactly, but an operator reading the JSON response without the docstring could misinterpret revisados as all diario credits examined. Cosmetic naming clarity only -- no behavior change needed for a temporary endpoint slated for removal in Phase 7.
2. No test exercises a mid-loop failure to confirm the whole-request-is-one-transaction behavior (no per-credit commit boundary, no try/except around individual recalcular_cuotas_futuras calls). This mirrors the precedent pattern used by the already-archived arrastre and cierre-saldo-cero backfills (per this endpoint own docstring), so it is not a new risk, and it is acceptable for a one-off admin migration endpoint per AGENTS.md documented temporary-migration convention.

## Deferred / Pending (not evaluated as failures)

Phase 6 (full-suite confirmation done here; prod audit SQL run and one-time production backfill POST execution remain PENDING per apply-progress and tasks.md). Phase 7 (follow-up PR to remove the temporary endpoint and its test file after prod audit confirms zero remaining Sunday-dated pending rows) remains PENDING, per AGENTS.md documented temporary-migration convention (admin-only POST once, deleted in a later commit).

## Artifacts

openspec/changes/daily-payments-skip-sunday/verify-report.md (this file, PR2 section appended)
Engram sdd/daily-payments-skip-sunday/verify-report (topic_key upsert, combined PR1+PR2 content)
