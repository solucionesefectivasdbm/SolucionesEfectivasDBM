# Proposal: Daily Payments Skip Sunday

Quote phase 2, item 4 (correction, $160.000 COP). Business rules are binding per owner decision (Engram #913).

## Intent

Daily (`diario`) credits currently schedule installments on Sundays, which is not a collection day. Collectors see Sunday-dated cuotas that cannot be collected, and the schedule does not match the agreed business practice. The system must never place a daily installment on Sunday, must reject a Sunday start date explicitly, and must correct pending Sunday-dated rows already in production.

## Scope

### In Scope
- `siguiente_fecha_maxima` diario branch: a computed date landing on Sunday shifts to Monday; all later installments shift accordingly. Same installment count; the credit ends later; never two installments on the same day.
- Reject `CreditoCreate` with `periodicidad = diario` and `fecha_inicial_pago` on Sunday with an operator-readable Spanish `detail` (no silent correction).
- Update `test_fechas_ancla.py::test_4_2_b_diario_month_boundary` (Jan-31-2026 -> Feb-02 Monday) and add Sunday-skip, cascade, creation-rejection and projection scenarios under strict TDD.
- Regression test combining a Sunday shift with a payment-carryover shortfall.
- Temporary admin-only POST backfill: pending (`pagado=False`, `deleted_at IS NULL`) rows of active daily credits, re-walked via `recalcular_cuotas_futuras`; idempotent; paid rows keep their historical date.
- Follow-up cleanup PR removing the backfill endpoint (AGENTS.md convention).

### Out of Scope
- `semanal`, `quincenal`, `mensual` scheduling (anchor helpers untouched).
- Holidays or any calendar beyond Sunday.
- Rewriting already-paid rows.
- Frontend changes (no date logic exists there; existing `e.response?.data?.detail` handling surfaces the rejection).
- Alembic migrations or schema changes.

## Capabilities

### New Capabilities
- `daily-installment-scheduling`: Sunday exclusion for daily installment dates, Sunday start-date rejection, projection parity, and the one-off pending-row backfill.

### Modified Capabilities
- None. `payment-carryover` (amount-based) and `credit-closure` (balance-based) are date-independent; `numero_cuota` is not altered, so "Past-term Installments Are Explainable" is unaffected. Non-interaction is proven by the regression test, not by spec changes.

## Approach

Add `_siguiente_diario(fecha_anterior)` mirroring the existing `_siguiente_mensual` / `_siguiente_quincenal` helpers, wired only into the diario branch. Because generation, projection (`routers/pagos.py`) and recalculation all funnel through `siguiente_fecha_maxima`, one change keeps every path consistent. Validation lives in `CreditoCreate.validar_reglas_negocio` (backend-owned message). Backfill reuses `recalcular_cuotas_futuras` directly, bypassing the edit-days router guard that rejects diario; the endpoint is separate from that route.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `backend/app/utils/fechas.py` | Modified | `_siguiente_diario` helper; diario branch |
| `backend/app/schemas/credito.py` | Modified | Sunday start-date rejection for diario |
| `backend/app/routers/creditos.py` (or admin router) | New (temporary) | Backfill endpoint |
| `backend/tests/test_fechas_ancla.py` | Modified | Update 4.2.b; new scenarios |
| `backend/tests/` | New | Schema rejection, projection, carryover regression, backfill tests |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Cascade shifts drift from projection | Low | Single function; projection parity test |
| Backfill touches wrong rows | Low | Filter pending + diario + active; dry-run report; idempotency test |
| Existing daily credits started on Sunday | Med | Validation applies to creation only; backfill handles subsequent rows |
| Hidden semanal regression | Low | Branch-scoped helper; existing semanal tests remain |

## Rollback Plan

Revert the PR (pure logic, no schema). Backfilled dates are recoverable by re-running `recalcular_cuotas_futuras` from the reverted function; keep the backfill response (credit IDs, before/after dates) as an audit record.

## Dependencies

- None external. Prior corrective patterns: `payment-carryover`, `zero-balance-credit-closure`.

## Success Criteria

- [ ] No daily installment (real or projected) has `fecha_maxima.weekday() == 6`.
- [ ] Sunday `fecha_inicial_pago` on a daily credit returns 422 with a business message.
- [ ] Installment count unchanged; no duplicate dates per credit.
- [ ] Backfill in production reports corrected rows; second run reports zero.
- [ ] Full backend suite green; `npx tsc --noEmit` clean.
