# Proposal: Recaudo registers amounts, Registrador supervises (revert amount)

## Intent

Today only admin/registrador register amounts; recaudador only validates the check. Business now wants `recaudador` to also register amounts, and `registrador` to act as supervisor with a new "revert amount" operation. No amount-reversal logic exists; mistakes in registered amounts cannot be undone.

## Scope

### In Scope
- Allow `recaudador` (plus existing admin, registrador) on `POST /{id}/registrar`, `POST /{id}/confirmar-excedente`, `POST /no-programado/{credito_id}`, on any validated payment regardless of who validated it.
- New endpoint "revert amount" (admin + registrador), any registered amount, including own/admin/recaudador's; optional reason.
- LIFO guard: blocked (clear 4xx) while later registered payments exist for the credit (incl. `no_programada`; order by `fecha_pago_real`/`created_at`, not `numero_cuota`).
- Cascade: restore reverted cuota to validated+unpaid (`validado_recaudador` kept; `pagado=False`, montos 0, `fecha_pago_real=None`, `es_excedente_a=None`); soft-delete generated cuota N+1 (must be unpaid, no montos); soft-delete the payment's repartos; RECOMPUTE (not invert) credit saldos and arrastre.
- Closed credits: reverting the last payment reopens (saldado and regla 14 explicit closure). `saldo_intereses` is recomputed from schedule state, not restored from audit_log; this is a design risk to settle in design.
- Receptor ledger: reversal allowed even if balance goes negative (computed on read; no blocking).
- Audit via `audit_service.registrar_*`; `FOR UPDATE` row locks.
- Frontend: `canRegistrarPago` adds recaudador; new `canRevertirMonto` (admin, registrador); "Revertir monto" action in `PagosPage.tsx` (semanal + diario).

### Out of Scope
- `registrado_por_id` column (permissions do not need it; optional audit nicety, deferred).
- Full-cascade or edit-and-recompute reversal (Approaches B/C).
- Blocking on negative receptor balance; mandatory reason.
- Changes to check validation/reversion rules.

## Capabilities

### New Capabilities
- `payment-amount-reversal`: revert registered amount, LIFO guard, cascade, reopen, audit, permissions.

### Modified Capabilities
- `pagos`: recaudador may register amounts / excedente / no-programado.
- `payment-validation-reversal`: `desvalidar` still requires unpaid; clarify interplay with reverted (validated-unpaid) state.
- `credit-closure`: reverting the last payment reopens saldado and explicit closures.
- `receptor-ledger`: reversal may yield negative balance.
- `pago-repartos`: repartos soft-deleted on revert.

## Approach

Approach A (LIFO-guarded) from exploration. Add `PagoService.revertir_monto` that locks the credit and pagos, validates guard, restores cuota N, soft-deletes N+1 and repartos, recomputes saldos from the schedule (credito_service recompute helpers, extended for excedente-to-intereses), reopens credit, re-derives arrastre via `recalcular_cuota_actual_si_no_pagada`, and audits. Expose via a role-gated router endpoint. Role-gate change is a one-line `require_role` edit plus frontend store.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `backend/app/routers/pagos.py` | Modified | role gates; revert endpoint |
| `backend/app/services/pago_service.py` | Modified | `revertir_monto` |
| `backend/app/services/credito_service.py` | Modified | saldo recompute / reopen |
| `backend/app/services/audit_service.py` | Modified | revert audit helper |
| `frontend/src/store/authStore.ts` | Modified | permissions |
| `frontend/src/pages/Pagos/PagosPage.tsx` | Modified | Revertir monto action |
| `backend/tests/` | New/Modified | 403 and revert tests |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Saldo drift on recompute (history PRs #30-#39) | Med | Recompute from schedule; property-style tests |
| Regla 14 closure zeroed interest not recoverable | Med | Design decides recompute rule; test reopen |
| Negative receptor balance | Med | Accepted by business; surfaced in ledger |
| N+1 loses check/aplazamientos | Low | Guard requires N+1 untouched; document |
| Segregation of duties (recaudador validates+registers) | Med | Accepted by business; audit trail |
| Concurrency | Low | `FOR UPDATE` locks |

## Rollback Plan

No schema change: revert PRs in reverse order (frontend, endpoint, role gates). Already-reverted payments remain valid validated-unpaid cuotas and can be re-registered.

## Dependencies

- None. No migration expected: no new column (AGENTS.md says startup hook, repo uses alembic via start.sh; moot here).

## Review Workload Forecast

| PR | Slice | Est. lines |
|----|-------|-----------|
| 1 | Role gates backend + frontend store + 403/200 tests | ~120 |
| 2 | Revert service + endpoint + audit + tests | ~380 (watch 400 budget) |
| 3 | Frontend "Revertir monto" action | ~150 |

Sequential PRs, each from fresh branch off updated main, merged in order.

## Success Criteria

- [ ] recaudador registers all three operations; other roles unchanged; unauthorized gets 403.
- [ ] Admin/registrador revert latest payment; cuota returns to validated-unpaid; N+1 and repartos soft-deleted; saldos match pre-payment state.
- [ ] Earlier payment revert is rejected with a clear 4xx.
- [ ] Closed credits reopen; ledger adjusts automatically.
- [ ] All changes audited; UI shows action only for admin/registrador.
