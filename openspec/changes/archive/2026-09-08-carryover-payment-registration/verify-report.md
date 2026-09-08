# Verification Report -- carryover-payment-registration (PR 1)

## SECOND PASS (post-remediation) -- 2026-09-06

**Change**: carryover-payment-registration
**Branch**: fix/pago-arrastre-cuota-fija (12 commits ahead of main@ae2d774, not pushed, no PR)
**Mode**: Full artifact set (proposal/spec/design/tasks/apply-progress) -- Strict TDD backend, standard frontend.

### History
- First pass (preserved verbatim below): FAIL -- 1 CRITICAL, 2 WARNING, 3 SUGGESTION.
- Remediation batch: 5 new commits (2 new tests, 1 spec-wording amendment, 2 suggestion fixes, 1 apply-progress update). Zero production code touched.
- Second pass (this section): all 6 findings independently re-verified, all CLOSED. One new minor SUGGESTION (tasks.md not updated for the remediation batch).

### Command evidence (independently re-run)

| Command | Result |
|---|---|
| cd backend + venv/Scripts/python.exe -m pytest -q | 246 passed, 0 failed (exit 0) -- matches claim exactly (was 244) |
| cd frontend + npx tsc --noEmit | clean, exit 0 |
| git diff main...HEAD --stat -- backend/app frontend | pagos.py + credito_service.py only, 187 insertions(+), 12 deletions(-) -- byte-identical to pre-remediation PR1 diff |
| Scoped -k "arrastre or backfill or reportes" | 23 passed, 223 deselected, no RuntimeWarning |

Note: pytest must be invoked with cwd=backend/ -- a stray untracked test_all.py at repo root causes an INTERNALERROR when pytest runs from the repo root (pre-existing repo-root noise, unrelated to this change).

### Claim-by-claim verification (adversarial)

1. CRITICAL closed -- reportes test: CONFIRMED genuine. test_totales_suben_tras_correccion_de_arrastre calls the real GET /api/v1/reportes endpoint (admin-gated, real ASGI transport, real DB). Independently inspected backend/app/routers/reportes.py:91-92 -- pending totals are computed from capital_a_pagar - capital_pagado / interes_a_pagar - interes_pagado per row filtered by fecha_maxima within the requested periodo. Test seeds a pending row at base (100/20), asserts totals equal base, mutates the row to arrastre-inclusive (150/30), re-queries, asserts totals rise by EXACTLY 50.00/10.00, no clamping. Real integration test, not tautological.
2. WARNING 1 closed -- excedente test: CONFIRMED genuine. TestExcedenteConArrastre::test_pago_supera_base_mas_arrastre_via_confirmar_excedente performs the real 2-step flow (registrar_pago then confirmar_excedente), asserts exact Decimal saldo reduction (850 to 650 capital, 0.00 interest) and next-cuota reset to base (100/20/120). Docstring corrected and verified true: TestExcedenteConArrastre is the only class in the file calling confirmar_excedente.
3. WARNING 2 closed -- spec amendment: CONFIRMED honest, not a quiet relaxation. Traced _pago_parcial (pago_service.py:202-269): it sets pago.pagado = True unconditionally (even for partial payments) and immediately persists a new successor row with capital_pagado=interes_pagado=0.00. There is no state in this codebase where an "unpaid blocking cuota" carries partial-payment progress -- a partial payment always finalizes the current row and rolls forward atomically. This independently confirms the amended Requirement 4: the projector can never observe a nonzero prior payment on the blocking row, so pending arrastre is always visible on the real persisted blocking row, never on a virtual successor. _calcular_virtuales's inline comment (pagos.py:372-393) corroborates this exactly. The spec wording was corrected to match a real structural constraint, not softened to dodge a shortcut.
4. Suggestions -- all 3 confirmed applied: (a) saldo_intereses now asserted for both credits in the backfill out-of-scope test; (b) make_db() returns AsyncMock(spec=AsyncSession), RuntimeWarning confirmed gone in full-suite and scoped runs; (c) misleading docstring corrected.
5. 246 passed, 0 failed -- confirmed exactly (was 244; +2 new test functions).
6. backend/app diff byte-identical -- CONFIRMED via independent git diff main...HEAD --stat. Only pagos.py and credito_service.py changed, 187(+)/12(-), unchanged from pre-remediation. Zero production code moved during the tests-and-docs batch.

### Guardrail re-check
- _validar_split and TOL = Decimal("0.01") in pago_service.py: file has ZERO diff vs main.
- No Alembic diff.
- No float( introduced in the backend/app diff.
- Frontend diff: empty. npx tsc --noEmit clean.

### Spec scenario compliance matrix (16 scenarios, spec as amended)

| # | Requirement / Scenario | Covering test | Status |
|---|---|---|---|
| 1 | Purely capital shortfall | test_falta_capital_pura + test_distribuye_al_componente_correcto | PASS |
| 2 | Purely interest shortfall | test_falta_interes_pura | PASS |
| 3 | Mixed shortfall | test_falta_mixta | PASS |
| 4 | Zero arrastre regression guard | test_total_cero_retorna_cero_cero + test_regresion_arrastre_cero_componentes_iguales_a_base | PASS |
| 5 | Chained partials, no double counting (3-step) | test_cadena_sin_doble_conteo | PASS |
| 6 | Component Sum Invariant | asserted across nearly every new test | PASS |
| 7 | Exact payment of base+arrastre | test_pago_exacto_base_mas_arrastre_no_lanza_error + chain step 3 | PASS |
| 8 | Payment below base | chain steps 1-2 | PASS |
| 9 | Payment between base and base+arrastre | chain step 2 | PASS |
| 10 | Payment above base plus arrastre (excedente) | test_pago_supera_base_mas_arrastre_via_confirmar_excedente | PASS (was UNCOVERED) |
| 11 | Non-arrastre overpayment still rejected | test_sobrepago_de_componente_sin_arrastre_sigue_siendo_rechazado | PASS |
| 12 | Projection matches generation (as amended) | test_sucesor_virtual_muestra_base_y_suma_exacta | PASS -- wording independently re-confirmed by code trace |
| 13 | Backfill: qualifying row corrected | test_fila_calificada_es_corregida | PASS |
| 14 | Backfill: idempotent re-run | test_segunda_corrida_es_idempotente | PASS |
| 15 | Backfill: out-of-scope rows untouched | test_fila_sin_cuota_previa_pagada_es_omitida + test_pagos_registrados_abono_capital_y_saldos_no_se_tocan | PASS |
| 16 | Reported pending totals rise after correction | test_totales_suben_tras_correccion_de_arrastre | PASS (was UNCOVERED, CRITICAL) |

16/16 scenarios PASS with a runtime-verified covering test. Zero UNCOVERED.

### tasks.md checkbox check
Phases 1-7 all [x], Phase 8 correctly [ ] (deferred to PR 2). Checkboxes match the diff exactly for the original PR1 scope. NOTE: tasks.md was not updated with new checkbox rows for the remediation batch. Non-blocking.

### Findings (second pass)

CRITICAL: 0
WARNING: 0
SUGGESTION (1 new)
1. tasks.md was not updated with checkbox rows for the remediation batch (2 new tests, spec amendment, 2 suggestion fixes). All work is real and verified, just not reflected in the task list. Recommend a "Remediation" mini-phase before archive; non-blocking.

### Verdict: PASS

All 16/16 spec scenarios now have a runtime-verified passing covering test. All guardrails (_validar_split, TOL, unchanged signatures, no Alembic migration, no float introduced, zero frontend diff) remain intact and independently re-confirmed. The spec Requirement 4 amendment was adversarially checked against the actual _pago_parcial / _calcular_virtuales code and found to be an honest correction of testable reality, not a relaxation. 246 passed, 0 failed; frontend type-check clean. This change is ready to open a PR and merge (PR 1 scope only -- Phase 8 backfill-endpoint deletion remains correctly deferred to PR 2, post-deploy).

---

## FIRST PASS (original) -- preserved for history


**Change**: carryover-payment-registration
**Branch**: fix/pago-arrastre-cuota-fija (6 commits ahead of main@ae2d774, not pushed)
**Mode**: Full artifact set (proposal/spec/design/tasks/apply-progress) -- Strict TDD backend, standard frontend.

## Command evidence (independently re-run, not taken from apply report)

| Command | Result |
|---|---|
| `backend/venv/Scripts/python.exe -m pytest` | 244 passed, 0 failed (exit 0) -- matches claim exactly |
| `cd frontend && npx tsc --noEmit` | clean, exit 0 |
| `git status --porcelain` (repo) | frontend/ untouched; only unrelated pre-existing untracked noise |
| `git diff main...HEAD --stat -- backend/app frontend` | backend/app/routers/pagos.py, backend/app/services/credito_service.py only -- 187 insertions(+), 12 deletions(-) combined. Matches claim exactly. |

## Task completeness

Phases 1-7 all [x] in tasks.md, matches diff content exactly. Phase 8 correctly left [ ] and out of scope for PR 1.

## Spec scenario compliance matrix (16 scenarios)

| # | Requirement / Scenario | Covering test | Status |
|---|---|---|---|
| 1 | Purely capital shortfall | test_falta_capital_pura + test_distribuye_al_componente_correcto | PASS |
| 2 | Purely interest shortfall | test_falta_interes_pura | PASS |
| 3 | Mixed shortfall | test_falta_mixta | PASS |
| 4 | Zero arrastre regression guard | test_total_cero_retorna_cero_cero + test_regresion_arrastre_cero_componentes_iguales_a_base | PASS |
| 5 | Chained partials, no double counting (3-step) | test_cadena_sin_doble_conteo (real PagoService.registrar_pago, unmocked generar_siguiente_cuota) | PASS -- strongest test in the suite |
| 6 | Component Sum Invariant | Asserted in nearly every new test (cap+int==monto) | PASS |
| 7 | Exact payment of base+arrastre | test_pago_exacto_base_mas_arrastre_no_lanza_error + chain step 3 | PASS |
| 8 | Payment below base | Implicit via chain steps 1-2, unchanged pre-existing _pago_parcial flow | PASS (adequate) |
| 9 | Payment between base and base+arrastre | Chain step 2 | PASS |
| 10 | Payment above base plus arrastre (excedente) | NONE -- docstring claims confirmar_excedente is exercised but it is never called | UNCOVERED -- WARNING |
| 11 | Non-arrastre overpayment still rejected | test_sobrepago_de_componente_sin_arrastre_sigue_siendo_rechazado | PASS |
| 12 | Projection matches generation | test_sucesor_virtual_muestra_base_y_suma_exacta | PASS but with a spec-wording deviation -- see finding below |
| 13 | Backfill: qualifying row corrected | test_fila_calificada_es_corregida | PASS |
| 14 | Backfill: idempotent re-run | test_segunda_corrida_es_idempotente | PASS |
| 15 | Backfill: out-of-scope rows untouched | test_fila_sin_cuota_previa_pagada_es_omitida + test_pagos_registrados_abono_capital_y_saldos_no_se_tocan | PASS (minor gap: saldo_intereses not asserted) |
| 16 | Reported pending totals rise after correction | NONE FOUND -- no test touches backend/app/routers/reportes.py | UNCOVERED -- CRITICAL |

## Critical claims verified by direct inspection

1. Unmocked claim -- CONFIRMED TRUE. Grep across all 4 new/modified test files for generar_siguiente_cuota/patch/monkeypatch shows zero mocking in the new files; the 9 pre-existing mocked tests in test_pago_service.py are untouched and still mock it.
2. Residual invariant -- CONFIRMED. desglosar_arrastre computes arr_int = total - arr_cap (residual, never independent subtraction), all Decimal, ROUND_HALF_UP, quantized to 0.01.
3. Chained-partial arithmetic -- CONFIRMED by test_cadena_sin_doble_conteo, real 3-step 120->180->200 chain through PagoService.registrar_pago, zero mocking of generation, matches design table exactly.
4. Guardrail intact -- CONFIRMED. git diff for pago_service.py is empty -- _validar_split and TOL = Decimal("0.01") byte-for-byte unchanged. test_sobrepago_de_componente_sin_arrastre_sigue_siendo_rechazado proves non-arrastre overpayment still raises ValueError.
5. Untouched surfaces -- CONFIRMED. generar_siguiente_cuota public signature unchanged; _siguiente_cuota_abono_capital has zero diff; no Alembic diff; frontend diff empty.
6. Backfill endpoint -- CONFIRMED. require_role("admin") guard present; predicate is self-terminating (idempotent by construction); rows with no prior paid cuota skipped+reported; never writes monto_a_pagar/capital_pagado/interes_pagado/Credito fields.
7. recalcular_cuota_actual_si_no_pagada -- CONFIRMED now re-derives and preserves pending arrastre instead of overwriting with base values.
8. No float in the diff -- CONFIRMED. Note: backend/app/routers/reportes.py uses float(...) for pending totals but is pre-existing/untouched -- and it is exactly the file Requirement 6 depends on, remaining untested by this change.
9. Zero-arrastre regression -- CONFIRMED unchanged via dedicated test.

## Test-infrastructure workaround judgment

- db=AsyncMock() + manual pago.id assignment: does NOT weaken assertions -- generar_siguiente_cuota performs no DB I/O, db.add() is captured via call_args_list, id assignment only enables PagoResponse round-trip.
- AsyncSession.refresh() workaround: legitimate -- endpoint and test share the same db_session fixture, asserting on the identity-mapped object is a correct verification, not a bypass.
- RuntimeWarning on unawaited AsyncMock coroutine: pre-existing artifact of db=AsyncMock(), cosmetic only.
- No tautological assertions found in any new test file.

## Findings

CRITICAL (1)
1. Requirement "Reported Pending Totals Reflect True Amounts" / Scenario "Totals rise after correction" has zero covering test. No test touches backend/app/routers/reportes.py. Code inspection suggests the fix is correct by construction, but per strict-TDD rules an untested required scenario is CRITICAL.

WARNING (2)
1. Requirement 4 scenario says the first projected row shows arrastre-inclusive values, but the implemented/tested behavior shows BASE values for the virtual successor. design.md has a reasoned justification (arrastre always lives in a real, already-persisted blocking row), plausible but not literally matching spec wording.
2. Requirement 3 scenario "Payment above base plus arrastre" (excedente) has no dedicated new test; module docstring inaccurately claims confirmar_excedente is exercised.

SUGGESTION (3)
1. Backfill out-of-scope test asserts saldo_capital unchanged but not saldo_intereses.
2. Fix the misleading confirmar_excedente docstring claim.
3. Consider AsyncMock(spec=AsyncSession) to eliminate cosmetic RuntimeWarning.

## Verdict: FAIL (blocked by 1 CRITICAL untested spec scenario)

Everything tested passes correctly; the deepest/most important claims (unmocked chained generation, exact residual invariant, unchanged guardrail, unchanged signatures, no migration, no float, no frontend diff) all hold up to direct inspection. The block is narrow: Requirement 6's scenario has no runtime-verified test. Recommend adding one focused integration test against reportes.py's pending-totals endpoint, optionally closing WARNING #2, then re-run verify.
