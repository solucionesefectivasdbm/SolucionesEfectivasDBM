## Exploration: zero-balance-explicit-closure (rule 14 — optional early close with interest waiver)

### Current State

Predecessor change `2026-09-11-zero-balance-credit-closure` (archived) implemented rules 9-13:
- `esta_saldado(credito)` (`backend/app/services/credito_service.py:90-107`): `cuota_fija` is settled only when `saldo_capital<=0` AND `saldo_intereses<=0`. `abono_capital` settles at `saldo_capital<=0` only (invariant: never carries `saldo_intereses`, rule 3).
- `cerrar_credito(credito)` (`credito_service.py:110-125`): ONLY writer of `activo=False`. Never touches `saldo_capital`/`saldo_intereses`. Idempotent (returns False if already closed).
- `credito_operativamente_abierto()` (`credito_service.py:128-150`): SQL predicate mirroring `esta_saldado`, used at read sites (resumen-cartera, GET /pagos real+virtual rows, alerts). Correctly keeps a capital=0/interest>0 credit visible/collectible.
- `_siguiente_cuota_fija_solo_interes` (`credito_service.py:614-658`): once capital=0 but interest>0, generation switches to interest-only installments (`TipoCuota.interes`, `capital_a_pagar=0`), capped at `min(interes_base, saldo_intereses)`. This is rule 10 — the DEFAULT path and must NOT regress.
- `confirmar_cierre_credito` (`backend/app/routers/creditos.py:428-476`): `POST /creditos/{id}/cerrar`, roles admin/recaudador/registrador. Validation order: 404 → 422 if already closed (non-idempotent, rule 11) → 422 if `not esta_saldado(credito)` (message names outstanding component, lines 457-467) → `cerrar_credito(credito)` → `audit_service.registrar_actualizacion_campos(cambios={"activo": ("True","False")})` → returns `_credito_response(credito)`.
- Call sites wiring `esta_saldado`/`cerrar_credito` in `pago_service.py`: `_pago_exacto:199-200`, `_pago_parcial:266-267`, `confirmar_excedente` path (`:334-335`), `registrar_pago_no_programado:411-412` (early-return keyed on `esta_saldado`, NOT on `cerrar_credito`'s boolean; documented at `:405-410`).
- `_credito_response()` (`creditos.py:41-50`): computes `pendiente_de_cierre = credito.activo and esta_saldado(credito)` — TRUE only when BOTH capital and interest are already zero and unconfirmed. This flag does NOT cover the new target state (capital=0, interest>0) — that state currently has NO backend signal at all.
- Frontend: `CreditosPage.tsx` (`:311-330`) renders a three-state badge (Cerrado / Saldado-pendiente-de-cierre / Activo) and a confirm-cierre button gated on `c.activo && c.pendiente_de_cierre` for admin/recaudador/registrador, opening `<Modal>` (`components/ui/Modal`) with an inline confirm (`:583-592`) calling `creditosApi.cerrar(id)` (`onConfirmarCierre`, `:231-243`). Errors surface via `toast.error(e.response?.data?.detail || '...')` — the established pattern (also in `PagosPage.tsx`).
- `window.confirm(...)` is used elsewhere for simple binary confirmations (`PagosPage.tsx:231`) — an alternative to `<Modal>` for the new two-option prompt.

### Affected Areas

- `backend/app/routers/creditos.py` (`confirmar_cierre_credito`, ~427-476) — new precondition branch: accept closure when `saldo_capital<=0` even if `saldo_intereses>0` for `tipo_credito==cuota_fija`, ONLY when the operator explicitly opts in (request body flag). capital>0 must still 422 unconditionally; default (no flag) keeps today's reject-if-interest-pending behavior so rule 10 stays the default path.
- `backend/app/services/credito_service.py` (`cerrar_credito`, `esta_saldado`, ~90-125) — the "never touches balances" invariant is relied on by 4 call sites in `pago_service.py` plus the confirm endpoint. Rule 14's interest waiver must NOT weaken this for those other call sites.
- `backend/app/services/pago_service.py` — verified: the 4 automatic-closure call sites are untouched; no change needed.
- `backend/app/schemas/pago.py` (`RegistrarPagoResponse`, `PagoResponse`) and `backend/app/routers/pagos.py` (payment routes) — response payload gap (see below).
- `backend/app/schemas/credito.py` (`CreditoResponse`, ~115-135) — already carries `saldo_capital`, `saldo_intereses`, `tipo_credito`, `activo`, `pendiente_de_cierre`. `pendiente_de_cierre` CANNOT be widened without breaking rule 11's existing UI gate — a NEW field is needed if the credit-list UI must detect "capital=0, interest>0, not yet closed".
- `frontend/src/pages/Creditos/CreditosPage.tsx` and `frontend/src/pages/Pagos/PagosPage.tsx` — need the new prompt/flow.
- `frontend/src/api/index.ts` — `creditosApi.cerrar(id)` takes no body; needs an optional flag param. `pagosApi.noProgramado` returns bare `Pago` (not wrapped), inconsistent with the other two payment routes.
- Read/report paths (`resumen-cartera`, `credito_operativamente_abierto`) — NOT affected: the predicate already requires `activo==True`, so once a credit closes and `saldo_intereses` is zeroed, it drops out of every open-credit read site. No phantom pending interest is possible because the zeroing happens atomically with `activo=False` in the same transaction.

### Critical gap found: payment response payloads do NOT carry credito state

`RegistrarPagoResponse` (`schemas/pago.py:60-68`) = `{pago: PagoResponse, requiere_decision, excedente, mensaje}`. `PagoResponse` (`:10-35`) has cuota-level fields but **no** `saldo_capital`, `saldo_intereses`, `tipo_credito`, or `activo`. True for all three money-moving routes:
- `POST /pagos/{id}/registrar` → `RegistrarPagoResponse`
- `POST /pagos/{id}/confirmar-excedente` → `RegistrarPagoResponse`
- `POST /pagos/no-programado/{credito_id}` → **bare `PagoResponse`** (`routers/pagos.py:852`; frontend types it as `Pago`, `api/index.ts:126-127`).

The frontend cannot detect "capital 0, interest > 0" from a payment-registration response today. It must either (a) receive new credito-state fields in the response, or (b) issue a follow-up read (`GET /creditos/{id}` or list refresh) after a successful payment.

### Approaches

1. **Enrich payment responses with credito state + explicit-flag confirm endpoint** — add credito-state fields (or one computed boolean) to `RegistrarPagoResponse`; migrate `no-programado` to the same wrapper. Endpoint gets a new optional body `{forzar_cierre_con_interes_pendiente: bool = False}`, accepted only when `saldo_capital<=0`.
   - Pros: single backend-computed source of truth (AGENTS.md: financial calculation lives in backend); no extra round-trip.
   - Cons: touches 3 response schemas + 3 routes; breaking shape change on `no-programado`; larger diff, likely needs its own PR slice.
   - Effort: Medium.

2. **Frontend re-fetches credito after any successful payment mutation; no payload change** — after `registrar`, `confirmarExcedente`, `noProgramado` succeed, call `GET /creditos/{id}` (or use loaded list state) and evaluate `tipo_credito==='cuota_fija' && saldo_capital<=0 && saldo_intereses>0` client-side (same class of read as the existing badge logic in `CreditosPage.tsx:304`).
   - Pros: zero backend schema changes; confirm-endpoint change isolated; smallest diff, fits the 400-line budget in one PR.
   - Cons: one extra round-trip per payment on the rare credits hitting this edge; duplicates a trivial three-field predicate on the frontend (not a financial calculation).
   - Effort: Low.

3. **Where the interest-zeroing writer lives**: (3a) a new dedicated `cerrar_credito_con_interes_pendiente(credito)` in `credito_service.py` that sets `saldo_intereses=0.00` THEN calls `cerrar_credito(credito)` as its only path to `activo=False` — vs (3b) a `condonar_interes: bool` parameter on `cerrar_credito`.
   - 3a pros: `cerrar_credito`'s contract stays literally true for every existing caller and test; the function name states the business exception at the call site; audit old-value capture is local.
   - 3a cons: "single writer" claim becomes "single physical writer, one gated caller" — documentation update.
   - 3b cons: weakens `cerrar_credito`'s docstring/tests; every existing test asserting "never writes balances" needs updating.
   - Recommendation: 3a.

### Recommendation

Approach 2 + 3a, with an explicit opt-in flag on `confirmar_cierre_credito` (capital>0 always 422 regardless of flag), keeping the validation order 404 → 422 already-closed → 422 capital-pending, then branching on capital-only-vs-fully-settled with the new flag. Adds a new `CreditoResponse` field (e.g. `puede_cerrar_con_interes_pendiente: bool`) mirroring `pendiente_de_cierre` so the credit-LIST view can also offer the close action for credits already in this state in prod.

### Risks

- UI must visually distinguish the new "capital=0, interest>0, optional early close" state from the existing "fully settled, pending confirm" state.
- The flag must never bypass the capital>0 rejection — a body-driven bypass would reopen the old debt-forgiveness bug class.
- Audit completeness: old `saldo_intereses` captured before zeroing and passed to `registrar_actualizacion_campos` alongside the `activo` change, in the SAME call.
- `registrar_pago_no_programado`'s bare `PagoResponse` is an existing inconsistency independent of this change — follow-up candidate, out of scope unless approach 1 is chosen.
- Engram observations #892/#897 could not be retrieved by the explore agent (tool gap); business rules were reconstructed from the archived proposal/design. Orchestrator note: #892 was read directly by the orchestrator in this session and rule 14 is already saved there; the reconstruction matches.

### Estimated changed lines (review-budget forecast)

| Surface | Est. Δ lines | Notes |
|---|---|---|
| `backend/app/routers/creditos.py` | ~35 | new body schema + branch + message |
| `backend/app/services/credito_service.py` | ~30 | new function + invariant docstring |
| `backend/app/schemas/credito.py` | ~5 | new signal field |
| `backend/tests/` | ~140 | RED-first: unit + endpoint flag matrix + audit row |
| `frontend/src/pages/Creditos/CreditosPage.tsx` | ~45 | badge/button for new state, prompt |
| `frontend/src/pages/Pagos/PagosPage.tsx` | ~40 | post-payment re-fetch + prompt |
| `frontend/src/api/index.ts` + `types/index.ts` | ~10 | |
| **Total** | **~305** | Fits ONE PR under 400 (Medium risk). Approach 1 would push to chained. |

### Open Questions for the owner

1. Confirm button labels for the two-option prompt (e.g. "Cerrar crédito" / "Seguir cobrando").
2. Credit-list badge for the new state: distinct third variant vs reuse of "Saldado — pendiente de cierre". Recommend distinct copy.
3. Confirm scope: rule 14 applies ONLY to `cuota_fija`; `abono_capital` is structurally inapplicable (rule 3). State explicitly in the spec.

### Ready for Proposal

Yes.
