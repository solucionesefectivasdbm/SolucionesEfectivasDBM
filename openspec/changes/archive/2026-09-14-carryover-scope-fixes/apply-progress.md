# Apply Progress: carryover-scope-fixes — PR-A (Bug A, batch 1) + PR-B (Bug B, batch 2)

## PR-A (Bug A) — batch 1 — Strict TDD (backend) + Standard (frontend)
Branch: `fix/abono-capital-interes-input-guard` (not committed by apply agent)

Completed Tasks (Phase 1-4, PR-A only):
- [x] 1.1-1.3 tipo_credito on PagoResponse + SELECT/_pago_row_a_dict/virtual dict
- [x] 2.1-2.4 frontend guard scoped to cuota_fija && interes; tsc clean
- [x] 3.1-3.5 _validar_split tipo_credito kwarg + message branching + 3 call sites
- [x] 4.1 full backend suite green (394 passed)
- [ ] 4.2 Open PR-A — orchestrator/owner-driven, out of scope

Files: `backend/app/schemas/pago.py`, `backend/app/routers/pagos.py`, `backend/app/services/pago_service.py`, `backend/tests/test_pago_service.py`, `backend/tests/test_pagos_listado.py`, `frontend/src/types/index.ts`, `frontend/src/pages/Pagos/PagosPage.tsx`

`git diff --stat`: 7 files, 183 insertions(+), 9 deletions(-)

## PR-B (Bug B + backfill) — batch 2 — Strict TDD
Branch: `fix/cuota-fija-post-plazo-sin-arrastre` (independent off main, does NOT contain PR-A's commits — intentional)

Completed Tasks (Phase 5-11):
- [x] 5.1/5.2 RED/GREEN `_es_cuota_fija_fuera_de_plazo(credito, numero)` pure predicate next to `desglosar_arrastre` in `credito_service.py` — true iff `cuota_fija`, `numero > numero_cuotas`, `saldo_capital > 0`
- [x] 6.1-6.5 RED/GREEN generation carve-out in `_siguiente_cuota_fija`: predicate checked AFTER the `saldo_capital<=0` tail return (rule 14 dominates 15); past-term → base cap+int from `capital_prestado`, arrastre 0, uncapped, `tipo_cuota=programada`
- [x] 7.1/7.2 RED/GREEN same predicate in `recalcular_cuota_actual_si_no_pagada` (cuota_fija branch): past-term skips the walk-back query, uses `arr_cap=arr_int=0`
- [x] 8.1 RED/GREEN partial-payment sibling test in `test_pago_service.py` (`test_ultima_cuota_pagada_parcial_con_capital_pendiente_genera_base`) — passed on first run (implementation already correct from phase 6)
- [ ] 8.2 NOT APPLICABLE this batch: PR-A's `_validar_split` `tipo_credito` kwarg (Phase 3) is not on this branch (independent PRs) — `test_capital_contra_cuota_solo_interes_lanza_mensaje_explicativo` needs no change here; revisit at PR-A/PR-B merge
- [x] 8.3 targeted suite green (`test_credito_service.py` + `test_pago_service.py`: 107 passed)
- [x] 9.1 confirmed `payment-carryover`/`credit-closure` spec deltas match implementation, no edits needed (`abono-capital-carryover` delta is PR-A's, out of scope)
- [x] 10.1-10.3 RED/GREEN `POST /pagos/admin/backfill-cuota-fija-fuera-de-plazo` in `pagos.py`: `require_role("admin")`, `dry_run: bool = Query(True)`, `# TEMPORAL` banner; SQL structural filter (unpaid, zero paid, `programada`, `cuota_fija`, `numero_cuota>numero_cuotas`, `saldo_capital>0`, `activo`); Python filter against `calcular_capital_cuota_fija`/`calcular_interes_cuota_fija` base; writes cap/int/monto/es_ultimo_pago only, saldos untouched; audited via `audit_service.registrar_actualizacion_campos`; response `{dry_run, revisados, corregidos, detalle[]}`. New test file `test_pagos_backfill_cuota_fija_fuera_de_plazo.py` (8 tests, `client_factory` pattern from `test_desvalidar_pago.py`)
- [x] 11.1 full backend suite green (405 passed, 0 failed)
- [ ] 11.2 Open PR-B — orchestrator/owner-driven, out of scope

## Files Changed (PR-B)

| File | Action | What |
|------|--------|------|
| `backend/app/services/credito_service.py` | Modified | `_es_cuota_fija_fuera_de_plazo` predicate + 2 carve-outs |
| `backend/app/routers/pagos.py` | Modified | imports (`TipoCredito`, `calcular_capital_cuota_fija`, `calcular_interes_cuota_fija`, `ROUND_HALF_UP`) + backfill endpoint |
| `backend/tests/test_credito_service.py` | Modified | `TestEsCuotaFijaFueraDePlazo`, `TestSiguienteCuotaFijaFueraDePlazo`, `TestRecalcularCuotaActualFueraDePlazo` (156 lines) |
| `backend/tests/test_pago_service.py` | Modified | partial-payment sibling test (43 lines) |
| `backend/tests/test_pagos_backfill_cuota_fija_fuera_de_plazo.py` | Created | 8 tests, 288 lines |

## Verification

- `backend/venv/Scripts/python.exe -m pytest backend/tests` (scoped, per repo NOTE): 405 passed, 0 failed
- `git diff --stat` (tracked files only): 4 files changed, 372 insertions(+), 27 deletions(-)
- New untracked test file: 288 lines (all additions)
- TOTAL changed lines including new file: ~687 — EXCEEDS the 400-line PR-B budget significantly

## Deviations / Risks

1. **Budget overage**: design.md forecast PR-B at ~330 lines (backfill+tests ~110-210 of those); actual is ~687 (carve-out+tests ~300, backfill endpoint+tests ~414 — the comprehensive 8-case backfill test file drove most of the overage). The carve-out-only portion (Phases 5-8, ~300 lines) was under the 370-line stop threshold when checked, so per instructions implementation continued into the backfill endpoint; the combined total now clearly exceeds 400. RECOMMENDATION: since nothing is committed/staged, the orchestrator should split at commit time into PR-B (`credito_service.py` + its tests, ~300 lines) and PR-B2 (`pagos.py` backfill endpoint + its test file, ~414 lines) — precedent PRs #31/#32. Files are cleanly separable, no overlap.
2. Task 8.2 could not be performed as literally written (assumes PR-A's `_validar_split` `tipo_credito` kwarg exists on this branch); it does not, since PR-B is cut independently off main. No code change was needed or made; flagged for revisit when PR-A and PR-B are both merged/rebased.
3. `_validar_split`/`pago_service.py` untouched in this batch (correctly out of scope for PR-B).

## Status

PR-B (Phases 5-11, tasks 8.2 N/A and 11.2 excluded) implementation complete, all tests green. Recommend orchestrator split into PR-B/PR-B2 before opening PRs due to budget overage. PR-C (cleanup) remains out of scope for this batch.
