## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~250-330 (helper/generator ~40, projector ~60, recalculo fix ~15, backfill ~50, tests ~150) |
| 400-line budget risk | Medium |
| Chained PRs recommended | Yes |
| Suggested split | PR 1: helper + generator + recalculo fix + projector + backfill + all tests. PR 2 (follow-up, post-deploy): delete backfill endpoint/schema/test |
| Delivery strategy | ask-on-risk |
| Chain strategy | stacked-to-main |

Decision needed before apply: Yes
Chained PRs recommended: Yes
Chain strategy: stacked-to-main
400-line budget risk: Medium

### Suggested Work Units

| Unit | Goal | Likely PR | Focused test command | Runtime harness | Rollback boundary |
|------|------|-----------|----------------------|-----------------|-------------------|
| 1 | `desglosar_arrastre` + `_siguiente_cuota_fija` wiring | PR 1 | `pytest backend/tests/test_credito_service_arrastre.py` | 3-step chain via `generar_siguiente_cuota`, unmocked | Revert helper + signature change + new test file |
| 2 | Payment acceptance / chained partials | PR 1 | `pytest backend/tests/test_pago_service_arrastre.py` | `POST /pagos/{id}/registrar`, httpx `AsyncClient`, unmocked | Revert new test file only (no prod code) |
| 3 | Recalculo arrastre-preservation fix | PR 1 | `pytest backend/tests/test_credito_service_arrastre.py -k recalcular` | Admin edit endpoint invoking `recalcular_cuota_actual_si_no_pagada` | Revert `recalcular_cuota_actual_si_no_pagada` diff only |
| 4 | Projector parity | PR 1 | `pytest backend/tests/test_pagos_listado.py` | `GET /pagos` listing (virtual rows) | Revert `_calcular_virtuales` diff only |
| 5 | Backfill endpoint (temporary) | PR 1 | `pytest backend/tests/test_pagos_backfill_arrastre.py` | `POST /pagos/admin/backfill-arrastre-componentes`, admin + non-admin | Revert endpoint + schema + test file |
| 6 | Backfill deletion (post-deploy) | PR 2 | `python -m pytest` (full suite, green) | N/A — endpoint executed once in prod before this PR, then removed | Revert deletion commit (restores endpoint) |

## Phase 1: Foundation — `desglosar_arrastre`

- [x] 1.1 RED: `backend/tests/test_credito_service_arrastre.py` (new) — pure-capital, pure-interest, mixed, `total=0`, `cuota_anterior=None`, component-overpay clamp cases for `desglosar_arrastre`
- [x] 1.2 GREEN: implement `desglosar_arrastre(cuota_anterior, saldo_pendiente)` in `backend/app/services/credito_service.py` per design (residual interest, clamp `[0,total]`)
- [x] 1.3 REFACTOR: confirm `Decimal("0.01")` / `ROUND_HALF_UP` quantization matches project convention

## Phase 2: Generator wiring

- [x] 2.1 RED: same test file — `_siguiente_cuota_fija` distributes shortfall to correct component, `cap+int == monto`
- [x] 2.2 GREEN: add `cuota_anterior` as 2nd positional to `_siguiente_cuota_fija` (`credito_service.py:406`); wire helper; update single dispatch site in `generar_siguiente_cuota` (`:397-399`)
- [x] 2.3 RED: zero-arrastre regression guard — prior cuota fully paid → components unchanged
- [x] 2.4 GREEN: verify passes with no extra code (helper returns 0/0)

## Phase 3: Chained-partial & acceptance (unmocked, `pago_service`)

- [x] 3.1 RED: `backend/tests/test_pago_service_arrastre.py` (new) — 3-step chain 120→180→200 (arrastre 50/10 then 60/20), unmocked
- [x] 3.2 RED: component-overpay clamp case (150/30/180 paid 160/0 → next 100/40/140)
- [x] 3.3 RED: exact payment of base+arrastre accepted, no HTTP 422
- [x] 3.4 RED: non-arrastre overpayment still rejected (`ValueError`, unchanged guardrail)
- [x] 3.5 GREEN: run suite; `_validar_split` stays untouched per design — no production diff expected here
- [x] 3.6 REFACTOR: dedupe shared chain fixtures if repetitive

## Phase 4: Adjacent defect — recalculo preserves arrastre

- [x] 4.1 RED: test in `test_credito_service_arrastre.py` — `recalcular_cuota_actual_si_no_pagada` (`credito_service.py:557-641`) preserves pending arrastre after Admin edits capital/tasa/abono
- [x] 4.2 GREEN: re-derive `saldo_pendiente = max(0, prev.monto_a_pagar - prev.capital_pagado - prev.interes_pagado)` from previous paid cuota, reuse `desglosar_arrastre`, stop overwriting with base values
- [x] 4.3 REFACTOR: assert `Pago.capital_pagado/interes_pagado` and `Credito.saldo_capital/saldo_intereses` remain untouched

## Phase 5: Projector parity

- [x] 5.1 RED: `backend/tests/test_pagos_listado.py` — virtual successor of an arrastre-carrying blocker shows base amounts, `cap+int == monto`
- [x] 5.2 GREEN: replace duplicated formula in `_calcular_virtuales` (`pagos.py:372-379`) with `calcular_capital_cuota_fija`/`calcular_interes_cuota_fija` + `desglosar_arrastre` (successors project `saldo_pendiente=0.00`)
- [x] 5.3 REFACTOR: drop now-dead duplicated constants

## Phase 6: One-off admin backfill

- [x] 6.1 RED: `backend/tests/test_pagos_backfill_arrastre.py` (new) — qualifying row corrected; idempotent 2nd run no-op; no-prior-cuota row skipped+reported; non-admin → 403; registered/historical payments, `abono_capital`, `Credito` saldos untouched
- [x] 6.2 GREEN: `POST /pagos/admin/backfill-arrastre-componentes` in `pagos.py`, `require_role("admin")`, selection predicate per design, `audit_service.registrar_actualizacion_campos` per row, response `{revisados, corregidos, omitidos, detalle[]}`, `# TEMPORAL — eliminar tras la ejecución` banner
- [x] 6.3 REFACTOR: align response schema/error messages with project conventions

## Phase 7: Verification

- [x] 7.1 `cd backend && python -m pytest` green (223+ existing + new arrastre tests); confirm zero mocks of `generar_siguiente_cuota` in new tests
- [x] 7.2 `cd frontend && npx tsc --noEmit` — confirm no frontend diff
- [x] 7.3 Confirm `capital_a_pagar + interes_a_pagar == monto_a_pagar` asserted across all new generated-row tests

## Phase 7b: Verify remediation (first verify pass returned FAIL)

The first `sdd-verify` pass raised 1 CRITICAL and 2 WARNING findings. Closing
them required tests and documentation only; `backend/app` stayed byte-identical.

- [x] 7b.1 RED/GREEN: `backend/tests/test_reportes_arrastre.py` (new) — CRITICAL. Requirement 6 had zero coverage. Calls `GET /api/v1/reportes` and asserts pending capital/interest totals rise by exactly the disaggregated arrastre (50.00/10.00) after a component correction, locking in the owner-accepted rise as intended behavior
- [x] 7b.2 RED/GREEN: `TestExcedenteConArrastre` in `backend/tests/test_pago_service_arrastre.py` — WARNING. Requirement 3's above-base-plus-arrastre scenario was untested. Drives the real 2-step `registrar_pago` -> `confirmar_excedente` flow with exact `Decimal` assertions; corrects the module docstring that overstated coverage
- [x] 7b.3 DOCS: amend spec Requirement 4 wording to match verified projector behavior, with an inline justification note. Traced against `_pago_parcial` and `_calcular_virtuales`: a partial payment always finalizes the blocking row and rolls forward atomically, so the projector can never observe unrealized arrastre. Documentation gap, not a behavioral defect — no production code changed
- [x] 7b.4 REFACTOR: add `saldo_intereses` assertions to the backfill out-of-scope test; use `AsyncMock(spec=AsyncSession)` to remove a cosmetic `RuntimeWarning`
- [x] 7b.5 Re-run `sdd-verify`: PASS, 0 CRITICAL / 0 WARNING, 246 passed / 0 failed, 16/16 spec scenarios covered

## Phase 8: Rollout & cleanup (PR 2, after prod deploy)

- [ ] 8.1 Deploy PR 1; run `POST /pagos/admin/backfill-arrastre-componentes` once as admin in prod; verify affected credits accept exact arrastre payment
- [ ] 8.2 Delete the backfill endpoint, its schema, and `test_pagos_backfill_arrastre.py`
- [ ] 8.3 `python -m pytest` green after deletion (no orphaned imports/fixtures)
