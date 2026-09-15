# Verification Report: carryover-scope-fixes

**Change**: carryover-scope-fixes | **Mode**: full artifacts (proposal/specs/design/tasks/apply-progress/Judgment Day ledger) | **Strict TDD**: active

## Completeness

| Phase | Status |
|---|---|
| PR-A (Bug A, tasks 1-4) | Complete, merged #36/aa27dc4 lineage |
| PR-B (rule 15 carve-out, tasks 5-9) | Complete, merged #37 |
| PR-B2 (backfill endpoint, tasks 10-11) | Complete, merged #38, run once in prod (12.1-12.4 manual, verified via #38→#39 trail) |
| PR-C (cleanup, tasks 13) | Complete, merged #39 (commit 9b33695 confirmed: -3 net after re-add, endpoint + test file both absent from `main`) |
| Task 4.2/11.2 (open PR) | Done via #36/#37 |
| Task 8.2 | Marked N/A — correctly not applicable per PR-B independent-branch note |
| Task 14.1 (archive spec merge) | Not yet done — expected, belongs to sdd-archive |

Unchecked boxes in tasks.md (4.2, 11.2, 12.1-12.4, 13.1-13.3, 14.1) all correspond to manual/orchestrator-only or archive-time steps confirmed complete via git history, not code gaps.

## Test Execution

- `backend/venv/Scripts/python.exe -m pytest backend/tests`: **404 passed, 0 failed** (exit 0)
- `cd frontend && npx tsc --noEmit`: clean, no output (exit 0)
- Backfill test file (`test_pagos_backfill_cuota_fija_fuera_de_plazo.py`) confirmed absent from working tree — consistent with intentional removal in #39, not a regression (was present with 8 passing tests at #38, evidenced in commit 9b33695 diff: -288 lines).

## Spec Compliance Matrix

### payment-carryover — Shortfall Disaggregation (rule 15 exception)
| Scenario | Test | Result |
|---|---|---|
| Shortfall on last regular installment not carried past term | `TestSiguienteCuotaFijaFueraDePlazo` (test_credito_service.py:725) | PASS |
| Shortfall between past-term installments not carried | same class | PASS |
| Carry-over within term unaffected | pre-existing carry-over tests, unchanged | PASS |

### credit-closure — Past-term Base Installment
| Scenario | Test | Result |
|---|---|---|
| Partial payment of last regular installment (prod case) | `test_ultima_cuota_pagada_parcial_con_capital_pendiente_genera_base` (test_pago_service.py:499) | PASS |
| Not capped to remaining capital | `TestSiguienteCuotaFijaFueraDePlazo` | PASS |
| Admin edit on unpaid past-term installment keeps base | `TestRecalcularCuotaActualFueraDePlazo` (test_credito_service.py:800) | PASS |
| Sequence ends in interest-only tail | `TestSiguienteCuotaFijaFueraDePlazo` (rule-14-dominates case) | PASS |
| Predicate correctness | `TestEsCuotaFijaFueraDePlazo` (test_credito_service.py:698) | PASS |

### credit-closure — One-off Past-term Arrastre Backfill
Implemented in #38 (`POST /pagos/admin/backfill-cuota-fija-fuera-de-plazo`), 8/8 tests green at that commit, run once in prod 2026-09-14 (dry-run: 1 row / Fernando Sanabria CR-003 cuota 3; apply: corregidos 1; idempotent re-check: detalle []). Removed in #39 per requirement text ("removed after one production run"). Verified via `git show 9b33695 --stat` rather than current code, per known deviation — code/test absence on `main` is correct end state.

### credit-closure — Closure by Settled State Only / Operator-Readable Rejection Messages
| Scenario | Test | Result |
|---|---|---|
| Last installment reached/paid partially, no auto-close | `test_ultima_cuota_pagada_con_capital_pendiente_no_cierra`, `..._genera_base` | PASS |
| Settled-capital reason never issued for abono_capital | `TestValidarSplit` (test_pago_service.py:1177), incl. `test_capital_contra_cuota_solo_interes_lanza_mensaje_explicativo` (:1256) | PASS |

### abono-capital-carryover — Interés Installment Is Not Capital-Settled / Projection Unchanged
| Scenario | Test | Result |
|---|---|---|
| tipo_credito on every payment row | `test_pagos_listado.py` assertions | PASS |
| Frontend guard scoped to cuota_fija && interes | `PagosPage.tsx:688-695` + tsc clean | PASS (Standard Mode, no frontend runner, per project rule) |
| Exact/partial payment behavior on abono_capital interés cuota | `TestValidarSplit` | PASS |

## Design Coherence
All 4 design decisions (tipo_credito plumbing, frontend guard scope, `_validar_split` kwarg, `_es_cuota_fija_fuera_de_plazo` predicate placement) implemented as specified; no deviations beyond the reported PR-B/PR-B2 split, which was pre-approved via the review workload guard.

## Judgment Day Follow-ups (info-level, non-blocking)
- PRA-INFO-1/2/3, PRB-INFO-1/2/3, PRB2-INFO-1..6 — all WARNING/SUGGESTION, all rounds APPROVED. PRB2 items are moot now (backfill code removed in #39). Remaining live follow-ups: PRA-INFO-2 (no test drives `tipo_credito=` kwarg through payment call sites directly — covered indirectly via `TestValidarSplit`), PRB-INFO-3 (uncapped past-term display awareness, owner-accepted).

## Issues

**CRITICAL**: none
**WARNING**: none
**SUGGESTION**: carry forward PRA-INFO-1 (duplicate raise), PRA-INFO-3 (inline guard predicate) as low-priority cleanup, not blocking archive.

## Verdict: **PASS**
