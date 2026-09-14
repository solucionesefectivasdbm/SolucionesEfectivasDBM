# Tasks: Zero-Balance Explicit Closure (rule 14)

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~335 |
| 400-line budget risk | Medium |
| Chained PRs recommended | No |
| Suggested split | Single PR |
| Delivery strategy | auto-forecast |
| Chain strategy | stacked-to-main |

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: stacked-to-main
400-line budget risk: Medium

### Suggested Work Units

| Unit | Goal | Likely PR | Focused test command | Runtime harness | Rollback boundary |
|------|------|-----------|----------------------|-----------------|-------------------|
| 1 | Predicate + writer + router flag + audit + frontend badge/prompt | PR 1 | `backend/venv/Scripts/python.exe -m pytest backend/tests/test_pago_service.py backend/tests/test_creditos_router.py` | httpx `AsyncClient` + `db_session`, unmocked | Revert single PR; no migration, `saldo_intereses` recoverable from audit row |

## Phase 0: Baseline

- [x] 0.1 Run `backend/venv/Scripts/python.exe -m pytest --collect-only -q | tail -1`; record baseline test count — **358 collected** (repo-root scope, includes stray `test_all.py`); `backend/tests`-scoped equivalent is 356 (387 final − 31 new)

## Phase 1: Service Layer — Predicate + Writer (RED → GREEN)

- [x] 1.1 RED (`backend/tests/test_pago_service.py`): `puede_cerrar_con_interes_pendiente` true only for active `cuota_fija`, capital<=0, interest>0; false for closed / capital>0 / both-zero / `abono_capital` (Req: Closable-with-Interest-Pending Signal, both scenarios)
- [x] 1.2 GREEN: add `puede_cerrar_con_interes_pendiente(credito)` to `backend/app/services/credito_service.py`, next to `esta_saldado`
- [x] 1.3 RED: writer zeroes `saldo_intereses`, sets `activo=False` via `cerrar_credito`, returns previous value; raises `ValueError` on capital>0 / `abono_capital` / inactive (Req: Explicit Closure Confirmation, writer precondition)
- [x] 1.4 GREEN: add `cerrar_credito_con_interes_pendiente(credito) -> Decimal` to `credito_service.py`; update `cerrar_credito` docstring (unique bounded exception)
- [x] 1.5 RED: existing `cerrar_credito` tests (`test_cerrar_credito_no_escribe_saldos`) still pass unmodified — regression lock (Req: Closure by Settled State Only, settled-only primitive never writes balances)

## Phase 2: Router + Schema (RED → GREEN)

- [x] 2.1 GREEN (schema): `CerrarCreditoRequest { cerrar_con_interes_pendiente: bool = False }` and `puede_cerrar_con_interes_pendiente: bool = False` on `CreditoResponse` in `backend/app/schemas/credito.py`
- [x] 2.2 RED (`backend/tests/test_creditos_router.py`, `TestConfirmarCierreConInteresPendiente`): no body / `{}` / `{flag:false}` on capital 0 / interest > 0 → 422 with existing interest message (Req: Explicit Closure Confirmation, interest-pending-without-flag scenario)
- [x] 2.3 RED: flag + capital 0 / interest > 0 → 200, `saldo_intereses == "0.00"`, `activo` False, exactly **two** `AuditLog` rows (`activo` True→False, `saldo_intereses` previous→0.00) via one `registrar_actualizacion_campos` call (Req: Explicit Closure Confirmation, interest-pending-with-flag scenario)
- [x] 2.4 RED: flag + capital > 0 (both `cuota_fija` and `abono_capital`) → 422, `detail` names the capital amount and does NOT contain "condonar" (Req: Operator-Readable Rejection Messages, flag-rejected-because-capital-is-pending scenario)
- [x] 2.5 RED: flag + fully-settled credit → 200, one audit row (`activo` only); flag + already-closed → 422, no audit row (Req: Explicit Closure Confirmation, flag-on-fully-settled + already-closed scenarios)
- [x] 2.6 RED: flag on active `abono_capital` — ignored: capital<=0 closes, capital>0 422; `saldo_intereses` never written (Req: Explicit Closure Confirmation, flag-on-abono_capital scenario)
- [x] 2.7 RED: roles — `admin`/`recaudador`/`registrador` × flag path → 200; `gestor` → 403 (Req: Explicit Closure Confirmation, forbidden-role scenario), parametrized
- [x] 2.8 GREEN: implement router branch order in `backend/app/routers/creditos.py` (404 → 422 closed → 422 capital>0-with-flag → 422 capital>0 → settled-close → flag-close → 422 interest-pending) with the pinned Spanish `detail` copy
- [x] 2.9 RED: `GET /creditos/{id}` and list — `puede_cerrar_con_interes_pendiente` true for the target state, false after close and for settled credits; `pendiente_de_cierre` unchanged (Req: Closable-with-Interest-Pending Signal, capital-settled-interest-outstanding + signal-false-outside-the-state scenarios)
- [x] 2.10 GREEN: set `resp.puede_cerrar_con_interes_pendiente` in `_credito_response` (`backend/app/routers/creditos.py:41`)
- [x] 2.11 RED: payment leaving capital 0 / interest > 0 on any of the four `pago_service.py` paths keeps `activo=True`, `saldo_intereses` unchanged, next installment interest-only — regression lock (Req: Closure by Settled State Only, payment-leaving-interest-pending-never-auto-closes scenario)
- [x] 2.12 Verify: `backend/venv/Scripts/python.exe -m pytest` — 0 failures, count >= baseline + new tests (387 passed, scoped to `backend/tests`)

## Phase 3: Frontend — Types, API, Shared Dialog

- [x] 3.1 Add `puede_cerrar_con_interes_pendiente: boolean` to `Credito` in `frontend/src/types/index.ts`
- [x] 3.2 Update `creditosApi.cerrar` in `frontend/src/api/index.ts` to accept optional `{ cerrar_con_interes_pendiente: boolean }` body
- [x] 3.3 Create `frontend/src/components/ui/ConfirmarCierreInteresPendiente.tsx` (props `{ isOpen, credito, onCerrar, onSeguir, loading }`, `<Modal>`, pinned copy, `btn-ghost`/`btn-primary` buttons); export via `frontend/src/components/ui/index.tsx`

## Phase 4: Frontend — Credit List Wiring

- [x] 4.1 `CreditosPage.tsx`: add "Capital saldado · interés pendiente" badge (`badge-info`) between `pendiente_de_cierre` and `Activo` states (Req: Credit List Badge and Action, badge-and-action-visible scenario)
- [x] 4.2 `CreditosPage.tsx`: extend close-button gate to `c.activo && (c.pendiente_de_cierre || c.puede_cerrar_con_interes_pendiente)`, same roles; route interest-pending credits to the new dialog instead of `ConfirmDelete` (Req: Credit List Badge and Action, action-hidden-for-other-roles scenario)
- [x] 4.3 Wire `onCerrar` → `creditosApi.cerrar(id, { cerrar_con_interes_pendiente: true })`, toast (read `detail` on error, rule 13), `cargar()`

## Phase 5: Frontend — Payments Wiring

- [x] 5.1 `PagosPage.tsx`: add `verificarCierreInteresPendiente(creditoId)` helper — `creditosApi.obtener`, sets `creditoCierre` state when field true; errors swallowed
- [x] 5.2 Call helper after success in `handleRegistrar`, `handleConfirmarExcedente`, `handleNoProgramado` (Req: Post-payment Closure Prompt, prompt-shown + prompt-not-shown scenarios)
- [x] 5.3 Wire dialog: "Cerrar crédito" → `creditosApi.cerrar(id, {...true})`, toast, `cargarPagos(false)`; "Seguir cobrando" → clear state only, no request (Req: Post-payment Closure Prompt, operator-closes + operator-keeps-collecting scenarios)

## Phase 6: Verification

- [x] 6.1 `backend/venv/Scripts/python.exe -m pytest` full suite green — 387 passed (scoped `backend/tests`; repo-root run hits a pre-existing unrelated `INTERNALERROR` from a stray `test_all.py` at repo root)
- [x] 6.2 `cd frontend && npx tsc --noEmit` clean
- [x] 6.3 Manual spot-check: badge/prompt copy matches pinned strings verbatim; no "condonar" wording anywhere (grep confirmed — only appears in a router docstring negatively, "nunca 'condonar'")

## Delivery status — DELIVERED (single PR, size:exception)

Actual diff is **~762 changed lines** (`git diff --stat`: 693 insertions + 24 deletions
across 9 tracked files, plus 1 new untracked file `ConfirmarCierreInteresPendiente.tsx`
~45 lines), above the 400-line budget and the ~335-line forecast (485 of those lines
are strict-TDD tests). The owner explicitly decided on 2026-09-14 to accept
`size:exception` and deliver as a single PR rather than chaining, given the diff is
almost entirely one deliverable feature plus its own test coverage.

Committed as two work-unit commits on `feat/zero-balance-explicit-closure`:
- `d784adf` — backend: predicate + writer + router + schema + tests (604 lines)
- `2147a39` — frontend: types + api + shared dialog + list/payments wiring (133 lines)

387 backend tests passed, `tsc --noEmit` clean, no "condonar" in user-facing text.
This `docs(sdd)` commit adds the openspec change folder itself. Owner will push and
open the PR.

## Scenario Coverage Map

| Requirement | Scenarios | Task(s) |
|---|---|---|
| Closable-with-Interest-Pending Signal | 2/2 | 1.1, 2.9 |
| Post-payment Closure Prompt | 4/4 | 5.2, 5.3 |
| Credit List Badge and Action | 2/2 | 4.1, 4.2 |
| Closure by Settled State Only | 6/6 (delta scenarios) | 1.5, 2.11 (new); others regression-locked pre-existing |
| Explicit Closure Confirmation | 8/8 | 2.2-2.7 |
| Operator-Readable Rejection Messages | 2/2 (delta scenarios) | 2.4, 2.2 |
