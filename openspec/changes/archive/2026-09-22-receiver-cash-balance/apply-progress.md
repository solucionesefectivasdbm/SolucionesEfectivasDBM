# Apply Progress: Receiver Cash Balance (item 9)

## PR 1 — Ledger Foundation (Phase 1)

**Mode**: Strict TDD (backend)
**Scope this run**: Phase 1 tasks only (1.1–1.9). Phase 2 (write endpoints) and Phase 3
(frontend) are explicitly out of scope — they belong to PR 2 per the feature-branch-chain
strategy confirmed by the product owner.
**Branch**: `feat/receptor-cash-balance-ledger`, created off latest `origin/main` (tip
`cfa7721`). Not pushed at the time. Not opened as a PR in this run (explicit instruction —
stop for review first). Superseded below: PR 1's branch is now the confirmed base for PR 2.

### Completed Tasks

- [x] 1.1 `backend/app/models/receptor_movimiento.py` — `TipoMovimiento` enum, `MovimientoReceptor` model (no AuditMixin, immutable), CHECK constraint, 2 indexes.
- [x] 1.2 `movimientos_receptor` backref on `Usuario`.
- [x] 1.3 Alembic migration `e5f6a7b8c9d0_create_receptor_movimientos.py` (`down_revision='d4e5f6a7b8c9'`) — explicit enum drop in `downgrade()`.
- [x] 1.4 `backend/app/schemas/receptor_movimiento.py` — `MovimientoCreate`, `CorreccionCreate`, `MovimientoResponse`, `SaldoCuentaResponse`, `SaldoReceptorResponse`.
- [x] 1.5 RED — `test_receptor_ledger_service.py` (22 cases).
- [x] 1.6 GREEN — `backend/app/services/receptor_ledger_service.py`.
- [x] 1.7 RED — `test_receptores_saldo_router.py` (17 cases).
- [x] 1.8 GREEN — read endpoints in `backend/app/routers/receptores.py`, `/saldos` registered before `/{receptor_id}`.
- [~] 1.9 Full suite run: DONE (558/558 passing). PR opened: NOT DONE (explicit instruction).

## TDD Cycle Evidence

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|-------------|----------|
| 1.1 | `tests/test_models.py::TestMovimientoReceptor` | Unit (real SQLite DB — CHECK constraints ARE enforced by SQLite, unlike `FOR UPDATE`) | ✅ 504/504 (whole-suite baseline) | ✅ Written (`ModuleNotFoundError` on collection) | ✅ Passed | ✅ 4 CHECK-constraint cases (salida>0 accepted, salida=0 rejected, salida<0 rejected, correccion=0 rejected, correccion<0 accepted) | ➖ None needed — matches `AuditLog` structure exactly |
| 1.2 | `tests/test_models.py::TestUsuarioMovimientosReceptorBackref` | Integration (real relationship traversal) | ✅ same baseline | ✅ Written | ✅ Passed | ➖ Single (structural relationship, one behavior) | ➖ None needed |
| 1.3 | N/A — no pytest harness for Alembic DDL exists anywhere in this repo (confirmed by repo-wide search before writing) | N/A | N/A (new file) | N/A | N/A | N/A | N/A |
| 1.4 | `tests/test_schema_receptor_movimiento.py` | Unit (pure Pydantic validation) | ✅ 512/512 | ✅ Written (`ModuleNotFoundError`) | ✅ Passed | ✅ 3 cases `MovimientoCreate` (positive/zero/negative) + 3 cases `CorreccionCreate` (positive/negative/zero) | ➖ None needed |
| 1.5/1.6 | `tests/test_receptor_ledger_service.py` | Unit (real SQLite DB for aggregation; pure-function compile check for `FOR UPDATE`) | ✅ 519/519 | ✅ Written (`ImportError`, whole file) | ✅ Passed (22/22 on first implementation) | ✅ 22 cases across recaudo filters, salida/correccion math, multi-cuenta isolation, Decimal precision, retroactive reassignment, receptor soft-delete survival, `saldos_por_receptor`, pagination, `FOR UPDATE` compiled-SQL assertion, and `registrar_movimiento` (within/exceeds/equals balance, correccion skips overdraft check, unknown cuenta → 404) | ➖ None needed — `_as_decimal` and `_select_cuenta_for_update` already extracted as pure functions |
| 1.7/1.8 | `tests/test_receptores_saldo_router.py` | Integration (HTTP via `ASGITransport`) | ✅ 541/541 | ✅ Written (11/17 failing for the right reasons; the other 6 "passed" pre-GREEN for a *different*, confirmed-understood reason — see Issues Found) | ✅ Passed (17/17) | ✅ 17 cases: route ordering, bulk vs singular saldo semantics, malformed UUID, roles × 3 endpoints, 404 (unknown + soft-deleted), pagination shape | ➖ None needed |

### Test Summary
- **Total tests written this run**: 54 (`test_models.py` +8, `test_schema_receptor_movimiento.py` +7 new file, `test_receptor_ledger_service.py` +22 new file, `test_receptores_saldo_router.py` +17 new file)
- **Full suite**: 504 → 558 (504 + 54)
- **Layers used**: Unit (41), Integration (13)
- **Approval tests**: None — no refactoring-of-existing-behavior tasks this run
- **Pure functions created**: `_as_decimal`, `_select_cuenta_for_update` (both in `receptor_ledger_service.py`, both directly unit-tested)

## Work Unit Evidence (Suggested Work Unit 1 — "ledger foundation")

| Evidence | Value |
|---|---|
| Focused test command and exact result | `venv/Scripts/python.exe -m pytest tests/test_models.py tests/test_schema_receptor_movimiento.py tests/test_receptor_ledger_service.py tests/test_receptores_saldo_router.py -q` → **64 passed** |
| Runtime harness command/scenario and exact result | HTTP-level integration harness via `httpx.AsyncClient(transport=ASGITransport(app=app))` against the real FastAPI app + real (in-memory SQLite) DB session — all 17 router tests exercise the actual ASGI request/response cycle, not mocked handlers. Additionally verified `app.openapi()` generates with no route/schema collisions, and Alembic `upgrade`/`downgrade --sql` (offline, Postgres dialect) confirmed the migration's DDL — including the enum-drop line — compiles correctly. |
| Rollback boundary | This PR's 5 commits are additive-only and self-contained: `git revert` (or simply not merging) removes the new module/schema/service/router-additions/migration cleanly. `alembic downgrade -1` drops the empty `receptor_movimientos` table + its enum type with zero data loss (table ships empty). No existing file's prior behavior was changed — `receptores.py`'s existing routes are untouched except for added imports and new routes appended around them. |

Full backend suite (all 558 tests, not just this unit): `venv/Scripts/python.exe -m pytest -q` → **558 passed**, 0 failed, 0 regressions.

## Files Changed (PR 1)

| File | Action | What Was Done |
|------|--------|----------------|
| `backend/app/models/receptor_movimiento.py` | Created | `TipoMovimiento` enum, `MovimientoReceptor` model |
| `backend/app/models/usuario.py` | Modified | `movimientos_receptor` backref |
| `backend/app/models/__init__.py` | Modified | Registered new model for Alembic autodiscovery |
| `backend/app/main.py` | Modified | Registered new model in `lifespan()`'s `create_all` import list |
| `backend/alembic/versions/e5f6a7b8c9d0_create_receptor_movimientos.py` | Created | First post-initial `create_table` migration; explicit enum drop in `downgrade()` |
| `backend/app/schemas/receptor_movimiento.py` | Created | `MovimientoCreate`, `CorreccionCreate`, `MovimientoResponse`, `SaldoCuentaResponse`, `SaldoReceptorResponse` |
| `backend/app/services/receptor_ledger_service.py` | Created | `saldos_por_cuenta`, `saldos_por_receptor`, `listar_movimientos`, `registrar_movimiento`, `_select_cuenta_for_update`, `_as_decimal` |
| `backend/app/routers/receptores.py` | Modified | `ROLES_LECTURA_SALDO`; `GET /saldos` (before `/{receptor_id}`), `GET /{id}/saldo`, `GET /{id}/movimientos` |
| `backend/tests/test_models.py` | Modified | +8 tests (CHECK constraint, backref) |
| `backend/tests/test_schema_receptor_movimiento.py` | Created | 7 tests (Pydantic validators) |
| `backend/tests/test_receptor_ledger_service.py` | Created | 22 tests (balance math, overdraft, FOR UPDATE compile check) |
| `backend/tests/test_receptores_saldo_router.py` | Created | 17 tests (roles, 404s, pagination, route ordering) |

## Deviations from Design (PR 1)

1. **Test file naming**: used `test_receptores_saldo_router.py` (singular "router", matching design.md's File Changes table AND this repo's established naming convention — `test_receptores_router.py`, `test_creditos_router.py`) rather than `test_receptores_saldo_routes.py` (plural "routes", used only in tasks.md's Suggested Work Units test-command column). Resolved by syncing tasks.md's row to the singular form.
2. **Extra test beyond tasks.md's explicit list**: added `TestSaldoSobreviveSoftDeleteDeReceptor` — spec.md's own formally named requirement ("Ledger Entries Survive Receptor Soft-Delete").
3. **Extra defensive guard**: `registrar_movimiento` raises 404 for a non-existent `cuenta_id` before attempting the insert (SQLite test DB doesn't enforce FKs by default). Test-covered (`test_cuenta_inexistente_devuelve_404`).
4. **`listar_movimientos` uses `isouter=True`** for the `Usuario` join (LEFT JOIN), matching `routers/auditoria.py`'s identical usuario-attribution pattern.
5. **Route-ordering proof**: temporarily reordered the routes, re-ran the suite to confirm 5 tests fail exactly as expected, then reverted before committing.

## Issues Found (PR 1)

- Pre-GREEN false-positive nuance in `test_receptores_saldo_router.py` (6/17 tests coincidentally passed before any router code existed, due to Starlette route-matching quirks) — fully understood, independently proven not to be a test-quality problem (mutation-revert experiment), and all 17 became genuine GREEN once the real routes existed.
- Minor process gap: ran only the schema file's own tests after task 1.4 instead of the whole suite at that checkpoint (arithmetically confirmed zero hidden regressions afterward, but flagged for transparency — **addressed in PR 2 below** by running the full suite after every checkpoint, not just at the end).

## Review Workload / PR Boundary (PR 1)

- **Mode**: chained PR slice (feature-branch-chain, PR 1 of 2, confirmed by product owner)
- **Boundary**: starts from latest `main` (`cfa7721`); ends at commit `38abd36` (5 commits, all backend-only)
- **Actual size vs forecast**: tasks.md forecast "Slice 1 ~250-350 changed lines". Actual diff vs `main`: **1412 lines** (504 production + 908 test) — driven by the mandatory strict-TDD + exhaustive-testing requirements, not scope creep. Accepted as `size:exception` by the product owner (see `verify-report.md`).

### Status (PR 1)

8/9 Phase 1 tasks fully complete (1.1–1.8); task 1.9 half-complete (suite green, PR intentionally not opened). 558/558 backend tests passing, 0 regressions. `sdd-verify` PASSED this scope (see `verify-report.md`) — two WARNING-tier doc-drift issues (spec.md wording, tasks.md filename), both fixed in a follow-up docs commit before PR 2 began.

---

## PR 2 — Movements + UI (Phase 2 + Phase 3)

**Mode**: Strict TDD (backend only). Frontend has no test infrastructure in this repo —
confirmed before starting: no `vitest`/`jest`/`playwright` dependency, no `test` script in
`frontend/package.json`. Per explicit instruction, no test framework was added; frontend
correctness was instead verified with `npx tsc --noEmit` and `npm run build` (both clean)
plus manual pattern-matching against the existing `modalCuentas`/`modalConfirmarCuenta`
precedent this PR mirrors.

**Scope this run**: Phase 2 (write endpoints) + Phase 3 (frontend) tasks only. PR 1's Phase 1
work (model, migration, service, read endpoints) was already merged into this branch's base
— read and reused via `receptor_ledger_service.registrar_movimiento`, not redone.

**Branch**: `feat/receptor-cash-balance-movimientos`, branched off `feat/receptor-cash-balance-ledger`
at its exact tip — confirmed via `git merge-base feat/receptor-cash-balance-movimientos
feat/receptor-cash-balance-ledger` == `cc97ee0` == `git rev-parse feat/receptor-cash-balance-ledger`.
Not pushed. Not opened as a PR (explicit instruction — stop for review first).

### Completed Tasks

- [x] 2.1 `ROLES_SALIDA = ("admin",)`, `ROLES_CORRECCION = ("admin",)` module-level tuples in `receptores.py`.
- [x] 2.2 RED — 18 tests in `test_receptores_movimientos_router.py` (201 within-balance, 409 exactly-over, 201 exactly-equal, 403 × 3 roles, 404 foreign cuenta, 404 nonexistent cuenta, negative + positive correccion, 422 zero correccion, no-overdraft-check on correccion, audit_log written × 2 routes, correccion→salida interaction).
- [x] 2.3 GREEN — `POST /receptores/{id}/cuentas/{cuenta_id}/salidas` and `.../correcciones` in `receptores.py`, via shared `_obtener_cuenta_del_receptor` ownership check (404) + `audit_service.registrar_creacion`. 17/17 passed on first implementation; 18th (triangulation) test passed immediately without further production changes.
- [ ] 2.4 Manual OPS (two concurrent salidas on staging Postgres) — **NOT DONE**, requires a live staging Postgres environment and manual concurrent execution outside this agent's capability. The underlying mechanism (`SELECT ... FOR UPDATE` row lock) is unchanged from PR 1, already compile-verified there, and exercised end-to-end (execution, not lock contention) by every test in this file.
- [x] 3.1 `TipoMovimiento`, `MovimientoReceptor`, `SaldoCuenta`, `SaldoReceptor` types in `frontend/src/types/index.ts`.
- [x] 3.2 `receptoresApi.saldos/saldo/movimientos/registrarSalida/registrarCorreccion` in `frontend/src/api/index.ts`.
- [x] 3.3 `ReceptoresPage.tsx`: `saldos(ids)` called from inside `cargar()` after the page resolves; "Saldo" badge column (`badge-success` ≥0, `badge-warning` <0 — the closest existing design-system tokens to green/amber; COP via `formatCOP`).
- [x] 3.4 `modalMovimientos` (mirrors `modalCuentas`): per-cuenta saldo breakdown, paginated history table, `modalRegistroMovimiento` salida/correccion forms gated by `perms.isAdmin`, `modalConfirmarMovimiento` two-step `ConfirmarCreacion` confirm, 409 overdraft surfaced via the existing `toast.error(detail)` catch pattern.
- [ ] 3.5 Open PR 2 targeting PR 1's branch — **NOT DONE**, explicit instruction to stop before push/PR for review.
- [x] 4.1 Confirmed design.md's Open Questions remain resolved after PR 2: no backfill needed either direction; assumption 2 (item 10 anticipation) correctly still deferred — PR 2 introduced no `receptor_id`-scoped write path, schema stays keyed only to `cuenta_bancaria_id`.

## TDD Cycle Evidence (PR 2, backend)

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|-------------|----------|
| 2.1/2.2/2.3 | `tests/test_receptores_movimientos_router.py` | Integration (HTTP via `ASGITransport`, real FastAPI app + real in-memory SQLite session, real `receptor_ledger_service.registrar_movimiento` call — not mocked) | ✅ 575/575 (full-suite run immediately after GREEN — see Issues Found in PR 1 for why this checkpoint discipline was tightened) | ✅ Written (17 tests; all 17 failed pre-GREEN with 404 Not Found — neither route existed. Confirmed genuine, not coincidental: 403-role tests correctly failed too since FastAPI routing precedes dependency resolution, and both "foreign cuenta" 404 tests assert the exact `detail` string, which pre-GREEN was Starlette's generic "Not Found", not "Cuenta no encontrada" — so status-code coincidence alone would not have passed them) | ✅ Passed 17/17 on the first implementation attempt | ✅ 18th test added post-GREEN: `test_salida_respeta_saldo_ya_reducido_por_correccion_previa` (correccion→salida interaction: a prior correccion narrows the overdraft boundary a later salida sees). Passed immediately — confirmatory/regression-locking triangulation of the existing compute-on-read design, not a bug fix | ➖ None needed — `_obtener_cuenta_del_receptor` was extracted as a shared helper from the first GREEN pass (DRY between the two routes), so there was no duplicate-then-refactor step |

### Test Summary (PR 2)
- **Total tests written this run**: 18, all in `test_receptores_movimientos_router.py` (new file)
- **Full suite progression**: 558 (PR 1 baseline) → 575 (+17 GREEN) → 576 (+1 triangulation)
- **Layers used**: Integration (18) — the service layer itself (`registrar_movimiento`) was already fully unit-tested in PR 1; PR 2 only adds two thin route handlers + one DB-querying helper, all exercised transitively through these 18 HTTP-level tests
- **Approval tests**: None — no refactoring-of-existing-behavior tasks this run
- **Shared helpers created**: `_obtener_cuenta_del_receptor` (async, DB-querying — not a pure function; exercised directly by both 404-path tests)

## Work Unit Evidence (Suggested Work Unit 2 — "movements + UI")

| Evidence | Value |
|---|---|
| Focused test command and exact result | `venv/Scripts/python.exe -m pytest tests/test_receptores_movimientos_router.py -q` → **18 passed**. Frontend: no test runner exists in this repo (confirmed before starting — no vitest/jest/playwright dependency, no `test` script in `frontend/package.json`) — substituted with `npx tsc --noEmit` (0 errors) and `npm run build` (clean Vite production build, 1660 modules transformed, no new warnings beyond a pre-existing unrelated Browserslist notice). |
| Runtime harness command/scenario and exact result | Backend: same HTTP-level integration harness as PR 1 — `httpx.AsyncClient(transport=ASGITransport(app=app))` against the real FastAPI app + real (in-memory SQLite) DB session; all 18 tests exercise the actual ASGI request/response cycle end-to-end through `receptor_ledger_service.registrar_movimiento` (not mocked), including execution of the `SELECT ... FOR UPDATE` statement (lock *contention* itself is Postgres-only behavior, already compile-verified in PR 1; unchanged in PR 2, not re-verified). Frontend: N/A — this repo has zero E2E/component-test infrastructure (Playwright/Cypress/RTL all absent); substituted with the production build above plus manual structural cross-reference against the working `modalCuentas`/`modalCuenta`/`modalConfirmarCuenta` trio this PR mirrors. |
| Rollback boundary | This PR's 4 commits are additive-only and self-contained on top of PR 1: reverting `feat/receptor-cash-balance-movimientos` (or simply not merging it) removes the two new POST routes, their test file, and the entire frontend surface (types, API methods, badge column, movimientos modal) cleanly. No existing file's prior behavior changed — `receptores.py`'s Phase 1 routes are untouched except for added imports/tuples; `ReceptoresPage.tsx`'s existing cuenta/receptor CRUD flows are untouched (only additive state/handlers/JSX). Zero schema/migration changes in this PR — PR 1's table is reused as-is. |

Full backend suite (all 576 tests, not just this unit): `venv/Scripts/python.exe -m pytest -q` → **576 passed**, 0 failed, 0 regressions.

## Files Changed (PR 2)

| File | Action | What Was Done |
|------|--------|----------------|
| `backend/app/routers/receptores.py` | Modified | `ROLES_SALIDA`, `ROLES_CORRECCION` module tuples; `_obtener_cuenta_del_receptor` helper; `POST .../salidas`, `POST .../correcciones` |
| `backend/tests/test_receptores_movimientos_router.py` | Created | 18 tests: success/overdraft/boundary/roles/404s/audit-log for both routes + correccion→salida interaction |
| `frontend/src/types/index.ts` | Modified | `TipoMovimiento`, `MovimientoReceptor`, `SaldoCuenta`, `SaldoReceptor` |
| `frontend/src/api/index.ts` | Modified | `receptoresApi.saldos/saldo/movimientos/registrarSalida/registrarCorreccion` |
| `frontend/src/pages/Receptores/ReceptoresPage.tsx` | Modified | Saldo badge column, `modalMovimientos`, `modalRegistroMovimiento`, `modalConfirmarMovimiento` |
| `openspec/changes/receiver-cash-balance/tasks.md` | Modified | Phase 2/3/4 checkboxes; corrected stale filename + frontend-test-command in the Suggested Work Units table |

## Deviations from Design (PR 2)

1. **`_obtener_cuenta_del_receptor` 404 covers both "foreign cuenta" and "nonexistent cuenta"** — design.md's endpoint description only explicitly names the former. Mirrors the exact precedent of the existing `actualizar_cuenta` route (identical query shape, identical 404), so this is a consistency choice, not new design. Note: `registrar_movimiento`'s own independent 404-for-nonexistent-`cuenta_id` (from PR 1) is now unreachable from these two routes specifically, since the router-level check runs first — it remains reachable and tested from direct service-level calls (PR 1's own unit tests), so no coverage was lost, just layered defense that happens to overlap on this call path.
2. **`usuario_nombre` in POST responses comes from `current_user.username` directly**, not a DB relationship refresh (`movimiento.usuario.username`). Avoids an unnecessary extra query — `current_user` is already the exact actor who performed the write, fully loaded by `get_current_user`. Not specified either way by design.md; consistent with how every other write route in this file uses `current_user.id` directly.
3. **HTTP status for "exactly-equal balance" salida is 201, not the literal "200" in tasks.md's task 2.2 wording** — design.md's own endpoint table specifies `POST .../salidas → 201 MovimientoResponse` with no distinct status for the boundary case. Followed design.md as the more precise source, per the same precedent PR 1 established for resolving tasks.md/design.md wording gaps.
4. **Frontend history list has no `cuenta_bancaria_id` filter control** — the API method accepts the optional filter (matches the backend's existing optional query param, wired for future use), but design.md's "Frontend Surface" section describes only "paginated history" with no filter UI, and the per-cuenta saldo breakdown already surfaces the cuenta-level detail. Kept scope to what was specified.
5. **tasks.md's Suggested Work Units table (Unit 2 row) corrected** — same class of fix PR 1 made for its own row: `test_receptores_movimientos_routes.py` (plural, stale) → `test_receptores_movimientos_router.py` (actual filename); the `pnpm --filter frontend test ReceptoresPage` clause replaced with an accurate description, since no frontend test runner exists in this repo.

## Issues Found (PR 2)

- None blocking. One self-correction during this run, addressing PR 1's own noted process gap: after the initial 17-test GREEN pass, ran the *full* suite immediately (575/575) rather than only the new file's tests, then identified that "correccion narrows a later salida's overdraft boundary" had no dedicated end-to-end test (only same-type-then-self and correccion-alone scenarios existed) — added test 18 to close that gap before considering Phase 2 complete, then re-ran the full suite again (576/576) as the final checkpoint.

## Review Workload / PR Boundary (PR 2)

- **Mode**: chained PR slice (feature-branch-chain, PR 2 of 2, per tasks.md's pre-resolved Chain strategy — `sdd-apply`'s Step 2a gate was already satisfied by this existing resolution; no new decision was needed or requested this run)
- **Current work unit**: Suggested Work Unit 2 — "movements + UI" (salida/correccion write endpoints + frontend badge/modal)
- **Boundary**: starts from `feat/receptor-cash-balance-ledger` tip (`cc97ee0`, confirmed via `git merge-base`); ends at commit `6127a39` (4 commits: 2 feat — backend and frontend kept separate since they're independently revertible layers — 1 docs, 1 test-only follow-up)
- **Actual size vs forecast**: tasks.md forecast **"Slice 2 ~300-400 changed lines"**. Actual diff vs PR 1 branch tip: **777 changed lines** (code only: 771 insertions + 6 deletions across `receptores.py`, the new test file, and the 3 frontend files; 799 including the separate `tasks.md` docs commit). Roughly **2x the upper end of forecast**.
  - **Why**: two compounding factors, both explicitly mandated rather than discretionary. (a) Strict TDD for the backend, combined with task 2.2's own explicit 8-behavior test list (already substantial) plus one additional triangulation case for the correccion→salida interaction — 18 tests, 395 lines including realistic `Pago`/`Credito`/`Cliente` fixture helpers (same balance-setup pattern PR 1 established). (b) The frontend scope explicitly requested for this run — a saldo badge AND a full movements modal (per-cuenta breakdown + paginated history + two gated write forms with a two-step confirm) — is inherently verbose in this codebase's established JSX style: the existing `modalCuentas`/`modalCuenta`/`modalConfirmarCuenta` trio this PR mirrors is itself roughly 100 lines for a simpler feature (no history, no overdraft handling, one write form instead of two).
  - **Not resolved unilaterally**: implemented exactly the assigned Phase 2 + Phase 3 scope (nothing from Phase 4 beyond the trivial 4.1 confirmation, nothing speculative). This overage is proportionally smaller than PR 1's (which was ~4x over and accepted as `size:exception`), but is still flagged here rather than self-declared acceptable — that determination belongs to the orchestrator/reviewer, consistent with PR 1's own precedent.
  - **Rollback boundary**: additive-only; see Work Unit Evidence table above.

### Status (PR 2)

8/10 Phase 2+3+4 tasks fully complete (2.1–2.3, 3.1–3.4, 4.1); 2.4 and 3.5 correctly left
unchecked — both require actions outside this agent's capability (a live staging Postgres
environment for the manual concurrency check; explicit user authorization to push/open a
PR). Backend: 576/576 tests passing, 0 regressions. Frontend: `tsc --noEmit` and
`npm run build` both clean. An automated pre-commit review hook (Gentleman Guardian Angel,
scoped to `*.ts,*.tsx,*.js,*.jsx` against this repo's `AGENTS.md`) independently reviewed
both frontend commits and returned `PASSED` with no convention violations noted.

**Cumulative across both PRs**: 16/19 total tasks in tasks.md fully complete, 1 half-complete
(1.9), 2 correctly pending on out-of-agent-scope manual steps (2.4, 3.5). Ready for review
before push — not yet ready for `sdd-verify` to sign off on 2.4/3.5, or to recommend
`sdd-archive`, since the manual OPS check and both PRs' pushes are still pending.
