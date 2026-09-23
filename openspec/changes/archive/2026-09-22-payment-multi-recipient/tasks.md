# Tasks: Payment Multi-Recipient Split (item 10)

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | PR1 ~350; PR2 ~350; PR3 ~350 |
| 400-line budget risk | Medium |
| Chained PRs recommended | Yes |
| Suggested split | PR 1 (foundation/ledger) → PR 2 (split API/reports) → PR 3 (frontend) |
| Delivery strategy | ask-on-risk |
| Chain strategy | stacked-to-main |

Decision needed before apply: Yes
Chained PRs recommended: Yes
Chain strategy: stacked-to-main
400-line budget risk: Medium

### Suggested Work Units

| Unit | Goal | Likely PR | Focused test command | Runtime harness | Rollback boundary |
|------|------|-----------|----------------------|-----------------|-------------------|
| 1 | Model + migration + backfill + default reparto + ledger rewrite, no visible API change | PR 1 | `pytest backend/tests/test_receptor_ledger_service.py backend/tests/test_pago_reparto_service.py -q` | Staging Postgres: `alembic upgrade head`, verify Σ(pago_repartos.monto) == Σ(capital_pagado+interes_pagado) for paid pagos pre/post | Revert PR 1; `alembic downgrade -1` drops table+enum, `Pago.cuenta_bancaria_id` untouched |
| 2 | Split schemas, GET/PUT `/repartos`, inheritance rule, EXISTS filter, `reportes.py` rewrite | PR 2 | `pytest backend/tests/test_pago_reparto_router.py backend/tests/test_pagos_router.py backend/tests/test_reportes.py -q` | Staging: PUT a 2-recipient split, confirm `GET /pagos?receptor_id=` matches once and revenue report splits correctly | Revert PR 2 only; PR 1's default-row behavior and ledger keep working |
| 3 | Frontend `RepartoPagoModal.tsx` + `PagosPage.tsx` integration | PR 3 | TypeScript build (`npm run build` in `frontend/`) — no test runner in repo | Manual: open a paid pago, split across 2 recipients, confirm submit disabled until remainder is 0 | Revert PR 3 only; backend split API from PR 2 unaffected |

## Phase 1: Model, Migration & Default Reparto (PR 1) — COMPLETE 2026-09-22

**PR1 actual (2026-09-22)**: production code landed at 341 changed lines (close to the ~350 estimate), but total changed lines including Strict-TDD test code reached 764 (341 production + 423 tests, across 4 new files + 8 modified files). See apply-progress for the full breakdown — flagged as a risk for the post-apply review routing (likely crosses the 400-line "Hot path" tier).

- [x] 1.1 Create `backend/app/models/pago_reparto.py`: `TipoDestinatario` enum, `PagoReparto(AuditMixin, Base)` with `pago_id`, `tipo_destinatario`, `cuenta_bancaria_id`, `cliente_id`, `monto`, CHECK `ck_pago_repartos_monto_positivo`, CHECK `ck_pago_repartos_destinatario`.
- [x] 1.2 Add `Pago.repartos` relationship (`lazy="noload"`) in `backend/app/models/pago.py`; register model in `backend/app/models/__init__.py`.
- [x] 1.3 **[Enum-drop task]** Create migration `backend/alembic/versions/f6a7b8c9d0e1_create_pago_repartos.py` (`down_revision='e5f6a7b8c9d0'`): `upgrade()` creates table + 2 indexes + backfill `INSERT ... SELECT` (`WHERE pagado AND cuenta_bancaria_id IS NOT NULL AND capital_pagado + interes_pagado > 0`); `downgrade()` drops indexes, drops table, explicitly drops `tipo_destinatario_reparto_enum`.
  - Evidence: `alembic heads` → single head `f6a7b8c9d0e1` (chain resolves cleanly on top of `e5f6a7b8c9d0`). Backfill SQL matches design.md verbatim. Not executed against real Postgres in this environment (no Postgres available); staging verification remains per design's Testing Strategy ("checked manually on staging Postgres").
- [x] 1.4 RED: write `backend/tests/test_pago_reparto_service.py` — `crear_reparto_por_defecto` creates exactly one 100% row matching `capital_pagado + interes_pagado`; no row created when `cuenta_bancaria_id` is null.
  - Evidence: RED confirmed via `ImportError: cannot import name 'pago_reparto_service'` before creating the service module.
- [x] 1.5 GREEN: implement `backend/app/services/pago_reparto_service.py::crear_reparto_por_defecto`.
  - Evidence: `pytest tests/test_pago_reparto_service.py -q` → 5 passed (includes the zero-amount guard and the `reemplazar_por_cuenta_unica` helper needed for 1.9/1.10).
- [x] 1.6 GREEN: call `crear_reparto_por_defecto` after `flush` in `_pago_exacto`, `_pago_parcial`, `confirmar_excedente`, `registrar_pago_no_programado` (`backend/app/services/pago_service.py`).
  - Evidence: `pytest tests/test_pago_service.py tests/test_pago_service_arrastre.py -q` → 70 passed (unaffected — these unit tests use `cuenta_bancaria_id=None`, hitting the no-op branch).
- [x] 1.7 RED: write `backend/tests/test_receptor_ledger_service.py` cases for the rewritten query — parity for single-cuenta paid pago, 2-cuenta split credits each share once, `cliente` rows ignored, soft-deleted reparto ignored, `pagado=False`/deleted `Pago` ignored.
  - Evidence: RED confirmed — 4 failing before the rewrite (2-account split, cliente-row-adjacent soft-delete case, and the 2 reassignment-semantics tests that replace the pre-item-10 "Pago-level reassignment moves balance" scenario per the receptor-ledger spec delta).
- [x] 1.8 GREEN: rewrite `receptor_ledger_service.saldos_por_cuenta` to aggregate `SUM(PagoReparto.monto)` joined on `Pago`, filtered by `deleted_at IS NULL` on both sides and `Pago.pagado`.
  - Evidence: `pytest tests/test_receptor_ledger_service.py -q` → 26 passed.
- [x] 1.9 RED: write a test for `PATCH /pagos/{id}/cuenta-bancaria` on a paid pago — asserts the prior active repartos are soft-deleted and replaced by one 100% row to the new cuenta.
  - Evidence: RED confirmed — `assert reparto_previo.deleted_at is not None` failed (`None is not None`) before wiring the router.
- [x] 1.10 GREEN: sync `PATCH /pagos/{id}/cuenta-bancaria` in `backend/app/routers/pagos.py` to call `pago_reparto_service` and preserve I1.
  - Evidence: `pytest tests/test_pagos_cuenta_bancaria.py -q` → 16 passed.
- [x] 1.11 Run full backend suite; verify I1 (Σ active repartos == capital_pagado+interes_pagado) holds for every paid pago fixture used in existing tests.
  - Evidence: `pytest -q` → 587 passed, 0 failed (Windows venv). One pre-existing fixture (`test_receptores_movimientos_router.py::_preparar_cuenta_con_saldo`) directly built a paid `Pago` with `cuenta_bancaria_id` set but no matching `pago_repartos` row — fixed to also seed the default reparto row (7 tests were RED until this fixture fix, now GREEN). No other test file's assertions depend on ledger totals from directly-constructed paid `Pago` fixtures (confirmed empirically by the full green run).

### Judgment Day (PR1) — 2026-09-22, 4 findings fixed

Two blind judges reviewed the frozen 12-file diff (native `gentle-ai` review was `ambiguous`/`lineage_selection_required` — substituted with Judgment Day, same as items 9/11). Judge A found 1 CRITICAL (suspect, not corroborated by B); both judges converged on the `deleted_at` backfill gap. Verified all findings against the code myself before fixing:

- **CRITICAL (Judge A only, verified real)**: `PATCH /pagos/{id}/cuenta-bancaria` called `_get_pago_con_credito` without `lock=True`, unlike `registrar_pago`/`confirmar_excedente`. Two concurrent PATCH calls on the same paid pago could each soft-delete + insert independently, leaving 2 active `pago_repartos` rows and doubling the ledger total. **Fixed**: `pagos.py:914` now passes `lock=True`. Added regression test `test_dos_reemplazos_concurrentes_no_dejan_dos_repartos_activos`.
- **WARNING (both judges)**: backfill migration didn't filter `Pago.deleted_at IS NULL`, unlike the read-side query — could create orphan reparto rows for soft-deleted pagos. **Fixed**: added the filter to the backfill `WHERE`.
- **WARNING (Judge B only, verified real)**: backfill wasn't idempotent (re-running the upgrade would duplicate rows) and used Postgres `now()` instead of the app's `ahora_bogota()` (UTC-5) convention, skewing backfilled timestamps by 5h vs. runtime-created rows. **Fixed**: added `NOT EXISTS` guard; timestamps now `now() - interval '5 hours'`.
- **SUGGESTION (Judge B)**: PATCH audit entry only recorded `cuenta_bancaria_id`, not the reparto state change. **Fixed**: `reemplazar_por_cuenta_unica` now returns `(repartos_antes, repartos_despues)`, included in the `audit_service` call as `"pago_repartos"`.

Full suite re-run after fixes: `pytest -q` → 588 passed, 0 failed.

## Phase 2: Split API, Inheritance & Reports (PR 2)

- [x] 2.1 Create `backend/app/schemas/pago_reparto.py`: `RepartoItem` (model_validator: exactly one id matching `tipo_destinatario`), `RepartoResponse`.
  - Evidence: also added `ReemplazarRepartosRequest` (PUT body wrapper, not explicitly named in design's Interfaces block but required to receive `{repartos: RepartoItem[]}`). Import-smoke-tested; no dedicated RED cycle (same precedent as PR1 tasks 1.1-1.3 — pure data-shape definitions exercised by the RED tests in 2.3).
- [x] 2.2 Add `repartos: list[RepartoResponse] = []` to `PagoResponse` in `backend/app/schemas/pago.py`.
  - Evidence: also had to add `"repartos": []` to `_pago_row_a_dict` in `pagos.py` — a pre-existing completeness test (`test_pagos_listado.py::TestPagoRowADict::test_dict_cubre_todos_los_campos_de_response`) asserts the dict covers every `PagoResponse` field; without it, that test regressed (caught and fixed before moving on).
- [x] 2.3 RED: write `backend/tests/test_pago_reparto_service.py` cases for `reemplazar_repartos` — exact-sum accepted, ±0.01 rejected, duplicate recipient rejected, unknown/deleted cuenta or cliente rejected, empty set rejected, pending pago rejected (422), no `Credito` created for client recipients.
  - Evidence: RED confirmed — 16 new tests (`TestReemplazarRepartos` + `TestCuentaHeredable` + `TestAplicarHerencia`, see 2.5) failed with `AttributeError: module 'app.services.pago_reparto_service' has no attribute 'reemplazar_repartos'` before implementation.
- [x] 2.4 GREEN: implement `reemplazar_repartos(db, pago, items)` in `pago_reparto_service.py` — validate, soft-delete active rows, insert new rows, return `(antes, despues)`.
  - Evidence: `pytest tests/test_pago_reparto_service.py -q` → 22 passed (sum check uses exact `Decimal` equality per design.md's Architecture Decision, not `_validar_split`'s TOL=0.01 — see Deviations in the apply-progress report; `spec.md`'s requirement prose still says "within TOL", superseded by design.md + this task's own "±0.01 rejected" wording).
- [x] 2.5 RED: write inheritance unit tests via `cuenta_heredable` — 1 recipient leaves next cuota untouched; 2+ recipients (cuenta+cuenta or cuenta+cliente) nulls the next pending cuota's `cuenta_bancaria_id` only if it still equals the previous value (manually changed next cuota is not touched).
  - Evidence: RED confirmed in the same run as 2.3 (`TestCuentaHeredable` — 4 tests; `TestAplicarHerencia` — 4 tests, all `AttributeError` before implementation).
- [x] 2.6 GREEN: implement `cuenta_heredable(repartos)` and wire it into the `PUT` handler's post-`reemplazar_repartos` step.
  - Evidence: same 22-passed run as 2.4. Also implemented `aplicar_herencia(db, pago, repartos_despues)` (not separately named in tasks.md but required to wire `cuenta_heredable`'s decision onto `pago.cuenta_bancaria_id` and the next pending cuota, per design.md's Data Flow pseudocode — see Deviations).
- [x] 2.7 RED: write `backend/tests/test_pago_reparto_router.py` — `GET /pagos/{id}/repartos` and `PUT /pagos/{id}/repartos` role checks (admin/recaudador 200, registrador 403), audit_log entry written via `audit_service.registrar_actualizacion_campos`.
  - Evidence: RED confirmed — 12 new tests, all failed with 404 (routes did not exist yet).
- [x] 2.8 GREEN: add `GET`/`PUT /pagos/{id}/repartos` to `backend/app/routers/pagos.py` with `_get_pago_con_credito(lock=True)`.
  - Evidence: `pytest tests/test_pago_reparto_router.py -q` → 12 passed. `PUT` locks the credito (same pattern as the PATCH legacy endpoint's Judgment Day PR1 fix) and audits both the `repartos` change on the target pago and, when `aplicar_herencia` clears a next pending cuota, a second `cuenta_bancaria_id` audit entry scoped to that cuota's own `entidad_id`.
- [x] 2.9 RED: write `backend/tests/test_pagos_router.py` cases for the `GET /pagos` EXISTS filter — split pago matches once per matching cuenta/receptor, no duplicate rows; pending pago still matches via legacy `cuenta_bancaria_id`.
  - Evidence: RED confirmed for 2 of 3 new `TestFiltroExistsRepartos` tests (a pago whose repartos no longer match `Pago.cuenta_bancaria_id`, and the batched-`repartos`-in-listing case). The "no duplicate rows" case already passed against the OLD filter too (it used an `IN` subquery, not a `JOIN`, so it never actually duplicated) — kept as a regression guard for the new `EXISTS` clause. "Pending pago still matches via legacy `cuenta_bancaria_id`" is already covered by the pre-existing PR2b cascading-filter tests in `test_pagos_cuenta_bancaria.py` (all use pending pagos) — confirmed still green after the rewrite, no new test duplicated.
- [x] 2.10 GREEN: rewrite the `receptor_id`/`cuenta_bancaria_id` filter in `GET /pagos` to the correlated `EXISTS` clause; batch-load `repartos` for the page's items into the response.
  - Evidence: `pytest tests/test_pagos_router.py -k TestFiltroExistsRepartos -q` → 3 passed. Broader regression check: `pytest tests/test_pagos_router.py tests/test_pagos_cuenta_bancaria.py tests/test_pagos_listado.py tests/test_pago_reparto_service.py tests/test_pago_reparto_router.py tests/test_receptor_ledger_service.py tests/test_receptores_saldo_router.py tests/test_receptores_movimientos_router.py -q` → 147 passed.
- [x] 2.11 RED: write `backend/tests/test_reportes.py` cases — split pago attributes revenue to each cuenta for its exact share, no double counting; client-type reparto rows excluded from cuenta-based report.
  - Evidence: RED confirmed — 3 new tests failed (KeyError / wrong totals) against the `Pago.cuenta_bancaria_id`-based grouping.
- [x] 2.12 GREEN: rewrite `backend/app/routers/reportes.py` revenue-by-cuenta grouping to read from `pago_repartos` instead of `Pago.cuenta_bancaria_id`.
  - Evidence: `pytest tests/test_reportes.py -q` → 3 passed. `pago_repartos.monto` has no separate capital/interest columns (unchanged from PR1's model), so the per-cuenta capital/interest sub-totals are prorated by each reparto's share of the pago's total — exact (proportion=1) for the common single-recipient case, ±0.01-tolerant for genuine splits (see Deviations). Fixed 5 pre-existing tests in `test_reportes_por_cuenta.py` whose fixtures built paid `Pago` rows directly without a matching `pago_repartos` row (same precedent as PR1 task 1.11's `_preparar_cuenta_con_saldo` fix) — added a `_repartos_para(*pagos)` helper seeding the default 100% row.
- [x] 2.13 Run full backend suite; verify no regression in existing `test_reportes_arrastre.py` and receiver-bank-account-assignment tests.
  - Evidence: `pytest -q` (full suite) → 622 passed, 0 failed (588 from PR1 + 34 new: 16 service + 12 router + 3 filter/listing + 3 reportes). `test_reportes_arrastre.py` unaffected (pending-only, doesn't touch `pago_repartos`). `test_pagos_cuenta_bancaria.py` (receiver-bank-account-assignment) fully green, including PR2b cascading filters.

### Deviations / notes for Phase 4 cleanup (task 4.2)

- `specs/pago-repartos/spec.md`'s "Split Integrity Validation" requirement prose still says the sum check applies "within the existing `_validar_split` TOL tolerance" — this is stale. `design.md`'s Architecture Decision explicitly overrides it to exact `Decimal` equality, and this task list's own 2.3 wording ("±0.01 rejected") confirms exact equality is what shipped. No scenario in the spec actually pins the ±0.01 boundary either way, so nothing observable is at risk, but the prose should be corrected during archive.
- `specs/receiver-bank-account-assignment/spec.md`'s `REMOVED Requirements` section says the legacy `PATCH /pagos/{id}/cuenta-bancaria` path "MUST return 404 or 405" — this contradicts `design.md`'s "Legacy PATCH — Kept" decision, which PR1 already implemented, tested, and shipped (including the Judgment Day lock fix). PR2 did not remove it — removing a merged, working, tested endpoint was never a Phase 2 task. This spec section needs correcting to match shipped behavior before archive.

### Judgment Day (PR2) — 2026-09-22, 1 finding fixed (doc-only)

Two blind judges reviewed the frozen 11-file diff (native `gentle-ai` review again `ambiguous`/`lineage_selection_required` — substituted with Judgment Day). Judge A found 1 CRITICAL; Judge B found 2 WARNING, no overlap.

- **CRITICAL (Judge A only, verified real)**: `cuenta_heredable` returned `None` for a single-recipient split whose sole recipient was type `cliente` — same as the 2+ recipient case — which contradicted `design.md`'s then-current wording ("1 recipient of any type leaves inheritance unchanged"). Investigated with the owner: the CODE was actually correct and the DESIGN PROSE was wrong. Owner refined the rule (2026-09-22): inheritance only fires when the sole recipient IS a `cuenta_bancaria` — a single `cliente` recipient blocks inheritance too. **No code change** — `pago_reparto_service.cuenta_heredable` already implemented this; only `design.md`'s "Inheritance" row/Open Questions and `specs/pago-repartos/spec.md`'s inheritance requirement (renamed "Account Inheritance Only From a Single Cuenta Recipient", new scenario added) were corrected to match.
- **WARNING (Judge B)**: no test exercised a genuine 3+-recipient split — every test capped at 2. **Fixed**: added `test_split_tres_destinatarios_dos_cuentas_y_un_cliente` (service) and `test_split_tres_destinatarios_prorratea_cada_cuenta` (reportes), both 2 cuentas + 1 cliente.
- **WARNING (Judge B, no action needed)**: `aplicar_herencia` also updates `pago.cuenta_bancaria_id` itself (not just the next cuota) when a single-recipient split changes to a different single cuenta. Confirmed this matches `design.md`'s Data Flow pseudocode intent — not a defect.

Full suite re-run after fixes: `pytest -q` → 624 passed, 0 failed.

## Phase 3: Frontend (PR 3) — COMPLETE 2026-09-22 (pending manual QA)

**PR3 actual (2026-09-22)**: 370 changed lines (59 insertions/5 deletions across 3 modified files + 306-line new `RepartoPagoModal.tsx`), close to the ~350 estimate, no test code (frontend has no test runner). Within the Medium-risk budget.

- [x] 3.1 Add `TipoDestinatario`, `RepartoItem`, `RepartoResponse` types to `frontend/src/types/index.ts`; add `repartos` to the `Pago` type.
  - Evidence: types added verbatim per design.md's Interfaces block (`RepartoResponse extends RepartoItem` adding `id`/`etiqueta`). `Pago.repartos: RepartoResponse[]` is non-optional, matching the backend's `PagoResponse.repartos: list[RepartoResponse] = []` default (always present — confirmed by reading `_pago_row_a_dict` in `backend/app/routers/pagos.py`, which always sets `"repartos": []` even before the batched overwrite).
- [x] 3.2 Add `pagosApi.obtenerRepartos(id)` / `pagosApi.reemplazarRepartos(id, items)` to `frontend/src/api/index.ts`.
  - Evidence: `GET /pagos/{id}/repartos` → `RepartoResponse[]`; `PUT /pagos/{id}/repartos` sends `{ repartos: RepartoItem[] }`, matching `ReemplazarRepartosRequest` and the router signatures verified by reading `backend/app/schemas/pago_reparto.py` and `backend/app/routers/pagos.py` directly (not assumed).
- [x] 3.3 Create `frontend/src/components/pagos/RepartoPagoModal.tsx`: recipient search (`SelectCuentaBancaria` for accounts, `clientesApi.listar({busqueda})` for clients), per-row `monto` input, live "asignado / restante" indicator, submit disabled until remainder is 0.
  - Evidence: per-row `tipo_destinatario` toggle (cuenta_bancaria/cliente); `SelectCuentaBancaria` reused as-is for accounts; new self-contained `BuscadorCliente` subcomponent for clients (debounced `clientesApi.listar({busqueda})`, 300ms, "cancelado" race-guard matching this file's existing effect pattern) — selection is always by id from search results, free text is never sent (spec.md "Free-text client recipient rejected"). Live "Asignado / Restante" indicator (green when balanced, amber when short, red when over). Submit gated on: exact balance (compared in rounded cents to sidestep JS float noise — backend's exact-`Decimal` check remains the sole authority), every row having a selected destinatario and `monto > 0`, no duplicate destinatario across rows, and at least 1 row (the last row cannot be deleted). Loads existing repartos via `pagosApi.obtenerRepartos` on open; falls back to one empty row if a paid pago somehow has none yet.
- [x] 3.4 In `frontend/src/pages/Pagos/PagosPage.tsx`, route paid pagos' "Modificar cuenta" action to `RepartoPagoModal`; pending pagos keep the existing single-cuenta modal.
  - Evidence: the existing button's `onClick` now branches on `p.pagado` (paid → `setModalReparto(true)`; pending → unchanged `modalCuentaBancaria` flow, byte-identical to before). The `receptoresCuenta` loader effect was extended to also fire when `modalReparto` opens, reusing the exact same list + `handleBusquedaReceptoresCuenta` callback as the legacy modal (no new receptor-loading logic introduced, per design's "reuse the same style/conventions").
- [x] 3.5 Verify TypeScript build passes (`npm run build` in `frontend/`); manual smoke test of a 2-recipient split against the PR 2 API.
  - Evidence: `npx tsc --noEmit` → exit 0, no errors. `npm run build` (`tsc && vite build`) → exit 0, `✓ built in 22.36s`, 1661 modules transformed, no new warnings.
  - **Manual UI smoke test performed 2026-09-22** (local backend `uvicorn` + `vite` dev server, non-prod local DB, browser automation): opened "Repartir Pago" on a paid pago (`Cuota #4`, $50.000). **Found and fixed a CRITICAL bug**: `totalObjetivo = pago.capital_pagado + pago.interes_pagado` (line 109) did plain `+` on the two fields — the backend serializes `Decimal` as JSON strings (`"50000.00"`, `"0.00"`), so this was **string concatenation** (`"50000.00"+"0.00"` → `"50000.000.00"`), not addition. That garbled string became `NaN` the moment it was compared against `asignado` (a number), permanently failing the `balanceado` check and disabling "Guardar reparto" for every possible input — `tsc` passed because the `Pago` type declares these fields as `number`, a type contract the runtime JSON payload doesn't honor. Fixed with `Number(pago.capital_pagado) + Number(pago.interes_pagado)`. Re-tested after the fix: single-recipient split (100% to one cuenta) saved successfully end-to-end (`PUT /pagos/{id}/repartos` → 200, toast "Reparto actualizado", list refreshed showing the new cuenta), and the live indicator correctly updated through "Restante" (amber) → "Cuadrado" (green) as a second/third row was added (verified up to a 2-cuenta + button-add-third-row state before ending the session). Backend was not touched — this was a pure frontend arithmetic bug.
  - Full backend suite re-run after the fix (unaffected, frontend-only change): `pytest -q` → 624 passed, 0 failed.

### Judgment Day (PR3) — 2026-09-22, 1 finding fixed

Two blind judges reviewed the frozen 4-file diff (native `gentle-ai` review again `ambiguous`/`lineage_selection_required` — substituted with Judgment Day). Both judges independently converged on the SAME WARNING, no CRITICAL from either:

- **WARNING (both judges, corroborated)**: the "duplicate destinatario" check built a key from `tipo_destinatario:id` without excluding empty ids, so two freshly-added blank rows of the same type (the normal flow of clicking "Agregar destinatario" before filling it in) collided on the same key and showed the red "Hay destinatarios duplicados" warning even though nothing had been selected yet. Never blocked saving (`filasCompletas` already gates that correctly) — a misleading UX message only. **Fixed**: `idsDestinatarios` now filters out empty-id rows before the duplicate check (`RepartoPagoModal.tsx`).
- Both judges independently confirmed the already-known `totalObjetivo` `Number()` fix was correctly in place, and found no other Decimal-string arithmetic bugs, no stale-closure/race bugs in the `obtenerRepartos`/`BuscadorCliente` effects, correct request/response shape matching against the live backend, and correct error handling via `mensajeError`/toast.

`npx tsc --noEmit` re-run after the fix: exit 0, no errors.

## Phase 4: Cleanup

- [x] 4.1 Update `openspec/changes/payment-multi-recipient/design.md` Open Questions: confirm prod Postgres ≥13 (`gen_random_uuid()`) — done 2026-09-22, prod runs PostgreSQL 18 (Railway). Note the accepted no-overdraft-check parity with item 9 decision 2.
- [x] 4.2 Confirm `receiver-bank-account-assignment` spec delta and `receptor-ledger` spec delta both reflect the shipped behavior; archive-ready.
  - Evidence: `specs/pago-repartos/spec.md` "Split Integrity Validation" corrected to state exact `Decimal` equality (was stale `_validar_split` TOL wording). `specs/receiver-bank-account-assignment/spec.md`'s "REMOVED Requirements" section (incorrectly said the legacy PATCH must 404/405) rewritten as a second `MODIFIED Requirement` — "Individual Payment Account Change" — documenting that PR1 kept the endpoint, syncs `pago_repartos`, and uses the `lock=True` fix from the PR1 Judgment Day finding, with 2 new scenarios. `specs/receptor-ledger/spec.md` reviewed — already accurate, no changes needed.
