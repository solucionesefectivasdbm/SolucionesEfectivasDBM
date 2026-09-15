```yaml
schema: gentle-ai.verify-result/v1
verdict: pass_with_warnings
blockers: 0
critical_findings: 0
requirements: 9/9
scenarios: 22/26 (pytest 22/22 automatable; 4 [manual] frontend scenarios verified by static code inspection only, no runner)
test_command: backend/venv/Scripts/python.exe -m pytest backend/tests
test_exit_code: 0
test_output_hash: sha256:5bac9b1b214ce361b29a01e0b00c6c09964f433086b108c9ca750235607b48d4
build_command: cd frontend && npx tsc --noEmit
build_exit_code: 0
build_output_hash: sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
```

## Verification Report

**Change**: scheduled-overdue-evaluation
**Mode**: Strict TDD (backend) + Standard (frontend, no runner)

### Completeness
| Metric | Value |
|--------|-------|
| Automatable tasks | 26 |
| Automatable tasks complete | 26/26 |
| Manual QA tasks (7.1-7.4) | 0/4 checked (intentionally, owner-driven) |
| Task 8.3 (open PR) | 0/1 (out of scope for sdd-apply, correctly unchecked) |

### Build & Tests Execution
**Tests**: 441 passed, 0 failed, 0 skipped (`backend/venv/Scripts/python.exe -m pytest backend/tests`)
Note: apply-progress and tasks.md record "581 passed" as of apply time; Judgment Day ronda 1 fix round corrected the record to 441 (the "581" was an inflated count from a stale full-suite run before dedup). 441 is the current, verified count including 12 new tests in `test_mora_momento_cerrado.py` + expansions to `test_momentos.py`.

**Build/Type-check**: Passed — `cd frontend && npx tsc --noEmit` exits 0, zero output.

**Coverage**: not available (pytest-cov not installed) — informational only, not blocking per project config.

### Spec Compliance Matrix (overdue-evaluation)
| Requirement | Scenario | Test | Result |
|---|---|---|---|
| Momento Instance Boundaries | Cross-month m2, Feb non-leap, Feb leap, Dec→Jan | `test_momentos.py::TestFechaLimiteMora` (+ property test, 1096 days 2026-2028) | COMPLIANT |
| Single Overdue Predicate | 8 scenarios (inside/after close, cross-month, Feb, Dec/Jan, far past) | `test_momentos.py::TestEnMora` | COMPLIANT |
| Overdue Fields on Pago Response | Past-due-inside, past-due-closed, due-today, paid/projected | `test_mora_momento_cerrado.py::TestPagoResponseFlagsMora`, `test_pagos_listado.py` | COMPLIANT |
| Overdue Alerts Count Only en_mora | Open-momento excluded, closed-momento included | `test_mora_momento_cerrado.py::TestAlertasVencidosMomentoCerrado` | COMPLIANT |
| Client Status Uses Same Predicate | al día inside momento, en atraso after close (filter/list/detail agree) | `test_mora_momento_cerrado.py::TestClientesAlDiaMomentoCerrado` | COMPLIANT |
| Deferred Payments Evaluated on Current Date | Moves out of mora, closed again | `test_mora_momento_cerrado.py::test_deferred_row_evaluated_on_current_date` | COMPLIANT |
| Partial Payments Not Special-Cased | Partial after close counts in mora | `test_mora_momento_cerrado.py::test_partial_payment_counts_as_unpaid` | COMPLIANT |
| Frontend Never Derives Overdue from Browser Time | Red w/o badge, red+badge, badge=KPI, browser-clock-irrelevant | Static inspection: `PagosPage.tsx` L528-532 uses `p.vencido`/`p.en_mora` only; `isVencido`/`MoraBadge` fully deleted | PARTIAL — code path confirmed, scenarios are `[manual]`, unexecuted |

### Spec Compliance Matrix (payment-deferral-tracking, MODIFIED)
| Requirement | Scenario | Evidence | Result |
|---|---|---|---|
| Row Styling and Badge (deferred, precedence, no browser clock) | 4 scenarios | Static inspection: `PagosPage.tsx` row className — violet only when `!p.vencido`; red wins per precedence; `en_mora` badge and deferral badge independent | PARTIAL — code matches spec, scenarios unexecuted |

**Compliance summary**: 22/22 automatable (`[pytest]`) scenarios compliant and passing. 8/8 `[manual]` frontend scenarios have matching code paths verified by static inspection but zero runtime evidence (no frontend test runner in this project — expected/accepted).

### Correctness (Static Evidence)
| Requirement | Status | Notes |
|---|---|---|
| No leftover naive `fecha_maxima < hoy` at the 4 original SQL sites | Implemented | `clientes.py` (3 sites), `pagos.py:973` use `Pago.fecha_maxima < limite`; only remaining `fecha_maxima < hoy` is inside `flags_mora` (`momentos.py:216`) computing `vencido` by design |
| `flags_mora`/`_pago_row_a_dict` shared helper (post-review fix) | Implemented | `momentos.py:203-218`; `pagos.py` computes `limite` once per request; `creditos.py:600` reuses `flags_mora` |
| `creditos.py` historial_cuotas applies flags | Implemented | L590-612, covered by `TestHistorialCuotasFlagsMora::test_historial_cuotas_flags` |
| `fijar_hoy` fixture pins all 3 routers | Implemented | `conftest.py:60-72` patches `pagos`, `clientes`, and `creditos` `hoy_bogota` (creditos added in the Judgment Day fix round) |
| Frontend fields required, no `new Date()` overdue derivation | Implemented | `types/index.ts` fields required; grep confirms remaining `new Date(` uses are unrelated to mora logic |
| `MoraBadge` / `isVencido` removed | Implemented | zero grep matches across `frontend/src` |

### Coherence (Design)
| Decision | Followed? | Notes |
|---|---|---|
| 1. Predicate from day thresholds, not `get_periodo_momento` | Yes | `fecha_limite_mora` implements threshold table; `get_periodo_momento` untouched (Feb bug tracked as follow-up I2) |
| 2. `fecha_maxima < limite` at all 4 SQL sites | Yes | Confirmed by grep |
| 3. Response fields via `_flags_mora`/`_pago_row_a_dict` | Superseded, not a deviation | Judgment Day fix round promoted the private 3-arg per-file helper to shared public `momentos.flags_mora(fecha_maxima, pagado, hoy, limite)` to fix ledger I4/I1. All scenarios still pass. Recommend amending `design.md` decision 3 at archive time |
| 4. `monkeypatch` fixture, not `freezegun`/`Depends` | Yes, extended | Also patches `app.routers.creditos.hoy_bogota` (added for the new mora-aware endpoint) |
| 5. Frontend styling exact line-level plan | Yes | `isVencido`/`MoraBadge` deleted, fields wired as planned |
| 6. No Dashboard/Header/Clientes logic change | Yes | Only a 1-line copy change in `ClientesPage.tsx` (ledger I6) |

### Issues Found

**CRITICAL**: None.

**WARNING**:
1. Phase 7 (4 manual QA scenarios, both delta specs) has zero runtime evidence — expected for this project, but unverified until the owner executes the checklist.
2. `design.md` decision 3 describes the pre-fix helper shape; actual shipped code is the post-Judgment-Day shared 4-arg helper. Documentation drift only, zero behavioral risk — reconcile at archive.
3. `tasks.md`/apply-progress record "581 passed"; verified current count is 441. Stale bookkeeping from before the Judgment Day fix round dedup, not a regression — correct the record.

**SUGGESTION**:
1. Ledger follow-up I2 (`get_periodo_momento` raises for `GET /pagos?mes=2&momento=m1` in non-leap years) remains open by design, confirmed out of scope. Recommend a dedicated change before February 2027.

### Verdict
**PASS WITH WARNINGS** — All 26 automatable tasks complete, 441/441 backend tests passing, `tsc --noEmit` clean, all 9 spec requirements have passing covering tests for every `[pytest]` scenario, and design decisions are followed (one accepted post-review improvement to decision 3 needs a design.md update at archive). The only gate before archive/PR is the unexecuted Phase 7 manual QA checklist, owner-driven per tasks.md.
