# Proposal: Receiver Bank Account Assignment

Change: `receiver-bank-account-assignment` · Quote phase 2, item 11 ($360.000 COP) · Exploration: `explore.md` · Owner + orchestrator decisions below are binding. First of the chain 11 → 9 (`receiver-cash-balance`) → 10 (multi-destination splits).

## Intent

Money is received into a specific bank account (Nequi, Bancolombia, Daviplata, ...), but today `Gestor` and `Pago` only know the *receptor*. Collectors cannot record or see which account a payment went to, and the future balance/ledger (item 9) would have no account to attach to. Success: every gestor and every payment points to one receptor bank account; the account is chosen when assigning or changing it, is shown wherever the receptor is shown, and lists/reports can be narrowed from receptor down to account.

## Binding decisions

| # | Decision |
|---|---|
| 1 | Replace, not add: `Gestor.receptor_id` and `Pago.receptor_id` become `cuenta_bancaria_id`. Receptor is derived via `CuentaBancaria.receptor`. `Cliente` stays on `gestor_id`. |
| 2 | Auto-assignment mirrors today: new cuotas inherit `gestor.cuenta_bancaria_id`; changing a gestor's account propagates to its unpaid pagos (`_propagar_receptor_a_pagos` → `_propagar_cuenta_a_pagos`). |
| 3 | Explicit `CuentaBancaria.es_predeterminada`; exactly one default per receptor; first account created gets it; admin endpoint to change it. |
| 4 | Backfill: receptores with no account get a generic default (`entidad_bancaria="Por definir"`, `Ahorros`, `numero_cuenta="0"`), then `cuenta_bancaria_id` is filled from each row's `receptor_id` default. Temporary idempotent admin endpoint, deleted in the cleanup PR. |
| 5 | Cascading filters/reports: `GET /pagos` filters by receptor, optionally by one of its accounts; `GET /reportes` keeps `por_receptor` and nests a per-account sub-breakdown. |
| 6 | `PATCH /pagos/{id}/receptor` → `PATCH /pagos/{id}/cuenta-bancaria` (same roles). No account deletion. |

## Scope

### In Scope
- Schema: `es_predeterminada` on `cuentas_bancarias` (one-default-per-receptor constraint); nullable `cuenta_bancaria_id` FK on `gestores` and `pagos`; later drop of both `receptor_id` columns.
- Default-account rule: auto-set on first create; `PATCH /receptores/{id}/cuentas/{cuenta_id}/predeterminada` flips it atomically.
- Backend cutover: schemas, `gestores.py`, `pagos.py` (list filter, serializer, PATCH), `creditos.py`, `credito_service.py`, `pago_service.py`, `reportes.py`.
- Backfill endpoint + idempotency tests (strict TDD).
- Frontend: Pagos (account column, cascading filter, "Modificar cuenta" modal with receptor → account selects), Gestores (account select/badge), Receptores (default marker + set-default action), Reportes (nested per-account rows).

### Out of Scope / Non-goals
- No balance, ledger, or "salidas" (item 9). No multi-destination payment splits (item 10).
- No account delete/deactivate, no soft delete on `CuentaBancaria`.
- No change to permissions/roles, `Cliente`, credit math, or audit-log mechanics beyond the renamed field.
- Changing a receptor's default account does **not** rewrite existing gestor/pago assignments (default is used only for backfill and UI preselection).

## Capabilities

### New Capabilities
- `receiver-bank-account-assignment`: default account rule, account as the money destination on gestor/pago, inheritance/propagation, cascading filters and report sub-breakdown, backfill.

### Modified Capabilities
- None (no existing spec references receptor).

## Approach

- **Data model.** `CuentaBancaria` gains `es_predeterminada BOOLEAN NOT NULL DEFAULT false` plus a partial unique index `(receptor_id) WHERE es_predeterminada`. `gestores.cuenta_bancaria_id` / `pagos.cuenta_bancaria_id` are added nullable (same nullability as today's `receptor_id`); ORM stops using `receptor_id` at cutover, DB columns dropped last.
- **Migration sequence.** DDL-only additive migration (repo convention) → prod backfill through the temp endpoint (written against SQL columns so it stays runnable after the ORM drops `receptor_id`) → cutover → re-run backfill for rows created in between → drop columns.
- **Reads.** Receptor name everywhere comes from one extra join `Pago → CuentaBancaria → Receptor`; `reportes.py` groups by `(receptor_id, cuenta_bancaria_id)` and rolls up, so the receptor totals stay identical to today.
- **Extensibility.** Item 9's ledger keys on `cuenta_bancaria_id` and reuses the per-account aggregation; item 10 can later move `Pago.cuenta_bancaria_id` into a child "destinations" table without touching the default/propagation rules.
- **UI.** Account labels use `Receptor — Entidad — numero` (exact format is a design decision); receptor select preselects its default account.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `backend/app/models/{receptor,gestor,pago}.py`, `backend/alembic/versions/` (2 files) | Modified/New | flag + FK columns; drop migration in PR4 |
| `backend/app/schemas/{receptor,gestor,pago,common}.py` | Modified | field rename, default flag, nested account in responses |
| `backend/app/routers/{receptores,gestores,pagos,creditos,reportes}.py` | Modified | default endpoint, propagation, cascading filter, PATCH rename, nested report |
| `backend/app/services/{credito_service,pago_service}.py` | Modified | mechanical parameter rename (~26 spots) |
| `backend/app/routers/admin.py` (temp) | New, then Removed | backfill endpoint |
| `backend/tests/` | Modified/New | fixtures + default/backfill/filter/report tests |
| `frontend/src/{types,api}/index.ts`, `pages/{Pagos,Gestores,Receptores,Reportes}` | Modified | account-based selects, columns, filters |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Rows created between PR1 and PR2 deploys lack `cuenta_bancaria_id` | High | idempotent backfill re-run after PR2; endpoint SQL-based |
| Generic "Por definir" accounts linger in reports | Med | visible label; admin edits them; success criterion lists count |
| `credito_service.py` rename done partially across PRs | Med | single atomic rename in PR2 with full pytest run |
| Virtual-row suppression in `GET /pagos` breaks with new filter | Med | re-verify `pagos.py:322-323,376-377` in tests |
| Reviewer load (520-680 lines) | Certain | 4 chained PRs below |

## Rollback Plan

PR1-PR3 are additive: revert code; columns stay nullable and harmless. Backfill only writes `cuenta_bancaria_id` and generic accounts (guarded, re-runnable). PR4 is the only destructive step and ships after prod verification; its migration has a `downgrade` that re-adds `receptor_id` (data re-derivable from `CuentaBancaria.receptor_id`).

## Delivery plan (Feature Branch Chain)

| PR | Content | Est. lines | Prod step |
|---|---|---|---|
| PR1 | migration, models, `es_predeterminada` rule + endpoint, backfill endpoint, tests | ~180-220 | deploy → run backfill → verify 0 gestores/pagos with receptor but no account |
| PR2 | backend cutover (schemas/routers/services/reports/tests) | ~150-200 | deploy with PR3 → re-run backfill → smoke |
| PR3 | frontend | ~120-170 | deploy → verify tables/filters/reports |
| PR4 | drop `receptor_id` columns, delete temp endpoint | ~30-50 | after prod verification |

Lesson from item 4: land each PR in `main` sequentially rather than keeping a long-lived chain open.

## Dependencies

- None. Item 9 depends on this change.

## Success Criteria

- [ ] Every receptor has exactly one default account; first created account is default; admin can change it.
- [ ] New credit cuotas inherit the gestor's account; changing a gestor's account updates its unpaid pagos only.
- [ ] `PATCH /pagos/{id}/cuenta-bancaria` changes one payment's account with an audit diff.
- [ ] Pagos tables (weekly, daily, deferred) show the account; filter by receptor then by account works; virtual rows unaffected.
- [ ] Report receptor totals equal pre-change values; per-account rows sum to the receptor total.
- [ ] Backfill is idempotent; after PR4 no `receptor_id` column remains on `gestores`/`pagos`.
- [ ] Backend pytest green under strict TDD; `npx tsc --noEmit` clean.

## Proposal question round

Owner decisions cover the product shape; remaining assumptions to confirm or correct (answer, skip, or request another round):
1. Changing a receptor's default account does not retroactively move existing gestor/pago assignments. Correct?
2. A payment's account may be changed to an account of a *different* receptor (as receptor changes work today). Correct?
3. Generic "Por definir" accounts should be visible as-is in tables/reports until the admin edits them (no special hiding). Correct?
4. Cascading filter: receptor-only shows all of that receptor's accounts combined; account level is optional. Correct?
