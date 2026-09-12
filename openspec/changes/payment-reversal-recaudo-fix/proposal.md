# Proposal: Payment Reversal Recaudo Fix

Quote phase 2, item 5 (correction, $320.000 COP). Owner decisions are binding: the failure is intermittent and browser-independent; no new business rules. Exploration: `explore.md` (Engram #932).

## Intent

Recaudador users intermittently cannot revert a validated check ("Reversar", `POST /pagos/{pago_id}/desvalidar`) and get either a generic `Error` toast or a silent bounce to `/login`. Exploration found no browser-specific code path; the plausible causes are (1) expired session with silent redirect, (2) double-submit with no button guard or row lock, (3) a generic toast hiding the real cause. There is no production evidence because rejected attempts are not logged and the endpoint has zero tests. Success: every failed attempt is explainable to the user and traceable in logs, and the double-submit path is closed.

## Scope

### In Scope
- Backend `desvalidar_pago`: load with `lock=True` (parity with `registrar_pago`); log every attempt (outcome, reason, `usuario_id`, `pago_id`) via the app logger; keep 422 for rejections with the existing Spanish messages.
- Backend tests (strict TDD): success, each 422 rejection, role matrix (`registrador` 403, `admin`/`recaudador` allowed), double call (second returns 422), audit entry on success.
- Frontend `handleDesvalidar`: `submitting` guard disabling the button while in flight; error mapping — backend `detail` (4xx) vs no response (network) vs session expired; refetch list after a 422 so the row reflects server state.
- Frontend axios interceptor: on failed refresh, persist a reason (`sessionStorage`) before redirecting; login page shows "Tu sesión expiró, vuelve a ingresar." once.
- Manual cross-browser verification checklist (Chrome, Safari, Firefox) for expired-token and throttled double-click reproductions.

### Out of Scope
- Reopening or reversing closed credits (`credit-closure` non-goal, spec line 249).
- New rules: time windows, same-user restriction, `credito.activo` guard (open question only).
- Proactive token refresh, refresh TTL changes, or auth architecture changes.
- Frontend test runner (project has none; `apply` rule: standard flow for frontend).
- Any change to `registrar_pago` / `validar` endpoints.

## Capabilities

### New Capabilities
- `payment-validation-reversal`: documents current reversal rules (who, when rejected), adds attempt logging, row locking, and UI feedback/guard requirements.
- `session-expiry-feedback`: when silent refresh fails, the login page explains the redirect instead of bouncing silently.

### Modified Capabilities
- None. `credit-closure`, `payment-carryover`, `daily-installment-scheduling` unchanged.

## Approach

Diagnostic-first, single PR. Decisions and alternatives:

| Decision | Chosen | Rejected | Why |
|----------|--------|----------|-----|
| Second call on already-reverted payment | Keep 422 + frontend refetch | Idempotent 200 | 200 would hide a real state mismatch (another user reverted); guard + lock already prevent UI double-submit; no contract change |
| Session expiry | Message on login page only | Proactive refresh timer | Minimal, evidence-gated; proactive refresh touches auth for all roles |
| Evidence | Logger lines on every attempt | New audit table/rows for rejections | No schema change; logs are enough to correlate with complaints |
| Row lock | `lock=True` | Leave unlocked | Consistency with sibling endpoints; closes race at near-zero cost |

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `backend/app/routers/pagos.py` (585-624) | Modified | lock, attempt logging |
| `backend/tests/test_desvalidar_pago.py` | New | endpoint tests |
| `frontend/src/pages/Pagos/PagosPage.tsx` (210-219, 462-472) | Modified | guard, error mapping, disabled button |
| `frontend/src/api/axios.ts` (75-79) | Modified | persist redirect reason |
| `frontend/src/pages/Login/*` | Modified | show expiry message |

Estimated changed lines: ~250 code + ~100 spec docs. Within the 400 budget (Medium risk; tests are the largest block).

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Root cause is none of the three hypotheses | Med | Logging ships regardless; verify phase correlates prod logs before closing item |
| Login message shown on unrelated visits | Low | Reason cleared on read; only set by the interceptor path |
| `lock=True` changes behaviour under SQLite tests | Low | Sibling endpoints already use it with the same test setup |

## Rollback Plan

Revert the PR. No schema, migration, or data changes; logging and UI copy are additive.

## Dependencies

- None external. Prior patterns: PR #11 (first-party refresh cookie), `daily-payments-skip-sunday` (single-PR corrective flow).

## Success Criteria

- [ ] Backend tests for `desvalidar` cover success, 3 rejections, role matrix, double call; suite green (baseline 305 + new).
- [ ] Every `desvalidar` attempt produces one log line with outcome and reason.
- [ ] Button is disabled during the request; double-click yields one request.
- [ ] Expired session on Reversar lands on `/login` with the expiry message in Chrome, Safari, Firefox.
- [ ] No toast ever collapses to the literal `Error`.
- [ ] `npx tsc --noEmit` clean.

## Open Questions

- Add a `credito.activo` guard to `desvalidar` as a pure bug fix? Default: no (owner said no new rules; closed-credit reversal stays undefined).
- Should the login expiry message use the existing toast system instead of inline text? Default: inline text on the login page (survives the full-page redirect).
