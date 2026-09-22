# Tasks: Receiver Bank Account Assignment

**Scenario count**: 9 requirements, 23 scenarios total (Default Bank Account: 5; Gestor Account Assignment and Propagation: 2; Payment Account Inheritance: 3; Individual Payment Account Change: 2; Cascading Filters on Payment Listing: 4; Report Per-Account Sub-Breakdown: 2; Backfill Endpoint: 2; Role Gates: 1; Account Visible Wherever the Receptor Was: 2 `[manual]`). All 23 mapped below — see Scenario Coverage Map. Gaps: 0.

Delivery strategy: `force-chained`, `stacked-to-main` — each branch is cut from `main`, merged to `main`, and the next branch is cut only after that merge (no PR targets another PR branch, per the item-4 lesson). Strict TDD active: `backend/venv/Scripts/python.exe -m pytest`, `npx tsc --noEmit`.

## Spec/Design Reconciliation

- **Divergence**: the spec's Requirement "Cascading Filters on Payment Listing" states that `GET /pagos` with a `cuenta_bancaria_id` that does not belong to `receptor_id` MUST return 422. The design's decision 9 and Interfaces section describe the two filters as ANDed SQL predicates but do not explicitly restate the 422 branch.
- **Resolution**: keep the spec's 422 behavior — the design does not contradict it, it simply omits the validation step from the narrative. PR2b implements an explicit pre-query check: when both `receptor_id` and `cuenta_bancaria_id` are supplied and the account's `receptor_id` does not match, raise `HTTPException(422)` before building the ANDed filter. This is called out again in PR2b's task list below so it is not lost during implementation.

## Review Workload Forecast

| PR | Branch | Estimated changed lines (code+tests, openspec excluded) | Exceeds 400? |
|---|---|---|---|
| PR1a | `feat/cuenta-bancaria-default` | migration ~35, `models/receptor.py` ~10, `models/gestor.py`+`models/pago.py` ~10, `schemas/receptor.py` ~20, `services/cuenta_bancaria_service.py` ~45 (new), `routers/receptores.py` (default endpoint + auto-default) ~40, `tests/test_cuentas_bancarias_predeterminada.py` ~150 (new) ≈ **~310** | No |
| PR1b | `feat/cuenta-bancaria-backfill` | `routers/receptores.py` (backfill endpoint) ~90, `tests/test_backfill_cuentas_bancarias.py` ~150 (new) ≈ **~240** | No |
| PR2a | `feat/cuenta-bancaria-cutover` | `schemas/{gestor,pago,common}.py` ~30, `services/credito_service.py` ~60, `services/pago_service.py` ~15, `routers/gestores.py` ~25, `routers/creditos.py` ~10, `routers/pagos.py` (PATCH rename + inheritance) ~40, fixture renames across 6 files ~60, `tests/test_gestores_cuenta_bancaria.py` ~90 (new), `tests/test_pagos_cuenta_bancaria.py` (PATCH + inheritance subset) ~70 (new), `tests/test_creditos_router.py` +1 test ~15 ≈ **~415** (see split note below) | Borderline — see note |
| PR2b | `feat/cuenta-bancaria-filtros-reportes` | `routers/pagos.py` (cascading filter + 422 check + virtual-row suppression) ~55, `routers/reportes.py` ~50, `tests/test_pagos_cuenta_bancaria.py` (filter subset) ~60, `tests/test_reportes_por_cuenta.py` ~110 (new) ≈ **~275** | No |
| PR3 | `feat/cuenta-bancaria-frontend` | `types/index.ts` ~15, `api/index.ts` ~15, `formatters.ts` ~10, `SelectCuentaBancaria.tsx` ~50 (new), `PagosPage.tsx` ~60, `GestoresPage.tsx` ~30, `ReceptoresPage.tsx` ~40, `ReportesPage.tsx` ~35 ≈ **~255** | No |
| PR4 | `chore/cuenta-bancaria-cleanup` | drop migration ~40, `models/{gestor,pago}.py` deletions ~15, `routers/receptores.py` deletions ~90, `tests/test_backfill_cuentas_bancarias.py` deletion ~-150 (removes the whole file) ≈ **~280** (mostly deletions) | No |

**Note on PR2a**: the design's own forecast (`design.md` Migration/Rollout table) already earmarked PR2 at ~340 with a marked split into PR2b (~180) for the filter/report slice. Re-splitting `test_pagos_cuenta_bancaria.py` between PR2a (PATCH + inheritance scenarios) and PR2b (filter scenarios) as the task list below does keeps PR2a at ~415, still functionally one deliverable work unit (the atomic rename) and reviewable in one sitting; if actual diff review during `sdd-apply` confirms it crosses 400, split the fixture-rename commits for `test_pagos_listado.py`/`test_pago_service*.py` into a preceding micro-PR `feat/cuenta-bancaria-rename-prep` that only renames fixtures with no behavior change (mechanical, near-zero review risk) before opening PR2a. This is a fallback, not a required action, since the atomic-rename constraint (decision 7) makes an in-flight split of PR2a itself unsafe.

- **400-line budget risk**: Low (5 of 6 PRs are comfortably under 400; PR2a is borderline but is one atomic, mechanically-necessary rename per design decision 7 and has a documented fallback).
- **Chained PRs recommended**: Yes.
- **Decision needed before apply**: No.

## Suggested Work Units

| Unit | Goal | PR | Focused test command | Runtime harness | Rollback boundary |
|------|------|-----|----------------------|-----------------|-------------------|
| 1 | Schema: `es_predeterminada` + partial unique index, nullable `cuenta_bancaria_id` on gestores/pagos, default-account service, default-change endpoint, auto-default on first account | PR1a | `cd backend && venv/Scripts/python.exe -m pytest tests/test_cuentas_bancarias_predeterminada.py -q` | httpx AsyncClient + aiosqlite integration tests (unmocked) | Revert migration file, `models/{receptor,gestor,pago}.py`, `schemas/receptor.py`, `services/cuenta_bancaria_service.py`, `routers/receptores.py` diff; delete test file; `alembic downgrade -1` |
| 2 | SQL-only idempotent admin backfill endpoint | PR1b | `cd backend && venv/Scripts/python.exe -m pytest tests/test_backfill_cuentas_bancarias.py -q` | Manual dry-run against a seeded local DB before prod use | Revert `routers/receptores.py` backfill diff; delete test file; endpoint is additive, no schema change |
| 3 | Atomic rename `receptor_id` → `cuenta_bancaria_id` across schemas/services/routers, PATCH rename, payment inheritance, gestor propagation | PR2a | `cd backend && venv/Scripts/python.exe -m pytest tests/test_gestores_cuenta_bancaria.py tests/test_pagos_cuenta_bancaria.py tests/test_creditos_router.py -q` | httpx AsyncClient + aiosqlite integration tests (unmocked); `db_session` fixture required for propagation | Revert the rename diff across the listed files; fixture-renamed test files revert to pre-cutover state; `receptor_id` columns remain populated (decision 7) so no data loss |
| 4 | Cascading `GET /pagos` filter + `GET /reportes` per-account nesting | PR2b | `cd backend && venv/Scripts/python.exe -m pytest tests/test_pagos_cuenta_bancaria.py tests/test_reportes_por_cuenta.py -q` | httpx AsyncClient + aiosqlite integration tests | Revert `routers/pagos.py` filter diff and `routers/reportes.py` diff; delete `test_reportes_por_cuenta.py`; no schema change |
| 5 | Frontend types/api/shared selector/pages | PR3 | `cd frontend && npx tsc --noEmit` + manual checklist (Phase 15) | Manual: Pagos/Gestores/Receptores/Reportes pages | Revert `types/index.ts`, `api/index.ts`, `formatters.ts`, `SelectCuentaBancaria.tsx`, page diffs; backend unaffected |
| 6 | Drop `receptor_id`, remove deprecated columns/relationships, delete backfill endpoint + tests | PR4 | `cd backend && venv/Scripts/python.exe -m pytest -q` (full suite) | `alembic upgrade head` then `downgrade -1` then `upgrade head` on a fresh DB | `alembic downgrade -1` re-adds and repopulates `receptor_id`; requires prod re-verification before re-attempting |

---

## PR1a — `feat/cuenta-bancaria-default`

### Phase 1: Foundation — Migration & Models

- [x] 1.1 Create `backend/alembic/versions/c3d4e5f6a7b8_add_cuenta_bancaria_assignment.py`, `down_revision='b2c3d4e5f6a7'`: add `cuentas_bancarias.es_predeterminada` (`Boolean`, `NOT NULL`, `server_default=sa.false()`); partial unique index `uq_cuentas_bancarias_default_por_receptor` on `(receptor_id)` `WHERE es_predeterminada` (both `postgresql_where` and `sqlite_where`); add nullable `gestores.cuenta_bancaria_id` and `pagos.cuenta_bancaria_id` (`sa.UUID()`, FKs `fk_gestores_cuenta_bancaria`/`fk_pagos_cuenta_bancaria`), `ix_pagos_cuenta_bancaria_id`; downgrade reverses all of the above
- [x] 1.2 Modify `backend/app/models/receptor.py`: `es_predeterminada` column (`default=False`, `server_default=sa.false()`) on `CuentaBancaria`, `__table_args__` partial unique index (mirrors the migration so `Base.metadata.create_all` enforces it in SQLite tests too, per design decision 1)
- [x] 1.3 Modify `backend/app/models/gestor.py`: add nullable `cuenta_bancaria_id` FK column + `cuenta_bancaria` relationship (design decision 5)
- [x] 1.4 Modify `backend/app/models/pago.py`: add nullable `cuenta_bancaria_id` FK column only, no ORM relationship (design decision 4)
- [x] 1.5 Verify: `cd backend && venv/Scripts/python.exe -m pytest -q` — 0 failures on existing suite (additive columns, no behavior change yet) — 447 passed

### Phase 2: Foundation — Schemas & Service Skeleton

- [x] 2.1 Modify `backend/app/schemas/receptor.py`: `CuentaBancariaResponse.es_predeterminada: bool`; add `ReceptorMin {id, nombre}`; add `CuentaBancariaResumen {id, receptor_id, entidad_bancaria, tipo_cuenta, numero_cuenta, es_predeterminada, receptor: ReceptorMin}` (design decision 6)
- [x] 2.2 Create `backend/app/services/cuenta_bancaria_service.py` (empty function stubs raising `NotImplementedError` for now): `obtener_cuenta_o_404`, `es_primera_cuenta`, `marcar_predeterminada`, `etiqueta_cuenta` (design decision 3)
- [x] 2.3 Verify: `cd backend && venv/Scripts/python.exe -m pytest -q` — 0 failures (schema addition backward-compatible) — 447 passed

### Phase 3: RED — Failing Tests for Default Rule (`backend/tests/test_cuentas_bancarias_predeterminada.py`, new file, fixtures copied from `test_desvalidar_pago.py`)

- [x] 3.1 RED: first account created for a receptor with no accounts is returned with `es_predeterminada = true` (Req: Default Bank Account — scenario "First account is default")
- [x] 3.2 RED: a second account created for a receptor that already has a default is returned with `es_predeterminada = false`, and the first account stays `true` (Req: Default Bank Account — scenario "Second account is not default")
- [x] 3.3 RED: `PUT /receptores/{id}/cuentas/{cuenta_id}/predeterminada` on account B (receptor has A default, B not) → B becomes `true`, A becomes `false`, exactly one default remains (Req: Default Bank Account — scenario "Admin changes the default") — merged with 3.4 into `test_admin_cambia_predeterminada_sin_mover_asignaciones`
- [x] 3.4 RED: after switching the receptor's default from A to B, an existing gestor and an existing unpaid payment still reference A unchanged (Req: Default Bank Account — scenario "Default change does not move assignments") — merged with 3.3 into `test_admin_cambia_predeterminada_sin_mover_asignaciones` (line-budget trim, both assertions in one flow)
- [x] 3.5 RED: calling the default endpoint with a `cuenta_id` that does not belong to `{id}` → 404, no default changes persisted (Req: Default Bank Account — scenario "Account of another receptor rejected")
- [x] 3.6 RED: calling the default endpoint again on an already-default account is idempotent — still 200, same single default, no error — folded as a second PUT call at the end of `test_admin_cambia_predeterminada_sin_mover_asignaciones` (line-budget trim)
- [x] 3.7 RED: non-admin caller (`registrador`/`gestor`/`recaudador`) → 403, no writes (Req: Role Gates — account create/update/default-change is admin-only)
- [x] 3.8 RED: direct ORM insert of a second `es_predeterminada=true` row for the same receptor raises `IntegrityError` (verifies the partial unique index is enforced in SQLite, per design decision 1)
- [x] 3.9 RED: `ReceptorResponse`/account list response exposes `es_predeterminada` on every account
- [x] 3.10 Verify RED: `cd backend && venv/Scripts/python.exe -m pytest tests/test_cuentas_bancarias_predeterminada.py -q` — all of 3.1-3.9 fail (endpoint/service not yet implemented) — 9 failed, 2 passed (the 2 that pass by coincidence — no route yet returns 404 — are `TestCuentaDeOtroReceptorRechazada` and the index test, both already correct against the additive model changes)

### Phase 4: GREEN — Implement Default Rule (`backend/app/services/cuenta_bancaria_service.py`, `backend/app/routers/receptores.py`)

- [x] 4.1 Implement `obtener_cuenta_o_404(db, cuenta_id)` with `selectinload(receptor)`; `es_primera_cuenta(db, receptor_id)`
- [x] 4.2 Implement `marcar_predeterminada(db, receptor_id, cuenta_id)`: 404 if the account does not belong to `receptor_id`; two explicit Core `update()` statements in order — clear the old default for the receptor, then set the new one (design decision 2, never rely on ORM flush order)
- [x] 4.3 Implement `etiqueta_cuenta(c)` → `"Entidad · Tipo · numero"`
- [x] 4.4 Modify `backend/app/routers/receptores.py`: `agregar_cuenta` calls `es_primera_cuenta` and sets `es_predeterminada` on create; add `PUT /{receptor_id}/cuentas/{cuenta_id}/predeterminada` (`require_role("admin")`, audit `cambios={"es_predeterminada": (old_id, new_id)}` on entity `receptores`)
- [x] 4.5 Verify GREEN: `cd backend && venv/Scripts/python.exe -m pytest tests/test_cuentas_bancarias_predeterminada.py -q` — all tests from Phase 3 pass — 9 passed

### Phase 5: Full Backend Regression (PR1a)

- [x] 5.1 Verify: `cd backend && venv/Scripts/python.exe -m pytest -q` — 0 failures, count ≥ baseline + all new tests from `test_cuentas_bancarias_predeterminada.py` — 456 passed (447 baseline + 9 new)

---

## PR1b — `feat/cuenta-bancaria-backfill`

**Prerequisite (operational)**: PR1a merged to `main`; branch `feat/cuenta-bancaria-backfill` cut from `main` post-merge.

### Phase 6: RED — Failing Tests for Backfill (`backend/tests/test_backfill_cuentas_bancarias.py`, new file, deleted in PR4)

- [x] 6.1 RED: receptor with zero accounts gets a generic default account (`entidad_bancaria='Por definir'`, `tipo_cuenta=TipoCuenta.ahorros`, `numero_cuenta='0'`, `es_predeterminada=true`)
- [x] 6.2 RED: receptor with accounts but none flagged default elects one via `MIN(id)` (Req: Backfill Endpoint — election rule confirmed by the owner in `design.md` Open Questions)
- [x] 6.3 RED: gestor with `cuenta_bancaria_id IS NULL` gets it set from its `receptor_id`'s default account
- [x] 6.4 RED: pago with `cuenta_bancaria_id IS NULL` gets it set from its `receptor_id`'s default account (step 4a)
- [x] 6.5 RED: gestor already on account B and a pago with null account whose `receptor_id` defaults to A — gestor keeps B, pago gets A (Req: Backfill Endpoint — scenario "Fills only gaps")
- [x] 6.6 RED: unpaid pago still `cuenta_bancaria_id IS NULL` after step 4a (its own `receptor_id` was also null) inherits from `credito → cliente → gestor.cuenta_bancaria_id` (step 4b)
- [x] 6.7 RED: paid and soft-deleted pagos are filled the same as active ones (history keeps its account, per design Interfaces note)
- [x] 6.8 RED: `dry_run=true` (default) executes the same predicates as `SELECT COUNT` and writes nothing; counts match what an apply run would produce
- [x] 6.9 RED: after a completed apply run, running again (apply or dry run) returns all counts `0` and changes no rows (Req: Backfill Endpoint — scenario "Idempotent re-run")
- [x] 6.10 RED: non-admin caller → 403, no writes (Req: Role Gates — backfill is admin-only)
- [x] 6.11 Verify RED: `cd backend && venv/Scripts/python.exe -m pytest tests/test_backfill_cuentas_bancarias.py -q` — all of 6.1-6.10 fail (endpoint not yet implemented) — 11 failed (404, route did not exist)

### Phase 7: GREEN — Implement Backfill (`backend/app/routers/receptores.py`)

- [x] 7.1 Declare `sa.table()`/`sa.column()` lightweight constructs (`_t_gestores`, `_t_pagos`, `_t_cuentas`, `_t_receptores`), `tipo_cuenta` typed `sa.Enum(TipoCuenta, name="tipo_cuenta_enum")` (design decision 8, avoids the wrong `'Ahorros'` literal) — also `_t_creditos`/`_t_clientes` added (not in the original decision-8 list) for step 4b's credito->cliente->gestor join; `id`/FK columns typed `sa.UUID(as_uuid=True)` (needed for SQLite parameter binding, matches the ORM's own UUID type)
- [x] 7.2 Add `POST /receptores/admin/backfill-cuentas-bancarias?dry_run=true` (`# TEMPORAL` banner, `require_role("admin")`, declared before parametric routes so it does not collide with `/{receptor_id}`), implementing steps 1→4b via correlated scalar subqueries, each statement guarded by `cuenta_bancaria_id IS NULL` / `NOT EXISTS default` so re-runs are no-ops
- [x] 7.3 Return `{dry_run, predeterminadas_elegidas, cuentas_genericas_creadas, gestores_actualizados, pagos_por_receptor, pagos_por_gestor, pendientes: {gestores_sin_cuenta, pagos_sin_cuenta}}`
- [x] 7.4 Verify GREEN: `cd backend && venv/Scripts/python.exe -m pytest tests/test_backfill_cuentas_bancarias.py -q` — all tests from Phase 6 pass — 11 passed

### Phase 8: Full Backend Regression (PR1b)

- [x] 8.1 Verify: `cd backend && venv/Scripts/python.exe -m pytest -q` — 0 failures — 471 passed (460 baseline + 11 new)

### Operational: Prod Sequencing After PR1a + PR1b

- [ ] OPS-1 Merge PR1a to `main`, then merge PR1b to `main`; deploy (Alembic runs automatically via `start.sh`)
- [ ] OPS-2 Run `POST /admin/backfill-cuentas-bancarias?dry_run=true` against prod; review counts
- [ ] OPS-3 Run `POST /admin/backfill-cuentas-bancarias?dry_run=false` against prod (apply)
- [ ] OPS-4 Verify `pendientes.gestores_sin_cuenta = 0` and `pendientes.pagos_sin_cuenta = 0`; verify `SELECT count(*) FROM receptores r WHERE NOT EXISTS (SELECT 1 FROM cuentas_bancarias c WHERE c.receptor_id = r.id AND c.es_predeterminada)` returns `0` for every receptor with at least one account

---

## PR2a — `feat/cuenta-bancaria-cutover`

**Prerequisite (operational)**: OPS-1 through OPS-4 complete; branch `feat/cuenta-bancaria-cutover` cut from `main` post-backfill.

### Phase 9: RED — Fixture Renames + New Cutover Tests

- [x] 9.1 RED: rename `receptor_id` → `cuenta_bancaria_id` in fixtures across `backend/tests/test_pagos_listado.py`, `test_credito_service*.py`, `test_pago_service*.py`, `test_creditos_router.py` (~23 spots) — these become the regression net; run and confirm they now fail against pre-cutover code (expected, since fixtures reference a column that does not exist under the old contract) — 16 failed, 462 passed
- [x] 9.2 RED (`backend/tests/test_gestores_cuenta_bancaria.py`, new file): create/update a gestor with `cuenta_bancaria_id` → `GestorResponse` exposes `cuenta_bancaria_id` and the nested `cuenta_bancaria` incl. its `receptor`; unknown `cuenta_bancaria_id` → 404, nothing persisted (Req: Gestor Account Assignment and Propagation)
- [x] 9.3 RED: `PATCH /gestores/{id}` changing `cuenta_bancaria_id` to a non-null value propagates to every unpaid, non-deleted payment of that gestor's active clientes' creditos; a paid payment on the same gestor is untouched (Req: Gestor Account Assignment and Propagation — scenario "Propagates to unpaid only")
- [x] 9.4 RED: a second gestor on the same original account is untouched when only the first gestor is moved (Req: Gestor Account Assignment and Propagation — scenario "Other gestor untouched") — folded into a shared fixture with 9.3 in `test_patch_gestor_no_afecta_otro_gestor_en_la_misma_cuenta`
- [x] 9.5 RED: `PATCH /gestores/{id}` with `cuenta_bancaria_id: null` does not propagate to any payment
- [x] 9.6 RED (`backend/tests/test_creditos_router.py`, +1 test): creating a credit for a cliente whose gestor is on account A produces a first payment referencing A (Req: Payment Account Inheritance — scenario "First cuota inherits") — added as `TestPrimeraCuotaHeredaCuentaBancaria`, also carries 9.8
- [x] 9.7 RED (`backend/tests/test_pagos_cuenta_bancaria.py`, new file, PATCH + inheritance subset): a credit whose gestor moved from A to B after the first cuota — paying the first cuota and generating the next produces a payment referencing B (Req: Payment Account Inheritance — scenario "Next cuota inherits current account")
- [x] 9.8 RED: a gestor with `cuenta_bancaria_id = null` — creating a credit produces a first payment with `cuenta_bancaria_id = null` (Req: Payment Account Inheritance — scenario "Gestor without account") — placed alongside 9.6 in `test_creditos_router.py` (both exercise `POST /creditos`, not the PATCH endpoint)
- [x] 9.9 RED: `PATCH /pagos/{id}/cuenta-bancaria` moves a payment on receptor R1's account A to receptor R2's account C — the payment references C, its derived receptor (via `cuenta_bancaria.receptor`) is R2, and the audit log shows `cuenta_bancaria_id: (A, C)` (Req: Individual Payment Account Change — scenario "Move to another receptor's account")
- [x] 9.10 RED: `PATCH /pagos/{id}/cuenta-bancaria` with an unknown `cuenta_bancaria_id` → 404, payment and audit log unchanged (Req: Individual Payment Account Change — scenario "Unknown account")
- [x] 9.11 RED: `PATCH /pagos/{id}/cuenta-bancaria` on a projected (virtual) row id → 404 (no id exists to match)
- [x] 9.12 RED: old path `PATCH /pagos/{id}/receptor` → 404 or 405 (Req: Individual Payment Account Change — "old path MUST return 404 or 405")
- [x] 9.13 RED: `registrador` calling `PATCH /pagos/{id}/cuenta-bancaria` → 403, payment unchanged; `admin` and `recaudador` → 200 (Req: Role Gates — scenario "Registrador cannot change payment account")
- [x] 9.14 Verify RED: `cd backend && venv/Scripts/python.exe -m pytest tests/test_gestores_cuenta_bancaria.py tests/test_pagos_cuenta_bancaria.py tests/test_creditos_router.py -q` — all of 9.2-9.13 fail; full suite run confirms the renamed fixtures (9.1) also fail pre-cutover — 10 failed / 45 passed on the new-test run, 16 failed / 462 passed on the fixture-rename full run (5 propagation/PATCH-404 tests pass by coincidence, same pattern as PR1a phase 3.10)

### Phase 10: GREEN — Atomic Rename (one pass, one commit per design decision 7)

- [x] 10.1 Modify `backend/app/models/{receptor,gestor,pago}.py`: keep `receptor_id` mapped but never read or written (`# DEPRECATED, dropped in PR4`); remove `Gestor.receptor`, `Pago.receptor`, `Receptor.gestores`, `Receptor.pagos` relationships (design decision 7 — relationship removal makes accidental use a hard error)
- [x] 10.2 Modify `backend/app/schemas/{gestor,pago,common}.py`: `receptor_id` → `cuenta_bancaria_id`; add `cuenta_bancaria: Optional[CuentaBancariaResumen] = None`; add `ModificarCuentaBancariaPagoRequest`; add `PagoFiltros.cuenta_bancaria_id`; `common.py` legacy report schemas gain `por_cuenta` field (used starting PR2b) — added `ReporteDetalleCuenta` + `ReporteDetalleReceptor.por_cuenta: list = []`
- [x] 10.3 Modify `backend/app/services/credito_service.py`: rename parameter `receptor_id` → `cuenta_bancaria_id` in `crear_primera_cuota`, `_primera_cuota_fija`, `_primera_cuota_abono_capital`, `generar_siguiente_cuota`, `_siguiente_cuota_fija`, `_siguiente_cuota_fija_solo_interes`, `_siguiente_cuota_abono_capital`, and every `Pago(...)` kwarg (lines 467-802); update docstring at line 862
- [x] 10.4 Modify `backend/app/services/pago_service.py`: lines 229, 297, 366, 384, 422 — `cuenta_bancaria_id=pago.cuenta_bancaria_id` / parameter rename
- [x] 10.5 Modify `backend/app/routers/gestores.py`: `_query_con_relaciones` load chain adds `selectinload(Gestor.cuenta_bancaria).selectinload(CuentaBancaria.receptor)`; create/update validate the account via `obtener_cuenta_o_404`; rename `_propagar_receptor_a_pagos` → `_propagar_cuenta_a_pagos` (same predicate — unpaid, non-deleted payments of active clientes' creditos — `.values(cuenta_bancaria_id=...)`)
- [x] 10.6 Modify `backend/app/routers/creditos.py`: lines 224-231 — `gestor.cuenta_bancaria_id` passed to `crear_primera_cuota`
- [x] 10.7 Modify `backend/app/routers/pagos.py`: `no-programado` payment creation uses `gestor.cuenta_bancaria_id`; rename `PATCH /pagos/{id}/receptor` → `PATCH /pagos/{id}/cuenta-bancaria` (body `ModificarCuentaBancariaPagoRequest`, `require_role("admin", "recaudador")`, 404 on unknown account, audit `cambios={"cuenta_bancaria_id": (old, new)}`, returns `PagoResponse` with nested `cuenta_bancaria`); old route removed — additionally: `_pago_row_a_dict`/select-columns/virtual-dict renamed `receptor_id`→`cuenta_bancaria_id` (required for `PagoResponse` validation post-rename, not deferrable to PR2b) and `cuenta_bancaria: None` placeholder added (populated in PR2b); the `receptor_id` list filter now resolves via a `cuentas_bancarias` subquery instead of reading the deprecated `Pago.receptor_id` column (decision 7 compliance) — full cascading/422/virtual-suppression semantics still land in PR2b Phase 13
- [x] 10.8 Verify GREEN: `cd backend && venv/Scripts/python.exe -m pytest tests/test_gestores_cuenta_bancaria.py tests/test_pagos_cuenta_bancaria.py tests/test_creditos_router.py -q` — all tests from Phase 9 pass — 55 passed

### Phase 11: Full Backend Regression (PR2a)

- [x] 11.1 Verify: `cd backend && venv/Scripts/python.exe -m pytest -q` — 0 failures, including the renamed fixture files from 9.1 (regression net for the atomic rename) — 493 passed

---

## PR2b — `feat/cuenta-bancaria-filtros-reportes`

**Prerequisite (operational)**: PR2a merged to `main`; branch `feat/cuenta-bancaria-filtros-reportes` cut from `main` post-merge.

### Phase 12: RED — Cascading Filters & Report Nesting

- [x] 12.1 RED (`backend/tests/test_pagos_cuenta_bancaria.py`, filter subset): `GET /pagos?receptor_id=R1` with payments on accounts A and B of R1 and C of R2 → only A and B payments returned (Req: Cascading Filters on Payment Listing — scenario "Receptor-only aggregates accounts")
- [x] 12.2 RED: `GET /pagos?receptor_id=R1&cuenta_bancaria_id=B` on the same data → only B payments returned (Req: Cascading Filters on Payment Listing — scenario "Account narrows")
- [x] 12.3 RED: `GET /pagos?receptor_id=R1&cuenta_bancaria_id=C` (C belongs to R2, not R1) → 422 (Req: Cascading Filters on Payment Listing — scenario "Mismatched pair rejected"; see Spec/Design Reconciliation above — this is the explicit validation step the design narrative omits)
- [x] 12.4 RED: with any of `receptor_id`/`cuenta_bancaria_id` active on a credit whose future cuotas are not yet persisted, no projected/virtual rows appear (Req: Cascading Filters on Payment Listing — scenario "Virtual rows suppressed"); without either filter, virtual rows still appear as today
- [x] 12.5 RED: each real row in `GET /pagos` exposes `cuenta_bancaria_id`, the nested `cuenta_bancaria`, and its derived receptor; each virtual row exposes `cuenta_bancaria: null`
- [x] 12.6 RED (`backend/tests/test_reportes_por_cuenta.py`, new file): paid payments of 100 on account A and 50 on account B of R1 — `GET /reportes` for that period shows R1 with `total_recaudado = 150` and `por_cuenta` rows A = 100, B = 50 (Req: Report Per-Account Sub-Breakdown — scenario "Subtotals sum to receptor")
- [x] 12.7 RED: the existing report fixture — receptor-level totals are byte-identical to the pre-change expectations (Req: Report Per-Account Sub-Breakdown — scenario "Totals equal pre-change values")
- [x] 12.8 RED: payments with `cuenta_bancaria_id = null` are excluded from both the receptor total and every `por_cuenta` row
- [x] 12.9 Verify RED: `cd backend && venv/Scripts/python.exe -m pytest tests/test_pagos_cuenta_bancaria.py tests/test_reportes_por_cuenta.py -q` — all of 12.1-12.8 fail — 8 failed, 8 passed (5 pagos filter tests + 3 reportes tests failed as expected)

### Phase 13: GREEN — Implement Filters & Report Nesting

- [x] 13.1 Modify `backend/app/routers/pagos.py`: expand `receptor_id` filter to `Pago.cuenta_bancaria_id IN (SELECT id FROM cuentas_bancarias WHERE receptor_id = :r)`; add `cuenta_bancaria_id: uuid | None` exact-match param; when both are present, pre-query check that the account's `receptor_id` matches `receptor_id`, else `HTTPException(422)` before building the ANDed filter (see Spec/Design Reconciliation); select columns + `outerjoin(CuentaBancaria).outerjoin(Receptor)` in `listar_pagos` and `listar_pagos_aplazados`; `_pago_row_a_dict` builds `cuenta_bancaria`; virtual dict keeps `cuenta_bancaria_id: None`; `_calcular_virtuales(..., cuenta_bancaria_id_filtro)` early-returns when either filter is active — additionally fixed `tests/test_pagos_listado.py::_fake_row` (missing `cb_*` attrs broke the pre-existing `TestPagoRowADict` unit tests against the new joined-column contract) and strengthened its two affected tests with real nested-account assertions instead of leaving them as smoke tests
- [x] 13.2 Modify `backend/app/routers/reportes.py`: add `ReporteDetalleCuentaExtendido`, aggregate by `cuenta_bancaria_id`, roll up per receptor into `por_receptor[].por_cuenta[]`; account/receptor metadata preloaded in one query; receptor totals keep the existing formula (replaces the old `pago.receptor_id`-based loop, deprecated since PR2a)
- [x] 13.3 Verify GREEN: `cd backend && venv/Scripts/python.exe -m pytest tests/test_pagos_cuenta_bancaria.py tests/test_reportes_por_cuenta.py -q` — all tests from Phase 12 pass — 16 passed

### Phase 14: Full Backend Regression (PR2b)

- [x] 14.1 Verify: `cd backend && venv/Scripts/python.exe -m pytest -q` — 0 failures — 504 passed

### Operational: Prod Sequencing After PR2a + PR2b

- [ ] OPS-5 Merge PR2a to `main`, then merge PR2b to `main`; deploy
- [ ] OPS-6 **Immediately re-run** `POST /admin/backfill-cuentas-bancarias?dry_run=false` (fills rows created between OPS-3 and this deploy; step 4b covers post-deploy unpaid rows whose `receptor_id` was already null under the new contract)
- [ ] OPS-7 Verify `pendientes.gestores_sin_cuenta = 0` and `pendientes.pagos_sin_cuenta = 0` again
- [ ] OPS-8 Smoke test in prod: create a credit, register a payment, `GET /pagos`, `GET /reportes` — confirm nested `cuenta_bancaria` data and `por_cuenta` rows render correctly

---

## PR3 — `feat/cuenta-bancaria-frontend`

**Prerequisite (operational)**: OPS-5 through OPS-8 complete; branch `feat/cuenta-bancaria-frontend` cut from `main` post-verification.

### Phase 15: Frontend Types, API, Shared Selector

- [x] 15.1 Modify `frontend/src/types/index.ts`: `CuentaBancaria.es_predeterminada`; `CuentaBancariaResumen`; `Gestor.cuenta_bancaria_id`/`cuenta_bancaria`; `Pago.cuenta_bancaria_id`/`cuenta_bancaria?`; `ReporteDetalleReceptor.por_cuenta`
- [x] 15.2 Modify `frontend/src/api/index.ts`: `receptoresApi.marcarPredeterminada(receptorId, cuentaId)`; `pagosApi.modificarCuentaBancaria(pagoId, cuenta_bancaria_id)`; `pagosApi.listar` params `+cuenta_bancaria_id`
- [x] 15.3 Modify `frontend/src/utils/formatters.ts`: `formatCuentaBancaria(c, receptorNombre?)` → `"Receptor · Entidad · Tipo · numero"` (receptor omitted inside optgroups)
- [x] 15.4 Create `frontend/src/components/ui/SelectCuentaBancaria.tsx`: one `<select>` with `<optgroup label={receptor.nombre}>` per receptor, options labelled by `formatCuentaBancaria` (design decision 11)
- [x] 15.5 Verify: `cd frontend && npx tsc --noEmit` — 0 errors

### Phase 16: Frontend — Pages

- [x] 16.1 Modify `frontend/src/pages/Pagos/PagosPage.tsx`: filter card gains Receptor → Cuenta selects (gated `perms.canValidarPago`, account list = selected receptor's accounts, "Todas" default, resets account on receptor change); new table column "Cuenta" after Cliente (`Entidad · numero`, tooltip full label, "—" for virtual/unassigned); "Modificar cuenta" modal replaces the receptor-only modal, uses `SelectCuentaBancaria` preselecting the current account; backend 4xx `detail` shown verbatim — filter selects gated on `!esAplazados` too (`pagosApi.listarAplazados` does not accept these params)
- [x] 16.2 Modify `frontend/src/pages/Gestores/GestoresPage.tsx` (or equivalent): form field `cuenta_bancaria_id` via `SelectCuentaBancaria`; list badge `receptor.nombre · entidad`
- [x] 16.3 Modify `frontend/src/pages/Receptores/ReceptoresPage.tsx`: "Predeterminada" badge on the default account's card; "Hacer predeterminada" button on the others, calling `marcarPredeterminada`
- [x] 16.4 Modify `frontend/src/pages/Reportes/ReportesPage.tsx`: render `por_cuenta` sub-rows nested under each receptor (`↳ etiqueta`, `text-xs text-gray-500`, indent), always rendered
- [x] 16.5 Verify: `cd frontend && npx tsc --noEmit` — 0 errors

### Phase 17: Manual Verification Checklist (frontend — no test runner)

- [ ] 17.1 Cascading filter: choosing a receptor then one of its accounts narrows the Pagos table at each step and the account column matches (Req: Account Visible Wherever the Receptor Was — scenario "Cascading filter in UI")
- [ ] 17.2 "Modificar cuenta" modal and Gestor form: the grouped `SelectCuentaBancaria` preselects the CURRENTLY assigned account (not the receptor's default), and it can still be changed (Req: Account Visible Wherever the Receptor Was — scenario "Current account preselected")
- [ ] 17.3 Weekly, daily, and deferred payment tables show the account as `Entidad · numero` where the receptor used to be shown, with the full label (including receptor name) in the cell tooltip
- [ ] 17.4 Gestor form/list: account select works, badge renders `receptor.nombre · entidad`
- [ ] 17.5 Receptores page: default badge and "set default" action work and reflect the change immediately
- [ ] 17.6 Reportes page: per-account nested rows render under each receptor and their sum matches the receptor total
- [ ] 17.7 Receptor search boxes (Pagos cascading filter, "Modificar cuenta" modal, Gestor form): typing refetches receptors from the backend with `busqueda` and any receptor beyond the first 50 becomes reachable, without losing the currently selected receptor/account from the list (Req: Account Visible Wherever the Receptor Was — scenario "Receptor search beyond the first page")

---

## PR4 — `chore/cuenta-bancaria-cleanup`

**Prerequisite (operational)**: a clean prod week after OPS-5 through OPS-8 with no `pendientes` regressions; owner confirms no rollback of PR2a/PR2b is planned.

> **OPERATIONAL NOTE (2026-09-20)**: code for this PR (Phase 18, tasks 18.1-18.6) is
> prepared ahead of the prod-week prerequisite, on branch `chore/cuenta-bancaria-cleanup`
> cut from `feat/cuenta-bancaria-frontend` (PR3, commit `a531256`), stacked on the PR1-3
> chain. **Do NOT merge this branch together with the rest of the chain.** It must stay
> unmerged until OPS-9 and OPS-10 are executed and verified in prod after a clean week —
> only then does OPS-11 (merge + deploy) happen. OPS-9/OPS-10 themselves are operational
> (prod) and were explicitly NOT executed as part of this apply batch.

- [ ] OPS-9 Re-run `POST /admin/backfill-cuentas-bancarias?dry_run=false` once more in prod as a final safety net before dropping columns
- [ ] OPS-10a Before running the drop migration, confirm the FK constraint names in prod: `SELECT constraint_name, table_name FROM information_schema.table_constraints WHERE table_name IN ('gestores','pagos') AND constraint_type = 'FOREIGN KEY' AND constraint_name LIKE '%receptor_id%'` must return exactly `gestores_receptor_id_fkey` and `pagos_receptor_id_fkey` (the names hardcoded in `d4e5f6a7b8c9`); the Render workspace visible from this machine is NOT the prod one, so this was not verified live
- [ ] OPS-10 Verify `SELECT count(*) FROM pagos WHERE cuenta_bancaria_id IS NULL AND receptor_id IS NOT NULL` = 0, and the same query for `gestores` = 0

### Phase 18: Cleanup

- [x] 18.1 Create `backend/alembic/versions/d4e5f6a7b8c9_drop_receptor_id_from_gestores_pagos.py`: drop FKs and `receptor_id` columns from `gestores` and `pagos`; downgrade re-adds nullable columns + FKs and repopulates via `op.execute` correlated `UPDATE ... SET receptor_id = (SELECT receptor_id FROM cuentas_bancarias WHERE id = cuenta_bancaria_id)`
- [x] 18.2 Modify `backend/app/models/gestor.py`, `backend/app/models/pago.py`: remove the deprecated `receptor_id` mapped columns
- [x] 18.3 Modify `backend/app/routers/receptores.py`: delete the temp `POST /admin/backfill-cuentas-bancarias` endpoint and its SQL Core table constructs
- [x] 18.4 Delete `backend/tests/test_backfill_cuentas_bancarias.py`
- [x] 18.5 Verify: `cd backend && venv/Scripts/python.exe -m pytest -q` — 0 failures, count = baseline minus the deleted backfill tests (507 - 18 deleted backfill tests + 4 new model tests = 493 passed)
- [x] 18.6 Verify migration round-trip on a fresh DB: `alembic upgrade head` then `downgrade -1` then `upgrade head` — clean at every step (offline SQL for Postgres both directions verified; live round trip via alembic blocked on SQLite repo-wide by pre-existing non-batch migrations, see apply-progress; functional DDL/DML round trip verified via raw sqlite3 scratch DB)
- [x] Extra (owner-approved cleanup): removed dead `ReporteDetalleGestor`, `ReporteDetalleCuenta`, `ReporteDetalleReceptor`, `ReporteResponse` from `backend/app/schemas/common.py` — confirmed unused (live `GET /reportes` uses its own `*Extendido` classes in `routers/reportes.py`)

### Operational: Prod Sequencing After PR4

- [ ] OPS-11 Merge PR4 to `main`; deploy (drop migration runs automatically via `start.sh`)
- [ ] OPS-12 Confirm the admin backfill endpoint returns 404 in prod (route removed)

---

## Scenario Coverage Map (9 requirements, 23 scenarios — all mapped, 0 gaps)

| Requirement | Scenarios | Task(s) |
|---|---|---|
| Default Bank Account | 5/5 | 3.1, 3.2, 3.3, 3.4, 3.5 |
| Gestor Account Assignment and Propagation | 2/2 | 9.3, 9.4 |
| Payment Account Inheritance | 3/3 | 9.6, 9.7, 9.8 |
| Individual Payment Account Change | 2/2 | 9.9, 9.10 |
| Cascading Filters on Payment Listing | 4/4 | 12.1, 12.2, 12.3, 12.4 |
| Report Per-Account Sub-Breakdown | 2/2 | 12.6, 12.7 |
| Backfill Endpoint | 2/2 | 6.9, 6.5 |
| Role Gates | 1/1 | 9.13 |
| Account Visible Wherever the Receptor Was | 3/3 `[manual]` | 17.1, 17.2, 17.7 |
