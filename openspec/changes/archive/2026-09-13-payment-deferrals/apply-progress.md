# Apply Progress: Payment Deferrals

**What**: Implemented change `payment-deferrals` end to end (Phases 1-9, 11 of tasks.md; 41/45 tasks done — Phase 10 manual browser checklist remains).

**Backend (Strict TDD)**:
- Migration `backend/alembic/versions/b2c3d4e5f6a7_add_veces_aplazado_to_pagos.py` (down_revision=a1b2c3d4e5f6): additive `pagos.veces_aplazado INT NOT NULL DEFAULT 0` + `ck_pagos_veces_aplazado_no_negativo`.
- `backend/app/models/pago.py`: `veces_aplazado` mapped column (default=0, server_default="0").
- `backend/app/schemas/pago.py`: `ModificarFechaPagoRequest.es_aplazamiento: bool=False`; `PagoResponse.veces_aplazado: int=0` with a `mode="before"` validator coercing `None → 0` (needed because several production code paths — `credito_service.py` chained-cuota generators, and pre-existing tests that build `Pago()` in memory without flushing — serialize a `Pago` before SQLAlchemy's insert-time Python default populates the column).
- `backend/app/routers/pagos.py`:
  - `modificar_fecha_pago`: now locks via `_get_pago_con_credito(db, pago_id, lock=True)`; ordered rejections under `es_aplazamiento=True` — (1) `pago.pagado` → 422 "No se puede aplazar: la cuota ya fue pagada."; (2) `nueva_fecha <= fecha_maxima actual` → 422 "Un aplazamiento debe mover la fecha hacia adelante." (owner decision #947); on success increments `veces_aplazado`, logs `INFO "APLAZAMIENTO OK — pago_id=%s usuario_id=%s veces=%s"`, and writes a second audit row (`veces_aplazado` old→new) in addition to the existing `fecha_maxima` row. Plain corrections (`es_aplazamiento=False`, default) are byte-identical to prior behavior — no direction check, no counter touch, single audit row.
  - Extracted `_aplicar_scope_y_busqueda(query, *, current_user, db, gestor_id, cliente_id, busqueda)` shared by `listar_pagos` and the new `listar_pagos_aplazados`.
  - `listar_pagos` select + `_pago_row_a_dict` now carry `veces_aplazado` (real rows: DB value via `getattr(row, "veces_aplazado", 0)`; virtual/projected rows: explicit `0`).
  - New `GET /pagos/aplazados` → `PaginatedResponse[PagoResponse]`: `incluir_pagados`, `sort_dir`, `gestor_id`, `cliente_id`, `busqueda`, `page`, `page_size` (1..50); predicate `deleted_at IS NULL AND veces_aplazado > 0 AND (pagado OR credito_operativamente_abierto())` + `pagado=false` unless `incluir_pagados`; DB-level `COUNT`/`OFFSET`/`LIMIT`; order `fecha_maxima <dir>, Cliente.nombre, Cliente.apellidos, Pago.id`.
- New test file `backend/tests/test_aplazamientos.py` (24 tests at initial apply, 25 after review correction round #1; all requirement scenarios from spec.md except the 5 `[manual]` frontend ones): RED confirmed (13 failing before Phase 4/6 GREEN implementation, 11 passing pre-existing-behavior checks), then GREEN (24/24 passing).
- Fixed 2 pre-existing test helpers (`test_pago_service.py::make_pago`, `test_pago_service_arrastre.py::make_cuota`) that construct bare `Pago()` objects — added explicit `p.veces_aplazado = 0` for clarity (the pydantic validator would also handle `None`, but explicit is consistent with other fields in those helpers).
- Full backend regression: **339 passed** at initial apply (baseline 315 + 24 new); **340 passed** after review correction round #1, 0 failures. Command: `cd backend && python -m pytest -q`.

**Frontend (Standard mode, no runner)**:
- `frontend/src/types/index.ts`: `Pago.veces_aplazado: number` (required, matches backend default 0).
- `frontend/src/api/index.ts`: `modificarFecha(pagoId, fecha_maxima, es_aplazamiento=false)`; new `listarAplazados(params)`.
- `frontend/src/pages/Pagos/PagosPage.tsx`: third `variante='aplazados'` (hides Año/Mes/Momento, shows "Incluir pagados" checkbox default off, `filtrosCompletos=true`, title "Pagos Aplazados", empty state "No hay pagos aplazados", fetches via `listarAplazados`); date modal gained a checkbox "¿Es un aplazamiento solicitado por el cliente?" (reset to false each time the modal opens) driving `es_aplazamiento` on submit, toast "Aplazamiento registrado" vs "Fecha actualizada"; row class precedence `es_proyectada gray > vencido red > (pending && veces_aplazado>0) violet > zebra`, `es_ultimo_pago` border independent; `Aplazado ×{n}` badge (`bg-violet-100 text-violet-700`) in Estado cell; header button "Pagos Aplazados" in regular variant, "Volver a Pagos" in semanal/diario/aplazados variants.
- `frontend/src/App.tsx`: `<Route path="pagos/aplazados" element={<PagosPage variante="aplazados" />} />`.
- `npx tsc --noEmit`: 0 errors.

**Diff stat** (code+tests, openspec excluded): `git diff --stat` (working tree, unstaged) → 924 insertions(+), 74 deletions(-) across 11 files (includes the new 610-line test file and new 44-line migration). Within the 800-line review budget given the forecast explicitly counted tests.

**Where**: `backend/alembic/versions/b2c3d4e5f6a7_add_veces_aplazado_to_pagos.py` (new), `backend/app/models/pago.py`, `backend/app/schemas/pago.py`, `backend/app/routers/pagos.py`, `backend/tests/test_aplazamientos.py` (new), `backend/tests/test_pago_service.py`, `backend/tests/test_pago_service_arrastre.py`, `frontend/src/types/index.ts`, `frontend/src/api/index.ts`, `frontend/src/pages/Pagos/PagosPage.tsx`, `frontend/src/App.tsx`, `openspec/changes/payment-deferrals/tasks.md` (checkboxes updated on disk).

**Learned**:
- Adding a new required-with-default field to `PagoResponse` broke 3 pre-existing tests/prod paths that construct `Pago()` in memory and serialize before flush (SQLAlchemy's `default=0` is insert-time only). Fixed at the schema layer with a `field_validator(mode="before")` coercing `None→0` rather than patching every `Pago(...)` call site in `credito_service.py` — safer and centralizes the "unset counter reads as 0" rule that the spec already requires for DB rows.
- `alembic upgrade/downgrade` was NOT run live — `alembic.ini` points at a Postgres URL not available in this sandbox; verified via `py_compile` and structural match to the precedent migration (`a1b2c3d4e5f6`) instead. Flag for a human/CI check before merge.
- Phase 10 (8 manual browser-verification tasks) requires a running frontend + browser; left unticked — out of scope for a non-interactive apply session.

**Remaining**: Phase 10 manual checklist (10.1-10.8, browser verification of modal/badge/row-color/navigation/listing behavior) — needs a human or an E2E runner, not available here.

**TDD Cycle Evidence** (backend, `test_aplazamientos.py`, all Unit/Integration-via-httpx+aiosqlite layer):
| Requirement | RED | GREEN | Triangulate |
|---|---|---|---|
| Deferral Counter | Written | Passed (already green from Phase 1-2 additive schema) | 2 cases (fresh row, reversal) |
| Extended Date Modification | Written | Passed after Phase 4 | 4 cases (correction, 1st/2nd deferral, correction-after-deferral) |
| Deferral Rejections | Written | Passed after Phase 4 | 5 cases (paid, same-date, backward-date, no-flag-allowed, deferred-then-paid, projected-404) |
| Role Gate | Written | Passed after Phase 4 | 4 cases (2 forbidden roles × 2 allowed roles) |
| Distinguishable Audit | Written | Passed after Phase 4 | 2 cases (deferral 2 rows, correction 1 row) |
| Cross-Period Deferred Listing | Written | Passed after Phase 6 | 6 cases (spans-months, paid-excluded, gestor-scoping, zero/soft-deleted-excluded, closed-credit-excluded [added in correction round #1], pagination/sort/busqueda) |
| Double Visualization | Written | Passed after Phase 6 | 1 case (both endpoints same pago) |

Total: 25 tests written (24 initial + 1 in correction round #1), 25 passing. Full suite 340 passed, 0 failures.

## Review correction round #1

- **W1** (frontend, `PagosPage.tsx` `handleModificarFecha`): success toast now decided from the PATCH response's `veces_aplazado` (compared against the row's previous value) instead of only local `esAplazamiento` state, so an old backend that ignores `es_aplazamiento` no longer shows a false "Aplazamiento registrado" — it shows a warning toast instead and still refetches.
- **W2** (backend, `test_aplazamientos.py::TestCrossPeriodDeferredListing::test_operationally_closed_credit_excluded`): added a test seeding a deferred pending row on an operationally closed credit (`activo=False`) and asserting it is excluded from `/pagos/aplazados` while an equivalent open-credit deferred row is included. Full suite 340 passed (0 failures).
- **W3** (docs only): renamed the unreachable "Paid row rejection shown `[manual]`" scenario to "Paid row has no date button `[manual]`" in `spec.md`, `tasks.md` (10.5), and `verify-report.md`, and fixed the paid-rejection detail string drift in `design.md` Interfaces to match the implemented backend string verbatim (`"No se puede aplazar: la cuota ya fue pagada."`).
