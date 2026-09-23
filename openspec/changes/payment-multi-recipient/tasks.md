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

## Phase 1: Model, Migration & Default Reparto (PR 1)

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

- [ ] 2.1 Create `backend/app/schemas/pago_reparto.py`: `RepartoItem` (model_validator: exactly one id matching `tipo_destinatario`), `RepartoResponse`.
- [ ] 2.2 Add `repartos: list[RepartoResponse] = []` to `PagoResponse` in `backend/app/schemas/pago.py`.
- [ ] 2.3 RED: write `backend/tests/test_pago_reparto_service.py` cases for `reemplazar_repartos` — exact-sum accepted, ±0.01 rejected, duplicate recipient rejected, unknown/deleted cuenta or cliente rejected, empty set rejected, pending pago rejected (422), no `Credito` created for client recipients.
- [ ] 2.4 GREEN: implement `reemplazar_repartos(db, pago, items)` in `pago_reparto_service.py` — validate, soft-delete active rows, insert new rows, return `(antes, despues)`.
- [ ] 2.5 RED: write inheritance unit tests via `cuenta_heredable` — 1 recipient leaves next cuota untouched; 2+ recipients (cuenta+cuenta or cuenta+cliente) nulls the next pending cuota's `cuenta_bancaria_id` only if it still equals the previous value (manually changed next cuota is not touched).
- [ ] 2.6 GREEN: implement `cuenta_heredable(repartos)` and wire it into the `PUT` handler's post-`reemplazar_repartos` step.
- [ ] 2.7 RED: write `backend/tests/test_pago_reparto_router.py` — `GET /pagos/{id}/repartos` and `PUT /pagos/{id}/repartos` role checks (admin/recaudador 200, registrador 403), audit_log entry written via `audit_service.registrar_actualizacion_campos`.
- [ ] 2.8 GREEN: add `GET`/`PUT /pagos/{id}/repartos` to `backend/app/routers/pagos.py` with `_get_pago_con_credito(lock=True)`.
- [ ] 2.9 RED: write `backend/tests/test_pagos_router.py` cases for the `GET /pagos` EXISTS filter — split pago matches once per matching cuenta/receptor, no duplicate rows; pending pago still matches via legacy `cuenta_bancaria_id`.
- [ ] 2.10 GREEN: rewrite the `receptor_id`/`cuenta_bancaria_id` filter in `GET /pagos` to the correlated `EXISTS` clause; batch-load `repartos` for the page's items into the response.
- [ ] 2.11 RED: write `backend/tests/test_reportes.py` cases — split pago attributes revenue to each cuenta for its exact share, no double counting; client-type reparto rows excluded from cuenta-based report.
- [ ] 2.12 GREEN: rewrite `backend/app/routers/reportes.py` revenue-by-cuenta grouping to read from `pago_repartos` instead of `Pago.cuenta_bancaria_id`.
- [ ] 2.13 Run full backend suite; verify no regression in existing `test_reportes_arrastre.py` and receiver-bank-account-assignment tests.

## Phase 3: Frontend (PR 3)

- [ ] 3.1 Add `TipoDestinatario`, `RepartoItem`, `RepartoResponse` types to `frontend/src/types/index.ts`; add `repartos` to the `Pago` type.
- [ ] 3.2 Add `pagosApi.obtenerRepartos(id)` / `pagosApi.reemplazarRepartos(id, items)` to `frontend/src/api/index.ts`.
- [ ] 3.3 Create `frontend/src/components/pagos/RepartoPagoModal.tsx`: recipient search (`SelectCuentaBancaria` for accounts, `clientesApi.listar({busqueda})` for clients), per-row `monto` input, live "asignado / restante" indicator, submit disabled until remainder is 0.
- [ ] 3.4 In `frontend/src/pages/Pagos/PagosPage.tsx`, route paid pagos' "Modificar cuenta" action to `RepartoPagoModal`; pending pagos keep the existing single-cuenta modal.
- [ ] 3.5 Verify TypeScript build passes (`npm run build` in `frontend/`); manual smoke test of a 2-recipient split against the PR 2 API.

## Phase 4: Cleanup

- [x] 4.1 Update `openspec/changes/payment-multi-recipient/design.md` Open Questions: confirm prod Postgres ≥13 (`gen_random_uuid()`) — done 2026-09-22, prod runs PostgreSQL 18 (Railway). Note the accepted no-overdraft-check parity with item 9 decision 2.
- [ ] 4.2 Confirm `receiver-bank-account-assignment` spec delta and `receptor-ledger` spec delta both reflect the shipped behavior; archive-ready.
