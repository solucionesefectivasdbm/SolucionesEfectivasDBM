# Apply Progress: abono_capital Carry-over Fix — PR-1

## Scope of this run

PR-1 only: tasks.md Phases 1-6 (carry helper + prior-row query, walk-back
generation, payment acceptance, recalculation preserves arrastre, projector
parity & invariant, PR-1 close-out). Phases 7-9 (backfill endpoint, rollout,
cleanup) are explicitly out of scope for this run.

## Mode

Strict TDD. Test runner: `backend/venv/Scripts/python.exe -m pytest` (repo
root, `backend/tests`, `asyncio_mode=auto`).

## Completed Tasks

- [x] 1.1-1.4 — `arrastre_interes_abono_capital` + `_ultima_cuota_interes_pagada`
- [x] 2.1-2.6 — walk-back wiring in `generar_siguiente_cuota` + three branches of `_siguiente_cuota_abono_capital` + mensual chain confirmation
- [x] 3.1-3.2 — `_pago_parcial` (pago_service.py) now calls the helper
- [x] 4.1-4.2 — `recalcular_cuota_actual_si_no_pagada` abono_capital branch (mensual + alternating interés) preserves arrastre
- [x] 5.1-5.3 — projector companion test (abono_capital), confirmed `_calcular_virtuales` byte-identical, invariant asserted across all new/modified branches
- [x] 6.2 — full suite green (357 passed)
- [ ] 6.1, 6.3 — operational (notify collectors) and deploy — out of scope for sdd-apply, left for orchestrator/owner

## TDD Cycle Evidence

| Task | RED (failed for right reason) | GREEN | REFACTOR |
|---|---|---|---|
| 1.1/1.2 `arrastre_interes_abono_capital` | ImportError on missing symbols, then 4 assertion tests written before impl | 11/11 pass after adding helper | n/a |
| 1.3/1.4 `_ultima_cuota_interes_pagada` | Same import RED as above; query tests written before impl | pass | n/a |
| 2.1-2.4 walk-back + 3 branches | `test_credito_service_arrastre_abono_capital.py` new tests written before wiring/branch fixes | 11/11 pass | n/a |
| 2.5/2.6 mensual chain | `TestAbonoCapitalMensualArrastreInteres` written first; failed (`45000+20000 != interes_a_pagar` mismatch investigated, expectation corrected to reflect saldo_capital reduction) then confirmed against 2.4's branch | 7/7 pass in file | n/a |
| 3.1/3.2 payment acceptance | RED test added (exact payment); passed immediately because Phase 2's fix already made the row's own components arrastre-inclusive — decision 5 is a pure refactor (documented as same-semantics in design), confirmed no behavior regression after refactor | 7/7 pass in file | Replaced duplicate faltante_interes formula with helper call (net -3 lines) |
| 4.1/4.2 recalculation | 2 of 3 new tests failed for the right reason (base values only, arrastre dropped); abono-type test passed trivially (interest-free by construction) | 3/3 pass after adding walk-back call in both mensual and alternating-interés branches | n/a |
| 5.1-5.3 projector | New fixture + test class asserting virtual successor shows base values; passed on first run — confirms `_calcular_virtuales` needs no change (decision 7) | 21/21 pass in `test_pagos_listado.py` | n/a |

## Work Unit Evidence

| Evidence | Value |
|---|---|
| Focused test command and result | `backend/venv/Scripts/python.exe -m pytest backend/tests/test_credito_service_arrastre_abono_capital.py backend/tests/test_pago_service_arrastre.py backend/tests/test_pagos_listado.py -q` → all pass (25 + 8 + 21) |
| Runtime harness | `PagoService.registrar_pago` chain exercised unmocked via `db_session` (aiosqlite) in `TestGenerarSiguienteCuotaWalkBack` and `TestRecalcularCuotaActualPreservaArrastreAbonoCapital`; HTTP integration via `client_admin_db` AsyncClient in the projector test |
| Full suite | `backend/venv/Scripts/python.exe -m pytest backend/tests -q` → 357 passed |
| Rollback boundary | Revert: `credito_service.py` (new helper/query functions + 3 branch edits + walk-back wiring + recalculo branch), `pago_service.py` lines around `_pago_parcial` (258-261 region), and the 3 test files (1 new, 2 modified) — no schema/migration touched, isolated to these 5 files |

## Files Changed

| File | Action | What Was Done |
|---|---|---|
| `backend/app/services/credito_service.py` | Modified | Added `arrastre_interes_abono_capital`, `_ultima_cuota_interes_pagada`; wired walk-back in `generar_siguiente_cuota`; fixed all 3 branches of `_siguiente_cuota_abono_capital` to fold shortfall into `interes_a_pagar` (mensual + alternating-interés); added abono_capital branch to `recalcular_cuota_actual_si_no_pagada` |
| `backend/app/services/pago_service.py` | Modified | `_pago_parcial` now calls `arrastre_interes_abono_capital(pago)` instead of the duplicated inline formula |
| `backend/tests/test_credito_service_arrastre_abono_capital.py` | Created | Pure helper tests, walk-back query tests, branch-folding tests, walk-back generation tests (db_session), recalculation tests (db_session) |
| `backend/tests/test_pago_service_arrastre.py` | Modified | Added `TestAbonoCapitalMensualArrastreInteres` and `TestAbonoCapitalPagoExactoConArrastre` |
| `backend/tests/test_pagos_listado.py` | Modified | Added abono_capital projector companion fixture + `TestProjectorParityArrastreAbonoCapital` |

## Deviations from Design

None — implementation matches design decisions 1-7 exactly. One correction
made during TDD: the RED expectation in `TestAbonoCapitalMensualArrastreInteres`
initially assumed the next cuota's base interest uses the ORIGINAL
`saldo_capital`; the actual (correct, pre-existing) behavior computes base
interest on the ALREADY-REDUCED `saldo_capital` (post `_aplicar_reduccion_saldos`).
This is expected behavior, not a defect — the test expectation was corrected,
no production code was changed to accommodate it.

## Issues Found

None.

## Budget / Diff Stat

Tracked diff (`git diff --stat`): 4 files, +262/-12 (accumulates modified
files only). Plus 1 new untracked test file
(`test_credito_service_arrastre_abono_capital.py`, 372 lines, all additions).
**Total actual changed lines: ~634**, exceeding the forecast ~300 and the
400-line review budget. Root cause: Requirement coverage for "Prior-Row
Selection Correctness" (4 skip-cases), "Shortfall Survives an Intervening
Abono Cuota" (2 chain scenarios), and "Recalculation Preserves Pending
Arrastre" (3 variants: mensual, alternating-interés, alternating-abono) each
needed dedicated `db_session` integration tests per spec scenario — test code
dominates the diff (production code changes are ~90 lines). Recommend the
orchestrator flag this for `size:exception` or a reviewer note when routing
to review, since the code-only diff is well within budget and trimming
Requirement-mapped tests was judged a higher risk than exceeding the line
count.

## Status

17/19 Phase 1-6 tasks complete (6.1 and 6.3 are operational/deploy actions,
intentionally left for the orchestrator/owner). Ready for `sdd-verify`, or for
the orchestrator to route this diff through `review/start(target)` before PR.
