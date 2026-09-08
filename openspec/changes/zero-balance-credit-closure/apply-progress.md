# Apply Progress: Zero-Balance Credit Closure

## Batch 1 — PR 1: Settled Predicate + Interest-only Tail

**Branch**: `feature/zero-balance-credit-closure-pr1` (off `main`, per `stacked-to-main`)
**Mode**: Strict TDD
**Status**: All Phase 1 tasks (1.1–1.12) complete. PR 1 scope closed.

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

### Work Unit Evidence (PR 1)

| Evidence | Value |
|---|---|
| Focused test command and result | `python -m pytest tests/test_credito_service.py tests/test_credito_service_arrastre.py tests/test_creditos_actualizar.py -q` → 51 passed. `python -m pytest tests/test_pago_service.py -q` → 37 passed |
| Runtime harness command/scenario and result | Unmocked `db_session` integration tests (`TestGenerarSiguienteCuotaTailTermination`, `TestRecalcularCuotaActualSoloInteres`) exercise the real aiosqlite path through `generar_siguiente_cuota` / `recalcular_cuota_actual_si_no_pagada` without patching — all passing |
| Rollback boundary | Revert commits `ef6e569` (credito_service.py + tests) and `7b4529a` (pago_service.py + test); no payment-closure wiring (`_verificar_cierre_credito`, `cerrar_credito`) touched — PR 2 unaffected |

### Full Suite Result (PR 1)

`cd backend && python -m pytest -q` → **257 passed, 0 failed** (baseline was 241 actual passing at session start, not 246 as pre-stated in the launch prompt — discrepancy noted, not investigated further since it predates this batch and both counts show 0 failing).

### Files Changed (PR 1)

| File | Action | What Was Done |
|---|---|---|
| `backend/app/services/credito_service.py` | Modified | Added `esta_saldado`, `_siguiente_cuota_fija_solo_interes`; changed `generar_siguiente_cuota` guard; unified `es_ultimo_pago` formula in `_siguiente_cuota_fija` and `recalcular_cuota_actual_si_no_pagada` |
| `backend/tests/test_credito_service.py` | Modified | Added `TestEstaSaldado`, `TestInteresOnlyTail`, `TestGenerarSiguienteCuotaTailTermination`, `TestEsUltimoPagoTail`, `TestRecalcularCuotaActualSoloInteres` |
| `backend/app/services/pago_service.py` | Modified | Rule-13 Spanish explanatory message in `_validar_split` when `capital_a_pagar <= 0` |
| `backend/tests/test_pago_service.py` | Modified | Added 2 tests to `TestValidarSplit` |
| `openspec/changes/zero-balance-credit-closure/tasks.md` | Modified | Marked tasks 1.1–1.12 `[x]` |

### Deviations from Design (PR 1)

None — implementation matches design.

### Issues Found (PR 1)

None blocking. Note (non-blocking): baseline test count at session start was 241, not the 246 stated in the launch prompt — pre-existing, unrelated to this batch.

### Workload / PR Boundary (PR 1)

- Mode: stacked-to-main, 3-deep chain (rule 12)
- Current work unit: PR 1 — Settled Predicate + Interest-only Tail
- Boundary: starts from `main`, ends with `es_ultimo_pago`/`recalcular_cuota_actual_si_no_pagada` interest-only support. Touches no read path, no admin path, no closure wiring.
- **Estimated review budget impact: forecast was ~230 (tasks.md) / ~370 (design.md, incl. tests). Actual authored diff is 461 lines, which is ABOVE the 400-line budget** — flagged as a risk, no task descoped.

---

## Batch 2 — PR 2: Single Writer + Closure Wiring (this batch)

**Branch**: `feature/zero-balance-credit-closure-pr2` (off `feature/zero-balance-credit-closure-pr1`, per `stacked-to-main`)
**Mode**: Strict TDD
**Status**: All Phase 2 tasks (2.1–2.11) complete. PR 2 scope closed. PR 3 NOT started.

### TDD Cycle Evidence

| Task | RED (failed for right reason) | GREEN (implementation) | REFACTOR |
|---|---|---|---|
| 2.1 | `ImportError: cannot import name 'cerrar_credito'` collecting `test_pago_service.py::TestCerrarCredito` | Added `cerrar_credito(credito)` to `credito_service.py` — idempotent, writes only `activo` | n/a |
| 2.2 | (paired with 2.1) | same | n/a |
| 2.3 | `AssertionError: assert Decimal('0.00') == Decimal('5000.00')` — old `_verificar_cierre_credito` forced `saldo_capital = 0.00` on reaching `numero_cuota == numero_cuotas`, even with real capital (`5000.00`) remaining | Deleted `_verificar_cierre_credito`; wired `if esta_saldado(credito): cerrar_credito(credito)` into `_pago_exacto` (test uses real, unmocked `generar_siguiente_cuota`) | n/a |
| 2.4 | (paired with 2.3 for `_pago_exacto`; wiring for `_pago_parcial`/`confirmar_excedente`/`registrar_pago_no_programado` verified by 2.6–2.9 below) | Same commit: wired `_pago_parcial`, `confirmar_excedente`; `registrar_pago_no_programado` early-return keyed on `esta_saldado`, not `cerrar_credito`'s boolean (per design's explicit call-out) | n/a |
| 2.5 | N/A — regression lock, ran unmodified `test_cierre_al_llegar_saldo_cero` after 2.4's GREEN: still 1 passed | n/a (no implementation change needed) | n/a |
| 2.6 | Gap-filling coverage, not new behavior — `_pago_parcial`/`confirmar_excedente` closure-on-settled already worked identically under the old `_verificar_cierre_credito` (it also checked `saldo_capital <= 0` unconditionally for all three call sites); tests added to close the "no prior coverage" gap named in the task, both pass immediately against the already-wired 2.4 implementation, unmocked | n/a (behavior pre-existing and correct; only coverage was missing) | n/a |
| 2.7 | Same class as 2.6 for the settle-closes case (gap-filling). The SECOND test in this task (`test_pago_no_programado_cuota_fija_capital_saldado_interes_pendiente_no_cierra`) proves genuinely NEW behavior: old code's `if credito.saldo_capital <= 0` would have incorrectly closed a `cuota_fija` credit with `saldo_intereses=2000` still outstanding; new `esta_saldado`-keyed check correctly keeps `activo=True` | Verified against current (already-wired) implementation — both pass | n/a |
| 2.8 | Gap-filling: proves the under-paid-final-installment case no longer forces `saldo_capital=0.00` (the debt-forgiveness bug this whole initiative removes) — passes against 2.4's implementation, unmocked | n/a | n/a |
| 2.9 | Gap-filling: `abono_capital` had zero closure-test coverage before this batch — added, passes against 2.4's implementation, unmocked | n/a | n/a |
| 2.10 | Gap-filling, explicitly pre-existing behavior per task wording ("not new logic") — `_aplicar_reduccion_saldos` ROUND_HALF_UP quantize on `saldo_intereses`, locked with a dedicated multi-decimal test | n/a | n/a |
| 2.11 | n/a (verify task) | `cd backend && python -m pytest -q` — 266 passed, 0 failed | n/a |

**Note on RED discipline for 2.6–2.10**: tasks 2.1–2.4 are genuine new-behavior RED→GREEN cycles (`cerrar_credito` didn't exist; the debt-forgiveness branch existed and had to be proven wrong before deletion). Tasks 2.6, 2.8, 2.9, 2.10 are gap-filling coverage for behavior that was already correct after 2.4's wiring (the task descriptions themselves say "no prior coverage" / "pre-existing behavior being locked, not new logic") — consistent with the strict-TDD module's characterization/approval-testing allowance for already-correct code. Task 2.7's second test is the one gap-filling task that also proves a genuine regression fix (the `esta_saldado` vs. `saldo_capital<=0` distinction for the unscheduled-payment path).

### Work Unit Evidence (PR 2)

| Evidence | Value |
|---|---|
| Focused test command and result | `cd backend && python -m pytest tests/test_pago_service.py -q` → 46 passed (37 baseline + 9 new) |
| Runtime harness command/scenario and result | Unmocked `generar_siguiente_cuota` exercised through `_pago_exacto`/`_pago_parcial`/`confirmar_excedente` in tasks 2.3, 2.6, 2.8 (no `patch("app.services.pago_service.generar_siguiente_cuota", ...)`); `registrar_pago_no_programado`'s real closure/recalculation branch exercised in 2.7 and 2.9 via `AsyncMock(spec=AsyncSession)` with a call-counting `db.execute` side effect (DB itself not queried by `generar_siguiente_cuota`, so no real aiosqlite session was needed for this file's existing test style — consistent with the pre-existing pattern in `test_pago_service.py`) |
| Rollback boundary | Revert commit `364b93c` (`pago_service.py` + `credito_service.py` + `test_pago_service.py`); PR 1's commits (`ef6e569`, `7b4529a`) are untouched and remain intact underneath |

### Full Suite Result (PR 2)

`cd backend && python -m pytest -q` → **266 passed, 0 failed** (up from PR 1's verified 257; +9 new tests, all in `test_pago_service.py`).

### Files Changed (PR 2)

| File | Action | What Was Done |
|---|---|---|
| `backend/app/services/credito_service.py` | Modified | Added `cerrar_credito(credito)` — sole writer of `activo=False`, never touches either balance, idempotent (+18 lines) |
| `backend/app/services/pago_service.py` | Modified | Deleted `_verificar_cierre_credito` (28 lines, incl. its debt-forgiveness `saldo_capital = Decimal("0.00")`); wired `esta_saldado`/`cerrar_credito` into `_pago_exacto`, `_pago_parcial`, `confirmar_excedente`; `registrar_pago_no_programado` early-return re-keyed to `esta_saldado` (net -2 lines) |
| `backend/tests/test_pago_service.py` | Modified | Added `TestCerrarCredito` (2 tests); rewrote `test_cierre_al_alcanzar_ultima_cuota` → `test_ultima_cuota_pagada_con_capital_pendiente_no_cierra`; added `TestCierreEnTodasLasRutas` (7 tests: parcial-cierra, excedente-cierra, no-programado-cierra, no-programado-cuota-fija-no-cierra-prematuro, cuota-final-subpagada-no-condona, abono-capital-cierra, interes-redondeo) (+274 net lines) |
| `openspec/changes/zero-balance-credit-closure/tasks.md` | Modified | Marked tasks 2.1–2.11 `[x]` |

### Deviations from Design (PR 2)

None. `cerrar_credito` matches the design's canonical primitive exactly (idempotent, balance-untouched). The `esta_saldado`-keyed early return in `registrar_pago_no_programado` follows the design's explicit call-out verbatim, including the reasoning about why the boolean return value would be wrong. `_verificar_cierre_credito` deletion matches the design's call-site replacement table exactly (`_pago_exacto`, `_pago_parcial`, `confirmar_excedente` → `if esta_saldado(credito): cerrar_credito(credito)`).

### Issues Found (PR 2)

None blocking. Pre-existing `RuntimeWarning: coroutine 'AsyncMockMixin._execute_mock_call' was never awaited` on `db.add(nueva_cuota)` in two tests — this is an artifact of `AsyncMock()` treating `db.add` (a sync SQLAlchemy method) as async; it predates this batch's changes (same pattern already present in `test_pago_exacto_reduce_saldo_capital` etc.) and does not affect assertion correctness. Not fixed — out of scope, would require changing the shared `db = AsyncMock()` fixture pattern across the whole file.

### Workload / PR Boundary (PR 2)

- Mode: stacked-to-main, 3-deep chain (rule 12)
- Current work unit: PR 2 — Single Writer + Closure Wiring
- Boundary: starts from PR 1's tip (`21da29b`), ends with the four closure call sites wired through `esta_saldado`/`cerrar_credito` and `_verificar_cierre_credito` deleted. Touches no read path (`credito_operativamente_abierto`, `resumen-cartera`, `GET /pagos` filters), no admin/confirm/backfill endpoint, no frontend — those are PR 3.
- **Estimated review budget impact: forecast was ~230 (tasks.md) / ~200 (design.md, PR 2 slice). Actual authored diff is 394 lines (18 credito_service.py + 52 pago_service.py [net, but see below] + 324 test_pago_service.py = 344 insertions + 50 deletions), which is UNDER the 400-line budget** (394/400). Driver of the size: 9 new/rewritten tests across 3 gap-filling closure paths plus the `cerrar_credito` primitive tests, each requiring its own credit/pago fixture per the "no shared mutable fixture across un-related scenarios" style already used in this file. No task was skipped or descoped.

### Remaining Tasks

- [ ] Phase 3 (PR 3 → this branch, `feature/zero-balance-credit-closure-pr2`): Read Paths, Confirmation, Backfill, Frontend (tasks 3.1–3.15)
- [ ] Phase 4 (post-deploy follow-up): run + remove backfill endpoint (tasks 4.1–4.2)

### Status

23/26 tasks complete (Phases 1 and 2 fully done). Ready for `sdd-verify` on PR 2, then `sdd-apply` again for Phase 3.
