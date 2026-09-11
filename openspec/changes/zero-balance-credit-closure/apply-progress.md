# Apply Progress: Zero-Balance Credit Closure

## Batch 1 — PR 1: Settled Predicate + Interest-only Tail (this batch)

**Branch**: `feature/zero-balance-credit-closure-pr1` (off `main`, per `stacked-to-main`)
**Mode**: Strict TDD
**Status**: All Phase 1 tasks (1.1–1.12) complete. PR 1 scope closed. PR 2 and PR 3 NOT started.

### TDD Cycle Evidence

| Task | RED (failed for right reason) | GREEN (implementation) | REFACTOR |
|---|---|---|---|
| 1.1 | `ImportError: cannot import name 'esta_saldado'` collecting `test_credito_service.py` | Added `esta_saldado(credito)` to `credito_service.py` | n/a |
| 1.2 | (paired with 1.1) | same | n/a |
| 1.3 | Would fail identically via same import error before 1.2's GREEN; verified logic separately once `esta_saldado` existed — `_siguiente_cuota_fija` produced normal (capital-bearing) cuota instead of interest-only for `saldo_capital<=0` | Added `_siguiente_cuota_fija_solo_interes` + dispatch in `_siguiente_cuota_fija` | n/a |
| 1.4 | Guard still read `saldo_capital <= 0`; interest-only branch missing | Changed guard to `esta_saldado(credito)`; wired dispatch | n/a |
| 1.5 | Failed via same import/logic gap before GREEN | Verified via unmocked `db_session` + real `generar_siguiente_cuota` call (no `generar_siguiente_cuota` patch) | n/a |
| 1.6 | `AssertionError: assert "solo interés" in "En pago exacto, capital_pagado (100.00) excede capital_a_pagar (0.00) + tolerancia (0.01)"` | Added rule-13 Spanish message branch in `_validar_split` when `capital_a_pagar <= 0` | n/a |
| 1.7 | (paired with 1.6) | same | n/a |
| 1.8 | First attempt: test premise wrong (my own fixture had interest fully settling in that same cuota) — corrected fixture to a historic-under-collection scenario (`saldo_intereses=60000 > interes_a_pagar=30000`), then failed for the right reason (`assert True is False`) before the `es_ultimo_pago` formula existed | Unified `es_ultimo_pago = saldo_capital<=capital_a_pagar and saldo_intereses<=interes_a_pagar` in `_siguiente_cuota_fija` | n/a |
| 1.9 | (paired with 1.8) | same, plus mirrored in `recalcular_cuota_actual_si_no_pagada`'s capital-bearing branch | n/a |
| 1.10 | Import/logic gap — `recalcular_cuota_actual_si_no_pagada` recomputed a normal capital-bearing cuota even when `saldo_capital<=0` | Added interest-only branch (capped, no arrastre) ahead of the capital-bearing branch | n/a |
| 1.11 | (paired with 1.10) | same | n/a |
| 1.12 | n/a (verify task) | `pytest tests/test_credito_service.py` — 51 passed (incl. arrastre + actualizar files run together) | n/a |

### Work Unit Evidence

| Evidence | Value |
|---|---|
| Focused test command and result | `python -m pytest tests/test_credito_service.py tests/test_credito_service_arrastre.py tests/test_creditos_actualizar.py -q` → 51 passed. `python -m pytest tests/test_pago_service.py -q` → 37 passed |
| Runtime harness command/scenario and result | Unmocked `db_session` integration tests (`TestGenerarSiguienteCuotaTailTermination`, `TestRecalcularCuotaActualSoloInteres`) exercise the real aiosqlite path through `generar_siguiente_cuota` / `recalcular_cuota_actual_si_no_pagada` without patching — all passing |
| Rollback boundary | Revert commits `ef6e569` (credito_service.py + tests) and `7b4529a` (pago_service.py + test); no payment-closure wiring (`_verificar_cierre_credito`, `cerrar_credito`) touched — PR 2 unaffected |

### Full Suite Result

`cd backend && python -m pytest -q` → **257 passed, 0 failed** (baseline was 241 actual passing at session start, not 246 as pre-stated in the launch prompt — discrepancy noted, not investigated further since it predates this batch and both counts show 0 failing).

### Files Changed

| File | Action | What Was Done |
|---|---|---|
| `backend/app/services/credito_service.py` | Modified | Added `esta_saldado`, `_siguiente_cuota_fija_solo_interes`; changed `generar_siguiente_cuota` guard; unified `es_ultimo_pago` formula in `_siguiente_cuota_fija` and `recalcular_cuota_actual_si_no_pagada` |
| `backend/tests/test_credito_service.py` | Modified | Added `TestEstaSaldado`, `TestInteresOnlyTail`, `TestGenerarSiguienteCuotaTailTermination`, `TestEsUltimoPagoTail`, `TestRecalcularCuotaActualSoloInteres` |
| `backend/app/services/pago_service.py` | Modified | Rule-13 Spanish explanatory message in `_validar_split` when `capital_a_pagar <= 0` |
| `backend/tests/test_pago_service.py` | Modified | Added 2 tests to `TestValidarSplit` |
| `openspec/changes/zero-balance-credit-closure/tasks.md` | Modified | Marked tasks 1.1–1.12 `[x]` |

### Deviations from Design

None — implementation matches design. `esta_saldado` and the interest-only tail follow the design's canonical primitives and cap semantics exactly. `cerrar_credito` and closure wiring were intentionally NOT touched (PR 2 scope).

### Issues Found

None blocking. Note (non-blocking): baseline test count at session start was 241, not the 246 stated in the launch prompt — pre-existing, unrelated to this batch.

### Workload / PR Boundary

- Mode: stacked-to-main, 3-deep chain (rule 12)
- Current work unit: PR 1 — Settled Predicate + Interest-only Tail
- Boundary: starts from `main`, ends with `es_ultimo_pago`/`recalcular_cuota_actual_si_no_pagada` interest-only support. Touches no read path, no admin path, no closure wiring (`cerrar_credito` does not exist yet — added in PR 2).
- **Estimated review budget impact: forecast was ~230 (tasks.md) / ~370 (design.md, incl. tests). Actual authored diff is 461 lines (+412 credito_service.py + tests, +49 pago_service.py + tests), which is ABOVE the 400-line budget and above both prior forecasts.** Driver: the RED-first strict-TDD test suite for 5 scenario groups (settled predicate, tail generation both branches, tail termination integration, last-installment indicator, admin-edit recalculation) required more fixture/assertion volume than estimated. No task was skipped or descoped to stay under budget — flagging as a risk for the orchestrator rather than silently trimming test coverage.

### Remaining Tasks

- [ ] Phase 2 (PR 2 → this branch): Single Writer + Closure Wiring (tasks 2.1–2.11)
- [ ] Phase 3 (PR 3 → PR 2's branch): Read Paths, Confirmation, Backfill, Frontend (tasks 3.1–3.15)
- [ ] Phase 4 (post-deploy follow-up): run + remove backfill endpoint (tasks 4.1–4.2)

### Status

12/26 tasks complete (Phase 1 fully done). Ready for `sdd-verify` on PR 1, then `sdd-apply` again for Phase 2.
