# Design: Payment Reversal Recaudo Fix

## Technical Approach

Close the three explainable failure paths of "Reversar" (`POST /pagos/{pago_id}/desvalidar`)
without touching business rules: (1) backend serializes the reversal against concurrent
payment registration (`lock=True`) and logs every attempt; (2) frontend cannot double-submit
and never collapses an error to the literal `Error`; (3) a failed silent refresh leaves a
marker so `/login` explains the bounce. No schema, no migration, no new guard on
`credito.activo`, no proactive refresh. Specs: `payment-validation-reversal`,
`session-expiry-feedback`.

Review first: `backend/app/routers/pagos.py` (`desvalidar_pago`, lines 585-624) and the new
test file; the frontend diff is mechanical.

## Architecture Decisions

| Decision | Choice | Rejected | Rationale |
|---|---|---|---|
| Row lock | `_get_pago_con_credito(db, pago_id, lock=True)` (`pagos.py:596`) | pago-row lock; no lock | Same lock as `registrar_pago:495` / `confirmar_excedente:547`: `SELECT ... FOR UPDATE` on the **credito** row, then `db.refresh(pago)` (`pagos.py:865-868`). A reversal racing a `registrar_pago` on the same cuota now waits and re-reads `pagado=True`, so it returns 422 instead of clearing `validado_recaudador` on a paid row. Single-row lock in the same order as siblings: no deadlock. Held only until `get_db` commits. SQLite ignores `FOR UPDATE`, so tests prove behavior, not serialization (accepted, same as siblings) |
| Log visibility | Module-level `logging.basicConfig(level=INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")` in `backend/app/main.py` before `app = FastAPI(...)` | log everything at WARNING; leave config untouched | Verified: no `basicConfig`/`dictConfig` under `backend/app`, `start.sh:28` runs uvicorn without `--log-config`, so `app.*` INFO lines are dropped today (`LOGIN OK` never reaches Render). `basicConfig` is a no-op if root already has handlers; uvicorn loggers have `propagate=False`, so no duplicate lines. Rejections still use WARNING so they survive even without this config (`lastResort`) |
| Log placement | Router (`desvalidar_pago`), printf-style, uppercase event prefix (`auth.py:160-217` convention) | audit rows for rejections; middleware | No schema; audit rows are for state changes only. 403 (dependency) and 404 (helper) happen before router code and are not logged (accepted: 403 is deterministic per role, 404 is not a reported symptom) |
| Rejection helper | Local `_rechazar_desvalidar(pago_id, usuario, motivo, detail)` logs WARNING then raises 422 | three inline `logger.warning` calls | One place guarantees every rejection is logged with the same keys; ~8 lines |
| Second call on reverted pago | Keep 422 `"Este pago no estaba validado."`; frontend refetches only when the server responded and the error is not the session-expiry rejection | idempotent 200 | Proposal decision; the 422 is the trace that a double-submit happened. Refetch is skipped on the expired-session path because the interceptor is already redirecting to `/login` — a refetch there would re-enter the interceptor and fire a second refresh + stray toast during unload |
| Submit guard | Reuse shared `submitting` state (`PagosPage.tsx:68`): early return, `disabled={submitting}` on the button | per-row `desvalidandoId` | Owner decision; pattern already used by `handleModificarFecha/Receptor`. Disabling every Reversar button for ~300 ms is acceptable |
| Error mapping | New `frontend/src/utils/apiErrors.ts` exporting `mensajeError(e, fallback): string \| null` | inline ternaries in handler | Decision table below is reusable; `null` means "redirect in progress, no toast" |
| Sibling handlers | Replace `e.response?.data?.detail \|\| 'Error'` with `mensajeError(e, '...')` in the 6 `PagosPage` catch blocks (`:186,206,230,243,295` + registrar) | leave siblings | One-line mechanical edits (~6 lines) that satisfy "no toast collapses to literal `Error`" for the same page; no other page is touched |
| Expiry marker | `sessionStorage` key `auth_redirect_reason` = `session_expired`, set in `axios.ts` only when the refresh call itself answered `401` (not on network errors or 5xx during refresh) | query string `/login?expired=1`; toast; marking on any refresh failure | Survives the full reload, is per-tab, is not shareable via URL, and cannot outlive the tab. Toast rejected: the page unloads immediately. Marking unconditionally on any refresh failure would misreport a backend outage as an expired session |
| Login request exclusion | The response interceptor's 401→refresh branch excludes requests whose `url` includes `/auth/login` | retrying refresh on a failed login | A wrong password already returns 401 from `/auth/login` itself; entering the refresh path there would trigger an unrelated refresh attempt and could bounce the login page with a false "session expired" message for a user who never had a session |
| Login rendering | Inline `<p role="alert">` above the form, read once via lazy `useState` initializer, cleared in `useEffect` | toast on mount | Inline survives the redirect; lazy read + effect clear is StrictMode-safe (both initializer calls read before any effect clears) |

## Data Flow

    Reversar click ──submitting?──▶ return
         │ no
         ▼ confirm() ──▶ setSubmitting(true) ──▶ POST /desvalidar
                                                     │
              ┌──────────────────────────────────────┼─────────────────────────┐
              ▼ 200                                  ▼ 422/403                  ▼ 401
      toast.success + refetch            toast(mensajeError) + refetch   refresh ──ok──▶ retry
                                                                            │ fail
                                                                            ▼
                                        sessionStorage[auth_redirect_reason]=session_expired
                                        logout() ──▶ location=/login ──▶ LoginPage reads,
                                        renders "Tu sesión expiró, vuelve a ingresar.", clears

    Backend: lock credito FOR UPDATE ──▶ refresh(pago) ──▶ guards ──▶ log ──▶ audit ──▶ commit

## File Changes

| File | Action | Description |
|---|---|---|
| `backend/app/main.py` | Modify | `import logging` + `basicConfig` (~5 lines) |
| `backend/app/routers/pagos.py` | Modify | `logger = logging.getLogger(__name__)`; `lock=True` at `:596`; `_rechazar_desvalidar` helper; three guards route through it; `logger.info` on success (~25 lines) |
| `backend/tests/test_desvalidar_pago.py` | Create | Role fixtures (MagicMock `Usuario`, pattern `test_pagos_router.py:78-97`) + cases below (~150 lines) |
| `frontend/src/utils/apiErrors.ts` | Create | `mensajeError`, `marcarSesionExpirada`, `leerSesionExpirada`, `AUTH_REDIRECT_REASON_KEY` (~35 lines) |
| `frontend/src/api/axios.ts` | Modify | `marcarSesionExpirada()` before `logout()` at `:77` (+2 lines); proxy/refresh flow unchanged |
| `frontend/src/pages/Login/LoginPage.tsx` | Modify | Lazy state + effect clear + inline alert (~8 lines) |
| `frontend/src/pages/Pagos/PagosPage.tsx` | Modify | `handleDesvalidar:210-219` guard/finally/mapper; `disabled={submitting}` at `:465`; sibling one-liners (~15 lines) |

Forecast: ~240 code lines. 400-line budget risk: Low. Chained PRs recommended: No. Decision needed before apply: No.

## Interfaces / Contracts

```python
# pagos.py — log lines (usuario_id and rol from current_user; motivo is a stable key)
logger.info("DESVALIDAR OK — pago_id=%s usuario_id=%s rol=%s", ...)
logger.warning("DESVALIDAR RECHAZADO — pago_id=%s usuario_id=%s rol=%s motivo=%s", ...)
# motivo ∈ {pagado, montos_registrados, no_validado}; HTTP 422 detail strings unchanged
```

```ts
// apiErrors.ts — decision table, evaluated top-down
// 1. leerSesionExpirada() pending          -> null   (redirect in flight; no toast)
// 2. typeof e.response?.data?.detail === 'string' -> detail (422/403/404 backend message)
// 3. Array.isArray(detail)                  -> detail.map(d => d.msg).join('; ') (Pydantic)
// 4. e.code === 'ERR_NETWORK' || !e.response -> 'Sin conexión con el servidor. Verifica tu red e intenta de nuevo.'
// 5. e.code === 'ECONNABORTED'              -> 'La solicitud tardó demasiado. Intenta de nuevo.'
// 6. otherwise                              -> fallback
export const AUTH_REDIRECT_REASON_KEY = 'auth_redirect_reason'   // value: 'session_expired'
```

Marker lifecycle: `marcarSesionExpirada()` (try/catch around `sessionStorage.setItem`) →
synchronous, committed before `window.location.href` navigates → `LoginPage` reads in the
`useState` initializer → `useEffect` removes the key on mount. Queued 401 requests rejected
by `processQueue(refreshError)` all hit rule 1, so no stray toasts appear during the redirect.
A later visit to `/login` (manual logout, new tab) finds no key and shows nothing.

## Testing Strategy (Strict TDD — backend RED first)

| Layer | What | How |
|---|---|---|
| Integration | Success: 200, `validado_recaudador=False`, `tipo_validacion=None`, `audit_log` row `campo_modificado='validado_recaudador'` plus a `tipo_validacion` row (prior value → `None`) when it was set; `caplog` INFO contains exactly one `DESVALIDAR OK` line with `pago_id`, `usuario_id` | `client_recaudador`, `caplog.at_level(logging.INFO, logger="app.routers.pagos")` |
| Integration | Rejections: `pagado=True` / `capital_pagado>0` / `validado_recaudador=False` → 422 with the exact existing message and exactly one `caplog` WARNING `motivo=<key>`; pago unchanged | parametrized |
| Integration | Role matrix: admin 200, recaudador 200, registrador/gestor 403 (`detail="No tienes permisos..."`), pago unchanged, no log line | fixtures per role |
| Integration | Repeated calls: first 200, second 422 `"Este pago no estaba validado."`; second call adds no new audit rows (row locking itself is not proven — SQLite ignores `FOR UPDATE`) | sequential calls on same client |
| Frontend | `npx tsc --noEmit` clean | no runner |
| Manual (Chrome, Safari, Firefox) | (a) Expired session: clear the refresh cookie (devtools > Application/Storage) while on Pagos, click Reversar → lands on `/login` with the inline expiry message; reload `/login` → message gone. (b) Throttled double-click: devtools Slow 3G, double-click Reversar → one request in Network, button disabled in flight, one success toast. (c) Offline: devtools Offline, click Reversar → toast "Sin conexión..." and no redirect. (d) Second Reversar on already reverted row (two tabs) → toast with the 422 message, table refreshed | checklist in tasks |

Command: `cd backend && python -m pytest` (Windows: `backend/venv/Scripts/python.exe -m pytest`).

## Threat Matrix

N/A — no routing, shell, subprocess, VCS/PR automation, executable-file classification, or
process-integration boundary. The only new persisted client value is a fixed enum string in
`sessionStorage`; it is never interpolated into markup or URLs.

## Migration / Rollout

No migration. Single PR. After deploy, verify in Render logs that `DESVALIDAR OK` lines appear
(proves the logging config took effect) and correlate any `DESVALIDAR RECHAZADO` with user
reports. Rollback = revert the PR; no data changes. Risk: `basicConfig` makes existing
`app.*` INFO lines (`LOGIN OK`, `CAMBIAR PASSWORD OK`) visible too — intended, but log volume
grows slightly.

## Open Questions

- [ ] None blocking.
- [ ] Follow-up (out of scope): `PagosPage` `cargarPagos:100` and other pages still use the raw
      `detail || '...'` pattern; adopt `mensajeError` project-wide in a separate change.
