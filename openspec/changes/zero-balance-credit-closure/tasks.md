# Tasks: Zero-Balance Credit Closure

**Re-validated against spec revision 2** (10 requirements, 26 scenarios, obs #894). Every
task below carries `esta_saldado` as: `cuota_fija` settled iff `saldo_capital <= 0` AND
`saldo_intereses <= 0`; `abono_capital` settled iff `saldo_capital <= 0` only (no
`saldo_intereses` involvement). No task uses `saldo_capital` alone for `cuota_fija`.

**Language note (rule 13)**: task prose stays English. All `HTTPException(detail=...)`
strings and new frontend display copy are user-facing Spanish product text — neutral,
professional register, no regionalisms. `sdd-apply` must not default to English UI copy.

**Status codes (design-pinned, spec-confirmed)**: confirm endpoint — 404 unknown credit →
422 already closed → 422 not settled → 200 success; 403 forbidden role (via
`require_role`, evaluated ahead of the body). Backfill: 403 non-admin. Every task
asserting these codes must assert the exact code, not just "rejected".

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~730 (PR1 ~230, PR2 ~230, PR3 ~270) |
| 400-line budget risk | High |
| Chained PRs recommended | Yes |
| Suggested split | PR 1 → main, PR 2 → PR 1 branch, PR 3 → PR 2 branch |
| Delivery strategy | auto-forecast |
| Chain strategy | stacked-to-main |

Decision needed before apply: No
Chained PRs recommended: Yes
Chain strategy: stacked-to-main
400-line budget risk: High

**Seam re-evaluated: the 2-PR split no longer holds; moved to 3 PRs.** Re-validation
against spec revision 2 surfaced 5 uncovered scenarios (see mapping below) whose RED
tests would have pushed the original PR1 (~378 lines) well past 400. This activates the
design's own documented fallback: the interest-only tail and its settled predicate
become a **leading PR1**; the single-writer/closure-wiring work (plus the new
gap-filling tests) becomes **PR2**; reads/confirm/backfill/frontend stays **PR3**. Each
PR now independently forecasts under 400.

### Suggested Work Units

| Unit | Goal | PR | Focused test | Runtime harness | Rollback boundary |
|---|---|---|---|---|---|
| 1 | Settled predicate + interest-only tail | 1 | `pytest tests/test_credito_service.py` | Unmocked aiosqlite integration tests | Revert `credito_service.py` tail/predicate diff; no payment-closure wiring touched |
| 2 | Single writer + closure wiring + gap tests | 2 | `pytest tests/test_pago_service.py` | Unmocked aiosqlite integration tests | Revert `pago_service.py` diff; PR1 stays intact |
| 3 | Read filters, confirm/backfill endpoints, frontend | 3 | `pytest tests/test_creditos_router.py tests/test_pagos_router.py`; `npx tsc --noEmit` | httpx AsyncClient integration tests | Revert routers/schemas/frontend diff independently of PR1/PR2 |

## Phase 1: Settled Predicate + Interest-only Tail (PR 1 → main)

- [x] 1.1 RED: `esta_saldado` — cuota_fija capital=0/interest>0 not settled; both=0 settled; abono_capital capital=0 settled, ignores `saldo_intereses` (Req: Settled Definition, both scenarios)
- [x] 1.2 GREEN: add `esta_saldado(credito)` to `credito_service.py`
- [x] 1.3 RED: interest-only installment — `capital_a_pagar==0`, `interes_a_pagar==min(base,saldo)`, `tipo_cuota==interes`; cap binds on final installment; degenerate `tasa=0` bills remainder in one installment (Req: Interest-only Tail — Tail generated, No overcharge)
- [x] 1.4 GREEN: change `generar_siguiente_cuota:415` guard to `esta_saldado`; add interest-only branch in `_siguiente_cuota_fija`
- [x] 1.5 RED: integration, unmocked — capital settles/interest remains → stays active, interest-only installment generated; paying tail to zero → closes, no further installment (Req: Interest-only Tail — Tail terminates)
- [x] 1.6 RED: exact payment of interest-only installment does not 422; `capital_pagado>0` on one does 422, AND (rule 13) asserts the `detail` explains the installment is interest-only because capital is settled (neutral professional Spanish) — extend, do not duplicate (Req: Operator-Readable Rejection Messages, capital-against-interest-only scenario)
- [x] 1.7 GREEN: rewrite that `ValueError` text in the **service layer** (`pago_service.py` `_validar_split`, ~lines 99-108 — NOT the router pass-throughs at `pagos.py:494/546/725`, which stay `str(exc)` unchanged) with the rule-13 explanatory Spanish message
- [x] 1.8 RED: `es_ultimo_pago` false when followed by the interest-only tail, true only when the cap binds (Req: Past-term Installments Are Explainable, last-installment indicator scenario)
- [x] 1.9 GREEN: redefine `es_ultimo_pago` (`credito_service.py:458`, `:669`)
- [x] 1.10 RED: `recalcular_cuota_actual_si_no_pagada` reproduces the interest-only shape after an admin edit (Req: Admin Capital Edit, interest-only preserved across edit)
- [x] 1.11 GREEN: update `recalcular_cuota_actual_si_no_pagada` (`credito_service.py:624-669`)
- [x] 1.12 Verify: `pytest tests/test_credito_service.py` — 0 failures

## Phase 2: Single Writer + Closure Wiring (PR 2 → PR 1 branch)

- [ ] 2.1 RED: `cerrar_credito` never writes either balance; second call returns `False` (Req: Closure by Settled State Only, "no path may write balances")
- [ ] 2.2 GREEN: add `cerrar_credito(credito)` to `credito_service.py`
- [ ] 2.3 RED: rewrite `test_cierre_al_alcanzar_ultima_cuota` — final installment paid with balance left MUST stay `activo=True`, generate a same-value installment, no carryover (Req: Closure by Settled State Only, last-installment-reached-with-balance scenario; deletes the debt-forgiveness assertion)
- [ ] 2.4 GREEN: delete `_verificar_cierre_credito` (`pago_service.py:337-364`); wire `esta_saldado`/`cerrar_credito` into `_pago_exacto`, `_pago_parcial`, `confirmar_excedente`; keep `registrar_pago_no_programado` early-return keyed on `esta_saldado`
- [ ] 2.5 RED: confirm existing `test_cierre_al_llegar_saldo_cero` still passes unmodified — locks the generic "payment settles the credit" scenario for `_pago_exacto` (regression lock, Req: Closure by Settled State Only)
- [ ] 2.6 RED: `_pago_parcial` and `confirmar_excedente` also close on reaching settled, unmocked — the two of four settling paths with no prior coverage (Req: Closure by Settled State Only, "payment settles the credit")
- [ ] 2.7 RED: unscheduled-payment settle test (`registrar_pago_no_programado`), unmocked — the fourth path (Req: Closure by Settled State Only, "payment settles the credit"; "Real path without mocking")
- [ ] 2.8 RED: under-paid final installment never forgives debt — both balances retain their real remaining amounts, `activo` stays `True`, unmocked (Req: Closure by Settled State Only, under-paid final installment)
- [ ] 2.9 RED: `abono_capital` credit closes when `saldo_capital` reaches `0.00`, unmocked (Req: Abono Capital Closure, settled abono capital credit)
- [ ] 2.10 RED: `abono_capital` paid interest rounds `ROUND_HALF_UP` to 2 decimals — add coverage if none exists; this is pre-existing behavior being locked, not new logic (Req: Abono Capital Closure, interest rounding)
- [ ] 2.11 Verify: `cd backend && python -m pytest` — 0 failures, ≥ baseline 246 + new tests

## Phase 3: Read Paths, Confirmation, Backfill, Frontend (PR 3 → PR 2 branch)

- [ ] 3.1 GREEN: add `credito_operativamente_abierto()` SQL predicate to `credito_service.py`
- [ ] 3.2 RED: settled credit absent from `resumen-cartera` and `GET /pagos` (real + virtual rows); capital-settled/interest-bearing credit still present (Req: Operationally Open Credits, both scenarios)
- [ ] 3.3 GREEN: apply predicate at `creditos.py:101-106`, `pagos.py:279` (`_calcular_virtuales`), `pagos.py:128-147` (unpaid rows only), `pagos.py:766`/`:796` alerts
- [ ] 3.4 GREEN: add `pendiente_de_cierre` to `schemas/credito.py`; PATCH handler exposes it without touching `activo`
- [ ] 3.5 RED: admin PATCH zeroing capital → `activo` stays `True`, `pendiente_de_cierre` true (Req: Admin Capital Edit, edit-settles-the-credit scenario)
- [ ] 3.6 RED: `POST /creditos/{id}/cerrar` — unknown credit `404`; already-closed `422`; not-settled `422`; each allowed role `200`; `gestor` `403` — assert the exact codes and evaluation order (Req: Explicit Closure Confirmation, all 4 scenarios + pinned status codes). (Rule 13) also assert `detail`: already-closed states closure cannot be confirmed twice; not-settled names WHICH balance remains (capital, interest, or both) and its amount — neutral professional Spanish
- [ ] 3.7 GREEN: implement confirm endpoint in `creditos.py` (404 → 422 closed → 422 not settled → `cerrar_credito` → `audit_service.registrar_actualizacion_campos`) with the rule-13 `detail` strings above
- [ ] 3.8 RED: backfill — settled credits closed; capital-only-settled `cuota_fija` left open; second run zero corrections; non-admin `403` (Req: One-off Closure Backfill, all 3 scenarios)
- [ ] 3.9 GREEN: implement `POST /creditos/admin/backfill-cierre-saldo-cero` (temporary, admin-only)
- [ ] 3.10 Frontend: add `pendiente_de_cierre` to `types/index.ts`; `creditosApi.cerrar(id)` in `api/index.ts`
- [ ] 3.11 Frontend: `CreditosPage.tsx` — badge state + confirm button (allowed roles) via `ConfirmDialog`; this NEW call site's `catch` MUST read `e.response?.data?.detail` from the start (Req: Operator-Readable Rejection Messages, frontend-surfaces-the-reason scenario)
- [ ] 3.12 Frontend: `PagosPage.tsx` — lock/disable `capital_pagado` input to 0 when `tipo_cuota === 'interes'`. `PagosPage.tsx:151` already reads `detail` correctly for the resulting rejection — verified, no fix needed there
- [ ] 3.13 (Rule 13) Frontend audit, scoped to this change's rejection paths only: fix swallow-sites `CreditosPage.tsx:71,92` and `ClientesPage.tsx:52,141,149` to read `detail` before `toast.error(...)`. `PagosPage.tsx:100` also swallows but is unrelated to a rejection path this change introduces — note only, out of scope, do not fix. Do not widen to a repo-wide refactor
- [ ] 3.14 Frontend: `CreditosPage.tsx` — informational note when `numero_cuota` exceeds `numero_cuotas` (interest-only tail), neutral professional Spanish, display only, not a rejection (Req: Past-term Installments Are Explainable, beyond-agreed-term scenario)
- [ ] 3.15 Verify: `cd backend && python -m pytest` full suite green; `cd frontend && npx tsc --noEmit` clean

## Phase 4: Follow-up (post-deploy)

- [ ] 4.1 Run backfill endpoint once in production as admin; confirm `resumen-cartera` drops accordingly
- [ ] 4.2 Remove `POST /creditos/admin/backfill-cierre-saldo-cero`, its schema/response model, and its tests (same pattern as the archived arrastre backfill)

## Scenario Coverage Map (spec revision 2, 26 scenarios — all mapped, 0 gaps)

| Requirement | Scenarios | Task(s) |
|---|---|---|
| Settled Definition | 2/2 | 1.1 |
| Closure by Settled State Only | 4/4 | 2.3, 2.5, 2.6, 2.7, 2.8 |
| Interest-only Installment Tail | 3/3 | 1.3, 1.5 |
| Abono Capital Closure and Interest Rounding | 2/2 | 2.9, 2.10 |
| Operationally Open Credits Only on Read Paths | 2/2 | 3.2 |
| Admin Capital Edit Does Not Auto-Close | 2/2 | 1.10, 3.5 |
| Explicit Closure Confirmation | 4/4 | 3.6 |
| Operator-Readable Rejection Messages | 4/4 | 1.6, 3.6, 3.11 |
| Past-term Installments Are Explainable | 2/2 | 1.8, 3.14 |
| One-off Closure Backfill | 3/3 | 3.8 |
