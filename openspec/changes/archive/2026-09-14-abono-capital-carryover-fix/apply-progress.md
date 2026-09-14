# Apply Progress: abono_capital Carry-over Fix

Cumulative apply-progress for abono-capital-carryover-fix, PR-1 + PR-2 + PR-3 batches. All phases complete as of 2026-09-14.

## PR-1 (Phases 1-6) — DONE

1.1-1.4 (arrastre_interes_abono_capital + _ultima_cuota_interes_pagada helpers in credito_service.py), 2.1-2.6 (walk-back wiring in generar_siguiente_cuota + 3 branches of _siguiente_cuota_abono_capital fold shortfall into interes_a_pagar), 3.1-3.2 (_pago_parcial calls the helper), 4.1-4.2 (recalcular_cuota_actual_si_no_pagada abono_capital branch preserves arrastre), 5.1-5.3 (projector companion test, decision 7 no-op confirmed), 6.2 (full suite green, 357 passed).

6.1 (notify collectors) and 6.3 (deploy PR-1 to prod) were completed by the owner outside sdd-apply; see tasks.md.

Files: backend/app/services/credito_service.py, backend/app/services/pago_service.py, backend/tests/test_credito_service_arrastre_abono_capital.py (new), backend/tests/test_pago_service_arrastre.py, backend/tests/test_pagos_listado.py.

## PR-2 (Phase 7) — DONE

7.1/7.2 backfill endpoint `POST /pagos/admin/backfill-arrastre-abono-capital` + `BackfillArrastreAbonoCapitalBody` schema in pagos.py, `test_pagos_backfill_arrastre_abono_capital.py` (10 tests). B1 clamp guard fix in `arrastre_interes_abono_capital` (Engram #969 risk WARNING). B2 predicate test correction in test_credito_service_arrastre_abono_capital.py (Engram #969 reliability WARNING). Full suite 368 passed.

Files: backend/app/routers/pagos.py, backend/app/services/credito_service.py, backend/tests/test_credito_service_arrastre_abono_capital.py, backend/tests/test_pagos_backfill_arrastre_abono_capital.py (new).

## Phase 8 (PR-2, prod rollout) — DONE

8.1 dry_run=true executed on Railway prod 2026-09-14 → revisados 0, corregidos 0, detalle []. 8.2/8.3: no-op — dry_run already returned 0 qualifying rows, so apply (`dry_run=false`) was not executed and post-apply verification is trivially satisfied (predicate count already 0). No production data was mutated by Phase 8.

## PR-3 (Phase 9) — DONE

### Work Unit Evidence

| Evidence | Value |
|---|---|
| Focused test command and result | `backend/venv/Scripts/python.exe -m pytest -q` → 358 passed (368 − 10 deleted backfill tests) |
| Runtime harness | N/A — deletion-only change (removes a route + schema + its test file); the temporary endpoint was already executed once in prod during Phase 8 before this PR, per design's stated rollback/rollout boundary |
| Rollback boundary | `git diff` is a pure removal: revert this commit to restore `backend/app/routers/pagos.py`'s backfill endpoint block and `backend/tests/test_pagos_backfill_arrastre_abono_capital.py`; no other files touched |

### Files Changed (this batch)

| File | Action | Lines |
|---|---|---|
| backend/app/routers/pagos.py | Modified — removed `BackfillArrastreAbonoCapitalBody` schema + `POST /admin/backfill-arrastre-abono-capital` endpoint (comment banner through closing `}`); module-level `ROUND_HALF_UP` and `TipoCredito` imports dropped after review (only used via local imports in `_calcular_virtuales`) | +2/−89 |
| backend/tests/test_pagos_backfill_arrastre_abono_capital.py | Deleted | −393 |
| openspec/changes/abono-capital-carryover-fix/tasks.md | Modified — 8.1/8.2/8.3/9.1/9.2 marked [x] with rollout notes | +5/−5 |

Total diff this batch (commit 51c561c): 3 files changed, +7/−487. Matches forecast (PR-3 negative, cleanup-only diff).

Import check: `require_role`, `audit_service.*`, `get_client_ip`, `Request`, `BaseModel` remain referenced elsewhere in pagos.py. The native review (round 1) flagged that module-level `ROUND_HALF_UP` and `TipoCredito` had no remaining module-scope use — `_calcular_virtuales` re-imports them locally — so both were removed in a bounded correction before commit. `ruff`/`pyflakes` are not installed in `backend/venv` (module-not-found on both) — manual grep-based verification was used instead as the fallback specified in the task.

### Deviations from Design

None. Task 9.3 (ARCHIVE NOTE: manually merge `payment-carryover` Non-Goals amendment into `specs/payment-carryover/spec.md`) was explicitly out of scope for the apply batch but completed during sdd-archive.

### Remaining Tasks Before Archive

None — all implementation phases complete. 9.3 spec merge, folder move and archive report were completed during sdd-archive on 2026-09-14.

### Status

Phases 1-9 complete. Full suite: 358 passed. Verified (PASS) and archived on 2026-09-14.
