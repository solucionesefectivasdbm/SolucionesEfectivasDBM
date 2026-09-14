# Archive Report: abono_capital Carry-over Fix

**Date**: 2026-09-14  
**Change**: abono-capital-carryover-fix  
**Project**: solucionesefectivasdbm  
**Status**: ARCHIVED AND CLOSED · Engram #974

## What Shipped

| PR | Merge commit on main | Content | Suite |
|---|---|---|---|
| #30 | `538ffb4` | Fix: `arrastre_interes_abono_capital` + `_ultima_cuota_interes_pagada`; walk-back in `generar_siguiente_cuota`; shortfall folded into `interes_a_pagar` in the three `_siguiente_cuota_abono_capital` branches; recalculation preserves arrastre; `_pago_parcial` accepts base + arrastre | 357 passed |
| #31 | `f40cb45` | Temporary `POST /pagos/admin/backfill-arrastre-abono-capital` (dry_run, audit, idempotent predicate) + 10 tests | 368 passed |
| #32 | `1ec134a` | Cleanup: endpoint, schema and test file deleted; orphaned module imports removed | 358 passed |

**Deploy**: Railway production on `1ec134a` (all three PRs). No migration.

**Prod rollout (Phase 8)**: backfill `dry_run=true` on 2026-09-14 returned `revisados: 0, corregidos: 0`. Apply was not executed. Rows affected before the fix had already been settled by collectors via the "unscheduled payment" workaround, which excludes them from the predicate by design.

## Spec Sync

| Domain | Action | File |
|---|---|---|
| `abono-capital-carryover` | Created | `openspec/specs/abono-capital-carryover/spec.md` |
| `payment-carryover` | Modified | Component Sum Invariant widened to all credit types and recalculation; Non-Goals line replaced (task 9.3, manual) |

## Follow-ups (not tasks)

1. Decision 9 deferred: `_validar_split` message guard cannot yet distinguish `cuota_fija` Rule-10 rows from `abono_capital` interés rows (`pago_service.py`). Separate change.
2. Projection underestimate: `_calcular_virtuales` divides `abono_capital` interest by `ppm` while the generator uses the full monthly interest; alternating credits are under-projected. Candidate future fix.
3. Residual risk accepted by owner: rows already lost via case 3 or re-derived via case 4 before the fix are not recoverable from `monto_a_pagar`.

## Rollback

Revert the PR #30 merge (`538ffb4`, feature commit `08cdbe3`). No schema change. Rows generated under the fix remain correct and payable.

## Engram Traceability

Proposal #963 · Tasks #966 · Apply progress #968 · State #969 · Verify #973 · Archive #974
