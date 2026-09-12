# Exploration: payment-reversal-recaudo-fix

Intermittent failure of the "Reversar" (desvalidar check) button for the `recaudador` role. Quote phase 2, item 5 (correction, $320.000 COP). Engram: `sdd/payment-reversal-recaudo-fix/explore` (obs #932).

## Current State

### Frontend — `frontend/src/pages/Pagos/PagosPage.tsx`

- Button rendered at lines 462-472: visible when `!p.es_proyectada && perms.canValidarPago && !p.pagado && p.validado_recaudador`.
- `perms.canValidarPago` (`frontend/src/store/authStore.ts:85`) = `role === 'admin' || role === 'recaudador'`. The role enum is `recaudador` (the quote says "recaudo" as shorthand); no naming mismatch.
- Handler `handleDesvalidar` (lines 210-219): native `confirm()`, then `pagosApi.desvalidar(pago.id)`, `toast.success`, `cargarPagos(false)` refetch, `toast.error(e.response?.data?.detail || 'Error')` on failure.
- **No `submitting`/disabled-state guard** on this handler (unlike `handleModificarFecha` / `handleModificarReceptor`). The button stays clickable during the in-flight request, enabling double-submit.
- Errors are surfaced via toast, but when `e.response` is undefined (network failure, CORS preflight failure, or the 401 → refresh → redirect path below) the toast collapses to the literal `'Error'`.
- API client `frontend/src/api/axios.ts` response interceptor (lines 45-87): on 401 it attempts a silent refresh via `/api/v1/auth/refresh` (first-party cookie through the Vercel proxy, PR #11). If refresh fails it calls `logout()` and sets `window.location.href = '/login'` **with no toast or message**.

### Backend — `backend/app/routers/pagos.py`

- Route `POST /pagos/{pago_id}/desvalidar` (lines 585-624), `require_role("admin", "recaudador")` (line 589).
- Loads the payment via `_get_pago_con_credito(db, pago_id)` with `lock=False` (no `FOR UPDATE`; `registrar_pago` / `confirmar_excedente` use `lock=True`, lines 495/547).
- Rejections, in order: `pago.pagado` → 422 "ya fue registrado con montos"; `capital_pagado > 0 or interes_pagado > 0` → 422 "tiene montos registrados"; `not pago.validado_recaudador` → 422 "Este pago no estaba validado".
- **No `credito.activo` check** (differs from `registrar_pago`, ~line 500).
- No idempotency protection: two rapid calls on the same `pago_id` yield one success + one 422.
- Only successful reversals are audited (`audit_service.registrar_actualizacion_campos`); rejected attempts leave no trace.

### Auth dependency — `backend/app/dependencies.py:73-93`

`require_role` is a plain role check off the JWT; `get_current_user` (lines 29-70) raises 401 on any `JWTError` or inactive/deleted user, which feeds the axios 401 path above.

### Cross-cutting / OpenSpec

- `openspec/specs/credit-closure/spec.md` line 249 (Non-Goals): "Reopening or reversing a closed credit (quote item 5) — no inverse of closure exists." That non-goal and this bug report share the label "item 5" but are different surfaces: `desvalidar_pago` never checks `credito.activo`, so closure does not block it today. Must be disambiguated with the owner.
- `payment-carryover` and `daily-installment-scheduling` specs do not reference reversal.
- Tests: **zero tests for `desvalidar`** in `backend/tests` (grep confirmed). Baseline: 305 passing on `main`.

## Ranked Root Causes (most to least plausible)

1. **Silent 401 → failed refresh → redirect to login with no feedback** (`frontend/src/api/axios.ts:75-79`). Reproduce: let the access token expire while idle on the Pagos page, or clear the refresh cookie, then click Reversar. Confirm in prod: correlate `/auth/refresh` 401s with complaint timestamps; check access-token TTL. Not role-specific in code, but recaudador users keep the tab open longer while scanning rows, so idle expiry hits them more often — matches "intermittent, not Safari-specific."
2. **No submit guard + no lock/idempotency on `desvalidar`**. Reproduce: throttle network, double-click Reversar → first call succeeds, second returns 422 "no estaba validado". Confirm in prod: audit log shows one `validado_recaudador: True→False` per intended action; look for close-in-time 422s.
3. **Generic `'Error'` toast masking the real cause**. Not a root cause, but explains "no error message" for #1, #2 and #4.
4. **Credit-state race** (no `credito.activo` check, no row lock in `desvalidar`). Low likelihood; the business rule for reverting on a closed credit is undefined (see open questions).
5. **Browser-specific code paths**: none found in this flow (no Safari-only branch, no date parsing, cookie/CORS already handled by PR #11). Consistent with the owner's report that it also fails on non-Apple devices.

## Recommended Approach: Diagnose Before Fixing

1. Instrument: log every `desvalidar_pago` attempt (success and rejection reason) with `usuario_id`, `pago_id`, timestamp.
2. Frontend: distinguish "no `e.response`" (network / 401 redirect) from a real 422/403 and show a specific message instead of `'Error'`.
3. Add the missing `submitting` guard to `handleDesvalidar` (low risk, removes cause #2 regardless).
4. Gate any 401/refresh-path change (proactive refresh, explicit re-auth prompt) on real evidence from prod logs or a forced reproduction.

## Open Questions for the Owner

- Can a check be reversed after the credit auto-closed (`activo = False`)? Today nothing blocks it.
- Should there be a time window (e.g., same day only) after which reversal is disallowed? Currently none.
- Should reversal be restricted to the recaudador who validated it, or open to any recaudador/admin (current)?
- Is this report the same "item 5" as the credit-closure non-goal ("no inverse of closure exists"), or a distinct defect in the existing revert-check feature?

## Ready for Proposal

Yes, with the open questions flagged. Suggested shape: diagnostic-first PR (logging + error-path clarity + submit guard + tests for `desvalidar`), with the 401/refresh fix evidence-gated.
