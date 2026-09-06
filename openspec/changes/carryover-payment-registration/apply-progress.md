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
