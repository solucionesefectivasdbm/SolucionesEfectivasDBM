# Proposal: Zero-balance explicit closure (rule 14)

> Follow-up to archived `2026-09-11-zero-balance-credit-closure` (rules 9-13). Owner
> decisions: Engram `negocio/cierre-creditos-por-saldo` (#892, rule 14) and
> `negocio/cierre-con-interes-pendiente-ui` (#977). Rejection copy: rule 13 (#897).

## Intent

A `cuota_fija` credit whose client pays all remaining capital early ends with
`saldo_capital = 0` and `saldo_intereses > 0`. Interest is simple and precomputed over
the full term, so the interest of the unused periods is **neither debt nor forgiveness**
— it never accrues. Today that credit can only follow rule 10 (interest-only
installments); `POST /creditos/{id}/cerrar` rejects it with 422
(`backend/app/routers/creditos.py:459`).

The same balance state also arises when capital was paid installment by installment but
interest was under-collected — there the interest **is** owed. Same numbers, different
business decision, so the **operator decides** (rule 14). Rule 10 stays the default; the
original defect (auto-closing with interest pending) is not reopened.

## Scope

### In Scope
- `POST /creditos/{id}/cerrar` accepts an explicit opt-in body flag. With the flag and
  `tipo_credito = cuota_fija`, `saldo_capital <= 0`, `saldo_intereses > 0`: close.
  Without the flag: exactly today's behavior. `saldo_capital > 0`: 422 always, flag or
  not. Validation order unchanged: 404 → 422 already closed → 422 capital pending →
  branch on fully-settled vs capital-only.
- New service function `cerrar_credito_con_interes_pendiente(credito)` in
  `credito_service.py`: captures the previous `saldo_intereses`, sets it to `0.00`,
  then calls the existing `cerrar_credito` (still the only physical writer of
  `activo = False`). Both changes are recorded in **one**
  `audit_service.registrar_actualizacion_campos` call, same transaction.
- New `CreditoResponse` field `puede_cerrar_con_interes_pendiente: bool` mirroring
  `pendiente_de_cierre`, so the credit list can offer the action for credits already in
  this state in production. `pendiente_de_cierre` semantics untouched (rule 11 gate).
- Frontend, credit list: distinct badge "Capital saldado · interés pendiente" with the
  close action available (roles admin, recaudador, registrador — rule 7).
- Frontend, payments: after a successful `registrar` / `confirmarExcedente` /
  `noProgramado`, re-fetch the credit; if `cuota_fija && saldo_capital <= 0 &&
  saldo_intereses > 0`, prompt "Crédito con saldo de capital en 0 pero interés pendiente
  de $X. ¿Desea cerrarlo o seguir cobrando el interés pendiente?" with buttons
  "Cerrar crédito" / "Seguir cobrando". "Seguir cobrando" does nothing (default path).
- Every new rejection carries a Spanish business-reason `detail`, written once in the
  backend and rendered verbatim (rule 13).

### Out of Scope
- Any automatic closure on the payment path; the four `pago_service.py` call sites and
  `cerrar_credito` itself are unchanged.
- `abono_capital`: structurally inapplicable, never carries `saldo_intereses` (rule 3).
- Enriching payment response schemas with credit state; the `no-programado` bare
  `PagoResponse` inconsistency is a separate follow-up.
- Reopening a closed credit (still no inverse primitive). Backfill of any kind.
- Alembic migrations; `activo` and both balances already exist.

## Capabilities

### New Capabilities
- None.

### Modified Capabilities
- `credit-closure`: (1) "Closure by Settled State Only" gains a bounded exception — the
  explicit operator-driven path MAY zero `saldo_intereses` on a capital-settled
  `cuota_fija`, with audit of the previous value; automatic paths still never write
  balances. (2) "Explicit Closure Confirmation" accepts the opt-in flag for that state
  and exposes `puede_cerrar_con_interes_pendiente`. (3) "Operator-Readable Rejection
  Messages" covers the flag-with-capital-pending case.

## Approach

Exploration approaches **2 + 3a**. The frontend evaluates a three-field read predicate
(not a financial calculation — same class as the existing badge logic), so payment
schemas stay untouched and the change fits one PR. The interest-zeroing writer is a new,
narrowly named function rather than a parameter on `cerrar_credito`, so the existing
"never touches balances" contract and its tests remain literally true.

**Tradeoff**: one extra `GET /creditos/{id}` per payment on the rare credits reaching
this state, versus a three-schema breaking change. Accepted.

Read paths need no change: `credito_operativamente_abierto` requires `activo = True`,
and zeroing happens atomically with `activo = False`, so no phantom pending interest can
surface in reports.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `backend/app/routers/creditos.py` | Modified | Request body schema, flag branch, rejection copy |
| `backend/app/services/credito_service.py` | Modified | `cerrar_credito_con_interes_pendiente`; invariant docstring update |
| `backend/app/schemas/credito.py` | Modified | `puede_cerrar_con_interes_pendiente` |
| `backend/tests/` | New | Flag matrix, audit row, `cerrar_credito` invariant preserved |
| `frontend/src/pages/Creditos/CreditosPage.tsx` | Modified | New badge + close action |
| `frontend/src/pages/Pagos/PagosPage.tsx` | Modified | Post-payment re-fetch + two-option prompt |
| `frontend/src/api/index.ts`, `types/index.ts` | Modified | Optional flag param, new field |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Flag bypasses the capital > 0 rejection (reopens debt forgiveness) | Med | Capital check runs before the flag is read; explicit RED test |
| Rule 10 default regresses (auto-close reintroduced) | Low | No payment-path change; test that a payment leaving capital 0 / interest > 0 keeps `activo = True` |
| Operator closes a credit whose interest was genuinely owed | Med | Explicit two-option prompt showing the amount; restricted roles; audit of previous value. Closure is irreversible — item 5 still blocked |
| Audit incomplete (interest change not recorded) | Low | Single `registrar_actualizacion_campos` call with both fields; asserted in tests |
| New badge confused with "Saldado — pendiente de cierre" | Low | Distinct copy and separate boolean field |

## Rollback

Single PR revert. `saldo_intereses` zeroing is data: credits closed via this path are
identifiable in `audit_log` (both `activo` and `saldo_intereses` in one row) and can be
restored by targeted SQL from the audited previous value.

## Dependencies

- Owner sign-off captured (#892, #977, #897). No client notification needed: the only
  behavior change is opt-in per credit.

## Review budget forecast

~305 changed lines. **400-line budget risk: Medium. Chained PRs recommended: No.
Decision needed before apply: No** — one PR to `main` (`stacked-to-main`).

## Success Criteria

- [ ] Closing a `cuota_fija` with capital 0 / interest > 0 without the flag still returns
      422 with the existing message.
- [ ] With the flag, the credit closes, `saldo_intereses = 0.00`, and one audit row
      records both `activo` and the previous `saldo_intereses`.
- [ ] With the flag and `saldo_capital > 0`, 422 with a Spanish business reason.
- [ ] `cerrar_credito` still never writes balances; the four payment-path call sites are
      byte-identical.
- [ ] `puede_cerrar_con_interes_pendiente` is true only for active `cuota_fija` credits
      with capital 0 / interest > 0.
- [ ] Payment UI shows the prompt only in that state; "Seguir cobrando" leaves the credit
      open and rule 10 continues.
- [ ] Backend suite green; `npx tsc --noEmit` clean.
