# Tasks: Payment Reversal Recaudo Fix

**Scenario count**: 9 requirements, 20 scenarios total (payment-validation-reversal: 7 req / 13 scenarios; session-expiry-feedback: 2 req / 7 scenarios, +2 added in the review correction round — wrong-credentials login and refresh-outage-sets-no-reason). All 20 mapped below — see Scenario Coverage Map. Gaps: 0.

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~240 (main.py +5, pagos.py ~25, test_desvalidar_pago.py new ~150, apiErrors.ts new ~35, axios.ts +2, LoginPage.tsx ~8, PagosPage.tsx ~15) |
| 400-line budget risk | Low |
| Chained PRs recommended | No |
| Suggested split | Single PR, branch `fix/payment-reversal-recaudo` → `main` |
| Delivery strategy | single-pr-default |
| Chain strategy | pending |

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: pending
400-line budget risk: Low

### Suggested Work Units

| Unit | Goal | Likely PR | Focused test command | Runtime harness | Rollback boundary |
|------|------|-----------|----------------------|-----------------|-------------------|
| 1 | Backend: logging config + reversal endpoint hardening (lock, order, logging) | PR 1 | `cd backend && pytest tests/test_desvalidar_pago.py -q` | httpx AsyncClient + aiosqlite integration tests (unmocked) | Revert `main.py` basicConfig line + `pagos.py` reversal diff + delete `test_desvalidar_pago.py`; no schema change |
| 2 | Frontend: error mapper + submit guard + session-expiry feedback | PR 1 (same PR, separable commits) | `cd frontend && npx tsc --noEmit` + manual checklist (Phase 8) | Manual: Chrome/Safari/Firefox expired-token, throttled double-click, offline | Revert `apiErrors.ts`, `axios.ts` diff, `LoginPage.tsx` diff, `PagosPage.tsx` diff; backend unaffected |

## Phase 1: Foundation — Logging Config

- [x] 1.1 Add `logging.basicConfig(level=INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")` in `backend/app/main.py` before `FastAPI()` instantiation
- [x] 1.2 Verify no duplicate log handlers: `cd backend && pytest -q` — 0 failures, baseline 305 still passing (config is additive, no test asserts it directly yet)

## Phase 2: RED — Failing Tests for Reversal Endpoint (`backend/tests/test_desvalidar_pago.py`, new file)

- [x] 2.1 RED: successful reversal — validated+unpaid+zero amounts → 200; `validado_recaudador=False`, `tipo_validacion=None`; audit row for `campo_modificado='validado_recaudador'` with caller id, plus a `tipo_validacion` audit row (prior value → `None`) when `tipo_validacion` was set; `caplog.at_level(logging.INFO, logger="app.routers.pagos")` captures one `DESVALIDAR OK` line (Req: Successful Reversal — scenario 1/13)
- [x] 2.2 RED: rejections parametrized — paid → 422; `capital_pagado>0` or `interes_pagado>0` → 422; not validated → 422; assert check order pagado → montos → not-validado; no mutation, no audit row on any branch; `caplog` WARNING line with matching `motivo` (`pagado`/`montos_registrados`/`no_validado`) (Req: Reversal Rejections — scenarios 2-4/13)
- [x] 2.3 RED: role matrix — `registrador`/`gestor` → 403 with zero DB reads/mutations and zero log lines; `admin` → 200; `recaudador` → 200 (Req: Role Matrix — scenarios 5-6/13)
- [x] 2.4 RED: concurrent/repeated calls — first call 200 (locked via `_get_pago_con_credito(lock=True)`); second call on same now-reverted pago → 422 not-validado; second call adds no new audit rows (Req: Concurrent and Repeated Calls — scenario 7/13)
- [x] 2.5 RED: attempt logging — success path emits exactly one INFO line with `pago_id`, `usuario_id`, `rol`; each of the 3 rejection paths emits exactly one WARNING line with the matching `motivo` key; assert via `caplog` against logger `app.routers.pagos` (Req: Attempt Logging — scenarios 8-9/13)
- [x] 2.6 Verify RED: `cd backend && pytest tests/test_desvalidar_pago.py -q` — all new tests fail (endpoint not yet modified)

## Phase 3: GREEN — Harden Reversal Endpoint (`backend/app/routers/pagos.py:585-624`)

- [x] 3.1 Add local helper `_rechazar_desvalidar(pago_id, usuario, motivo, detail)` logging one WARNING line then raising `HTTPException(422, detail)`, reusing existing Spanish detail strings verbatim
- [x] 3.2 Switch payment lookup to `_get_pago_con_credito(..., lock=True)` (same pattern as `registrar_pago:495` / `confirmar_excedente:547`); re-read `pago.pagado` after acquiring the lock, before any mutation
- [x] 3.3 Route the 3 rejection checks (pagado → montos → not-validado, in that order) through `_rechazar_desvalidar`
- [x] 3.4 On success, log INFO `"DESVALIDAR OK — pago_id=%s usuario_id=%s rol=%s"` after mutation + audit write, before returning the response
- [x] 3.5 Verify GREEN: `cd backend && pytest tests/test_desvalidar_pago.py -q` — 0 failures

## Phase 4: Full Backend Regression

- [x] 4.1 Verify: `cd backend && pytest -q` — 0 failures, count ≥ 305 (baseline) + new tests from Phase 2 (314 passed = 305 + 9 new)

## Phase 5: Frontend Error Mapping Utility

- [x] 5.1 Create `frontend/src/utils/apiErrors.ts` exporting `mensajeError(e, fallback): string | null` implementing the design's 6-branch precedence: (1) pending `leerSesionExpirada()` → `null`; (2) string `detail` → `detail`; (3) array `detail` → joined `msg`s; (4) `e.code === 'ERR_NETWORK'` or no response → network message; (5) `ECONNABORTED` → timeout message; (6) `fallback`. Also export `marcarSesionExpirada`, `leerSesionExpirada`, `AUTH_REDIRECT_REASON_KEY`
- [x] 5.2 Verify: `cd frontend && npx tsc --noEmit` — 0 errors

## Phase 6: Frontend Wiring — Submit Guard + Error Mapping (`PagosPage.tsx`)

- [x] 6.1 Guard the "Reversar" action with the existing `submitting` state (`PagosPage.tsx:68`): disable the button at `:465` while `submitting`, early-return if already submitting, `finally setSubmitting(false)` (Req: Frontend Submit Guard — scenario 10/13)
- [x] 6.2 Replace the 6 sibling catch blocks in `PagosPage.tsx` (`:186, :206, :230, :243, :295` + registrar) with one-line `mensajeError(e, fallback)` calls; ensure the reversal list refetches after a 422, but not when the error is the session-expiry rejection (Req: Error Message Mapping — scenario 12/13; Frontend Submit Guard — scenario 11/13)
- [x] 6.3 Verify: `cd frontend && npx tsc --noEmit` — 0 errors

## Phase 7: Session Expiry Feedback Wiring

- [x] 7.1 In `frontend/src/api/axios.ts` (~line 77), on failed silent refresh, set `sessionStorage['auth_redirect_reason'] = 'session_expired'` (wrapped in try/catch) before `logout()`/redirect to `/login`; explicit logout path must NOT set this key (Req: Redirect Reason Persisted — scenarios 14-15/18)
- [x] 7.2 In `frontend/src/pages/Login/LoginPage.tsx`, read `leerSesionExpirada()` via a lazy `useState` initializer, clear the key in a mount-only `useEffect` (StrictMode-safe), render inline `<p role="alert">Tu sesión expiró, vuelve a ingresar.</p>` when set (Req: Login Page Shows Expiry Message Once — scenarios 16-17/18)
- [x] 7.3 Verify: `cd frontend && npx tsc --noEmit` — 0 errors

## Phase 8: Manual Verification Checklist (frontend — no test runner)

- [ ] 8.1 Expired token: expire/clear the refresh cookie, click Reversar → redirected to `/login`, inline expiry message shown once, cleared on reload (Req: Redirect Reason Persisted + Login Page Shows Expiry Message Once — scenarios 14, 16, 17/18)
- [ ] 8.2 Throttled double-click: DevTools "Slow 3G", double-click Reversar → exactly one network request, button visibly disabled during flight (Req: Frontend Submit Guard — scenarios 10-11/13)
- [ ] 8.3 Offline: disable network, click Reversar → network message shown, no redirect, no literal "Error" text anywhere (Req: Error Message Mapping — scenario 12/13)
- [ ] 8.4 Two-tab conflict: reverse the same pago from two open tabs → second tab shows the 422 detail verbatim and its list refreshes (Req: Error Message Mapping — scenario 13/13)
- [ ] 8.5 Cross-browser parity: repeat 8.1 in Chrome, Safari, and Firefox — identical redirect + message behavior in all three (Req: Login Page Shows Expiry Message Once — scenario 18/18)

## Phase 9: Post-Deploy Verification

- [ ] 9.1 After merge/deploy, confirm `DESVALIDAR OK` / `DESVALIDAR RECHAZADO` lines appear in Render logs, proving `logging.basicConfig` is wired in production

## Scenario Coverage Map (9 requirements, 20 scenarios — all mapped, 0 gaps)

| Requirement | Scenarios | Task(s) |
|---|---|---|
| Successful Reversal | 1/1 | 2.1 |
| Reversal Rejections | 3/3 | 2.2 |
| Role Matrix | 2/2 | 2.3 |
| Concurrent and Repeated Calls | 1/1 | 2.4 |
| Attempt Logging | 2/2 | 2.5 |
| Frontend Submit Guard | 2/2 | 6.1, 6.2, 8.2 |
| Error Message Mapping | 2/2 | 6.2, 8.3, 8.4 |
| Redirect Reason Persisted | 4/4 | 7.1, 8.1 (wrong-credentials + refresh-outage scenarios added in review correction round, covered by axios.ts login-exclusion and 401-only marker guard) |
| Login Page Shows Expiry Message Once | 3/3 | 7.2, 8.1, 8.5 |
