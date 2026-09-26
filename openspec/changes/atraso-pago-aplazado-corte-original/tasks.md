# Tasks: Mora cut-off by original momento for deferred payments

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~850-950 (prod ~450, tests ~400) |
| 400-line budget risk | High |
| Chained PRs recommended | Yes |
| Suggested split | PR1 → PR2 → PR3 → PR4 |
| Delivery strategy | ask-on-risk |
| Chain strategy | feature-branch-chain |

Decision needed before apply: Yes
Chained PRs recommended: Yes
Chain strategy: feature-branch-chain
400-line budget risk: High

### Suggested Work Units

| Unit | Goal | Likely PR | Focused test command | Runtime harness | Rollback boundary |
|------|------|-----------|----------------------|-----------------|-------------------|
| 1 | Schema + model: migration, `before_insert`, schema field | PR 1 (base: tracker) | `pytest backend/tests/test_models_pago.py -k fecha_maxima_original` | `alembic upgrade head` on local DB | Revert migration + model listener, no readers depend yet |
| 2 | Core mora logic + `pagos.py` call sites | PR 2 (base: PR 1) | `pytest backend/tests/test_momentos.py backend/tests/test_aplazamientos.py backend/tests/test_mora_momento_cerrado.py -k pagos` | `GET /pagos?momento=` manual check | Revert `momentos.py`/`pagos.py` diff, column stays inert |
| 3 | Remaining call sites (`clientes.py`, `creditos.py`, `reportes.py`) + re-anchor resync | PR 3 (base: PR 2) | `pytest backend/tests/test_mora_momento_cerrado.py backend/tests/test_dias_pago_endpoint.py backend/tests/test_reportes_cartera_vencida.py` | `GET /reportes/cartera-vencida` manual check | Revert per-file, PR 2 behavior unaffected |
| 4 | Backfill service + temporary admin endpoint | PR 4 (base: PR 3) | `pytest backend/tests/test_fecha_original_backfill.py backend/tests/test_admin_backfill.py` | `POST /admin/migracion/fecha-maxima-original?dry_run=true` against staging copy | Delete `admin.py`/service/router registration; no other behavior depends on it |

## Phase 1: Schema & Model Foundation

- [x] 1.1 Create Alembic revision `a7b8c9d0e1f2_add_fecha_maxima_original_to_pagos.py`: nullable column, `UPDATE ... SET fecha_maxima_original = fecha_maxima WHERE NULL`, index `ix_pagos_fecha_maxima_original`. Confirm `down_revision` via `alembic heads`. Confirmed head was `f6a7b8c9d0e1` via `alembic heads` (matches design.md D1). Verified via an isolated SQLite `Operations` test (RED→GREEN) plus `alembic upgrade f6a7b8c9d0e1:a7b8c9d0e1f2 --sql` (Postgres dialect render through the real `env.py`).
- [x] 1.2 RED: test asserting new `Pago()` sets `fecha_maxima_original == fecha_maxima` on insert. Added `TestPagoFechaMaximaOriginal` in `backend/tests/test_models.py` (not a new `test_models_pago.py` — this repo keeps Pago model-field tests inside `test_models.py`; see `TestReceptorIdDroppedFromGestorAndPago` precedent). Confirmed RED (AttributeError/TypeError) before 1.3.
- [x] 1.3 GREEN: add column + `before_insert` mapper listener to `backend/app/models/pago.py`. Triangulated with a second case (explicit non-None value is not overwritten) — verified the naive Fake-It (unconditional copy) breaks that second test, then reverted to the real `is None` guard.
- [x] 1.4 Add `fecha_maxima_original: Optional[date] = None` to `PagoResponse` (`backend/app/schemas/pago.py`). **Resolved in PR2, as task 2.4** (was deferred from PR1 — see history below): landed together with its first real producer (`_pago_row_a_dict`), keeping `test_pagos_listado.py::TestPagoRowADict::test_dict_cubre_todos_los_campos_de_response` green throughout.
  - _(Original PR1 note, kept for history)_: Adding it in PR1 alone breaks the pre-existing regression guard `test_pagos_listado.py::TestPagoRowADict::test_dict_cubre_todos_los_campos_de_response`, which asserts `_pago_row_a_dict` covers every `PagoResponse` field — and `_pago_row_a_dict` is explicitly out of scope for PR1 (task 2.4). Bundling the schema field with its first real producer in PR2 keeps `main` green after every merge and matches task 2.4's own scope (`_pago_row_a_dict` already lists `fecha_maxima_original` as something it must select/pass). No PR1 code depends on this field existing yet.

## Phase 2: Core Mora Evaluation + Listing

- [x] 2.1 RED `test_momentos.py`: `flags_mora` unchanged when original==current; deferral crossing boundary → `en_mora=True, vencido=True`; deferral inside same momento → no mora. DONE: `TestFlagsMora` (4 cases, incl. explicit backward-compat case for callers that omit the new kwarg).
- [x] 2.2 GREEN: `backend/app/utils/momentos.py` — `flags_mora` keyword-only `fecha_maxima_original`; `en_mora = original < limite`; `vencido = (fecha_maxima < hoy) or en_mora`; update docstrings. DONE: kwarg is `date | None = None` (not a bare required kwarg) — a required kwarg would break the untouched `creditos.py::historial_cuotas` call site (Phase 3 scope), regressing the item-8 scheduled-overdue-evaluation feature. Confirmed no regression via `test_mora_momento_cerrado.py::TestHistorialCuotasFlagsMora` (unchanged, still green).
- [x] 2.3 RED `test_aplazamientos.py`: PATCH `/pagos/{id}/fecha` (both `es_aplazamiento` true/false) leaves `fecha_maxima_original` unchanged; pago stays in `GET /pagos?momento=` original momento. DONE: `TestFechaMaximaOriginalInmutable` (3 cases: aplazamiento unchanged, corrección libre unchanged per D4, momento-persistence end-to-end via real PATCH + GET).
- [x] 2.4 GREEN: `routers/pagos.py` — `_pago_row_a_dict`, `listar_pagos`, `listar_pagos_aplazados` select/filter/pass `fecha_maxima_original`. Also add `fecha_maxima_original: Optional[date] = None` to `PagoResponse` (moved from 1.4 — see note there) in the same PR, so the schema field and its first producer land together. DONE: `listar_pagos`'s WHERE range filter (month/momento) now uses `fecha_maxima_original`; display/sort/ORDER BY stay on `fecha_maxima` with `Pago.id` tiebreaker (unchanged, already present). `listar_pagos_aplazados` has no date-range filter, so only SELECT+passthrough changed there. Fixed `test_pagos_listado.py::_fake_row` to default `fecha_maxima_original` to the row's own `fecha_maxima` (never-deferred baseline) so pre-existing unit tests keep passing.
- [x] 2.5 RED `test_mora_momento_cerrado.py` (pagos.py scope): `alertas/vencidos` flags a crossing deferral, not a non-crossing one. DONE: `TestAlertasVencidosCorteOriginal` (2 cases) + 1 assertion added to the existing virtual-row test (`fecha_maxima_original == fecha_maxima` for projected rows).
- [x] 2.6 GREEN: `alertas_vencidos` uses `fecha_maxima_original < limite`, `ORDER BY fecha_maxima_original, Pago.id`; `_calcular_virtuales` sets `fecha_maxima_original = fecha_proy`. DONE.

## Phase 3: Remaining Call Sites + Re-anchor Resync — DONE 7/7

- [x] 3.1 RED `test_mora_momento_cerrado.py` (clientes/creditos scope): 3 `al_dia` predicates and `historial_cuotas` flag a crossing deferral. DONE: added `test_aplazamiento_cruza_cierre_marca_en_atraso` + `test_aplazamiento_dentro_del_mismo_momento_sigue_al_dia` to `TestClientesAlDiaMomentoCerrado`, and `test_historial_cuotas_aplazamiento_cruza_cierre_marca_en_mora` + `test_historial_cuotas_aplazamiento_dentro_del_momento_no_marca_mora` to `TestHistorialCuotasFlagsMora`. Confirmed RED (crossing cases failed; non-crossing cases already passed — forward deferral within an still-open momento can never flip `< limite`, so they only guard against over-counting).
- [x] 3.2 GREEN: `routers/clientes.py` L59/113/203 (`listar_clientes` list+page subqueries, `obtener_cliente` detail) use `fecha_maxima_original < limite`. DONE.
- [x] 3.3 GREEN: `routers/creditos.py` `historial_cuotas` passes `fecha_maxima_original=p.fecha_maxima_original` to `flags_mora`. DONE.
- [x] 3.4 RED `test_reportes_cartera_vencida.py`: deferred pago counts in the window derived from its original date. DONE: added `test_aplazamiento_no_saca_de_la_ventana_de_su_corte_original`; extended `_mk_pago` helper with an optional `fecha_maxima_original` kwarg. Confirmed RED. Also discovered and fixed a PRE-EXISTING test that encoded the OLD (now superseded) behavior — see Deviations.
- [x] 3.5 GREEN: `routers/reportes.py` cartera-vencida query: `lo <= Pago.fecha_maxima_original < hi`. DONE.
- [x] 3.6 RED `test_dias_pago_endpoint.py` + `test_credito_service.py`: `recalcular_cuotas_futuras` resyncs `fecha_maxima_original` on pending cuotas; paid cuotas unchanged. DONE: unit test `test_6_6_a_fecha_maxima_original_resincronizada_en_pendientes` in `TestRecalcularCuotasFuturasAnchor`, integration test `test_fecha_maxima_original_resincronizada_para_pendientes` in `TestDiasPagoReanchorSemantics` (real `PATCH /creditos/{id}/dias-pago`), plus a companion assertion added to the pre-existing `test_paid_cuotas_untouched`. Confirmed RED on both new tests; companion assertion already green (paid cuotas were never in `recalcular_cuotas_futuras`'s query).
- [x] 3.7 GREEN: `credito_service.py` `recalcular_cuotas_futuras` sets `cuota.fecha_maxima_original = fecha_actual` alongside `fecha_maxima`/`momento`. DONE.
- [x] Confirmed no regression (verification only, not a new task): `PATCH /pagos/{id}/fecha` (`modificar_fecha_pago`, pagos.py) still touches only `fecha_maxima` and `veces_aplazado` — `fecha_maxima_original` is untouched in both `es_aplazamiento` modes, matching design D4. Re-verified via full `test_aplazamientos.py` run (28/28 passing).

## Phase 4: Backfill Service + Admin Endpoint

- [ ] 4.1 RED unit tests for `resolver_fecha_original`: earliest audit row wins; no rows → fallback; unparsable value; events before re-anchor ignored; pago paid before re-anchor keeps audit value.
- [ ] 4.2 GREEN: create `backend/app/services/fecha_original_backfill.py` — `resolver_fecha_original(...)` (pure) and `ejecutar(db, usuario_id, ip, dry_run)` (3 batched queries, no N+1).
- [ ] 4.3 RED integration tests: `dry_run=true` (default) writes nothing; apply writes rows + `audit_log` via `registrar_actualizacion_campos`; second run gives `a_modificar=0`; non-admin gets 403.
- [ ] 4.4 GREEN: create `backend/app/routers/admin.py` — `POST /admin/migracion/fecha-maxima-original?dry_run=true`, admin-only; register router in `backend/app/main.py`.

## Phase 5: Verification & Cleanup

- [ ] 5.1 Run full backend suite; confirm no regression in existing mora/pagos/reportes tests.
- [ ] 5.2 Deploy: auto-migrate fills the column; run dry run in prod; review counts with user before apply.
- [ ] 5.3 Notify users: deferred pagos crossing their momento switch to en mora on deploy (accepted risk, per spec).
- [ ] 5.4 Follow-up commit (after backfill confirmed applied): delete `admin.py`, `fecha_original_backfill.py`, and router registration in `main.py`.
