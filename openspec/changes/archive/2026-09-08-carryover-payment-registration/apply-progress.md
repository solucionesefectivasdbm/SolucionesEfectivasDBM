# Apply Progress: carryover-payment-registration — PR 1 (Phases 1-7)

**Branch**: `fix/pago-arrastre-cuota-fija` (from `main` @ `ae2d774`)
**Mode**: Strict TDD (backend); no frontend change.
**Batch**: first and only so far — no prior apply-progress existed.

Phase 8 (PR 2 — delete the backfill endpoint) intentionally NOT started;
out of scope for this run per the owner's confirmed PR split.

## Completed Tasks

All Phase 1-7 checkboxes are marked `[x]` in `tasks.md`. Summary:

- **Phase 1**: `desglosar_arrastre` pure helper (RED confirmed via `ImportError`, then GREEN). 6 unit cases.
- **Phase 2**: `_siguiente_cuota_fija` gains `cuota_anterior` as 2nd positional; single dispatch site in `generar_siguiente_cuota` updated; zero-arrastre regression guard.
- **Phase 3**: Unmocked `pago_service` integration tests (3-step chain, component-overpay clamp, exact-payment acceptance, guardrail-reject). No production diff in this phase, as designed.
- **Phase 4**: `recalcular_cuota_actual_si_no_pagada` re-derives and preserves pending arrastre from the previous paid cuota instead of overwriting with base values.
- **Phase 5**: `_calcular_virtuales` shares `calcular_capital_cuota_fija`/`calcular_interes_cuota_fija` + `desglosar_arrastre(None, 0.00)` instead of a third duplicated formula.
- **Phase 6**: Temporary admin-only `POST /pagos/admin/backfill-arrastre-componentes`, idempotent, skips-and-reports rows with no prior paid cuota, never touches registered payments/`abono_capital`/credit balances.
- **Phase 7**: Full suite green (244/244, baseline 223 + 21 new), `npx tsc --noEmit` clean, zero frontend diff, invariant `capital_a_pagar + interes_a_pagar == monto_a_pagar` asserted across all new generated-row tests.

## Files Changed

| File | Action |
|---|---|
| `backend/app/services/credito_service.py` | Modified — `desglosar_arrastre`, `_siguiente_cuota_fija` wiring, `recalcular_cuota_actual_si_no_pagada` fix |
| `backend/app/routers/pagos.py` | Modified — projector parity, temporary backfill endpoint |
| `backend/tests/test_credito_service_arrastre.py` | Created — 10 tests |
| `backend/tests/test_pago_service_arrastre.py` | Created — 5 tests, zero mocks of `generar_siguiente_cuota` |
| `backend/tests/test_pagos_listado.py` | Modified — +1 projector-parity test |
| `backend/tests/test_pagos_backfill_arrastre.py` | Created — 5 tests |

## Verification

- `cd backend && python -m pytest`: **244 passed**, 0 failed.
- `cd frontend && npx tsc --noEmit`: clean.
- `git status --porcelain frontend/`: empty (no frontend diff).
- Zero mocks/patches of `generar_siguiente_cuota` in any new test file (grep-verified).

## Deviations

None — implementation matches `design.md` exactly.

## Known test-only gotchas (documented inline in the affected test files)

- `db=AsyncMock()` leaves `Pago.id=None` until a real flush; chained tests
  that reuse a `db.add()`-captured `Pago` must assign an id manually before
  it round-trips through `PagoResponse`.
- `AsyncSession.refresh()` does not autoflush pending in-memory mutations on
  the object being refreshed in this project's test session config — assert
  directly on the identity-mapped object instead when the endpoint and the
  test share the same `db_session`.

## Delivery

Chain strategy: `stacked-to-main`. This is PR 1 (Phases 1-7), delivered as
5 work-unit commits, no push, no PR opened.

`git diff main...HEAD --stat`: 14 files changed, 1793 insertions(+), 12
deletions(-). Backend code+tests: ~1063 lines; openspec docs: ~742 lines.
Exceeds the original ~250-330 Medium forecast and the 400-line budget,
driven by the mandated unmocked test coverage — accepted per the owner's
explicit "PR 1 = Phases 1-7" instruction for this run.

## Remediation batch (closes sdd-verify findings)

Second batch on the same branch, closing the `verify-report.md` FAIL
verdict. No production code touched — `backend/app` diff vs `main` is
still exactly 187 insertions(+)/12 deletions(-), byte-identical to PR 1.

1. **CRITICAL closed** — Requirement 6 "Reported Pending Totals Reflect
   True Amounts" had zero covering test. Added
   `backend/tests/test_reportes_arrastre.py`: a runtime test against
   `GET /api/v1/reportes` proving pending capital/interest totals rise by
   exactly the disaggregated arrastre (50.00/10.00) once a pending
   `cuota_fija` row's components are corrected, and do NOT clamp back to
   base. RED confirmed (temporarily broke the expected value, saw the
   assertion fail) before restoring the correct value — GREEN by
   construction since `reportes.py` needed no code change.
2. **WARNING closed** — Requirement 3 scenario "payment above base plus
   arrastre" (`destino_excedente`) had no covering test, and the
   `test_pago_service_arrastre.py` module docstring falsely claimed
   `confirmar_excedente` was already exercised. Added
   `TestExcedenteConArrastre` (2-step `registrar_pago` →
   `confirmar_excedente`, real generation, asserts exact saldo reduction
   and base-value next cuota) and corrected the docstring wording. RED
   confirmed via a deliberately wrong assertion before restoring GREEN.
3. **WARNING closed** — Requirement 4 (projector) wording said the first
   projected row shows arrastre-inclusive values; design.md and the
   tested implementation establish a blocking unpaid cuota always has
   zero paid components (a partial payment immediately persists a real
   successor instead of leaving the blocker partially paid), so the
   projector can never observe an unrealized arrastre and always
   projects base values. Amended `specs/payment-carryover/spec.md`
   Requirement 4 wording + scenario to describe the verified, testable
   behavior, with an inline justification note. No production code
   change — this was a documentation gap, not a behavioral defect.
4. **Suggestions applied**:
   - Added `saldo_intereses` assertions (both credits) to
     `test_pagos_registrados_abono_capital_y_saldos_no_se_tocan` in
     `test_pagos_backfill_arrastre.py` (previously only asserted
     `saldo_capital`).
   - Switched `db=AsyncMock()` to `db=AsyncMock(spec=AsyncSession)` via a
     `make_db()` helper in `test_pago_service_arrastre.py`, eliminating
     the cosmetic "coroutine was never awaited" `RuntimeWarning` on
     `db.add()` without weakening any assertion.

Verification after remediation: `246 passed, 0 failed` (244 baseline + 2
new test functions: `test_totales_suben_tras_correccion_de_arrastre`,
`test_pago_supera_base_mas_arrastre_via_confirmar_excedente`; the
remaining changes added assertions to existing test bodies rather than
new test functions). `cd frontend && npx tsc --noEmit`: clean, zero
frontend diff.

Delivered as 4 additional work-unit commits on `fix/pago-arrastre-cuota-fija`,
no push, no PR opened:
- `test(reportes): verify pending totals reflect true arrastre amounts`
- `test(pago): cover excedente-with-arrastre path and fix misleading docstring`
- `docs(spec): reconcile projector requirement with verified behavior`
- `test(pagos): assert saldo_intereses untouched by arrastre backfill`
