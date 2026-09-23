# Verification Report — reportes-cartera-vencida-y-rango-fechas (PR1 scope)

**Change**: reportes-cartera-vencida-y-rango-fechas
**Scope verified**: Phase 1 (PR1) only — tasks 1.1-1.10. Task 1.11 intentionally deferred to PR3 (excluded from CRITICAL findings per verify instructions).
**Commit**: 1f7f9355d31e8fa72629e81e16b60b422bc1182f on feat/reportes-rango-fechas, not pushed.
**Mode**: Full artifact set (proposal/spec/design/tasks) + apply-progress with TDD evidence.

## Task Completeness (Phase 1)

| Task | Status | Evidence |
|---|---|---|
| 1.1 TestFechaEntradaMora | Done | test_momentos.py L389-466, 11 tests incl. 5 spec + 5 design extra cases + consistency-with-en_mora |
| 1.2 fecha_entrada_mora | Done | momentos.py — reuses get_mes_momento/get_momento/get_periodo_momento, matches D3 formula exactly |
| 1.3 TestBoundsEntradaMora | Done (deviation, see below) | test_momentos.py L468-507 |
| 1.4 bounds_entrada_mora | Done | momentos.py — (fecha_limite_mora(inicio-1d), fecha_limite_mora(fin)), matches Interfaces contract verbatim |
| 1.5 test_reportes_intervalo.py created | Done | 209 lines, 9 tests |
| 1.6 resolver_ventana | Done | reportes.py — validates both/neither/partial-momento/partial-interval/invalid-momento/fecha_desde>fecha_hasta, all to 422 |
| 1.7 interval aggregation test | Done | test_modo_intervalo_agrega_igual_que_modo_momento |
| 1.8 /reportes/ingresos generalized | Done | handler renamed generar_reporte_ingresos, anio/mes/momento now Optional, fecha_inicio/fecha_fin added (D9) |
| 1.9 /reportes hidden alias | Done | same handler, second @router.get("", include_in_schema=False) decorator (D1) |
| 1.10 regression proof | Done | verified independently — see below |
| 1.11 frontend typing | Deferred to PR3 | Reasonable scope boundary — see Deviation Review #1 |

No unchecked core task in PR1 scope. 1.11 is explicitly out of this batch's instructed scope, not a silently dropped requirement.

## Independent Test Execution

Ran full suite myself (not just trusting the apply report):

    backend/venv/Scripts/python.exe -m pytest -q
    -> 645 passed, 11 warnings in 4.81s

Matches the apply report claim of 645 passed / 0 failed exactly. Warnings are pre-existing (AsyncMock coroutine, jose utcnow() deprecation, pytest-asyncio scope) — none newly introduced by this PR (confirmed by warning source paths: pago_service.py, jose/jwt.py, unrelated to reportes.py/momentos.py).

Ran the 3 pre-existing test_reportes*.py files in isolation, unedited (git diff confirms zero changes to these files):

    pytest tests/test_reportes.py tests/test_reportes_arrastre.py tests/test_reportes_por_cuenta.py -q
    -> 10 passed

Confirmed these tests hit REPORTES_URL = "/api/v1/reportes" — i.e., they genuinely exercise the hidden alias route, not the new /ingresos route, which is the real regression proof for D1 (backward compatibility).

## Spec Scenario -> Test Mapping

### reportes/spec.md

| Scenario | Test | Genuine? |
|---|---|---|
| Momento mode resolves as today | test_modo_momento_resuelve_igual_que_get_periodo_momento | Yes — asserts exact fecha_inicio/fecha_fin window (2026-09-25..2026-09-29) plus echoed anio/mes/momento |
| Interval mode uses raw bounds | test_modo_intervalo_usa_los_limites_crudos | Yes — asserts exact echoed bounds and anio/mes/momento all None |
| Both modes supplied is rejected | test_ambos_modos_es_rechazado | Yes — 422 |
| Neither mode supplied is rejected | test_ningun_modo_es_rechazado | Yes — 422 |
| Momento mode output matches today endpoint | Covered structurally: same handler/response model reused for both routes; not a diff-based byte comparison test, but the shared-handler design makes divergence structurally impossible. Acceptable given D1 alias mechanism. | Yes (structural, not literal A/B) |
| Interval mode aggregates the same way | test_modo_intervalo_agrega_igual_que_modo_momento | Yes — non-trivial: 3 payments (paid-in-window, pending-in-window, out-of-window), asserts exact totals AND that the out-of-window payment does not contribute (total_recaudado=100.0, not 1000+). Not tautological. |

Plus design-derived 422 cases beyond the literal spec text (partial momento, partial interval, invalid momento, fecha_desde greater than fecha_hasta) — all covered and genuinely exercised, each asserting a distinct rejection path in resolver_ventana.

Cartera Vencida scenarios (Totals/por-gestor, live-recompute, future-clamp, etc.) are Phase 2 scope — correctly not present in this PR1 diff, not evaluated here.

### overdue-evaluation/spec.md delta

| Scenario | Test | Genuine? |
|---|---|---|
| Inside m1, closes day after | test_dentro_de_m1_cierra_dia_siguiente | Yes, exact date assertion |
| Cross-month m2 | test_m2_cruce_de_mes | Yes |
| February non-leap | test_febrero_no_bisiesto | Yes |
| February leap | test_febrero_bisiesto | Yes |
| December m2 into January | test_diciembre_m2_hacia_enero | Yes |
| Consistency with en_mora | test_consistencia_con_en_mora | Present, exercises the property directly |
| (design extras: m3 day14, day31 to day5, Mar3 to Mar5, Dec30 to Jan5, Jan2 to Jan5) | 5 additional tests | Yes, all present with exact-date assertions |

All scenarios have real, non-shallow covering tests that passed at runtime.

## Deviation Review

1. Task 1.11 deferred to PR3 — ACCEPTED, not a dropped requirement.
The verify task instructions explicitly frame this batch as backend-only on branch feat/reportes-rango-fechas and state task 1.11 was deliberately deferred to PR3 — do not flag it as missing/incomplete. Independently confirmed via git diff that zero frontend files are touched in this commit, and the /reportes alias (D1) means the frontend keeps working unmodified against the old route in the meantime. This is a legitimate, documented scope boundary, not silent scope-dropping.

2. TestBoundsEntradaMora as boundary-sweep vs literal cross-product — ACCEPTED as a rigorous equivalence proof, flagged WARNING for documentation only.
Design Testing Strategy text says to loop over every fm and window endpoint across 2025-01..2028-12, which read literally would require an intractable O(n^2) enumeration (1461 fm times roughly 1461 squared window pairs). The implemented test instead iterates all 1461 fm values in the range (including 2028 leap year, cross-month Dec to Jan, Feb boundaries) and for each one constructs 4 windows anchored exactly at that fm own fecha_entrada_mora value: the exact point, day-before, day-after, and a wide 30-day window on each side. This is mathematically sound: bounds_entrada_mora(inicio, fin) is a pure function of (inicio, fin) only (does not depend on fm), so the correctness question for any fixed fm is fully determined by testing enough different (inicio, fin) windows relative to that fm own critical boundary — which is exactly what varies here. Since every fm in the 4-year range is swept, and the 4 window shapes hit the only points where the predicate can flip (the day immediately before/at/after fecha_entrada_mora(fm)), this genuinely proves the equivalence at all boundary-risk points, including the m2 cross-month case, Feb leap/non-leap, and December year-crossing — not just a subset that happens to pass. 5844 assertions, runs in about 0.1s. This is WARNING-tier (design-text deviation), not CRITICAL — it does not break the spec guarantee.

3. PR1 diff size (about 489 code lines vs forecast 180-240) — ACCEPTED, legitimate test-coverage growth, no scope creep.
Independently verified via git diff --stat HEAD~1 HEAD: only 4 code files changed — backend/app/routers/reportes.py (+104/-10), backend/app/utils/momentos.py (+53/-1), backend/tests/test_momentos.py (+123), backend/tests/test_reportes_intervalo.py (+209, new file). 332 of 489 lines are tests. Grepped the full repo for cartera_vencida/carteraVencida — the only 4 hits are the same 4 PR1 files (docstring references to the upcoming D3/D4-based endpoint, not actual Phase 2 code). Confirmed zero frontend files touched (git diff HEAD~1 HEAD --stat -- frontend is empty). No Phase 2 or Phase 3 code present. The size growth is explained by thorough Strict-TDD scenario coverage (11+1 tests for momentos, 9 for the interval endpoint including several 422 edge cases beyond the literal spec text), not by scope leakage.

## AGENTS.md Convention Check

- SQLAlchemy 2.x async: unchanged patterns (AsyncSession, await db.execute) preserved; resolver_ventana and the route changes do not touch the query layer.
- Decimal for money: PR1 introduces no new financial arithmetic (no capital/interest math changed); existing Decimal accumulation logic in generar_reporte_ingresos untouched. Decimal-for-cartera-vencida is Phase 2 scope (D7), not yet implemented — correctly absent here.
- No float used for money in the diff: confirmed — the diff only adds date-typed fields (fecha_inicio/fecha_fin) and Optional typing changes to existing float-typed aggregate fields already present pre-PR.
- No audit_log writes needed (read-only endpoints) — consistent with design Migration/Rollout note.
- No password/password_hash logging — not applicable to this diff.

## Backward Compatibility (D1)

Confirmed via unedited-file diff (empty) + independent test run: test_reportes.py, test_reportes_arrastre.py, test_reportes_por_cuenta.py (10 tests) pass against the hidden /api/v1/reportes alias route without any modification. This is the regression proof required by design and it holds.

## Scope Leakage Check

- git diff HEAD~1 HEAD --stat -- frontend gives empty output. No frontend changes.
- Grep for cartera_vencida/carteraVencida/cartera.vencida repo-wide finds only the 4 PR1 files, all docstring cross-references to future work, no Phase 2 endpoint code.
- No new routes, models, or schemas beyond resolver_ventana and the /ingresos plus alias generalization.

## Issues

CRITICAL: None.
WARNING: 1 — TestBoundsEntradaMora boundary-sweep approach deviates from the literal wording of design Testing Strategy (loop over every fm and window endpoint); accepted as a mathematically equivalent and genuinely rigorous proof, but flagged for reviewer awareness per deviation review 2 above.
SUGGESTION: None.

## Verdict

PASS WITH WARNINGS (1 non-blocking WARNING, 0 CRITICAL). PR1 (tasks 1.1-1.10) is complete, correctly scoped, spec-compliant, and independently verified with passing runtime evidence (645/645 backend tests, including 10/10 unedited regression tests). Task 1.11 deferral to PR3 is a legitimate, explicitly-instructed scope boundary, not a gap. No Phase 2/3 scope leakage detected. Safe to push branch and open PR1.


---

# Verification Report -- reportes-cartera-vencida-y-rango-fechas (PR2 scope)

**Change**: reportes-cartera-vencida-y-rango-fechas
**Scope verified**: Phase 2 (PR2) only -- tasks 2.1-2.9, on branch feat/reportes-cartera-vencida (stacked on feat/reportes-rango-fechas), commit fa8757b, not pushed. PR1 findings above stand unchanged.
**Mode**: Full artifact set (spec/design/tasks) + apply-progress with TDD evidence + independent spec date-arithmetic recomputation.

## Task Completeness (Phase 2)

| Task | Status | Evidence |
|---|---|---|
| 2.1 RED membership scenarios | Done | test_reportes_cartera_vencida.py -- 3 tests (included/excluded/paid-excluded) |
| 2.2 RED totals/gestor/no-receptor | Done | 2 tests |
| 2.3 RED deferral/future-clamp scenarios | Done | 3 tests |
| 2.4 RED D6/D8 guards | Done | 3 tests (soft-delete, closed credit, gestor-less) + 2 extra shared-validation smoke tests |
| 2.5 GREEN Pydantic models | Done | CarteraVencidaGestor/CarteraVencidaResponse, no por_receptor field |
| 2.6 GREEN endpoint | Done | generar_reporte_cartera_vencida, single outer-join query, D4/D5/D6 wired correctly |
| 2.7 GREEN Decimal accumulation | Done | total_capital/total_intereses accumulate as Decimal, float() only at response construction |
| 2.8 GREEN por_gestor sort + total check | Done | sorted by (gestor_nombre, gestor_id); grand-total-equals-sum asserted in test |
| 2.9 Full cartera test file green | Done | 13/13 passing |

No unchecked task in PR2 scope.

## Independent Test Execution

    backend/venv/Scripts/python.exe -m pytest backend/tests -q
    -> 658 passed, 0 failed, 11 warnings in 4.15s

Matches the apply report exactly (645 PR1 baseline + 13 new). Warnings are the same pre-existing set (AsyncMock coroutine, jose utcnow deprecation) -- none newly introduced. Confirms the apply agent claim.

Note: bare pytest -q from repo root fails via a pre-existing root-level test_all.py sys.exit() -- confirmed as an unrelated repo quirk, correctly worked around by scoping to backend/tests.

## Spec Scenario -> Test Mapping (Phase 2 scenarios)

Read test_reportes_cartera_vencida.py in full (437 lines, 13 tests). All assertions are genuine (exact numeric/date/order checks), not tautological.

| Scenario | Test | Genuine? |
|---|---|---|
| Included when entrada-en-mora falls in the window | test_incluido_cuando_entrada_en_mora_cae_en_la_ventana | Yes -- exact totals (100.0/80.0/20.0) |
| Excluded when entrada-en-mora falls outside the window | test_excluido_cuando_entrada_en_mora_cae_fuera_de_la_ventana | Yes -- same payment, narrower window, asserts 0 count/0 total/empty por_gestor |
| Paid payments are never included | test_pago_pagado_nunca_se_incluye | Yes |
| Totals and gestor breakdown present | test_totales_y_desglose_por_gestor | Yes -- 2 gestores, per-gestor subtotals, explicit sum equals grand total assertion, order check (Ana before Beto) |
| No receptor breakdown in the response | test_sin_desglose_por_receptor | Yes -- asserts por_receptor key absent |
| Deferred payment disappears from a past window on re-query | test_pago_aplazado_desaparece_de_ventana_pasada_al_reconsultar | Yes -- before/after re-query against the SAME window, non-trivial |
| Window entirely in the future returns an empty report | test_ventana_totalmente_futura_retorna_reporte_vacio | Yes -- includes a payment that WOULD match the raw window but is excluded by the D5 clamp; also asserts fecha_fin equals 2026-09-23 (clamped) |
| Window partially in the future is clamped, not rejected | test_ventana_parcialmente_futura_se_recorta_no_se_rechaza | Yes -- two payments, one inside the clamped portion (included) and one only inside the raw/unclamped window (excluded), proving the clamp is real |
| D6: soft-deleted cuota excluded | test_cuota_soft_deleted_excluida | Yes |
| D6: operationally-closed credit excluded | test_credito_saldado_excluido | Yes -- zero-balance credit, activo still True, confirms credito_operativamente_abierto is used (not just activo) |
| D8: gestor-less cuota in totals, absent from por_gestor | test_cuota_sin_gestor_cuenta_en_totales_pero_no_en_desglose | Yes -- asserts cantidad_cuotas 1, total_vencido 100.0, por_gestor empty simultaneously |
| Shared validation (momento mode resolves) | test_modo_momento_resuelve_la_ventana_en_cartera_vencida | Yes, smoke-level but legitimate |
| Shared validation (neither mode 422) | test_ningun_modo_es_rechazado_en_cartera_vencida | Yes |

All 13 scenarios have real covering tests, all passing at runtime.


## Independent Date-Arithmetic Investigation (spec discrepancy)

Apply agent flagged that the spec Deferred payment scenario states fecha_maxima=2026-09-10 gives fecha_entrada_mora=2026-09-15, but the canonical function allegedly produces 2026-09-14.

Independently recomputed by hand, tracing the actual canonical chain in backend/app/utils/momentos.py:

- get_momento(date(2026, 9, 10)): day 10, 5 <= 10 <= 13, m3.
- get_mes_momento(date(2026, 9, 10)): day 10 > 4, returns (2026, 9).
- get_periodo_momento(2026, 9, m3): inicio 2026-09-05, fin 2026-09-13.
- fecha_entrada_mora = fin + 1 day = 2026-09-14.

Confirmed: the apply agent is correct. The spec parenthetical 2026-09-15 is wrong; the canonical value is 2026-09-14.

Fix applied: corrected openspec/changes/reportes-cartera-vencida-y-rango-fechas/specs/reportes/spec.md line 124, replacing 2026-09-15 with 2026-09-14. This is a low-risk documentation correction -- the THEN-clause does not independently re-assert this number, so the fix does not change scope or requirement semantics.

Internal-consistency re-check after the fix:
- Window bound: scenario window is 2026-09-01 to 2026-09-30. 2026-09-14 is inside it.
- Later deferred to 2026-10-12 claim: independently recomputed -- get_momento(2026-10-12) day 12, m3; get_mes_momento gives (2026,10); get_periodo_momento(2026,10,m3) gives (2026-10-05, 2026-10-13); fecha_entrada_mora equals 2026-10-14. That is outside the 2026-09-01/2026-09-30 window -- the spec claim holds and required no correction.

Test trustworthiness: test_pago_aplazado_desaparece_de_ventana_pasada_al_reconsultar does NOT hardcode the spec formerly-wrong 2026-09-15 value anywhere -- its inline comment already correctly states fecha_entrada_mora=2026-09-14, and its assertions only check counts, not the literal entrada-mora date. The test was trustworthy before and after the spec-text fix; only the spec illustrative doc text needed correcting.

## fecha_fin Clamping -- Implementation and Test Check

Confirmed in code: CarteraVencidaResponse.fecha_fin is populated as fin_efectivo = min(fecha_fin, hoy_bogota()) (reportes.py L441, L500), not the raw resolver_ventana output. Both future-window tests explicitly assert the clamped value (fecha_fin equals 2026-09-23), which independently proves the response really returns the clamped date rather than the raw requested fecha_hasta.

Doc-clarity note (non-blocking, does not affect verdict): this clamping behavior is stated in design.md Interfaces contract inline comment and now also in the model own docstring in reportes.py, but the spec THEN-clauses for the two future-window scenarios describe the cartera contents being empty/clamped without explicitly stating that the response fecha_fin field itself reflects the clamp. SUGGESTION: a future sdd-spec pass could add one line to those two scenarios THEN-clauses making this explicit, for readers who only consult spec.md.


## Deviation 1 Algebraic Soundness Check (no explicit future-window branch)

Independently verified fecha_limite_mora (momentos.py L146-187) is monotonic non-decreasing in its input hoy: it maps hoy to the start-date of the momento (m1..m5) window containing hoy, and momento boundaries partition the calendar into a non-decreasing sequence of step intervals with no overlap or reordering (confirmed by reading the day-threshold branches: 1-4 goes to prior month m2 start, 5-13 to m3 start, 14-18 to m4 start, 19-24 to m5 start, 25-29 to m1 start, 30+ to m2 start -- each branch output date increases or stays flat as hoy increases within/across months).

Given monotonicity: if fecha_inicio is greater than fin_efectivo (window entirely in the future after the D5 clamp), then fecha_inicio minus 1 is greater than or equal to fin_efectivo, so fecha_limite_mora(fecha_inicio minus 1) is greater than or equal to fecha_limite_mora(fin_efectivo), meaning lo is greater than or equal to hi in bounds_entrada_mora output. The SQL predicate fecha_maxima >= lo AND fecha_maxima < hi is then unsatisfiable for any date, producing a naturally empty result set -- no special-case branch is needed. Confirmed algebraically sound, not just trusted from the apply agent claim.

## AGENTS.md Convention Check

- SQLAlchemy 2.x async: await db.execute(query) on an AsyncSession, consistent with the rest of the codebase.
- Decimal for money: confirmed -- total_capital/total_intereses/per-gestor capital/intereses accumulate as Decimal; float() conversion happens only inside the CarteraVencidaGestor/CarteraVencidaResponse construction calls (reportes.py L489-491, L505-507), matching D7 and the AGENTS.md rule.
- Single query, no N+1: confirmed -- one select(Pago, Gestor) with joins to Credito, Cliente, and outerjoin to Gestor, all guards in the WHERE clause; per-gestor aggregation happens in-memory over the single result set, not via per-row queries.
- Soft delete: Pago.deleted_at is None guard present.
- No audit_service concern -- read-only endpoint.
- No password/password_hash logging -- not applicable.

## Scope Leakage Check

    git diff feat/reportes-rango-fechas..feat/reportes-cartera-vencida --stat
     backend/app/routers/reportes.py                    | 127 +++++-
     backend/tests/conftest.py                          |   1 +
     backend/tests/test_reportes_cartera_vencida.py     | 437 +++++++++++++++++++++
     openspec/changes/.../tasks.md                      |  18 +-
     4 files changed, 573 insertions(+), 10 deletions(-)

Exactly the 4 expected files (3 backend + tasks.md checkbox flips). No frontend files touched. Confirms no Phase 3 leakage.

## Issues

CRITICAL: None.
WARNING: None blocking. (Carried forward from PR1: 1 WARNING on TestBoundsEntradaMora documentation-vs-literal-design-text deviation -- unaffected by PR2, still non-blocking.)
SUGGESTION: 1 -- spec.md future-window scenarios could explicitly state in their THEN-clauses that the response fecha_fin field itself is clamped (currently only in design.md and code docstrings), for readers who only consult spec.md. Non-blocking.

Fixed during this verify pass: spec.md date-arithmetic typo (2026-09-15 to 2026-09-14) in the Deferred payment disappears from a past window on re-query scenario, confirmed via independent hand-computation of the canonical fecha_entrada_mora chain. Test file already used the correct value and required no change.

## Verdict

PASS WITH WARNINGS (0 new CRITICAL, 0 new blocking WARNING, 1 non-blocking SUGGESTION, plus 1 pre-existing non-blocking WARNING carried from PR1). PR2 (tasks 2.1-2.9) is complete, correctly scoped, spec-compliant (after the spec-text date fix applied in this pass), and independently verified with passing runtime evidence (658/658 backend tests, 13/13 new cartera-vencida tests). Decimal/async/single-query/soft-delete AGENTS.md conventions all confirmed. No Phase 3 (frontend) scope leakage. Safe to push feat/reportes-cartera-vencida and open a stacked PR2 (base = feat/reportes-rango-fechas).
