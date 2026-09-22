# Tasks: Receiver Cash Balance (item 9)

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | Slice 1 ~250-350; Slice 2 ~300-400 |
| 400-line budget risk | Medium |
| Chained PRs recommended | Yes |
| Suggested split | PR 1 (ledger foundation) → PR 2 (movements + UI) |
| Delivery strategy | ask-on-risk |
| Chain strategy | feature-branch-chain |

Decision needed before apply: Yes
Chained PRs recommended: Yes
Chain strategy: feature-branch-chain
400-line budget risk: Medium

### Suggested Work Units

| Unit | Goal | Likely PR | Focused test command | Runtime harness | Rollback boundary |
|------|------|-----------|----------------------|-----------------|-------------------|
| 1 | Model + migration + schemas + service + 3 read endpoints, no UI change | PR 1 (base = tracker/feature branch) | `pytest backend/tests/test_receptor_ledger_service.py backend/tests/test_receptores_saldo_router.py -q` | Staging Postgres: run alembic upgrade head, hit `GET /receptores/saldos` | Revert PR 1; `alembic downgrade -1` drops table+enum, zero data loss |
| 2 | Salida/correccion write endpoints + frontend badge/modal | PR 2 (base = PR 1 branch) | `pytest backend/tests/test_receptores_movimientos_routes.py -q && pnpm --filter frontend test ReceptoresPage` | Staging Postgres: two concurrent salidas on same cuenta, assert exactly one succeeds | Revert PR 2 only; ledger table/data from PR 1 untouched |

## Phase 1: Backend Foundation (PR 1)

- [x] 1.1 Create `backend/app/models/receptor_movimiento.py`: `TipoMovimiento` enum, `MovimientoReceptor` model (no AuditMixin, immutable), CHECK constraint, 2 indexes.
- [x] 1.2 Add `movimientos_receptor` backref on `Usuario` model.
- [x] 1.3 **[Enum-drop task]** Create Alembic migration `backend/alembic/versions/e5f6a7b8c9d0_create_receptor_movimientos.py` (`down_revision='d4e5f6a7b8c9'`): `upgrade()` creates table + 2 indexes; `downgrade()` drops indexes, drops table, THEN explicitly `sa.Enum(name='tipo_movimiento_receptor_enum').drop(op.get_bind())` — Postgres does not drop the enum with `op.drop_table`.
- [x] 1.4 Create `backend/app/schemas/receptor_movimiento.py`: `MovimientoCreate`, `CorreccionCreate`, `MovimientoResponse`, `SaldoCuentaResponse`, `SaldoReceptorResponse`.
- [x] 1.5 RED: write `test_receptor_ledger_service.py` cases (no pagos, pagado=False ignored, soft-deleted Pago ignored, salida subtracts, +/- correccion, multi-cuenta isolation, Decimal cent precision, retroactive reassignment, FOR UPDATE present in compiled Postgres statement).
- [x] 1.6 GREEN: implement `backend/app/services/receptor_ledger_service.py` — `saldos_por_cuenta`, `saldos_por_receptor`, `listar_movimientos`, `registrar_movimiento` (with `SELECT ... FOR UPDATE`).
- [x] 1.7 RED: write route tests for `GET /receptores/saldos`, `GET /receptores/{id}/saldo`, `GET /receptores/{id}/movimientos` (200/403 by role, 404 unknown receptor, pagination shape).
- [x] 1.8 **[Route-ordering task]** GREEN: add read endpoints to `backend/app/routers/receptores.py` with `ROLES_LECTURA_SALDO`. Register `GET /receptores/saldos` BEFORE `GET /receptores/{receptor_id}` — verify no 422 from UUID path-param shadowing.
- [ ] 1.9 Run full backend suite (DONE — 558/558 passing); open PR 1 targeting the tracker/feature branch (NOT DONE — explicit instruction to stop before push/PR for review; branch `feat/receptor-cash-balance-ledger` ready with 5 commits off latest `main`, not pushed).

## Phase 2: Write Endpoints + Tests (PR 2, base = PR 1 branch)

- [ ] 2.1 Add `ROLES_SALIDA = ("admin",)`, `ROLES_CORRECCION = ("admin",)` module-level tuples in `receptores.py`.
- [ ] 2.2 RED: write tests for `POST .../salidas` and `POST .../correcciones` (201, 409 exactly-over, 200 exactly-equal, 403 recaudador, 404 foreign cuenta, negative correccion ok, zero correccion rejected, audit_log row written).
- [ ] 2.3 GREEN: implement `POST /receptores/{id}/cuentas/{cuenta_id}/salidas` and `.../correcciones`, verifying cuenta ownership (404) and calling `audit_service.registrar_creacion`.
- [ ] 2.4 Manual OPS: two concurrent salidas draining same cuenta on staging Postgres — confirm exactly one succeeds.

## Phase 3: Frontend

- [ ] 3.1 Add `TipoMovimiento`, `MovimientoReceptor`, `SaldoCuenta`, `SaldoReceptor` types to `frontend/src/types/index.ts`.
- [ ] 3.2 Add `receptoresApi.saldos/saldo/movimientos/registrarSalida/registrarCorreccion` to `frontend/src/api/index.ts`.
- [ ] 3.3 In `ReceptoresPage.tsx`, call `saldos(ids)` after `cargar()`, render "Saldo" badge column (green ≥0, amber <0, COP format).
- [ ] 3.4 Add `modalMovimientos` (mirrors `modalCuentas`): per-cuenta breakdown, paginated history, salida/correccion forms gated admin-only, two-step `ConfirmarCreacion` confirm, 409 via `toast.error(detail)`.
- [ ] 3.5 Open PR 2 targeting PR 1's branch; verify diff shows only PR 2's changes.

## Phase 4: Cleanup

- [ ] 4.1 Confirm `openspec/changes/receiver-cash-balance/design.md` Open Questions remain resolved; no backfill needed either direction.
