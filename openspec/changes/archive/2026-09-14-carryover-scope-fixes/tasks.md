# Tasks: Carry-over scope fixes (Bug A + Bug B)

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | PR-A ~170, PR-B ~330 (backfill endpoint + tests ~110 of those), PR-C negative diff (~-90) |
| 400-line budget risk | Low per PR. PR-B is closest to the 400 line budget; if implementation exceeds it, split the backfill endpoint into PR-B2 (precedent PRs #31/#32) |
| Chained PRs recommended | No — three independent branches off `main` (lesson from #21-#25, #30-#33) |
| Decision needed before apply | Only if PR-B forecast exceeds ~370 real lines during implementation → split into PR-B (carve-out+tests) and PR-B2 (backfill endpoint+tests) |

### Suggested Work Units

| Unit | Goal | PR | Focused test command | Rollback boundary |
|------|------|----|-----------------------|--------------------|
| A | `tipo_credito` plumbing + frontend guard + `_validar_split` scoping | PR-A | `backend/venv/Scripts/python.exe -m pytest backend/tests/test_pago_service.py backend/tests/test_pagos_listado.py` ; `cd frontend && npx tsc --noEmit` | Revert schema field, SELECT additions, `_validar_split` param, frontend guard |
| B | `_es_cuota_fija_fuera_de_plazo` at generation + recalculation + spec deltas + backfill endpoint | PR-B (or PR-B/PR-B2) | `backend/venv/Scripts/python.exe -m pytest backend/tests/test_credito_service.py backend/tests/test_pago_service.py backend/tests/test_pagos_backfill_cuota_fija_fuera_de_plazo.py` | Revert predicate, both call sites, backfill endpoint+schema+test file |
| C | Delete backfill endpoint after one prod run | PR-C | `backend/venv/Scripts/python.exe -m pytest` (full suite) | Revert deletion commit |

## Phase 1: `tipo_credito` Plumbing (PR-A)

- [x] 1.1 RED: `backend/tests/test_pagos_listado.py` — `listar_pagos`, `listar_aplazados`, and `_calcular_virtuales` rows all expose `tipo_credito` matching the parent `Credito` (Req: abono-capital-carryover / "Interés Installment Is Not Capital-Settled")
- [x] 1.2 GREEN: `backend/app/schemas/pago.py` — add `tipo_credito: Optional[TipoCredito] = None` to `PagoResponse`
- [x] 1.3 GREEN: `backend/app/routers/pagos.py` — append `Credito.tipo_credito.label("tipo_credito")` to the `listar_pagos`/`listar_aplazados` SELECTs, thread through `_pago_row_a_dict` and the `_calcular_virtuales` dict, per design decision 1

## Phase 2: Frontend Guard Scoping (PR-A)

- [x] 2.1 RED: `frontend/src/pages/Pagos/__tests__` (or equivalent) — capital input stays enabled when `tipo_credito === 'abono_capital'` and `tipo_cuota === 'interes'`; stays locked only when `tipo_credito === 'cuota_fija' && tipo_cuota === 'interes'`; null `tipo_credito` fails open (Req: abono-capital-carryover) — no frontend test runner exists (config.yaml: `strict_tdd.frontend: false`); Standard Mode applied, verified via `tsc --noEmit` per project rule
- [x] 2.2 GREEN: `frontend/src/types/index.ts` — add `tipo_credito?: TipoCredito | null` to `Pago`
- [x] 2.3 GREEN: `frontend/src/pages/Pagos/PagosPage.tsx:688-695` — scope the lock/message guard to `tipo_credito === 'cuota_fija' && tipo_cuota === 'interes'`
- [x] 2.4 `cd frontend && npx tsc --noEmit` clean

## Phase 3: `_validar_split` Message Scoping (PR-A)

- [x] 3.1 RED: `backend/tests/test_pago_service.py` — `TestValidarSplit` gains cases: `cuota_fija` keeps existing rule-13 text; `abono_capital` gets the alternating-cycle message (capital not settled, register in abono cuota or split); `tipo_credito=None` gets the generic component message (Req: payment-carryover / abono-capital-carryover)
- [x] 3.2 RED: same file — exact payment with capital > TOL on an `abono_capital` interés installment → 422 with cycle message, never "capital saldado"; partial free split on the same installment still accepted (Req: abono-capital-carryover)
- [x] 3.3 GREEN: `backend/app/services/pago_service.py:62-135` — add `tipo_credito: TipoCredito | None = None` keyword param to `_validar_split`, branch message per decision 3
- [x] 3.4 GREEN: `backend/app/services/pago_service.py:184,227,299` — `_pago_exacto`, `_pago_parcial`, `confirmar_excedente` pass `credito.tipo_credito`
- [x] 3.5 `backend/venv/Scripts/python.exe -m pytest backend/tests/test_pago_service.py backend/tests/test_pagos_listado.py` green

## Phase 4: PR-A Close-out

- [x] 4.1 `backend/venv/Scripts/python.exe -m pytest` full suite green
- [ ] 4.2 Open PR-A (independent branch off `main`) — OUT OF SCOPE for sdd-apply, requires orchestrator/owner-driven PR + deploy

## Phase 5: Past-term Predicate (PR-B)

- [x] 5.1 RED: `backend/tests/test_credito_service.py` — `_es_cuota_fija_fuera_de_plazo(credito, numero)`: true only when `tipo_credito == cuota_fija`, `numero > numero_cuotas`, `saldo_capital > 0`; false for `abono_capital`, within-term, and `saldo_capital <= 0` (Req: credit-closure / "Past-term Base Installment")
- [x] 5.2 GREEN: `backend/app/services/credito_service.py` — add pure predicate `_es_cuota_fija_fuera_de_plazo` next to `desglosar_arrastre` per design decision 4

## Phase 6: Generation Carve-out (PR-B)

- [x] 6.1 RED: `backend/tests/test_credito_service.py` — `_siguiente_cuota_fija` on installment 13-of-12 after a PARTIAL payment on 12/12 (`saldo_pendiente=5000`) → cuota 13 = base (10000/3600/13600), no arrastre, `programada` (Req: payment-carryover exception scenario, credit-closure)
- [x] 6.2 RED: same file — installment 13→14 after ANOTHER partial payment on 13/12 → cuota 14 still equals base, no arrastre re-added (validator-found gap)
- [x] 6.3 RED: same file — past-term installment is NOT capped when remaining `saldo_capital` (e.g. 2000) is below `capital_por_cuota` (e.g. 10000) → `capital_a_pagar` stays 10000, uncapped (validator-found gap; Req: credit-closure "not capped" scenario)
- [x] 6.4 RED: same file — once `saldo_capital` reaches 0 mid past-term-tail, the following installment switches to the rule-14 interest-only tail (Req: credit-closure)
- [x] 6.5 GREEN: `backend/app/services/credito_service.py:608-654` — call `_es_cuota_fija_fuera_de_plazo` in `_siguiente_cuota_fija` after the `saldo_capital<=0` tail check (rule 14 dominates rule 15); when true, emit base cap + base interest, arrastre 0, uncapped, `programada`, existing `es_ultima` formula unchanged

## Phase 7: Recalculation Carve-out (PR-B)

- [x] 7.1 RED: `backend/tests/test_credito_service.py` (via `db_session`) — `recalcular_cuota_actual_si_no_pagada` on an unpaid past-term cuota after an admin field edit keeps base values, no re-added shortfall, skips the walk-back query (Req: credit-closure "admin edit on unpaid 13/12 keeps base")
- [x] 7.2 GREEN: `backend/app/services/credito_service.py:879-926` — same predicate check in `recalcular_cuota_actual_si_no_pagada`, mirroring Phase 6's branch

## Phase 8: Payment-side Regression Coverage (PR-B)

- [x] 8.1 RED: `backend/tests/test_pago_service.py` — PARTIAL-payment sibling of `test_ultima_cuota_pagada_con_capital_pendiente_no_cierra` (line 449): partial payment (e.g. 8000 capital + 3600 interest) on installment 12/12 → installment 13 = 10000/3600/13600, no arrastre (Req: credit-closure)
- [ ] 8.2 NOT APPLICABLE in this batch: `_validar_split`'s `tipo_credito` message-scoping kwarg (Phase 3) lives only on PR-A's branch (`fix/abono-capital-interes-input-guard`), which this branch does not contain — `test_capital_contra_cuota_solo_interes_lanza_mensaje_explicativo` still passes unmodified against the current `_validar_split` signature. Revisit at PR-A/PR-B merge or rebase time.
- [x] 8.3 `backend/venv/Scripts/python.exe -m pytest backend/tests/test_credito_service.py backend/tests/test_pago_service.py` green (107 passed)

## Phase 9: Spec Deltas (PR-B)

- [x] 9.1 Confirmed `openspec/changes/carryover-scope-fixes/specs/{payment-carryover,credit-closure}/spec.md` match the implemented behavior (Phases 5-8); no edits needed. `abono-capital-carryover/spec.md` delta belongs to PR-A, out of scope here.

## Phase 10: Backfill Endpoint (PR-B, or split PR-B2)

- [x] 10.1 RED: `backend/tests/test_pagos_backfill_cuota_fija_fuera_de_plazo.py` (new) — qualifying row (unpaid, zero paid, `programada`, `cuota_fija`, `numero_cuota > numero_cuotas`, `saldo_capital > 0`, components > base+TOL) corrected to base; dry-run writes nothing; idempotent second run is a no-op; `abono_capital`/paid/within-term/base rows untouched; non-admin → 403 (Req: credit-closure "One-off Past-term Arrastre Backfill")
- [x] 10.2 GREEN: `POST /pagos/admin/backfill-cuota-fija-fuera-de-plazo` in `backend/app/routers/pagos.py`, `require_role("admin")`, `dry_run: bool = Query(True)` default, `# TEMPORAL` banner; SQL predicate per design; Python filter on components vs. `calcular_*_cuota_fija(capital_prestado)`; write cap/int/monto/es_ultimo_pago; saldos untouched; audit via `audit_service.registrar_actualizacion_campos`; response `{dry_run, revisados, corregidos, detalle[]}`
- [x] 10.3 `backend/venv/Scripts/python.exe -m pytest backend/tests/test_pagos_backfill_cuota_fija_fuera_de_plazo.py` green (8 passed)

## Phase 11: PR-B Close-out

- [x] 11.1 `backend/venv/Scripts/python.exe -m pytest` full suite green (405 passed)
- [ ] 11.2 Open PR-B (independent branch off `main`; split into PR-B/PR-B2 if the diff exceeds ~370 lines) — OUT OF SCOPE for sdd-apply, requires orchestrator/owner-driven PR + deploy

## Phase 12: Backfill Rollout (prod, manual)

- [ ] 12.1 MANUAL: from a browser console on the deployed frontend, obtain a token via `fetch('/api/v1/auth/refresh', {method: 'POST', credentials: 'include'})`, then call `POST /pagos/admin/backfill-cuota-fija-fuera-de-plazo?dry_run=true` through the `/api` proxy
- [ ] 12.2 MANUAL: review `detalle[]` — confirm it lists exactly Fernando Sanabria's past-term row(s) and no unexpected credits
- [ ] 12.3 MANUAL: apply once with `dry_run=false`; capture the response for the change ledger
- [ ] 12.4 MANUAL: re-run with `dry_run=true` — confirm `revisados`/`corregidos` show the row is no longer flagged (idempotent no-op)

## Phase 13: Cleanup (PR-C)

- [ ] 13.1 Delete `POST /pagos/admin/backfill-cuota-fija-fuera-de-plazo`, its request/response schema, and `test_pagos_backfill_cuota_fija_fuera_de_plazo.py`
- [ ] 13.2 `backend/venv/Scripts/python.exe -m pytest` green after deletion (no orphaned imports/fixtures)
- [ ] 13.3 Open PR-C (independent branch off `main`, negative diff) — OUT OF SCOPE for sdd-apply, requires orchestrator/owner-driven PR + deploy

## Phase 14: Archive

- [ ] 14.1 ARCHIVE NOTE: at sdd-archive, merge the three delta spec files into `openspec/specs/{payment-carryover,credit-closure,abono-capital-carryover}/spec.md` (precedent: abono-capital-carryover-fix Non-Goals merge)

## Follow-ups (not in scope, not tasks)

- Pending-totals reports will show a one-time drop for corrected rows after the backfill (proposal risk table, "Certain" — intended, not a defect).
- `_calcular_virtuales` (`pagos.py:510`) still divides `abono_capital` interest by `ppm` while the generator uses full monthly interest for the alternating-credit projection (carried over from abono-capital-carryover-fix follow-ups; not required by this change).
