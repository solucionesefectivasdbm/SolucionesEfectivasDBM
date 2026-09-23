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
