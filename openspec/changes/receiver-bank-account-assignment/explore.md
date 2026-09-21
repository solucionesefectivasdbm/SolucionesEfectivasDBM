# Exploration: Receiver Bank Account Assignment (`receiver-bank-account-assignment`)

Quote item 11 ($360,000 COP). Builds on the receptor domain also touched by item 9 (`receiver-cash-balance`, see `openspec/changes/receiver-cash-balance/explore.md`; that doc covers the future balance ledger built on top of whatever FK this change lands). Investigation only, no code written.

## Current State

**`CuentaBancaria` model** (`backend/app/models/receptor.py:46-64`): no `AuditMixin` (no soft delete, no `created_at`/`updated_at`), `id`, `receptor_id` FK (not null), `entidad_bancaria` (String 100), `tipo_cuenta` (Enum `Ahorros`/`Corriente`), `numero_cuenta` (String 30). Relationship `Receptor.cuentas_bancarias` is 1:N with `cascade="all, delete-orphan"` (only fires on a real DB delete of the parent row; `Receptor` uses soft delete via `AuditMixin.deleted_at`, so this cascade never triggers in practice). **No ordering/insertion-marker column exists** (no `created_at`, no `es_predeterminada` flag): "first account created is default" cannot be determined today without adding one (`id` is a random UUID, not insertion-ordered).

**`CuentaBancaria` CRUD** (`backend/app/routers/receptores.py`): `POST /receptores/{id}/cuentas` (create, admin only) and `PATCH /receptores/{id}/cuentas/{cuenta_id}` (update, admin only). **No DELETE endpoint exists for accounts**, which removes the "FK target hard-deleted while referenced" concern for the initial cut; the design should still decide whether to add delete/deactivate later (soft-delete column needed if so).

**`Gestor.receptor_id`** (`backend/app/models/gestor.py:39-43`): nullable FK to `receptores.id`. Set at gestor creation/update (`GestorCreate`/`GestorUpdate` in `backend/app/schemas/gestor.py:33,43`). `PATCH /gestores/{id}` (`backend/app/routers/gestores.py:141-180`) detects a `receptor_id` change and calls `_propagar_receptor_a_pagos` (lines 183-205), which bulk-updates all **unpaid** `Pago` rows for that gestor's active clientes/creditos to the new `receptor_id`. This is the propagation path the requirement's "assign or change receiver" language refers to; it must become "assign or change bank account."

**`Pago.receptor_id`** (`backend/app/models/pago.py:67-69`): nullable FK. Populated in two ways:
1. At cuota generation, inherited from the owning cliente's gestor (`backend/app/routers/creditos.py:224-231` for the first cuota via `crear_primera_cuota`; `backend/app/services/credito_service.py` threads `receptor_id` as a plain parameter through ~14 internal builder functions, lines 467-863, all pass-through).
2. Individually via `PATCH /pagos/{pago_id}/receptor` (`backend/app/routers/pagos.py:843-863`), which lets recaudador/admin override a single payment's receptor, writing an audit-log diff.

**List/filter usage of `Pago.receptor_id`**: `GET /pagos` supports `receptor_id: uuid.UUID | None = Query(None)` (`backend/app/routers/pagos.py:225,293-294`) and disables "virtual" (not-yet-generated) rows when a receptor filter is active (comments at 322-323, 376-377) because virtuals have no receptor yet. The paginated list serializer (line 81) and the query columns loaded (lines 171, 264) expose it.

**Reporting** (`backend/app/routers/reportes.py:116-134`): groups `Pago` rows by `receptor_id` for a period, joining to `Receptor` for `receptor_nombre`, producing `ReporteDetalleReceptorExtendido` (`reportes.py:32-33,54`) with `por_receptor`, rendered in `frontend/src/pages/Reportes/ReportesPage.tsx:155-178`.

**`pago_service.py`**: 5 occurrences (lines 229, 297, 366, 384, 422), all pass-through of `receptor_id` when building next-cuota records during payment registration/reversal.

## Occurrence Counts (backend, `receptor_id`/`receptor`)

| File | Count | Nature |
|---|---|---|
| `app/services/credito_service.py` | 21 | Parameter threading only (cuota builders) |
| `app/routers/pagos.py` | 15 | Filter, list serialization, PATCH endpoint |
| `app/routers/receptores.py` | 16 | Receptor + CuentaBancaria CRUD |
| `app/routers/gestores.py` | 5 | Assignment + propagation to pagos |
| `app/routers/reportes.py` | 5 | Group-by aggregation |
| `app/schemas/gestor.py` | 3 | Create/Update/Response fields |
| `app/schemas/pago.py` | 3 | Filter param, PATCH body, response |
| `app/models/gestor.py` | 2 | FK column + relationship |
| `app/routers/creditos.py` | 2 | Read gestor.receptor_id, pass to first cuota |
| `alembic/versions/d9144df95951_initial.py` | 6 | Baseline schema |
| `app/models/receptor.py`, `app/models/pago.py`, `app/schemas/receptor.py`, `app/schemas/common.py` | 1 each | FK/model/schema declarations |
| Tests (7 files) | ~23 total | Fixtures building gestor/pago with receptor_id |

Total: 103 occurrences across 21 backend files. Frontend: 110 occurrences across 10 files (`types/index.ts` 10, `api/index.ts` 15, `PagosPage.tsx` 25, `GestoresPage.tsx` 20, `ReceptoresPage.tsx` 27, `ReportesPage.tsx` 7, plus `App.tsx`, `authStore.ts`, `Sidebar.tsx`, `AuditoriaPage.tsx` for routing/permissions).

## Frontend Affected Areas

- `frontend/src/types/index.ts:29-59,115,149-165`: `Receptor`, `CuentaBancaria`, `Gestor.receptor_id`/`.receptor`, `Pago.receptor_id`/`.receptor`, `ReporteDetalleReceptor`.
- `frontend/src/api/index.ts:39-50,85,124-125`: `receptoresApi` (list/crear/actualizar/eliminar/agregarCuenta/actualizarCuenta, no `eliminarCuenta`), `pagosApi.listar` filter `receptor_id`, `pagosApi.modificarReceptor(pagoId, receptor_id)`.
- `frontend/src/pages/Pagos/PagosPage.tsx:47-53,73,126-129,284-293,593-600,835-849`: "Modificar Receptor" modal loads the receptor list into a `<select>` and calls `modificarReceptor`. This select must become a bank-account select (grouped by receptor or flattened "Receptor — Entidad — ****1234" labels); the table column showing the receptor must show the account instead.
- `frontend/src/pages/Gestores/GestoresPage.tsx:18,24,55-150,187-296`: "Receptor asignado" select and badge in gestor create/edit form and list; becomes "Cuenta bancaria asignada."
- `frontend/src/pages/Receptores/ReceptoresPage.tsx` (27 occurrences): CRUD page for receptores + cuentas; needs a "default" marker/affordance if `es_predeterminada` is modeled explicitly.
- `frontend/src/pages/Reportes/ReportesPage.tsx:155-178`: "Desglose por Receptor" table; unchanged if reports stay receptor-level (join rewritten server-side).
- Permission gating unchanged: `Sidebar.tsx`, `authStore.ts`, `App.tsx` reference receptor only for the `/receptores` route.

## Alembic Precedent Findings

Only 3 migrations exist: `d9144df95951_initial` (baseline), `a1b2c3d4e5f6_add_anchor_days_to_creditos` (nullable additive columns + check constraints, DDL only; data derivation deferred to an idempotent admin endpoint `POST /admin/migracion/anclar-fechas`, later deleted), `b2c3d4e5f6a7_add_veces_aplazado_to_pagos` (additive column with `server_default='0'`).

**No precedent exists for an in-migration data backfill (`op.execute`) or for adding a NOT NULL FK to a populated table.** The established convention: ship the additive nullable column via DDL-only migration, backfill in production through a temporary idempotent admin endpoint, delete that endpoint in a follow-up PR. Tests build schema via `Base.metadata.create_all` (`backend/tests/conftest.py:39`), not Alembic, so migrations are not exercised by pytest; the model change is what tests pin.

## Options: Defining the Default Bank Account

1. **Implicit, earliest row wins (add `created_at` to `CuentaBancaria`).**
   - Pros: minimal schema change, matches "first one created" literally.
   - Cons: `created_at` is required (UUID ids are not insertion-ordered); no admin override.
   - Effort: Low.
2. **Explicit `es_predeterminada` flag, one default per receptor (partial unique index).**
   - Pros: unambiguous, admin can change the default later.
   - Cons: more schema and flip logic. Effort: Medium.

**Recommendation: Option 1 now**; adopt Option 2 only if the owner anticipates admin-selectable defaults soon (avoids a second migration).

## Options: FK Migration Strategy (Gestor/Pago: `receptor_id` → `cuenta_bancaria_id`)

**A. Replace: drop `receptor_id`, add `cuenta_bancaria_id`, backfill via temp admin endpoint (recommended).**
- Steps: (1) additive nullable-FK migration adds `cuenta_bancaria_id` to `gestores`/`pagos`; (2) temp admin endpoint creates the generic "Por definir" account for receptores with none and backfills `cuenta_bancaria_id` from each row's `receptor_id` default account; (3) code cutover swaps schemas/routers/services to `cuenta_bancaria_id`, receptor derived via `CuentaBancaria.receptor`; (4) follow-up PR drops `receptor_id` columns and the temp endpoint.
- Pros: single source of truth, no drift, matches "money is per account", reuses the existing cleanup convention.
- Cons: every receptor-name read needs one extra join through `CuentaBancaria`; `GET /pagos?receptor_id=` semantics must be decided (Q1).
- Effort: Medium-High (mostly mechanical renames/joins).

**B. Keep `receptor_id` and add `cuenta_bancaria_id` alongside.** Rejected: two sources of truth kept in sync forever, the bug class this codebase already paid for twice.

**C. Keep `receptor_id`, derive account only from the receptor's default.** Rejected: contradicts the requirement that users choose among a receptor's accounts.

**Recommendation: Option A**, executed as a multi-PR sequence.

## Impact on Existing Receptor-Scoped Filters/Reports (Option A)

- `GET /pagos?receptor_id=` (`pagos.py:225,293-294`): rename to `cuenta_bancaria_id` or keep `receptor_id` expanded server-side via a subquery over `CuentaBancaria` (Q1).
- `reportes.py:116-134`: join `Pago.cuenta_bancaria_id` → `CuentaBancaria.receptor_id` to keep a receptor-level rollup, or switch to per-account rollup (Q2; interacts with items 9/13).
- `gestores.py:_propagar_receptor_a_pagos` becomes `_propagar_cuenta_a_pagos`, same shape.

## Blast Radius Table

| Layer | File | Change type | Est. lines |
|---|---|---|---|
| Backend model | `app/models/receptor.py` | Add `created_at` to `CuentaBancaria` | ~5 |
| Backend model | `app/models/gestor.py` | Rename FK column + relationship | ~10 |
| Backend model | `app/models/pago.py` | Rename FK column + relationship | ~10 |
| Backend migration | new file (add columns + FK) | New | ~50 |
| Backend migration | new file (drop old columns, follow-up PR) | New | ~20 |
| Backend schema | `app/schemas/gestor.py` | Field rename | ~6 |
| Backend schema | `app/schemas/pago.py` | Field rename (3 spots) | ~10 |
| Backend schema | `app/schemas/receptor.py` | Add `created_at`, maybe default flag | ~5 |
| Backend router | `app/routers/gestores.py` | Rename propagation function/column | ~15 |
| Backend router | `app/routers/pagos.py` | PATCH body/field, filter decision | ~25-40 |
| Backend router | `app/routers/creditos.py` | Read `gestor.cuenta_bancaria_id` | ~5 |
| Backend router | `app/routers/reportes.py` | Rewrite join/group-by | ~15-25 |
| Backend router | `app/routers/receptores.py` | Default-account helper/endpoint | ~10-20 |
| Backend service | `app/services/credito_service.py` | Rename parameter across ~14 functions | ~30-40 |
| Backend service | `app/services/pago_service.py` | Rename parameter (5 spots) | ~10 |
| Backend temp admin endpoint | new file | Backfill endpoint, deleted in follow-up | ~40-60 |
| Backend tests | 7+ existing files + 2-3 new | Update fixtures, add backfill/default-account tests | ~150-250 |
| Frontend types | `types/index.ts` | Add `CuentaBancaria` refs, rename fields | ~15 |
| Frontend api | `api/index.ts` | Rename filter/PATCH param | ~10 |
| Frontend page | `PagosPage.tsx` | Modal select becomes account select, table column | ~40-60 |
| Frontend page | `GestoresPage.tsx` | Select/badge becomes account-based | ~40-60 |
| Frontend page | `ReceptoresPage.tsx` | Default marker on account list | ~10-20 |
| Frontend page | `ReportesPage.tsx` | Only if report becomes account-level | ~0-20 |

**Total estimate: ~520-680 lines**, above the 400-line single-PR budget.

## Suggested PR Split (Feature Branch Chain)

1. **PR1, backend schema + backfill.** Migration (additive FK columns, `created_at` on `CuentaBancaria`), model changes, temp backfill admin endpoint, tests. ~180-220 lines.
2. **PR2, backend cutover.** Schemas/routers/services swap to `cuenta_bancaria_id`, filters/reports rewritten, propagation renamed, tests updated. Targets PR1. ~150-200 lines.
3. **PR3, frontend.** Types, API client, Pagos/Gestores/Receptores UI. Targets PR2. ~120-170 lines.
4. **PR4, cleanup.** Drop `receptor_id` columns, delete temp endpoint, after prod backfill verified. ~30-50 lines.

## Open Technical Questions

1. Does `GET /pagos?receptor_id=` stay receptor-scoped (expanding to all of a receptor's accounts) or become account-scoped (`cuenta_bancaria_id=`)?
2. Should `reportes.py`'s `por_receptor` breakdown become per-account, or stay receptor-level (summed across accounts)?
3. Explicit `es_predeterminada` flag or insertion-order via `created_at`?
4. Should `CuentaBancaria` gain a delete/deactivate endpoint in this change? If yes, soft delete is required.
5. Rename `PATCH /pagos/{id}/receptor` to `/pagos/{id}/cuenta-bancaria` or keep the URL and change body semantics?
6. Confirm generic backfill account fields: `entidad_bancaria="Por definir"`, `tipo_cuenta=Ahorros`, `numero_cuenta="0"`. No uniqueness constraint on `numero_cuenta`, so no DB conflict.

## Risks

- `credito_service.py`'s 21 occurrences are mechanical renames across ~14 builder functions; do one atomic rename pass with a full test-suite run, not incremental renames across PRs.
- No precedent for NOT-NULL FK with backfill in one migration; nullable-then-backfill-then-drop across PRs must be sequenced procedurally (backfill in prod before cutover ships).
- Frontend account-select labeling when a receptor has multiple accounts needs a small UX decision.
- `GET /pagos` virtual-row suppression (`pagos.py:322-323,376-377`) must be re-verified once the column is `cuenta_bancaria_id`.
- Blast radius exceeds the 400-line budget; the 4-PR chain also gives backend schema/backfill/cutover separate landing points for production-migration safety.

## Ready for Proposal

Yes, contingent on resolving Q1-Q3 before finalizing the delta spec. Q4-Q6 can be resolved during `sdd-design`.
