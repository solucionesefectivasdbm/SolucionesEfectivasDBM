# Exploration: carryover-scope-fixes

Bug A: abono_capital capital-input guard. Bug B: cuota_fija past-term arrastre.

Engram: `sdd/carryover-scope-fixes/explore` (observation #992). Source decisions: #990 (diagnosis), #991 (rule 15).

## Current State

**Bug A root cause (verified):** `TipoCuota.interes` is shared by two unrelated situations:

1. `abono_capital` quincenal/alternating cycle's INTEREST half-installment (`credito_service.py:763-782`, `_siguiente_cuota_abono_capital`) — capital NOT settled, `capital_a_pagar=0.00` is just this installment's structure.
2. `cuota_fija` post-closure solo-interest tail (rule 10/13, `_siguiente_cuota_fija_solo_interes` line 657-701, and `recalcular_cuota_actual_si_no_pagada` line 860-878) — capital IS truly settled (`credito.saldo_capital <= 0`).

`frontend/src/pages/Pagos/PagosPage.tsx:688-695` disables "Capital pagado" and shows "el capital ya está saldado" whenever `pagoSeleccionado.tipo_cuota === 'interes'`, conflating both cases. `Pago`/`PagoResponse` (frontend `types/index.ts:103-127`, backend `schemas/pago.py` `PagoResponse`) has NO `tipo_credito` field, so the frontend structurally cannot distinguish today. `pagoSeleccionado` is set directly from the list row (`PagosPage.tsx:570/585/600`, `p` from `listar_pagos`/`listar_aplazados`) — no separate fetch — so adding a field to the list query flows straight through.

Real user impact confirmed beyond cosmetics: business rule (`pago_service.py:70-135` `_validar_split` docstring) allows FREE component split on a PARTIAL payment (total < monto_a_pagar), regardless of cuota type. Disabling the capital input blocks that free split entirely for abono_capital quincenal clients on their "interes" half-cuota — a genuine functional regression, not just a wrong message.

Backend mirror bug: `_validar_split` (`pago_service.py:104-114`) raises the SAME message "Esta cuota es de solo interés porque el capital del crédito ya fue saldado" whenever `capital_pagado > capital_a_pagar + TOL` and `capital_a_pagar <= 0` on an EXACT split — this fires for abono_capital's interes cuota too, where the statement is factually false (capital isn't saldado, it just isn't due on this half of the cycle). Rejecting is still correct (component targets don't allow it), only the message is wrong. `_validar_split` currently receives only `pago`, not `credito`/`tipo_credito` — both call sites (`_pago_exacto` line 184, `_pago_parcial` line 227) already have `credito` in scope, so threading it through is trivial.

Before commit 47305b5 (cuota_fija rule 10/13 guard), there was no such disable at all — abono_capital's interes-cuota input worked correctly; the guard was added generically for cuota_fija and unintentionally caught abono_capital too.

`/pagos/diarios` is the SAME `PagosPage` component (`App.tsx:61`, `<PagosPage variante="diario" />`) — fixing `PagosPage.tsx` fixes both routes; no separate parity work needed.

**Bug B root cause (verified):** `_siguiente_cuota_fija` (`credito_service.py:608-654`) only special-cases `credito.saldo_capital <= 0` (routes to solo-interest tail). It has NO check for `numero > credito.numero_cuotas` — when the last regular installment (`numero_cuota == numero_cuotas`) is paid PARTIALLY (not exactly) leaving `saldo_capital > 0`, `_pago_parcial` (`pago_service.py:219-268`) computes `saldo_a_arrastrar = faltante` (full shortfall, since `credito.tipo_credito == cuota_fija`, line 259-260) and calls `generar_siguiente_cuota` → `_siguiente_cuota_fija`, which unconditionally adds `arr_cap`/`arr_int` via `desglosar_arrastre` (line 637-639) onto the base installment — producing an INFLATED past-term installment. This directly contradicts the existing spec (`credit-closure/spec.md`, "Last installment reached with balance outstanding": "a further installment is generated with the SAME value, carrying no arrastre") and the owner's rule-15 decision (Engram #991): past-term installment = full base (capital_por_cuota + base interest), NO arrastre, NOT capped to remaining balance, repeated until `saldo_capital = 0`, then rule 14 (interest-only tail) applies.

Existing test `test_pago_service.py:449-496` (`test_ultima_cuota_pagada_con_capital_pendiente_no_cierra`) passes today ONLY because it exercises an EXACT payment on the last regular cuota (10000+3600=13600, no shortfall) — `desglosar_arrastre(cuota_anterior, 0.00)` returns `(0,0)` regardless of the missing guard, so the bug is invisible to this test. The bug only manifests on a PARTIAL payment of the last regular installment, which is exactly Fernando Sanabria's prod case (m4 October installment 13-of-12, generated with inflated capital/interest, still unpaid).

`recalcular_cuota_actual_si_no_pagada` (`credito_service.py:879-926`, the "elif cuota_fija and numero_cuotas" branch used when admin edits capital/tasa mid-cycle) has the SAME missing guard: it re-derives `arr_cap`/`arr_int` from the previous paid row unconditionally, so if the CURRENT unpaid cuota is already past-term, an admin edit would re-inflate it the same way. Both sites need the numero > numero_cuotas carve-out.

`_calcular_virtuales` (`routers/pagos.py:453-483`) does NOT need the fix — it already stops projecting entirely once `n > credito.numero_cuotas` (line 478-483, `break`). Virtual (projected) rows are never generated past term; only real, persisted rows can exist there (created via `generar_siguiente_cuota` after a real payment). This is pre-existing, correct, and unrelated to the bug.

Spec conflict confirmed: `credit-closure/spec.md` requirement "Closure by Settled State Only" already documents the correct past-term behavior (no arrastre, same base value repeated) but `payment-carryover/spec.md` requirement "Shortfall Disaggregation" states shortfall MUST be added to the next cuota unconditionally with no numero_cuotas carve-out — the code follows the generic carryover path and never reaches the closure spec's exception because no code branch checks for it. `payment-carryover/spec.md` needs an explicit exception scenario for `numero_cuota > numero_cuotas`; `credit-closure/spec.md`'s existing scenario needs a companion scenario covering the PARTIAL (not just exact) case explicitly, since that's the actual gap.

## Affected Areas

- `frontend/src/pages/Pagos/PagosPage.tsx:688-695` — scope the capital-input disable/message to `tipo_credito === 'cuota_fija' && tipo_cuota === 'interes'` (needs `tipo_credito` on `Pago`).
- `frontend/src/types/index.ts:103-127` (`Pago` interface) — add `tipo_credito: TipoCredito` (already exists as a type, line 4).
- `backend/app/schemas/pago.py` (`PagoResponse`) — add `tipo_credito: TipoCredito` field (import from `app.models.credito`).
- `backend/app/routers/pagos.py:56-90` (`_pago_row_a_dict`), `:158-180` and `:247-274` (`listar_pagos`/`listar_aplazados` SELECT columns — `Credito` already joined in both) — add `Credito.tipo_credito` to selected columns and the dict.
- `backend/app/routers/pagos.py` virtual-row dict construction (~line 535-550) — add `"tipo_credito": credito.tipo_credito` for consistency (virtuales already carry `credito` in scope).
- `backend/app/services/pago_service.py:62-135` (`_validar_split`) — accept `tipo_credito` (or `credito`) param; branch the rule-13 message so it only fires for `cuota_fija`; add a distinct, factually-correct message for `abono_capital`.
- `backend/app/services/pago_service.py:184` / `:227` (`_pago_exacto`, `_pago_parcial`) — pass `credito.tipo_credito` into `_validar_split`.
- `backend/app/services/credito_service.py:608-654` (`_siguiente_cuota_fija`) — add `numero > credito.numero_cuotas` branch: base-only, no arrastre, uncapped, before/alongside the existing `saldo_capital <= 0` branch.
- `backend/app/services/credito_service.py:879-926` (`recalcular_cuota_actual_si_no_pagada`, cuota_fija branch) — same past-term carve-out for the currently-unpaid cuota.
- `openspec/specs/payment-carryover/spec.md` — add exception scenario to "Shortfall Disaggregation" for `numero_cuota > numero_cuotas`.
- `openspec/specs/credit-closure/spec.md` — add explicit PARTIAL-payment scenario alongside the existing exact-payment "Last installment reached with balance outstanding" scenario.
- `openspec/specs/abono-capital-carryover/spec.md` and/or a new spec — document the corrected `_validar_split` message scoping (currently silent on message text per credit type).
- Data correction: Fernando Sanabria's existing inflated, unpaid cuota 13-of-12 needs a one-off admin backfill (pattern precedent: `abono-capital-carryover-fix` archive, PR #31/#32 — dry-run + apply + remove-after-one-run). Recompute rule: for unpaid rows with `numero_cuota > numero_cuotas`, `tipo_credito == cuota_fija`, `capital_pagado = interes_pagado = 0`, and `capital_a_pagar/interes_a_pagar` exceeding the base (`calcular_capital_cuota_fija` / `calcular_interes_cuota_fija` recomputed on `capital_prestado`), reset components to base values (no arrastre) and recompute `monto_a_pagar`.
- Marelvis Mattos (Bug A) — confirmed UI-only: the guard only BLOCKED a valid split, it never wrote wrong data (frontend disabled input ⇒ no bad payment was ever persisted). No backfill needed for this case.
- Backend tests: `backend/tests/test_pago_service.py` (existing `test_ultima_cuota_pagada_con_capital_pendiente_no_cierra` covers exact-only; needs a new partial-payment sibling test), `backend/tests/test_credito_service.py` (likely home for `_siguiente_cuota_fija`/`recalcular_cuota_actual_si_no_pagada` unit tests — not yet inspected line-by-line, should be checked in spec/tasks phase).
- Test/build commands: backend `cd backend && python -m pytest` (or `backend/venv/Scripts/python.exe -m pytest` on Windows); frontend `cd frontend && npx tsc --noEmit` (no frontend test runner exists).

## Approaches

1. **Minimal targeted fix (recommended)** — add `tipo_credito` to the Pago payload (frontend+backend), scope the frontend guard and backend message by credit type; add the `numero > numero_cuotas` carve-out at both `_siguiente_cuota_fija` and `recalcular_cuota_actual_si_no_pagada`; ship a one-off backfill endpoint for Fernando Sanabria's existing bad row.
   - Pros: surgical, matches existing spec intent (credit-closure already describes the desired past-term behavior), reuses established backfill pattern, low review-budget risk (touches ~6 files, mostly small diffs).
   - Cons: two unrelated bugs in one change — needs care in tasks/PR splitting to stay within review budget and keep rollback independent per bug.
   - Effort: Medium.

2. **Introduce a distinct `TipoCuota` member for the past-term tail** instead of relying on `numero_cuotas` comparison at read time.
   - Pros: makes past-term installments self-describing.
   - Cons: new enum member needs the Postgres enum altered; `credit-closure/spec.md` Non-Goals explicitly say "reuse the existing `tipo_cuota` enum members". Directly conflicts with an existing non-goal.
   - Effort: High.

3. **Frontend-only fix using `capital_a_pagar <= 0` instead of `tipo_cuota === 'interes'`.**
   - Rejected: `capital_a_pagar` is ALWAYS exactly `0.00` for both the abono_capital interes cuota and the cuota_fija solo-interest tail — identical to the current buggy condition. Documented to prevent this dead-end being retried in design.

## Recommendation

Approach 1. Smallest change that resolves both bugs, aligns with the existing `credit-closure` spec wording, respects the non-goal against new enum members/migrations, and follows the one-off-backfill-then-delete pattern. Split into two focused PRs (Bug A: tipo_credito plumbing + guard scoping + message scoping; Bug B: past-term carve-out + backfill) to keep each diff small and independently revertable.

## Risks

- `_validar_split` signature change touches two call sites (`_pago_exacto`, `_pago_parcial`) — re-check with a global grep in apply.
- The `numero > numero_cuotas` carve-out must be added at BOTH `_siguiente_cuota_fija` and `recalcular_cuota_actual_si_no_pagada` or the two paths diverge again (same class as the `saldo_capital` reset-on-edit defect, see comments at `credito_service.py:895` and `:941`).
- Backfill must recompute using `calcular_capital_cuota_fija`/`calcular_interes_cuota_fija` on ORIGINAL `capital_prestado` (simple-interest model). Must audit via `audit_service.registrar_*` per AGENTS.md.
- Backfill must scan ALL qualifying rows (unpaid, `numero_cuota > numero_cuotas`, `tipo_credito=cuota_fija`, components above base), not hardcode a single credit ID.
- `backend/tests/test_credito_service.py` not read line-by-line; confirm structure before writing new unit tests.

## Ready for Proposal

Yes — scope, root causes, and affected files verified against running code.
