# Tasks: Recaudo registers amounts, Registrador reverts amounts

Change: `recaudo-registra-montos-registrador-supervisa`
Mode: Strict TDD (RED -> GREEN -> refactor per work unit). Test runner: pytest (backend), per sdd-init.
Chain: stacked-to-main. Each PR branches from the freshly updated `main` and merges to `main` before the next branch is cut. Not a feature-branch chain.
Commits: Spanish conventional commits, no AI attribution. Backend and frontend of one concern may share a commit (AGENTS.md).

Spec amendments applied (D5, D6): a restored scheduled cuota keeps its stored amounts (no `recalcular_cuota_actual_si_no_pagada` for scheduled targets); reverting a `no_programada` payment soft-deletes it and its repartos, then recomputes the current cuota.

## Review Workload Forecast

| PR | Slice | Est. changed lines | Risk vs 400 budget |
|----|-------|--------------------|--------------------|
| PR1 | Role gates (3 endpoints) + role matrix tests | ~120 | Low |
| PR2a | Pure helpers (`reduccion_efectiva`, `saldos_por_cronograma`, `reabrir_credito`), `soft_delete_repartos_de_pago`, `ResultadoReversion`, `PagoService.revertir_monto`, unit tests | ~310 | Medium (under budget, little slack) |
| PR2b | `RevertirMontoRequest`, `POST /pagos/{id}/revertir-monto`, guards, audit, integration tests | ~400 | HIGH (at budget; split tests into PR2b-i / PR2b-ii if it exceeds) |
| PR3 | Frontend: `authStore`, API client, `PagosPage` button + modal | ~115 | Low |
| Total | | ~945 | Exceeds 400 as a single PR |

- Chained PRs recommended: YES (4 PRs, optionally 5 if PR2b is split). A single PR is not reviewable within the 400-line budget.
- Decision needed before apply: confirm the PR2b split policy. Proposed default: implement PR2b as one PR; if the diff measured after GREEN exceeds 400 lines, move the integration test groups T2b.7-T2b.9 to a follow-up PR2b-ii (endpoint and guard/round-trip core tests stay in PR2b-i). Also confirm accepted open question: backdated `no_programada` may sort before a later-registered scheduled payment (design Open Question 2).
- Dependency order is strictly sequential: PR1 -> PR2a -> PR2b -> PR3. PR2b depends on PR2a helpers; PR3 depends on the PR2b endpoint. PR1 is independent of PR2a, but sequential merging is kept for simplicity.
- Backend-only PRs (1, 2a, 2b) ship no user-visible UI. The recaudador UI and the Revertir monto button become visible only after PR3. Between PR1 and PR3, the recaudador can register through the API only.

---

## PR1 - Role gates (branch `feat/recaudador-registra-montos`)

Spec: pagos / "Recaudador May Register Amounts".

- [x] T1.1 RED: create `backend/tests/test_registro_roles.py` with a role matrix for `POST /pagos/{id}/registrar`, `POST /pagos/{id}/confirmar-excedente`, `POST /pagos/no-programado/{credito_id}`. Cases: admin, registrador, recaudador -> 2xx (recaudador on a payment validated by another user); gestor -> 403 with no state change. Reuse fixtures from `test_desvalidar_pago.py`. Confirm recaudador cases fail (403) and the admin/registrador/gestor cases already pass.
- [x] T1.2 GREEN: in `backend/app/routers/pagos.py` add `recaudador` to the `require_role` of the three endpoints. Run `test_registro_roles.py` and the existing pagos tests; all green.
- [x] T1.3 Refactor: de-duplicate test setup helpers if repeated; no production refactor expected.
- [x] T1.4 Commit: `feat(pagos): permitir al recaudador registrar montos, confirmar excedente y registrar pago no programado`.

## PR2a - Helpers and service (branch `feat/revertir-monto-servicio`)

Spec: payment-amount-reversal / "Installment Restore", "Successor Installment Removal", "Credit Balance Recompute", "Credit Reopen". Design D2-D7.

Work unit A: `reduccion_efectiva` (D4)
- [x] T2a.1 RED: create `backend/tests/test_saldos_cronograma.py` with unit tests for `reduccion_efectiva(pago) -> (capital, interes)`: exact payment, partial, excedente with destino capital, excedente with destino intereses, `no_programada`. All `Decimal`.
- [x] T2a.2 GREEN: add `reduccion_efectiva` in `backend/app/services/credito_service.py`, mirroring `confirmar_excedente` (destino authoritative).
- [x] T2a.3 Commit: `feat(creditos): agregar reduccion_efectiva para recomponer saldos por cronograma`.

Work unit B: `saldos_por_cronograma` (D2)
- [x] T2a.4 RED: tests for `saldos_por_cronograma(credito, pagados)` returning `R(paid)`: cuota_fija base formula, abono_capital (interest 0), floor-at-zero clipping, and the anchored-delta formula `new = stored + (R(paid \ {P}) - R(paid))` with injected drift in the stored saldos (drift must be preserved, not overwritten).
- [x] T2a.5 GREEN: implement `saldos_por_cronograma` in `credito_service.py`.
- [x] T2a.6 Commit: `feat(creditos): calcular saldos desde el cronograma con piso en cero`.

Work unit C: `reabrir_credito` (D7) and repartos wrapper
- [x] T2a.7 RED: tests for `reabrir_credito(credito) -> bool`: returns True and sets `activo=True` when `activo=False`; returns False and leaves state when already active; sole writer of False -> True.
- [x] T2a.8 GREEN: implement `reabrir_credito`; add public `soft_delete_repartos_de_pago` wrapper in `backend/app/services/pago_reparto_service.py`.
- [x] T2a.9 Commit: `feat(creditos): agregar reabrir_credito y borrado logico publico de repartos`.

Work unit D: `PagoService.revertir_monto`
- [x] T2a.10 RED: service-level tests (DB fixtures) for `revertir_monto(db, pago, credito, pagos_credito) -> ResultadoReversion`: scheduled restore (pagado False, montos 0, `fecha_pago_real` None, `es_excedente_a` None, `validado_recaudador`/`tipo_validacion` kept, stored `*_a_pagar`/`es_ultimo_pago` untouched per D5); successor N+1 soft-deleted; repartos soft-deleted; `no_programada` soft-deleted with repartos then current-cuota recompute (D6); settled-credit reopen; regla 14 reopen with `saldo_intereses = R(paid \ {P})` (D3); open credit `activo` unchanged; `ResultadoReversion.cambios` lists pago/credit/successor changes for audit.
- [x] T2a.11 GREEN: add `ResultadoReversion` and `revertir_monto` in `backend/app/services/pago_service.py` following the data-flow order: repartos -> restore or soft-delete P -> soft-delete N+1 -> saldos (D2/D3) -> reopen (D7) -> `no_programada` only: `recalcular_cuota_actual_si_no_pagada`. The service performs no commit/audit (router audits).
- [x] T2a.12 Refactor: tidy helpers and naming; run full backend suite.
- [x] T2a.13 Commit: `feat(pagos): agregar servicio revertir_monto con restauracion de cuota y recomputo de saldos`.

Note: if PR2a exceeds ~400 lines, move work unit D (T2a.10-T2a.13) to its own PR (PR2a-ii) before PR2b.

Applied 2026-10-21: units A-C measured 300 changed lines on `feat/revertir-monto-servicio` (3 commits, 17 new tests). Unit D forecast >= 200 more lines (service ~80 + DB-fixture tests ~150), so it is deferred to PR2a-ii (T2a.10-T2a.13), cut from `main` after PR2a merges. Added helper `saldos_tras_reversion` (D2 anchored delta + D3 reopen replay) so the drift-injection test of T2a.4 exercises production code; `revertir_monto` must call it BEFORE restoring the pago and BEFORE `reabrir_credito`.

Applied 2026-10-21 (PR2a-ii): unit D (T2a.10-T2a.13) done on `feat/revertir-monto-servicio-ii`, commit `cce3905`, 385 changed lines (101 prod + 284 tests), full suite 720 passed. Public `PagoService.cuotas_sucesoras(pago, pagos_credito)` added so the PR2b successor guard (T2b.5 guard 3) reuses the same lookup. Guards stay in the router. `ResultadoReversion.cambios` = `CambioReversion(entidad, entidad_id, campos, eliminado)`; the router adds the `motivo_reversion` pseudo-field. Not covered here, left for T2b.10: re-registration after revert and the multi-recipient split case (`aplicar_herencia` clears `pago.cuenta_bancaria_id`, so a re-registered pago gets no default reparto).

## PR2b - Endpoint, guards, audit (branch `feat/revertir-monto-endpoint`)

Spec: payment-amount-reversal / "Role Gate", "Revertible Target", "LIFO Guard", "Optional Reason, Audit and Concurrency". Design D1, D8.

Work unit E: schema + role gate + revertible target
- [x] T2b.1 RED: create `backend/tests/test_revertir_monto.py` (httpx ASGI + SQLite fixtures as in `test_desvalidar_pago.py`). Tests: admin and registrador -> 2xx; recaudador and gestor -> 403 with no state change; unpaid cuota -> 422 plain-string detail; double call -> first 2xx, second 422, only first call's audit entries exist; reason omitted -> 2xx.
- [x] T2b.2 GREEN: add `RevertirMontoRequest` (`motivo: str | None`, max 500) in `backend/app/schemas/pago.py`; add `POST /pagos/{pago_id}/revertir-monto` in `backend/app/routers/pagos.py` with `require_role(admin, registrador)` first, `_get_pago_con_credito(lock=True)`, `SELECT ... FOR UPDATE` of the credit's pagos ordered `(numero_cuota, id)`, guard 1 (pagado), call `PagoService.revertir_monto`, return `PagoResponse`.
- [x] T2b.3 Commit: `feat(pagos): agregar endpoint revertir-monto con control de rol`.

Work unit F: LIFO and successor guards
- [x] T2b.4 RED: tests: P1 then P2 -> revert P1 is 422 (message says to revert later payments first) and nothing changes; revert P2 is 2xx, then revert P1 is 2xx; scheduled P1 followed by registered `no_programada` U -> revert P1 422 until U is reverted; successor with `capital_pagado > 0` or `pagado=True` -> 422 with no state change and no audit; more than one unpaid successor -> 422 (inconsistent); no successor (final cuota / settled closure / `no_programada`) -> 2xx.
- [x] T2b.5 GREEN: implement guards 2 (LIFO by `(fecha_pago_real, created_at, id)`, counting `no_programada`) and 3 (successor), each with `logger.warning` like `_rechazar_desvalidar`; rejections raise before any write.
- [x] T2b.6 Commit: `feat(pagos): agregar guardas LIFO y de cuota sucesora a revertir-monto`.

Work unit G: audit
- [x] T2b.7 RED: tests: successful revert writes audit entries attributed to the caller with `pagado` True -> False, `motivo_reversion` when given, credit saldos/`activo`, and successor/`no_programada` deletion; rejected calls write no audit entries.
- [x] T2b.8 GREEN: in the router, audit via `registrar_actualizacion_campos` (pago fields + `motivo_reversion` pseudo-field, credit saldos/activo) and `registrar_eliminacion` (successor / `no_programada`); no `audit_service` changes (D8).
- [x] T2b.9 Commit: `feat(pagos): auditar la reversion de monto`.

Work unit H: round trips and cascades (integration; candidates for PR2b-ii if over budget)
- [x] T2b.10 RED: tests: round trip (snapshot before registrar -> registrar -> revert -> compare) for cuota_fija, abono_capital (`saldo_intereses` stays 0), excedente-to-intereses (`es_excedente_a` cleared), floor-at-zero; restored cuota can be registered again; settled credit reopens with a single unpaid validated cuota; regla 14 reopen with `saldo_intereses` reflecting the schedule (not zero); repartos soft-deleted and re-registering recreates exactly one; receptor ledger decreases and may go negative; `desvalidar` after revert works; `no_programada` revert soft-deletes pago and repartos and re-derives arrastre; concurrency limited to sequential double-call (SQLite ignores FOR UPDATE; note in test docstring).
- [x] T2b.11 GREEN: fix any gaps the tests expose in `revertir_monto` / router; no new design decisions (escalate if D2-D7 are contradicted by results).
- [x] T2b.12 Refactor and full backend suite run; verify no float usage and ORDER BY ends in PK.
- [x] T2b.13 Commit: `test(pagos): cubrir reversion de monto en ciclos completos, reapertura y repartos`.

Applied 2026-10-21 (PR2b-i): units E, F, G (T2b.1-T2b.9) done on `feat/revertir-monto-endpoint` (cut from main daffb07), 4 local commits (`0f690f2` E, `392db43` F, `89d43f5` G, `34ae933` LIFO ordering fix), 399 changed lines (80 router + 9 schema + 310 tests), full suite 736 passed. Unit H (T2b.10-T2b.13) is NOT started: it is PR2b-ii (budget exhausted). The audit loop (G production) was kept in PR2b-i because a mutating endpoint without audit would break the AGENTS.md audit rule; only the test-only unit H and the declarative `max_length=500` boundary test move to PR2b-ii.
Spec amendment needed (LIFO Guard, found by running the H scenarios through the router): a scheduled cuota's own `created_at` is its GENERATION time (created when the previous cuota is paid), not its registration time. With the literal key `(fecha_pago_real, created_at, id)`, a `no_programada` registered after cuota N is generated but before N is paid, on the same day, sorts AFTER N, so the guard blocks reverting the true latest payment and forces reverting the `no_programada` first, which on `abono_capital` leaves N with a stale `interes_a_pagar`/`monto_a_pagar` (e.g. 72500 instead of 78500). Fix applied (commit `34ae933`): the registration instant of a `no_programada` is its `created_at`; for a scheduled cuota it is the `created_at` of its live scheduled successor (created in the same transaction), falling back to its own `updated_at` when there is no successor (closing payment). Key is `(fecha_pago_real, instant, id)`; still never `numero_cuota`. The spec text "then created_at" should read "then registration instant".
T2b.10 decision (multi-recipient split): NO production change. After a 2+ recipient split `aplicar_herencia` leaves `pago.cuenta_bancaria_id = None`; a reverted pago keeps None and a re-registration creates no default reparto (money unattributed, invariant I1 not met) because there is no single account to restore (2+ accounts; audit_log reads are excluded by D2/D3) and guessing one would misattribute cash in the receptor ledger. Verified recovery, both with the existing `PATCH /pagos/{id}/cuenta-bancaria` (admin/recaudador): assign the account on the restored cuota BEFORE re-registering, or on the paid pago AFTER; either creates the default reparto. Deviation from the literal spec scenario "Re-registration recreates default reparto" only for pagos whose account was cleared by a split. PR2b-ii should pin this with a test.
Applied 2026-10-22 (PR2b-ii): unit H (T2b.10-T2b.13) done on `feat/revertir-monto-pruebas-ida-vuelta` (cut from main 9802388), commit `9337baf`, TESTS ONLY: `backend/tests/test_revertir_monto_ida_vuelta.py`, 398 changed lines, 19 tests; full suite 755 passed (736 + 19). T2b.11: the tests exposed no gap, so no production change (35 of 36 mutation probes killed; the survivor is an equivalent mutant, see apply-progress). Coverage: 10 LIFO round-trip scenarios, each run twice (the restored cuota is registered and reverted again); a fortnightly regla 14 closure that pins the payments-per-month divisor of the D3 replay (no earlier test used a non-monthly credit); settled-credit reopen; repartos and receptor ledger (decrease, negative allowed, exactly one reparto after re-registration); `desvalidar` before and after revert (admin, recaudador); the multi-recipient pin (two tests); the `max_length=500` boundary moved out of PR2b-i; second call on a reverted `no_programada` is 404. Concurrency stays limited to the sequential double call (SQLite ignores FOR UPDATE).

## PR3 - Frontend (branch `feat/frontend-revertir-monto`)

Spec: pagos / "Frontend Registration Permission"; payment-amount-reversal / "Frontend Action". No frontend runner: verification is the manual checklist below (Strict TDD not applicable to frontend; backend contract is already covered).

- [x] T3.1 `frontend/src/store/authStore.ts`: `canRegistrarPago` adds `recaudador`; add `canRevertirMonto` (admin, registrador only). `canValidarPago` unchanged.
- [x] T3.2 `frontend/src/api/index.ts`: add `revertirMonto(id, motivo?)` posting to `/pagos/{id}/revertir-monto` via the shared axios instance.
- [x] T3.3 `frontend/src/pages/Pagos/PagosPage.tsx`: "Revertir monto" button shown when `!es_proyectada && canRevertirMonto && pagado` (weekly and daily views), confirmation modal with optional motivo textarea, `handleRevertirMonto` cloned from `handleDesvalidar` (control disabled while in flight; toast with `e.response?.data?.detail` verbatim, never the literal `Error`; refetch after success or 4xx).
- [x] T3.4 Type-check and lint the frontend build (`tsc`/build as configured).
- [ ] T3.5 Manual checklist (record results in the PR description): admin and registrador see the button on paid rows; recaudador and gestor do not; recaudador sees register actions on validated unpaid rows; revert of a non-latest payment shows the backend LIFO message and refreshes; successful revert refreshes and the row returns to validated unpaid; double click does not fire twice; daily view behaves identically.
- [x] T3.6 Commit: `feat(frontend): permitir al recaudador registrar y agregar accion Revertir monto`.

Applied 2026-10-22 (PR3): T3.1-T3.4 and T3.6 done on `feat/revertir-monto-frontend` (cut from main 729ff6e; the branch name differs from the planned `feat/frontend-revertir-monto`), ONE commit `3cab138`, 3 files, 108 insertions + 2 deletions = 110 changed lines (authStore +4/-1, api client +5, PagosPage +99/-1). `npm run build` (`tsc && vite build`) passes; the frontend has NO linter configured (no ESLint/Prettier/Biome in package.json, node_modules or repo), so `tsc` strict is the only static check. GGA review on commit: PASSED. `PagosPage` is ONE component for every variant (`regular`, `semanal`, `diario`, `aplazados`: routes in App.tsx) with a single table, so the one button covers the weekly and daily views. Handler/modal cloned from `handleDesvalidar`: `mensajeError` (backend `detail` verbatim, never the literal `Error`), refetch after success or any error that carries a server response (except expired session), confirm and row controls disabled while in flight, modal stays open on error so the reason is not lost. Textarea `maxLength=500` (backend `max_length=500`; a longer body would be a 422 with a LIST `detail`, which `mensajeError` joins). Recaudador also gets "Registrar pago" and "Pago No Programado" through `canRegistrarPago`. T3.5 (manual checklist) is NOT executed: see the checklist in the PR description. Extra, uncommitted evidence: a throwaway jsdom harness (vitest, scratchpad only) ran the REAL PagosPage with the API mocked: 41 tests green (role matrix x weekly/daily, flow, LIFO message verbatim, in-flight double click, error paths), and 23 of 23 deliberate source mutations were killed.

## Spec coverage map

| Requirement | Tasks |
|-------------|-------|
| pagos: Recaudador May Register Amounts | T1.1-T1.2 |
| pagos: Frontend Registration Permission | T3.1, T3.5 |
| amount-reversal: Role Gate | T2b.1-T2b.2 |
| amount-reversal: Revertible Target | T2b.1-T2b.2 |
| amount-reversal: LIFO Guard | T2b.4-T2b.5 |
| amount-reversal: Installment Restore | T2a.10-T2a.11, T2b.10 |
| amount-reversal: Successor Installment Removal | T2a.10-T2a.11, T2b.4-T2b.5 |
| amount-reversal: Credit Balance Recompute | T2a.1-T2a.6, T2b.10 |
| amount-reversal: Credit Reopen | T2a.7-T2a.8, T2a.10, T2b.10 |
| amount-reversal: Optional Reason, Audit, Concurrency | T2b.1, T2b.7-T2b.8 (concurrency: sequential only) |
| amount-reversal: Frontend Action | T3.1-T3.5 |
| receptor-ledger / pago-repartos deltas | T2a.8, T2b.10 |

## Risks

- PR2b sits at the 400-line budget; the split contingency is defined above.
- Concurrency cannot be proven on SQLite; only `FOR UPDATE` presence is reviewed.
- `saldos_por_cronograma` anchored-delta correctness depends on non-negative reductions; keep the drift-injection test (T2a.4).
- Interim state between PR1 and PR3: recaudador permitted by API but not by UI.
