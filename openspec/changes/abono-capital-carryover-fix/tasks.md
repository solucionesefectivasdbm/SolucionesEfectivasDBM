# Tasks: abono_capital Carry-over Fix

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | PR-1 ~300, PR-2 ~110, PR-3 negative diff (~20) |
| 400-line budget risk | Low per PR (Medium if merged as one) |
| Chained PRs recommended | Yes |
| Suggested split | PR-1 fix+tests → PR-2 backfill+tests → PR-3 cleanup, 3 independent PRs to `main` in sequence (NOT stacked) |
| Delivery strategy | ask-on-risk |
| Chain strategy | pending (owner decision: independent-sequential, not stacked-to-main/feature-branch-chain) |

Decision needed before apply: Yes
Chained PRs recommended: Yes
Chain strategy: pending
400-line budget risk: Low

### Suggested Work Units

| Unit | Goal | Likely PR | Focused test command | Runtime harness | Rollback boundary |
|------|------|-----------|----------------------|-----------------|-------------------|
| 1 | Helper + walk-back query + generator wiring + recalculo fix + projector companion test | PR-1 | `backend/venv/Scripts/python.exe -m pytest backend/tests/test_credito_service_arrastre_abono_capital.py` | 3-step `PagoService.registrar_pago` chain via `db_session`, unmocked | Revert helper/query/branches + new test file; `pago_service.py` 258-261 revert |
| 2 | Backfill endpoint (temporary) | PR-2 | `backend/venv/Scripts/python.exe -m pytest backend/tests/test_pagos_backfill_arrastre_abono_capital.py` | `POST /pagos/admin/backfill-arrastre-abono-capital?dry_run=true` on Railway prod | Revert endpoint + test file |
| 3 | Backfill deletion (post prod run) | PR-3 | `backend/venv/Scripts/python.exe -m pytest` (full suite) | N/A — endpoint executed once in prod before this PR | Revert deletion commit |

## Phase 1: Carry Helper & Prior-Row Query (PR-1)

- [x] 1.1 RED: `backend/tests/test_credito_service_arrastre_abono_capital.py` (new) — `arrastre_interes_abono_capital`: shortfall, overpaid clamps to 0, `None` → 0, `tipo_cuota == abono` → 0 (Req: Interest-only Shortfall Carry; Prior-Row Selection Correctness)
- [x] 1.2 GREEN: add `arrastre_interes_abono_capital(cuota_pagada)` in `credito_service.py` after `desglosar_arrastre` per design decision 1
- [x] 1.3 RED: same file — `_ultima_cuota_interes_pagada`: skips unpaid/soft-deleted/abono/no_programada rows, orders by `numero_cuota` DESC (Req: Prior-Row Selection Correctness)
- [x] 1.4 GREEN: add `_ultima_cuota_interes_pagada(db, credito_id, antes_de)` per decision 3

## Phase 2: Walk-back Generation (PR-1)

- [x] 2.1 RED: chained-partials + intervening-abono scenarios in `test_credito_service_arrastre_abono_capital.py` via `db_session` (Req: Shortfall Survives an Intervening Abono Cuota)
- [x] 2.2 GREEN: wire walk-back in `generar_siguiente_cuota` (abono_capital, non-mensual, prior tipo == abono) per decision 2
- [x] 2.3 RED: `_siguiente_cuota_abono_capital` mensual/interés fold `saldo_pendiente` into `interes_a_pagar`; abono successor ignores it (Req: Interest-only Shortfall Carry; Component Sum Invariant)
- [x] 2.4 GREEN: implement three branches per decision 4
- [x] 2.5 RED: `TestAbonoCapitalMensualArrastreInteres` in `test_pago_service_arrastre.py` (AsyncMock safe for mensual)
- [x] 2.6 GREEN: confirm mensual chain passes with 2.4's branch

## Phase 3: Payment Acceptance (PR-1)

- [x] 3.1 RED: exact payment of `capital + arrastre-inclusive interés` accepted, no 422 (Req: Arrastre-inclusive Payment Acceptance)
- [x] 3.2 GREEN: replace `pago_service.py:258-261` with `saldo_a_arrastrar = arrastre_interes_abono_capital(pago)` per decision 5

## Phase 4: Recalculation Preserves Arrastre (PR-1)

- [x] 4.1 RED: `recalcular_cuota_actual_si_no_pagada` (abono_capital, mensual & alternating interés) keeps arrastre after `pago no programado` and admin edits; abono cuota stays interest-free (Req: Recalculation Preserves Pending Arrastre)
- [x] 4.2 GREEN: add abono_capital branch per decision 6 (`base + helper(await _ultima_cuota_interes_pagada(...))`)

## Phase 5: Projector Parity & Invariant (PR-1)

- [x] 5.1 RED: companion test in `test_pagos_listado.py` — virtual abono_capital rows show base values, `cap+int == monto` (Req: Projection and Frontend Unchanged)
- [x] 5.2 CONFIRM: `_calcular_virtuales` stays byte-identical (decision 7, no production diff)
- [x] 5.3 Assert Component Sum Invariant holds across all Phase 1-4 generated/recalculated rows

## Phase 6: PR-1 Close-out

- [x] 6.1 OPERATIONAL: notify collectors before PR-1 deploy — stop the "pay base + pago no programado" workaround; after the fix it double-charges (design Migration/Rollout) — OUT OF SCOPE for sdd-apply, requires human/owner action before deploy
- [x] 6.2 `backend/venv/Scripts/python.exe -m pytest` green (full suite) — 357 passed
- [x] 6.3 Deploy PR-1 to prod — OUT OF SCOPE for sdd-apply, requires orchestrator/owner-driven PR + deploy

## Phase 7: Backfill Endpoint (PR-2)

- [x] 7.1 RED: `backend/tests/test_pagos_backfill_arrastre_abono_capital.py` (new) — qualifying row corrected, dry-run writes nothing, idempotent 2nd run no-op, `cuota_fija`/paid/out-of-scope rows untouched, non-admin 403 (Req: One-off Backfill Correction)
- [x] 7.2 GREEN: `POST /pagos/admin/backfill-arrastre-abono-capital` in `pagos.py`, `require_role("admin")`, `dry_run: bool = True`, predicate per design, `interes_a_pagar = monto - capital`, audit via `audit_service.registrar_actualizacion_campos`, `# TEMPORAL` banner
- [x] 7.3 `backend/venv/Scripts/python.exe -m pytest` green (368 passed) — deploy PR-2 to prod (Railway) OUT OF SCOPE for sdd-apply, requires orchestrator/owner-driven PR + deploy

## Phase 8: Backfill Rollout (PR-2, prod)

- [ ] 8.1 Run `dry_run=true` on Railway prod; review `detalle[]`
- [ ] 8.2 Apply once (`dry_run=false`)
- [ ] 8.3 Verify: backfill predicate SQL count = 0 after apply

## Phase 9: Cleanup & Archive (PR-3)

- [ ] 9.1 Delete `POST /pagos/admin/backfill-arrastre-abono-capital`, its schema, and `test_pagos_backfill_arrastre_abono_capital.py`
- [ ] 9.2 `backend/venv/Scripts/python.exe -m pytest` green after deletion (no orphaned imports/fixtures)
- [ ] 9.3 ARCHIVE NOTE: manually merge `payment-carryover` Non-Goals amendment into `specs/payment-carryover/spec.md` — it is a Non-Goals text replacement, not a Requirement block, so `sdd-archive` tooling will not auto-apply it

## Follow-ups (not in scope, not tasks)

- Design decision 9 (deferred): `pago_service.py:105-109` message guard needs a `_validar_split` signature change to distinguish cuota_fija Rule-10 rows from abono_capital interés rows.
- Observation: `_calcular_virtuales` (`pagos.py:510`) divides abono_capital interest by `ppm` while the generator uses full monthly interest — alternating-credit projection underestimates. Candidate future fix, not required by this change.
