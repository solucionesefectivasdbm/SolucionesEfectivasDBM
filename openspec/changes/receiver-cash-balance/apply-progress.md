# Apply Progress: Receiver Cash Balance (item 9) — PR 1 (ledger foundation)

**Mode**: Strict TDD (backend)
**Scope this run**: Phase 1 tasks only (1.1–1.9). Phase 2 (write endpoints) and Phase 3
(frontend) are explicitly out of scope — they belong to PR 2 per the feature-branch-chain
strategy confirmed by the product owner.
**Branch**: `feat/receptor-cash-balance-ledger`, created off latest `origin/main` (tip
`cfa7721`). Not pushed. Not opened as a PR (explicit instruction — stop for review first).

## Completed Tasks

- [x] 1.1 `backend/app/models/receptor_movimiento.py` — `TipoMovimiento` enum, `MovimientoReceptor` model (no AuditMixin, immutable), CHECK constraint, 2 indexes.
- [x] 1.2 `movimientos_receptor` backref on `Usuario`.
- [x] 1.3 Alembic migration `e5f6a7b8c9d0_create_receptor_movimientos.py` (`down_revision='d4e5f6a7b8c9'`) — explicit enum drop in `downgrade()`.
- [x] 1.4 `backend/app/schemas/receptor_movimiento.py` — `MovimientoCreate`, `CorreccionCreate`, `MovimientoResponse`, `SaldoCuentaResponse`, `SaldoReceptorResponse`.
- [x] 1.5 RED — `test_receptor_ledger_service.py` (22 cases).
- [x] 1.6 GREEN — `backend/app/services/receptor_ledger_service.py`.
- [x] 1.7 RED — `test_receptores_saldo_router.py` (17 cases).
- [x] 1.8 GREEN — read endpoints in `backend/app/routers/receptores.py`, `/saldos` registered before `/{receptor_id}`.
- [~] 1.9 Full suite run: DONE (558/558 passing). PR opened: NOT DONE (explicit instruction).

### Remaining Tasks (out of scope this run)

- [ ] Phase 2 (2.1–2.4): write endpoints (`POST .../salidas`, `POST .../correcciones`), their router tests, and the manual OPS concurrency check. `registrar_movimiento` itself is already implemented and unit-tested in this PR (task 1.6) — Phase 2 only needs to wire the two POST routes to the already-tested service and add router-level tests (403/409/404/audit-log assertions).
- [ ] Phase 3 (3.1–3.5): frontend types, API client, balance badge, movimientos modal.
- [ ] Phase 4 (4.1): design.md open-questions cleanup confirmation.

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
- **Total tests written this run**: 64 (8 model + 7 schema + 22 service + 17 router... = 54; recount below)
- **Exact new test count**: `test_models.py` +8, `test_schema_receptor_movimiento.py` +7 (new file), `test_receptor_ledger_service.py` +22 (new file), `test_receptores_saldo_router.py` +17 (new file) = **54 new tests**
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

## Files Changed

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

## Deviations from Design

1. **Test file naming**: used `test_receptores_saldo_router.py` (singular "router", matching design.md's File Changes table AND this repo's established naming convention — `test_receptores_router.py`, `test_creditos_router.py`) rather than `test_receptores_saldo_routes.py` (plural "routes", used only in tasks.md's Suggested Work Units test-command column). Design.md's own table is the more precise source for file structure; this resolves a minor inconsistency between the two artifacts, not a deviation from either taken alone. **Orchestrator: if `sdd-verify` checks the exact filename from the tasks.md table, update the test command there to match, or tell me and I'll rename.**
2. **Extra test beyond tasks.md's explicit list**: added `TestSaldoSobreviveSoftDeleteDeReceptor` — not named in tasks.md's task-1.5 case list, but it is spec.md's own formally named requirement ("Ledger Entries Survive Receptor Soft-Delete") with an explicit Given/When/Then scenario. Closing a named spec requirement, not scope creep.
3. **Extra defensive guard**: `registrar_movimiento` raises 404 for a non-existent `cuenta_id` before attempting the insert. Not explicitly specified in design.md (which only specifies the router-level "cuenta belongs to another receptor → 404" check, a Phase 2 concern). Added because this repo's SQLite test DB does **not** enforce foreign keys by default — without this guard, `registrar_movimiento` against a bogus `cuenta_id` would either silently "succeed" in tests (masking a real bug) or fail with a raw, unhandled `IntegrityError` in production Postgres instead of a clean 404. Test-covered (`test_cuenta_inexistente_devuelve_404`).
4. **`listar_movimientos` uses `isouter=True`** for the `Usuario` join (LEFT JOIN), matching the exact precedent in `routers/auditoria.py`'s identical usuario-attribution pattern, rather than an inner join. Deliberate consistency choice: a movimiento row must never silently vanish from the ledger history if its `usuario_id` ever becomes unresolvable.
5. **Route-ordering proof**: beyond writing the required test, I temporarily reordered the routes, re-ran the suite to confirm 5 tests fail exactly as expected (proving the test is a genuine regression guard, not a coincidental pass), then reverted before committing. Documented in the commit message.

## Issues Found

- **Pre-GREEN false-positive nuance (not a bug, but worth recording)**: in the RED run for `test_receptores_saldo_router.py`, 6 of 17 tests "passed" before any router code existed. This is expected and understood, not a test-quality problem: `GET /receptores/saldos` was, pre-implementation, silently matched by the *existing* `GET /receptores/{receptor_id}` route (Starlette route matching, no type converter in the path pattern). For `registrador`/`gestor` roles, that pre-existing route's own `require_role("admin")` check rejects them with 403 *before* FastAPI ever attempts UUID conversion of the literal `"saldos"` — coincidentally matching my expected 403 for the wrong reason. Malformed-UUID and unknown-receptor 404 tests were similarly coincidentally green (no matching route → generic 404). All of these became genuine tests of my own code the moment the real routes were added (confirmed: full 17/17 GREEN afterward, and the mutation-revert experiment above independently proves the ordering-sensitive subset is a real guard).
- **Minor process gap**: after the schema cycle (task 1.4), I ran only that file's own tests (7 passed) before committing, not the whole suite. I did run the whole suite after the very next cycle (541 passed = exactly 512 + 7 + 22, arithmetically confirming zero hidden regressions from the schema cycle), and again at the end (558 passed). No actual regression occurred, but strict safety-net discipline should have re-run the full suite at that checkpoint too — flagging for transparency.

## Review Workload / PR Boundary

- **Mode**: chained PR slice (feature-branch-chain, PR 1 of 2, confirmed by product owner)
- **Current work unit**: Suggested Work Unit 1 — "ledger foundation" (model + migration + schemas + service + 3 read endpoints, no user-visible behavior change)
- **Boundary**: starts from latest `main` (`cfa7721`); ends at commit `38abd36` (5 commits, all backend-only)
- **Actual size vs forecast**: tasks.md forecast **"Slice 1 ~250-350 changed lines"**. Actual diff vs `main`: **1412 lines** (504 production + 908 test, per `git diff --stat`). Production-only (504 lines) already exceeds both the forecast and the default 400-line budget by itself (~26% over); the full diff including tests is well over.
  - **Why**: the user's explicit instruction mandated strict TDD (`strict-tdd.md` exactly) plus several explicitly named required cases (FOR UPDATE compiled-statement test, enum-drop migration verification), and design.md separately mandates "exhaustive" testing "given this repo's carryover-bug history" as a first-class requirement, not a nice-to-have. I did not trim coverage to fit the original line forecast, since both instructions outrank the forecast and neither was optional.
  - **Not resolved unilaterally**: I implemented exactly the assigned Phase 1 scope (nothing from Phase 2/3), added no speculative code, and the two test-count additions beyond tasks.md's literal list (soft-delete-survival, unknown-cuenta 404) are both narrowly justified and documented above. Splitting this further, or accepting it as-is with `size:exception`, is a delivery decision for the orchestrator/reviewer — flagging here rather than deciding it myself.
- **Rollback boundary**: additive-only; see Work Unit Evidence table above.

## Status

8/9 Phase 1 tasks fully complete (1.1–1.8); task 1.9 half-complete (suite green, PR intentionally not opened). 558/558 backend tests passing, 0 regressions. Ready for review before push — **not** yet ready for `sdd-verify` to sign off on 1.9 or to recommend `sdd-archive`, since the PR itself hasn't been opened.
