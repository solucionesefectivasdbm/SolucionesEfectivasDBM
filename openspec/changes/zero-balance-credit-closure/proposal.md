# Proposal: Zero-balance credit closure

> **Refreshed after owner rounds 2 and 3.** The authoritative artifacts are
> `specs/credit-closure/spec.md` (behavior), `design.md` (technical decisions) and
> `tasks.md` (work units and forecast). This proposal states intent, scope and business
> impact only; where the three disagree with it, they win.

## Intent

Credits are closed by the wrong rule, in two opposite directions.

- `_verificar_cierre_credito` (`backend/app/services/pago_service.py:337-364`) closes on
  `numero_cuota >= numero_cuotas` and then forces `saldo_capital = 0`, **silently
  forgiving real debt**.
- `PATCH /creditos/{id}` (`backend/app/routers/creditos.py:246-264`) writes
  `saldo_capital` outside the canonical mutator and runs **no** closure check, so settled
  credits stay `activo = True` and keep inflating the portfolio total and the collection
  list.

This change merges quote items **2** (zero balance does not close) and **3** (fixed-quota
credit with balance past its term) — one defect seen from two sides.

## The definition of "settled" (rules 9 and 10 — supersedes the first draft)

Closure is **not** "capital reaches zero".

- A `cuota_fija` credit is settled only when `saldo_capital <= 0` **AND**
  `saldo_intereses <= 0`. Zero capital alone is not enough.
- While capital is at zero and interest is still outstanding, the system keeps generating
  **interest-only** installments, each capped at the remaining interest, until interest
  reaches zero. Only then is the credit settled.
- An `abono_capital` credit is settled at `saldo_capital <= 0`; it has no
  `saldo_intereses` by invariant. Paid interest is rounded `ROUND_HALF_UP` to 2 decimals.

## Scope

### In Scope
- Remove the count-based closure branch and its `saldo_capital = 0` overwrite. Credits
  past `numero_cuotas` with capital outstanding keep generating full-value installments,
  with no carryover of any shortfall (rule 5).
- Single settled predicate and a single writer of `activo = False` that never writes
  balances; wire it into `_pago_exacto`, `_pago_parcial`, the excess path and
  `registrar_pago_no_programado` (preserving that path's early-return semantics).
- Interest-only installment tail (rule 10), reusing the existing `TipoCuota.interes`.
- `PATCH /creditos/{id}` never touches `activo`; it exposes a pending-closure signal.
  **No auto-close** (rule 2).
- New confirmation endpoint for `admin`, `recaudador`, `registrador` (`gestor` excluded,
  rule 7). Confirming an already-closed credit is **rejected with an error, never a
  silent idempotent 200** (rule 11).
- Read paths return only *operationally open* credits, so a settled-but-unconfirmed
  credit leaves the portfolio and the collection list immediately; confirmation only
  formalizes `activo = False` (rule 6).
- Every rejection this change introduces or touches carries an operator-readable business
  reason, written **once** in the backend `HTTPException(detail=...)` in neutral
  professional Spanish and rendered verbatim by the frontend (rule 13, obs #897).
- One-time admin backfill endpoint closing settled `activo = True` credits, deliberately
  bypassing confirmation as a historic correction (rules 4 and 8).

### Out of Scope
- Reopening / reversing a closed credit (quote item 5). No inverse of closure exists —
  blocking dependency, unchanged.
- Any Alembic migration. `activo` already exists, and `tipo_cuota` is a **native PG
  enum**, so reusing `TipoCuota.interes` (rather than adding a member) keeps the change
  migration-free by construction.
- Frontend automated tests; the frontend gate is `npx tsc --noEmit` only.

## Capabilities

### New Capabilities
- `credit-closure`: when a credit is settled, how it closes, who confirms it, and how
  rejections are explained.

### Modified Capabilities
- None (`payment-carryover` requirements unchanged).

## Approach

One settled predicate, one writer of `activo = False`, and that writer never touches a
balance — debt forgiveness is removed *by construction*, not by a guard. The installment
generator stops on *settled* instead of on capital alone, which is what produces the
interest-only tail. See `design.md` for the primitives, the cap on the final interest
installment, the termination proof and the full read-site verdict table.

**Tradeoff**: two-step admin closure costs a click but prevents a mis-typed capital
correction from irreversibly closing a credit — irreversible because no reopen primitive
exists. Rule 6 removes the operational cost of that delay: the credit leaves the
portfolio and the collection list as soon as it is settled, not when it is confirmed.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `backend/app/services/credito_service.py` | Modified | Settled predicate, closure writer, SQL open-credit predicate, interest-only tail, `es_ultimo_pago`, installment recalculation |
| `backend/app/services/pago_service.py` | Modified | Delete `_verificar_cierre_credito`; rewire four call sites |
| `backend/app/routers/creditos.py` | Modified/New | Pending-closure signal on PATCH; confirmation endpoint; temporary backfill endpoint; portfolio read filter |
| `backend/app/routers/pagos.py` | Modified | Read filters on `GET /pagos` real rows, virtual rows and the alert queries |
| `backend/app/schemas/credito.py` | Modified | Pending-closure field |
| `backend/tests/` | Modified/New | Real-path closure and interest-only coverage |
| `frontend` credits and payments pages | Modified | Pending-closure badge and confirm action; capital input locked on interest-only installments; surface backend `detail` |

`reportes.py` is **unaffected** — verified to contain zero `Credito.activo` references.

## Behavior change (client must be warned)

1. Stuck settled credits will close, and settled-but-unconfirmed credits leave the read
   paths → **portfolio total and the collection list will drop**.
2. Credits past their term with capital outstanding will **keep generating full-value
   installments**, exactly like the item-1 report increase.
3. **Rule 10 lengthens the collection cycle** for `cuota_fija` credits whose interest was
   under-collected: installment counts will exceed `numero_cuotas` (installment 13 of 12
   is expected, not a bug), and collection volume rises accordingly. The UI must explain
   this on the installment itself (rule 13).

All three are corrections, not regressions. Announce before deploy.

**Correction to the first draft**: `/pagos/diarios` is not a backend route. The frontend
page calls `GET /pagos`, whose real-row query (`backend/app/routers/pagos.py:128-147`)
has no `activo` filter at all — only `_calcular_virtuales` (`:279`) does. Filtering the
virtual rows alone would not satisfy rule 6.

## Testing strategy

Strict TDD is ON for the backend; the frontend has no test runner.

**Testing trap — mandatory**: the two existing closure tests
(`backend/tests/test_pago_service.py:288-336`) patch `generar_siguiente_cuota`
unconditionally and cover only the full-payment happy path. This exact blind spot hid the
item-1 bug. `test_cierre_al_alcanzar_ultima_cuota` asserts the **deleted** behavior and
must be rewritten, not preserved. New tests MUST exercise the real path without mocking
the code under test. The full RED/GREEN matrix is in `design.md` and `tasks.md`.

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Closing a credit with interest still owed | Med | Rule 9 predicate branches on `tipo_credito`; dedicated unit and integration tests |
| Overcharging interest on the final tail installment | Med | Cap at `min(interes_base, saldo_intereses)`; the `max()` floor would otherwise hide the excess |
| Rule-6 filter missed at a read site | Med | Shared SQL predicate applied from the enumerated site table in `design.md`, not inlined per site |
| Blanket backfill closes a credit with a real residual | Med | Selection is the settled predicate in SQL; interest-bearing credits excluded; every closed ID logged |
| Closure is irreversible (no reopen) | High | Explicit confirmation, restricted roles, non-idempotent by design; item 5 stays blocked |
| Rejections read as platform failures | Med | Rule 13: business-reason `detail` written once in the backend, surfaced verbatim by the frontend |
| Frontend regression undetected | Med | `npx tsc --noEmit` + manual QA |

## Rollback

Revert per PR — the stacked seam is designed so PR 1 is independently deployable. `activo`
is data, not schema; credits closed by the backfill can be reverted with a targeted SQL
update against the logged ID list. A follow-up PR deletes the temporary backfill endpoint
per `AGENTS.md`.

## Dependencies

- Owner sign-off captured: Engram `negocio/cierre-creditos-por-saldo` (13 binding rules)
  and `negocio/mensajes-rechazo-cierre-creditos` (rule 13).
- Client notification of the three behavior changes before deploy.

## Review budget forecast

~630 changed lines total. **400-line budget risk: High. Chained PRs recommended: Yes.
Decision needed before apply: No** — rule 12 fixes the chain strategy as
`stacked-to-main`.

| PR | Target | Lines | Content |
|----|--------|-------|---------|
| 1 | `main` | ~378 | Settled predicate, single writer, `_verificar_cierre_credito` deletion, interest-only tail, `es_ultimo_pago`, backend tests |
| 2 | PR 1's branch | ~260 | Read filters, pending-closure signal, confirmation endpoint, backfill, frontend, rejection copy |

Both slices stay under 400 individually. If RED tests push PR 1 over, the fallback split
is in `tasks.md`.

## Success Criteria

- [ ] No credit closes because of installment count.
- [ ] No closure path writes `saldo_capital` or `saldo_intereses`.
- [ ] A `cuota_fija` credit with capital at zero and interest outstanding stays open and
      keeps generating capped interest-only installments until interest reaches zero.
- [ ] Admin capital edit never changes `activo`; it reports pending closure.
- [ ] Settled-but-unconfirmed credits disappear from the portfolio total and the
      collection list (real and virtual rows).
- [ ] Confirming closure on an already-closed credit is rejected with an explanatory
      error, not a silent success.
- [ ] Every rejection this change touches states its business reason in Spanish and the
      frontend renders it verbatim.
- [ ] Backfill closes all settled production credits with `activo = True`, leaves
      interest-bearing credits open, and reports zero corrections on a second run.
- [ ] Backend suite green; new tests exercise real paths without mocking the code under
      test. Frontend `npx tsc --noEmit` clean.
