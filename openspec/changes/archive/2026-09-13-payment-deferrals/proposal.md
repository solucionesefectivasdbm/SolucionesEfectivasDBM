# Proposal: Payment Deferrals ("Aplazamientos de pago")

Change: `payment-deferrals` · Quote phase 2, item 7 ($450.000 COP, new feature) · Exploration: Engram #946 · Owner decisions: Engram #947 (binding)

## Intent

Today `PATCH /pagos/{id}/fecha` overwrites `fecha_maxima` with no signal of *why*. A client who asked to defer is indistinguishable from a clerical correction, and from a credit-level "momento" change (`PATCH /creditos/{id}/dias-pago`). Collectors cannot tell "the client who warned" from "the client who simply did not pay", nor prioritize clients who defer repeatedly.

Success: a deferred payment is visibly marked everywhere it appears, its deferral count is known, and all deferred payments can be reviewed on one page regardless of month.

## Scope

### In Scope
- `pagos.veces_aplazado INT NOT NULL DEFAULT 0` (additive Alembic migration; head is `a1b2c3d4e5f6`).
- `ModificarFechaPagoRequest.es_aplazamiento: bool = False`; when true, the same endpoint increments the counter and writes a distinct audit entry (deferral vs. correction).
- `PagoResponse.veces_aplazado`.
- Backend listing of deferred payments across periods (no `anio`/`mes` bound) for the new page.
- Frontend: yes/no question in the existing "Modificar fecha" flow; dedicated row style for `veces_aplazado > 0` in the shared `PagosPage.tsx` (weekly + daily); new route `/pagos/aplazados` (double visualization).

### Out of Scope / Non-goals
- No reason/motivo field. No deferral history table (counter only). No backfill of historical deferrals.
- No change to `dias-pago` / momento mechanism. No new role or permission: reuse `require_role("admin", "recaudador")` of `modificar_fecha_pago`.
- Virtual/projected rows (`es_proyectada`) cannot be deferred (no DB row).

## Capabilities

### New Capabilities
- `payment-deferral-tracking`: marking, counting, listing and highlighting client-requested deferrals.

### Modified Capabilities
- None (existing specs untouched at requirement level).

## Approach

Single counter over a boolean: `veces_aplazado > 0` derives "is deferred", so no separate `es_aplazado` column (avoids two fields drifting). Reuse the existing endpoint, role gate and `audit_service`; the audit row carries a deferral marker so the log distinguishes the two intents. Cross-period listing bypasses the in-memory month merge of `listar_pagos` (real rows only, `WHERE veces_aplazado > 0`).

Design questions deferred to sdd-design: reject deferral when `pagado=true` (recommend yes); counter unchanged when paid; color precedence (deferred over `bg-red-50` only while `fecha_maxima >= today`, red wins once overdue again; gray projected unaffected); page as third `variante` vs. new component; counter as column/badge; default sort `fecha_maxima` asc.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `backend/app/models/pago.py`, `backend/alembic/versions/` | Modified/New | counter column + migration |
| `backend/app/schemas/pago.py` | Modified | request flag, response counter |
| `backend/app/routers/pagos.py` | Modified | `modificar_fecha_pago`, deferred listing |
| `backend/tests/` | New | router + listing tests (strict TDD) |
| `frontend/src/pages/Pagos/PagosPage.tsx`, `App.tsx`, `types`, `api/index.ts` | Modified | question, row style, route, types |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Color precedence confuses collectors | Med | explicit rule in design; overdue red wins |
| Deferred page misses payments | Low | dedicated cross-period query, not month filter |
| Counter over-increment by accidental "yes" | Med | confirm dialog; audit trail; admin can not decrement in v1 (accept) |

## Rollback Plan

Revert PR; feature is UI-gated. Migration is additive: `alembic downgrade -1` drops the column; leaving it in place is harmless.

## Dependencies

- None.

## Success Criteria

- [ ] Answering "yes" increments `veces_aplazado` and moves the date; "no" only moves the date.
- [ ] Deferred rows are visually distinct in weekly and daily pages.
- [ ] `/pagos/aplazados` lists every deferred pending payment across months.
- [ ] Audit log distinguishes deferral from correction.
- [ ] Backend tests green; `tsc --noEmit` clean.

## Proposal question round

Assumptions needing owner review (answer, skip, or correct):
1. Should a deferral be refused once the payment is already paid (`pagado=true`)?
2. When a deferred payment becomes overdue again, should red (vencido) win over the deferred color?
3. Does the deferred page show only pending payments, or also paid ones that were deferred?
4. Is one deferred color enough, or should repeated deferrals (e.g. 2+) look stronger?
