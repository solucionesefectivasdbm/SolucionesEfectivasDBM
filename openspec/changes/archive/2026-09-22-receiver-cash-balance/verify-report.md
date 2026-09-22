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

---

# Verification Report — receiver-cash-balance PR 2/2 (write endpoints + frontend)

**Scope**: Phase 2 (write endpoints, tasks 2.1-2.4) + Phase 3 (frontend, tasks 3.1-3.5) + Phase 4 (4.1) only. PR 1 (Phase 1) already independently verified PASS above — not re-verified here.
**Branch**: `feat/receptor-cash-balance-movimientos`, branched off `feat/receptor-cash-balance-ledger` at tip `cc97ee0` (confirmed via `git merge-base`), 6 local commits, not pushed, no PR opened.
**Size**: 777 changed lines vs a 300-400 forecast — explicitly accepted by the product owner as `size:exception`. Not re-flagged as a blocking finding; substance was verified instead.

## Verdict: PASS

Ready for push/PR, scoped to PR 2's work only.

## Test execution (independently run, not trusted from apply-progress)

- `cd backend && venv/Scripts/python.exe -m pytest -q` → **576 passed**, 0 failed, 0 skipped — matches apply-progress's claimed 576/576 exactly.
- `cd frontend && npx tsc --noEmit` → 0 errors, clean exit.
- `cd frontend && npm run build` → clean Vite production build (1660 modules transformed), no errors, only a pre-existing unrelated Browserslist notice — matches the claim.

## Spec vs implementation

- **POST salida (admin-only, overdraft-protected)**: `ROLES_SALIDA = ("admin",)` gates `registrar_salida` via `require_role`. `registrar_movimiento` in `receptor_ledger_service.py` takes a `SELECT ... FOR UPDATE` lock on the `cuentas_bancarias` row, recomputes `saldos_por_cuenta` under that lock, and raises `HTTPException(409, ...)` when `monto > saldo_actual`, without ever calling `db.add()` — confirmed no row is persisted on rejection (`test_salida_excede_saldo_devuelve_409_y_no_persiste` asserts a `COUNT(*) == 0` query, not just the HTTP status). Exactly-equal case (`monto == saldo_actual`) is accepted (201) — confirmed by both source logic (`>` not `>=`) and `test_salida_exactamente_igual_al_saldo_devuelve_201`. `audit_service.registrar_creacion` is called after every successful write; `test_salida_escribe_audit_log` queries the real `AuditLog` table and asserts a matching row with `accion == CREATE` and the correct `usuario_id` — matches spec exactly.
- **POST correccion (admin-only, no overdraft check)**: `ROLES_CORRECCION = ("admin",)` gates `registrar_correccion`. Both positive and negative amounts are accepted freely (`test_correccion_no_tiene_chequeo_de_sobregiro` drives the balance to `-400.00` and asserts 201, confirming no overdraft rejection path exists for this type — correccion never enters the salida-only overdraft branch). Optional free-text `nota` confirmed via schema and a passing test with a note attached. Zero-amount correccion is rejected (422) at the Pydantic schema layer, confirmed by `test_correccion_monto_cero_devuelve_422`. `audit_log` row written, confirmed the same way as salida.
- **Correccion → salida interaction is genuinely correct in the code, not just claimed by a test**: verified this directly by reading `receptor_ledger_service.py`. Both `registrar_salida` and `registrar_correccion` call the *same* `registrar_movimiento` function, which *always* recomputes `saldo_actual` via a fresh `saldos_por_cuenta` query under the row lock — there is no cached/stale balance anywhere in this path. `test_salida_respeta_saldo_ya_reducido_por_correccion_previa` proves this end-to-end at the HTTP layer: a -50000 correccion against a 100000 balance is applied first (201), then a 50001 salida is correctly rejected (409) and an exactly-50000 salida is correctly accepted (201), with a final `GET /saldo` confirming `saldo_total == 0.00`. This is a real behavioral assertion against actual computed values, not a mocked or tautological check.
- **Ledger read endpoints (admin + recaudador)**: unchanged from PR 1, not touched by this diff — re-confirmed not regressed (576/576 includes PR 1's read-endpoint tests, still green).

## Design vs implementation

- Both write routes use the shared `_obtener_cuenta_del_receptor` helper (identical query shape to the existing `actualizar_cuenta` route) to verify cuenta ownership before any ledger write, raising 404 "Cuenta no encontrada" for both a foreign cuenta and a nonexistent cuenta — matches design.md's endpoint table and the documented PR-2 deviation (the router-level 404 shadows `registrar_movimiento`'s own service-level 404 for this call path, but that path remains independently covered by PR 1's service-level unit tests — no coverage was lost).
- HTTP 201 (not 200) for the exactly-equal-balance salida — matches design.md's endpoint table verbatim (design.md, not tasks.md's imprecise wording, is the authoritative source per PR 1's own established precedent).
- `usuario_nombre` sourced from `current_user.username` directly rather than a relationship reload — reasonable, avoids an extra query, consistent with the rest of this router's pattern; no spec/design violation.
- Frontend history list has no `cuenta_bancaria_id` filter UI — correctly scoped out per design.md's "Frontend Surface" section, which describes only "paginated history" with no filter control.

## Frontend verification (source-read, not just claimed)

- `ReceptoresPage.tsx`: `saldosMap` populated via `receptoresApi.saldos(ids)` inside `cargar()`; a "Saldo" badge column renders `badge-success` when `saldo_total >= 0` and `badge-warning` when negative, formatted via `formatCOP` — matches spec/design.
- `modalMovimientos` (line 445) renders the per-cuenta saldo breakdown and a paginated movement history table (salida rows tagged `badge-warning`, correccion rows tagged `badge-info`).
- Write forms (`modalRegistroMovimiento` triggering `registrarSalida`/`registrarCorreccion`) are rendered only inside the `{perms.isAdmin && (...)}` block at line 473 — confirmed by direct source read, not inferred. Non-admin users (recaudador) never see the write form.
- `modalConfirmarMovimiento` implements the required two-step `ConfirmarCreacion` confirm pattern before submission, mirroring the existing `modalCuentas`/`modalConfirmarCuenta` precedent.
- 409 overdraft errors surface via the existing `toast.error(detail)` catch pattern — confirmed present in the submit handler.

## Task completion (tasks.md cross-checked against code)

- 2.1-2.3: genuinely complete — `ROLES_SALIDA`/`ROLES_CORRECCION` tuples, both POST routes, and `_obtener_cuenta_del_receptor` helper all confirmed present by direct source read; 18 real behavioral tests confirmed in `test_receptores_movimientos_router.py` (17 named test functions, one parametrized over 3 roles for both salida and correccion role-rejection tests, totaling 18 collected test items — matches the claimed count).
- 3.1-3.4: genuinely complete — types, API client methods, saldo badge, and `modalMovimientos`/`modalRegistroMovimiento`/`modalConfirmarMovimiento` all confirmed present and wired by direct source read.
- 2.4 and 3.5: correctly left unchecked in tasks.md, and this is accurately represented — not silently-incomplete work mislabeled as out-of-scope. 2.4 requires a live staging Postgres environment for a manual concurrency race test (the underlying `FOR UPDATE` lock mechanism itself was already compile-verified in PR 1 and is exercised end-to-end, execution-wise, by every test in this file). 3.5 requires explicit user authorization to push/open a PR, which is outside this agent's capability and was explicitly deferred per instruction. Neither task's absence hides any missing production code.
- 4.1: genuinely complete — design.md's Open Questions section confirmed still consistent with PR 2's actual scope (no `receptor_id`-scoped write path was introduced; schema remains keyed only to `cuenta_bancaria_id`).

## Issues

- **CRITICAL**: none.
- **WARNING**: none new in PR 2 (PR 1's two WARNING-tier doc-drift issues were already fixed in a follow-up docs commit before PR 2 began, per apply-progress's own note — confirmed no regression of those fixes in this diff).
- **SUGGESTION**: none.
