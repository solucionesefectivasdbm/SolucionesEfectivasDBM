# Verification Report: abono_capital Carry-over Fix

**Change**: `abono-capital-carryover-fix` · **Mode**: Full artifacts (proposal #963, specs, design, tasks #966, apply-progress #968) · Strict TDD: active · **Verdict**: PASS (0 CRITICAL, 0 WARNING, 0 SUGGESTION) · Engram #973

## Completeness

| Phase | Tasks | Status |
|---|---|---|
| 1-7 (PR-1 fix, PR-2 backfill endpoint) | Complete | All `[x]` |
| 8 (prod rollout) | Complete | dry_run on Railway 2026-09-14 → 0 rows; apply not executed (no-op) |
| 9.1-9.2 (PR-3 cleanup) | Complete | Endpoint, schema and test file deleted; suite green |
| 9.3 (archive-time spec merge) | Complete | Done during sdd-archive |

## Test Execution Evidence

`cd backend && venv/Scripts/python.exe -m pytest -q` → **358 passed, 0 failed** (main `1ec134a`).

## Spec → Code → Test Mapping

| Requirement | Code | Tests |
|---|---|---|
| Interest-only Shortfall Carry / Prior-Row Selection Correctness | `credito_service.py` `arrastre_interes_abono_capital`, `_ultima_cuota_interes_pagada` | `TestArrastreInteresAbonoCapital`, `TestUltimaCuotaInteresPagada` |
| Shortfall Survives an Intervening Abono Cuota | walk-back in `generar_siguiente_cuota` | `TestGenerarSiguienteCuotaWalkBack` |
| Arrastre-inclusive Payment Acceptance | `pago_service.py` `_pago_parcial` | `test_pago_service_arrastre.py::TestAbonoCapitalMensualArrastreInteres` |
| Recalculation Preserves Pending Arrastre | `recalcular_cuota_actual_si_no_pagada` abono_capital branch | `TestRecalcularCuotaActualPreservaArrastreAbonoCapital` |
| Component Sum Invariant | `_siguiente_cuota_abono_capital` (3 branches) | `TestSiguienteCuotaAbonoCapitalArrastre` |
| Projection and Frontend Unchanged | `_calcular_virtuales` byte-identical | `test_pagos_listado.py` abono_capital companion test |
| One-off Backfill Correction | Historical — endpoint deleted in PR-3 | Tests deleted with the endpoint |

No gaps found.

## Design Decisions Honored

- Migration-free: no Alembic migration in any of the three PRs.
- `saldo_capital` / `saldo_intereses` never written by any carry-over branch; only `Pago` row fields are mutated.
- Walk-back derives strictly from a persisted `pagado=True, deleted_at IS NULL` row via `_ultima_cuota_interes_pagada`.
- Backfill endpoint fully removed: `rg "backfill-arrastre-abono-capital|BackfillArrastreAbonoCapitalBody|backfill_arrastre"` over `backend/` and `frontend/` returns zero matches.
