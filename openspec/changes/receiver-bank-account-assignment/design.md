# Design: Receiver Bank Account Assignment (`receiver-bank-account-assignment`)

Proposal: `proposal.md` (binding decisions 1-6; question-round assumptions 1-4 confirmed). Exploration: `explore.md`. Item 9 (`receiver-cash-balance`) and item 10 (splits) build on this FK; extensibility notes inline.

## Technical Approach

Replace the receptor FK on `gestores`/`pagos` with `cuenta_bancaria_id` in four stages: (1) additive schema + explicit default-account rule + SQL backfill endpoint; (2) backend cutover in one atomic rename pass, receptor always derived through `CuentaBancaria.receptor`; (3) frontend; (4) drop `receptor_id` and the temp endpoint. Every stage lands in `main` sequentially and is deployable on its own; the backfill is re-runnable at any point of the sequence because it reads/writes SQL columns through lightweight Core table constructs, never the ORM mapping.

## Architecture Decisions

| # | Decision | Choice | Rejected | Rationale |
|---|---|---|---|---|
| 1 | Default flag | `cuentas_bancarias.es_predeterminada BOOLEAN NOT NULL server_default=false` + partial unique index `uq_cuentas_bancarias_default_por_receptor (receptor_id) WHERE es_predeterminada`, declared in `__table_args__` with both `postgresql_where` and `sqlite_where` | `created_at` earliest-wins | Owner decision 3; the index makes "one default" a DB invariant; declaring it on the model means `Base.metadata.create_all` (conftest.py:39) enforces it in SQLite tests too |
| 2 | Default flip | Two explicit Core `update()` statements in order: clear old default for the receptor, then set the new one. Never rely on unit-of-work flush order | ORM attribute toggling | The partial unique index is checked per statement (non-deferrable); flush order of two dirty rows is not guaranteed |
| 3 | Default rule home | New `backend/app/services/cuenta_bancaria_service.py`: `obtener_cuenta_o_404`, `es_primera_cuenta`, `marcar_predeterminada`, `etiqueta_cuenta` | Inline in `receptores.py` | Reused by `receptores.py`, `gestores.py`, `pagos.py`; item 9 adds its balance function to the same module |
| 4 | Pago relationship | `Pago.cuenta_bancaria_id` column only, **no** ORM relationship; nested account data comes from explicit joins in list queries and an explicit fetch after PATCH | `relationship("CuentaBancaria")` on Pago | `PagoResponse` is `from_attributes`; a lazy relationship touched by pydantic under asyncio raises `MissingGreenlet`. Same precedent as `tipo_credito` (schemas/pago.py:38-42): Optional, populated only where the router builds the row |
| 5 | Gestor relationship | `Gestor.cuenta_bancaria` relationship, always loaded via `selectinload(Gestor.cuenta_bancaria).selectinload(CuentaBancaria.receptor)` in `_query_con_relaciones` | Column only | Every gestor endpoint already goes through `_query_con_relaciones` (gestores.py:26-34); nested validation is safe |
| 6 | Nested account shape | One shared `CuentaBancariaResumen {id, receptor_id, entidad_bancaria, tipo_cuenta, numero_cuenta, es_predeterminada, receptor: {id, nombre}}` in `schemas/receptor.py`, used by `GestorResponse.cuenta_bancaria` and `PagoResponse.cuenta_bancaria` | Flattened `receptor_nombre` | pydantic `from_attributes` traverses nested objects, not dotted paths; the list-row dict builder mirrors the same shape |
| 7 | `receptor_id` in PR2 | Keep `receptor_id` **mapped but never read or written** (`# DEPRECATED, dropped in PR4`), remove `Gestor.receptor`/`Pago.receptor`/`Receptor.gestores`/`Receptor.pagos` relationships | Unmap in PR2 | SQLite test schema comes from the models; the backfill tests must stay green through PR2/PR3. Relationship removal makes accidental use a hard error |
| 8 | Backfill SQL | `sa.table()/sa.column()` lightweight constructs (`_t_gestores`, `_t_pagos`, `_t_cuentas`, `_t_receptores`) + correlated scalar subqueries; `tipo_cuenta` column typed `sa.Enum(TipoCuenta, name="tipo_cuenta_enum")` | `UPDATE ... FROM`; ORM `update(Gestor)` | Correlated subqueries render identically on SQLite and Postgres; Core statements survive the PR4 column drop; the Enum type binds `TipoCuenta.ahorros` to the stored enum **name** `ahorros` (initial migration line 66), avoiding a wrong `'Ahorros'` literal |
| 9 | `GET /pagos` filter | Keep `receptor_id` (expanded to `Pago.cuenta_bancaria_id IN (SELECT id FROM cuentas_bancarias WHERE receptor_id = :r)`) and add `cuenta_bancaria_id` (exact match). Both ANDed; either one suppresses virtual rows | Replace with account-only filter | Owner assumption 4; virtual rows still have no account (pagos.py:322-323, 389-390) |
| 10 | Report nesting | `por_receptor[].por_cuenta[]`; aggregate by `cuenta_bancaria_id`, roll up per receptor; account/receptor metadata preloaded in one query | Flat per-account list | Owner decision 5; receptor totals stay byte-identical (same formula); item 9 reuses the per-account aggregation |
| 11 | Account chooser UI | New `frontend/src/components/ui/SelectCuentaBancaria.tsx`: one `<select>` with `<optgroup label={receptor.nombre}>` and options labelled by `formatCuentaBancaria` | Two cascading selects in every form | One component serves Pagos modal and Gestores form; the filter card is the only place that needs the receptor-only level and uses two plain selects |
| 12 | PATCH validation | `PATCH /pagos/{id}/cuenta-bancaria`, `POST/PATCH /gestores` return 404 `"Cuenta bancaria no encontrada"` for unknown ids | FK error surfacing as 500 (today) | Same cost, clearer contract; account of another receptor is allowed (assumption 2) |

## Data Flow

    POST /receptores/{r}/cuentas ── es_primera_cuenta? ──> es_predeterminada=True
    PUT  /receptores/{r}/cuentas/{c}/predeterminada ── clear old ──> set new (2 stmts)

    POST/PATCH /gestores {cuenta_bancaria_id} ── obtener_cuenta_o_404
         └─ changed & not None ──> _propagar_cuenta_a_pagos(unpaid pagos of gestor's active creditos)
    POST /creditos ── gestor.cuenta_bancaria_id ──> crear_primera_cuota(credito, cuenta_bancaria_id)
    PagoService.registrar_pago / reversal ── pago.cuenta_bancaria_id ──> generar_siguiente_cuota(...)
    PATCH /pagos/{id}/cuenta-bancaria ── audit {"cuenta_bancaria_id": (old, new)} ── nested resumen in response

    GET /pagos?receptor_id&cuenta_bancaria_id ── LEFT JOIN cuentas_bancarias, receptores ──> row dict + cuenta_bancaria{}
    GET /reportes ── group by cuenta_bancaria_id ──> por_receptor[receptor].por_cuenta[account] (sum == receptor)

    Backfill (SQL-only, idempotent):
      1 elect default where receptor has accounts but none flagged (MIN(id))
      2 insert generic default for receptors with zero accounts
      3 gestores.cuenta_bancaria_id  <- default of gestores.receptor_id
      4a pagos.cuenta_bancaria_id    <- default of pagos.receptor_id
      4b unpaid pagos still NULL     <- gestor.cuenta_bancaria_id via credito->cliente->gestor

## File Changes

| File | PR | Action | Description |
|---|---|---|---|
| `backend/alembic/versions/c3d4e5f6a7b8_add_cuenta_bancaria_assignment.py` | 1 | Create | `down_revision='b2c3d4e5f6a7'`. `es_predeterminada` (Boolean, NOT NULL, `server_default=sa.false()`), partial unique index; `gestores.cuenta_bancaria_id`/`pagos.cuenta_bancaria_id` (`sa.UUID()`, nullable, `fk_gestores_cuenta_bancaria`, `fk_pagos_cuenta_bancaria`), `ix_pagos_cuenta_bancaria_id`. Downgrade reverses |
| `backend/app/models/receptor.py` | 1 | Modify | `es_predeterminada` (default False + server_default), `__table_args__` index |
| `backend/app/models/gestor.py`, `models/pago.py` | 1 | Modify | Add nullable `cuenta_bancaria_id` FK (Gestor also `cuenta_bancaria` relationship) |
| `backend/app/schemas/receptor.py` | 1 | Modify | `CuentaBancariaResponse.es_predeterminada`; `ReceptorMin`, `CuentaBancariaResumen` |
| `backend/app/services/cuenta_bancaria_service.py` | 1 | Create | Decision 3 helpers |
| `backend/app/routers/receptores.py` | 1 | Modify | `agregar_cuenta` auto-default; `PUT /{receptor_id}/cuentas/{cuenta_id}/predeterminada` (admin, audit `cambios={"es_predeterminada": (old_id, new_id)}` on entity `receptores`); temp `POST /admin/backfill-cuentas-bancarias` (declared before parametric routes, `# TEMPORAL` banner, `require_role("admin")`, `dry_run: bool = True`) |
| `backend/tests/test_cuentas_bancarias_predeterminada.py` | 1 | Create | Default rule + index tests |
| `backend/tests/test_backfill_cuentas_bancarias.py` | 1 | Create, deleted in PR4 | Backfill tests |
| `backend/app/models/{receptor,gestor,pago}.py` | 2 | Modify | Decision 7 (deprecate column, drop relationships) |
| `backend/app/schemas/{gestor,pago,common}.py` | 2 | Modify | `receptor_id` -> `cuenta_bancaria_id`; `cuenta_bancaria: Optional[CuentaBancariaResumen] = None`; `ModificarCuentaBancariaPagoRequest`; `PagoFiltros.cuenta_bancaria_id`; `common.py` legacy report schemas gain `por_cuenta` |
| `backend/app/services/credito_service.py` | 2 | Modify | Parameter `receptor_id` -> `cuenta_bancaria_id` in `crear_primera_cuota`, `_primera_cuota_fija`, `_primera_cuota_abono_capital`, `generar_siguiente_cuota`, `_siguiente_cuota_fija`, `_siguiente_cuota_fija_solo_interes`, `_siguiente_cuota_abono_capital` and every `Pago(...)` kwarg (lines 467-802) + docstring 862. One pass, one commit |
| `backend/app/services/pago_service.py` | 2 | Modify | Lines 229, 297, 366, 384, 422: `cuenta_bancaria_id=pago.cuenta_bancaria_id` / parameter rename |
| `backend/app/routers/gestores.py` | 2 | Modify | `_query_con_relaciones` load chain; create/update validate account; `_propagar_receptor_a_pagos` -> `_propagar_cuenta_a_pagos` (same predicate, `.values(cuenta_bancaria_id=...)`) |
| `backend/app/routers/creditos.py` | 2 | Modify | Lines 224-231: `gestor.cuenta_bancaria_id` |
| `backend/app/routers/pagos.py` | 2 | Modify | Select columns + `outerjoin(CuentaBancaria).outerjoin(Receptor)` in `listar_pagos` and `listar_pagos_aplazados`; `_pago_row_a_dict` builds `cuenta_bancaria`; virtual dict `cuenta_bancaria_id: None`; filter params (decision 9) and `_calcular_virtuales(..., cuenta_bancaria_id_filtro)` early return; PATCH rename; no-programado uses `gestor.cuenta_bancaria_id` |
| `backend/app/routers/reportes.py` | 2 | Modify | `ReporteDetalleCuentaExtendido`, `por_cuenta`, aggregation by account |
| `backend/tests/{test_pagos_listado,test_credito_service*,test_pago_service*,test_creditos_router}.py` | 2 | Modify | Fixture/param renames (~23 spots) |
| `backend/tests/test_pagos_cuenta_bancaria.py`, `test_gestores_cuenta_bancaria.py`, `test_reportes_por_cuenta.py` | 2 | Create | See testing strategy |
| `frontend/src/types/index.ts`, `api/index.ts`, `utils/formatters.ts`, `components/ui/SelectCuentaBancaria.tsx`, `pages/{Pagos,Gestores,Receptores,Reportes}/*.tsx` | 3 | Modify/Create | See Interfaces |
| `backend/alembic/versions/d4e5f6a7b8c9_drop_receptor_id_from_gestores_pagos.py` | 4 | Create | Drop FKs + columns. Downgrade re-adds nullable columns + FKs and repopulates via `op.execute` correlated `UPDATE ... SET receptor_id = (SELECT receptor_id FROM cuentas_bancarias WHERE id = cuenta_bancaria_id)` |
| `backend/app/models/{gestor,pago}.py`, `routers/receptores.py`, `tests/test_backfill_cuentas_bancarias.py` | 4 | Modify/Delete | Remove deprecated columns, temp endpoint and its tests |

## Interfaces / Contracts

```python
# services/cuenta_bancaria_service.py
async def obtener_cuenta_o_404(db, cuenta_id: uuid.UUID) -> CuentaBancaria          # selectinload(receptor)
async def es_primera_cuenta(db, receptor_id: uuid.UUID) -> bool
async def marcar_predeterminada(db, receptor_id, cuenta_id) -> CuentaBancaria        # 404 if not of receptor; decision 2
def etiqueta_cuenta(c: CuentaBancaria) -> str   # "Entidad · Tipo · numero" (reports)

# credito_service.py (renamed positional/keyword parameter, same order)
async def crear_primera_cuota(credito, cuenta_bancaria_id: uuid.UUID | None) -> Pago
async def generar_siguiente_cuota(db, credito, cuota_anterior, cuenta_bancaria_id, saldo_pendiente=Decimal("0.00"))
```

Endpoints: `PUT /receptores/{receptor_id}/cuentas/{cuenta_id}/predeterminada` -> `CuentaBancariaResponse` (admin; 404 receptor/cuenta; idempotent when already default). `PATCH /pagos/{pago_id}/cuenta-bancaria` body `{cuenta_bancaria_id}` (admin, recaudador; 404 pago/cuenta; audit one row `cuenta_bancaria_id`). `GET /pagos` adds `cuenta_bancaria_id: uuid | None`. `POST /receptores/admin/backfill-cuentas-bancarias?dry_run=true` -> `{dry_run, predeterminadas_elegidas, cuentas_genericas_creadas, gestores_actualizados, pagos_por_receptor, pagos_por_gestor, pendientes: {gestores_sin_cuenta, pagos_sin_cuenta}}`; dry run executes the same predicates as `SELECT COUNT` and writes nothing; apply run executes steps 1-4b in order, every statement guarded by `cuenta_bancaria_id IS NULL` / `NOT EXISTS default`, so re-runs are no-ops. Generic account: `entidad_bancaria='Por definir'`, `tipo_cuenta=TipoCuenta.ahorros`, `numero_cuenta='0'`, `es_predeterminada=true`. Soft-deleted receptores and paid/soft-deleted pagos are included (history must keep its account).

Report: `ReporteDetalleReceptorExtendido.por_cuenta: list[ReporteDetalleCuentaExtendido]` with `cuenta_bancaria_id, etiqueta, es_predeterminada` + the six totals; pagos with `cuenta_bancaria_id IS NULL` excluded as today.

Frontend: `CuentaBancaria.es_predeterminada`; `CuentaBancariaResumen`; `Gestor.cuenta_bancaria_id/cuenta_bancaria`; `Pago.cuenta_bancaria_id/cuenta_bancaria?`; `ReporteDetalleReceptor.por_cuenta`. API: `receptoresApi.marcarPredeterminada(receptorId, cuentaId)`, `pagosApi.modificarCuentaBancaria(pagoId, cuenta_bancaria_id)`, `pagosApi.listar` params `+cuenta_bancaria_id`. `formatCuentaBancaria(c, receptorNombre?)` -> `"Receptor · Entidad · Tipo · numero"` (receptor omitted inside optgroups). Pagos: filter card gains Receptor -> Cuenta selects (gated `perms.canValidarPago`, account list = selected receptor's accounts, "Todas" default); new table column "Cuenta" after Cliente (`Entidad · numero`, tooltip full label, "—" for virtual/unassigned); modal "Modificar cuenta" uses `SelectCuentaBancaria` preselecting the current account. Gestores: form field `cuenta_bancaria_id` via `SelectCuentaBancaria`; badge `receptor.nombre · entidad`. Receptores: "Predeterminada" badge on the card, "Hacer predeterminada" button on the others. Reportes: sub-rows under each receptor (`↳ etiqueta`, `text-xs text-gray-500`, indent), always rendered.

## Testing Strategy (strict TDD; `backend/venv/Scripts/python.exe -m pytest`, `npx tsc --noEmit`)

| PR | File | Key scenarios |
|---|---|---|
| 1 | `test_cuentas_bancarias_predeterminada.py` (fixtures copied from `test_desvalidar_pago.py`) | first account -> default; second -> not; `PUT predeterminada` flips and old cleared; already-default idempotent; account of another receptor 404; non-admin 403 no writes; direct ORM insert of a second default raises `IntegrityError` (index enforced in SQLite); `ReceptorResponse` exposes flag |
| 1 | `test_backfill_cuentas_bancarias.py` | receptor without accounts gets generic default; receptor with accounts but no default elects one; gestor/pago filled from receptor default; already-assigned rows untouched; unpaid pago with `receptor_id NULL` inherits gestor account (4b); paid and soft-deleted pagos filled; dry run writes nothing, counts match apply; second apply run all zeros; non-admin 403 |
| 2 | fixture renames in 6 existing files | suite green after the atomic rename (regression net) |
| 2 | `test_gestores_cuenta_bancaria.py` | create/update with account -> nested resumen incl. receptor; unknown account 404; change propagates to unpaid pagos of active clientes only (paid, other gestor, deleted cliente untouched); `None` does not propagate; audit row `cuenta_bancaria_id` |
| 2 | `test_pagos_cuenta_bancaria.py` | PATCH changes one pago, audit diff, response nested, other-receptor account allowed, unknown 404, 403 matrix; `receptor_id` filter returns all accounts of receptor; `cuenta_bancaria_id` narrows; both combined; virtual rows suppressed with either filter, present without; list row and aplazados row carry `cuenta_bancaria`; virtual row `cuenta_bancaria_id None`; no-programado inherits gestor account |
| 2 | `test_creditos_router.py` (+1) | first cuota inherits `gestor.cuenta_bancaria_id` |
| 2 | `test_reportes_por_cuenta.py` | two accounts of one receptor: receptor totals == sum of `por_cuenta`; totals equal the pre-change formula; unassigned pagos excluded; `etiqueta` format |
| 3 | manual checklist | modal preselects current account; filter receptor -> account cascade resets account on receptor change; table column; gestor badge; default badge + action; report sub-rows sum |
| 4 | existing suite | green with columns removed; backfill test file deleted |

Constraint: propagation and backfill tests need `db_session` (real SQL), not `AsyncMock`.

## Threat Matrix

N/A: no routing, shell, subprocess, VCS/PR automation, executable-file classification or process-integration boundary. New admin routes are covered by the RBAC tests above.

## Migration / Rollout

Feature Branch Chain, each PR merged to `main` before the next branch is cut (lesson from item 4). Line forecasts are additions+deletions of code and tests; openspec artifacts excluded.

| PR | Branch | Content | Forecast | Prod step |
|---|---|---|---|---|
| 1 | `feat/cuenta-bancaria-schema` | migration, models, schemas, service, default endpoint, backfill endpoint, 2 test files | ~430 (**split point**: backfill endpoint + its tests ~170 -> PR1b `feat/cuenta-bancaria-backfill` if sdd-tasks confirms) | deploy (Alembic via `start.sh`) -> dry run -> apply -> verify `pendientes` all 0 and `SELECT count(*) FROM receptores r WHERE NOT EXISTS (default)` = 0 |
| 2 | `feat/cuenta-bancaria-cutover` | atomic rename, gestores/creditos/pagos/pago_service, list serialization, PATCH, fixture renames, 2 test files | ~340 (**split point**: cascading filter + report nesting + `test_reportes_por_cuenta.py` ~180 -> PR2b `feat/cuenta-bancaria-filtros-reportes`) | deploy -> **immediately re-run backfill** (fills rows created since PR1; step 4b covers post-deploy rows) -> smoke: create credit, register payment, `GET /pagos`, `GET /reportes` |
| 3 | `feat/cuenta-bancaria-frontend` | types, api, formatter, `SelectCuentaBancaria`, 4 pages | ~250 | deploy -> manual checklist |
| 4 | `chore/drop-receptor-id` | drop migration, deprecated columns, temp endpoint + tests | ~280 (mostly deletions) | after a clean prod week: `SELECT count(*) FROM pagos WHERE cuenta_bancaria_id IS NULL AND receptor_id IS NOT NULL` = 0, same for gestores; then deploy |

Rollback: PR1/PR1b revert code only; columns stay nullable, index harmless, generic accounts remain valid data. PR2/PR2b revert restores receptor-based code while `receptor_id` is still populated for pre-cutover rows; rows created under PR2 have `receptor_id NULL` and would show no receptor until re-cutover (accepted; window is minutes). PR3 revert is UI-only. PR4: `alembic downgrade -1` re-adds and repopulates `receptor_id` from `cuentas_bancarias`.

## Open Questions

- [ ] PR1 and PR2 forecasts exceed the 400-line budget; sdd-tasks must forecast and either split at the marked points (recommended, sequencing unchanged) or obtain `size:exception`.
- [ ] Election rule for receptores that already have several accounts and no default: `MIN(id)` (arbitrary but deterministic); admin corrects via the UI. Confirm or ask the owner for a manual list before the apply run.
