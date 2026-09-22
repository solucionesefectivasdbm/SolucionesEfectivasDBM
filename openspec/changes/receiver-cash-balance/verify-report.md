# Verification Report — receiver-cash-balance PR 1/2 (ledger foundation)

**Scope**: Phase 1 tasks 1.1-1.9 only (Phase 2/3 explicitly out of scope, belong to a future PR 2).
**Branch**: `feat/receptor-cash-balance-ledger`, 6 local commits off latest `main` (cfa7721), not pushed, no PR opened.

## Verdict: PASS

Ready for the review lifecycle / PR push, scoped to Phase 1 work only.

## Test execution (independently run, not trusted from apply-progress)

- `venv/Scripts/python.exe -m pytest -q` → **558 passed**, 0 failed — matches apply-progress's claim exactly.
- New-file-only run (`test_models.py`, `test_schema_receptor_movimiento.py`, `test_receptor_ledger_service.py`, `test_receptores_saldo_router.py`) → **64 passed** — matches claimed count.
- `FOR UPDATE` race-safety mechanism confirmed present, not just claimed: `_select_cuenta_for_update` in `receptor_ledger_service.py` uses `.with_for_update()`, and `test_for_update_presente_en_sql_compilado_postgres` asserts `"FOR UPDATE"` appears in the Postgres-dialect-compiled SQL string (SQLite test DB ignores FOR UPDATE at execution time — the compile-check correctly works around that).

## Spec vs implementation

- Compute-on-read balance: confirmed, no cached column on `Receptor`/`CuentaBancaria`. Formula `saldo = recaudado - salidas + correcciones` in `saldos_por_cuenta`, `Decimal` throughout, grouped SQL `SUM`, no per-row Python loop / no N+1.
- **Note**: spec.md's own prose says `SUM(Pago.monto ...)` but `Pago` has no `monto` field — only `monto_a_pagar`, `capital_pagado`, `interes_pagado`. design.md correctly specifies `capital_pagado + interes_pagado` and the code matches design.md exactly. This is a spec.md wording imprecision, not a code defect (WARNING, not CRITICAL — design.md is the authoritative technical source and both design and code agree).
- Overdraft: `registrar_movimiento` takes `FOR UPDATE` lock on `cuentas_bancarias` row first, recomputes balance under lock, rejects `salida` when `monto > saldo_actual` with 409, accepts exactly-equal. Matches spec scenarios exactly.
- Correccion: signed, zero rejected via Pydantic validator, no overdraft check — matches design decision 4.
- Ledger survives receptor soft-delete: explicit test `TestSaldoSobreviveSoftDeleteDeReceptor` present.
- Read endpoint roles: `ROLES_LECTURA_SALDO = ("admin", "recaudador")` — matches spec's read-access requirement.

## Design vs implementation

- `receptor_movimientos` table DDL (model + migration) matches design.md exactly: no `deleted_at`/`updated_at`, CHECK constraint `(tipo='salida' AND monto>0) OR (tipo='correccion' AND monto<>0)`, `Numeric(15,2)`, 2 indexes, FKs to `cuentas_bancarias.id` and `users.id`.
- Migration `e5f6a7b8c9d0` — `down_revision='d4e5f6a7b8c9'` confirmed correct against the actual file `d4e5f6a7b8c9_drop_receptor_id_from_gestores_pagos.py`. `downgrade()` drops both indexes, drops table, then explicitly `sa.Enum(name='tipo_movimiento_receptor_enum').drop(op.get_bind())`.
- Route ordering: `GET /receptores/saldos` (line 101) registered BEFORE `GET /receptores/{receptor_id}` (line 132), confirmed via direct file read.
- `Usuario.movimientos_receptor` backref present; model registered in `app/models/__init__.py`.
- Documented deviations (test filename, extra 404 guard, LEFT JOIN) are all reasonable and test-covered — no spec violations. WARNING-tier only: tasks.md's Suggested Work Units table still references the old test filename.

## Task completion (tasks.md cross-checked against code)

- 1.1-1.8: genuinely complete, code backs every checked box — verified by direct source read.
- 1.9: correctly left unchecked — full suite green but PR intentionally not opened per explicit instruction. No gap between apply-progress's claim and actual repo state.
- Phase 2/3/4: correctly left unchecked and untouched; no write-endpoint or frontend code leaked into this diff.

## Size exception

Actual diff vs `main`: 1412 lines (504 production + 908 test), independently reproduced via `git diff --stat`, matching apply-progress's self-reported figure exactly. Accepted `size:exception` per product owner — not re-flagged as blocking.

## Issues

- **CRITICAL**: none.
- **WARNING**: spec.md prose references a nonexistent `Pago.monto` field instead of `capital_pagado + interes_pagado`; recommend fixing spec.md wording before archive (design.md and code are already correct).
- **WARNING**: tasks.md's Suggested Work Units table cites `test_receptores_saldo_routes.py` (plural) instead of the actual `test_receptores_saldo_router.py`; cosmetic, recommend syncing before archive.
- **SUGGESTION**: none beyond the above.
