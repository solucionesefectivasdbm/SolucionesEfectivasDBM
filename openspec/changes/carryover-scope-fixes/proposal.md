# Proposal: Carry-over scope fixes (Bug A + Bug B)

> Exploration: `exploration.md` / Engram `sdd/carryover-scope-fixes/explore` (#992).
> Owner decisions: rule 15 (#991), diagnosis (#990). Execution mode: auto — owner
> decisions are binding; no open product question remains.

## Intent

Two production reports, same root class: guards written for `cuota_fija` leak into
other situations.

- **Bug A** (Marelvis Mattos, `abono_capital` quincenal, m2 Sept): the "Capital pagado"
  input is disabled and "el capital ya está saldado" is shown on the alternating
  INTEREST half-installment. Capital is not settled; only this half has no capital due.
  Free split on partial payments (`_validar_split`) is blocked — functional regression
  since 47305b5. Backend mirror: `_validar_split` emits the same false message.
- **Bug B** (Fernando Sanabria, `cuota_fija` m4, installment 13-of-12): partial payment of
  the last regular installment carries the shortfall into the past-term successor,
  producing an inflated installment. Contradicts `credit-closure` ("same value, no
  arrastre") and rule 15.

## Business rules (binding)

- **Rule 15**: `cuota_fija`, `numero_cuota > numero_cuotas`, `saldo_capital > 0` → full
  base installment (`capital_por_cuota` + base interest), NO arrastre, NOT capped to the
  remaining balance, repeated until `saldo_capital = 0`; then rule 14 applies.
- Capital-input lock and "capital ya está saldado" apply ONLY to the `cuota_fija`
  interest-only tail. `abono_capital` interés installments keep the input enabled and
  receive a factually correct rejection message when capital is targeted.

## Scope

### In Scope
- Expose `tipo_credito` on `PagoResponse` (list, deferred list, virtual rows).
- `PagosPage.tsx`: scope lock/message to `tipo_credito === 'cuota_fija' && tipo_cuota
  === 'interes'` (covers `/pagos` and `/pagos/diarios`, same component).
- `_validar_split` receives `tipo_credito`; rule-13 message only for `cuota_fija`;
  distinct message for `abono_capital`.
- Past-term carve-out in `_siguiente_cuota_fija` AND
  `recalcular_cuota_actual_si_no_pagada` (both, or paths diverge again).
- Spec amendments: `payment-carryover`, `credit-closure`, `abono-capital-carryover`.
- One-off admin backfill (dry-run + apply, then delete): all unpaid `cuota_fija` rows
  with `numero_cuota > numero_cuotas`, zero paid, components above base → reset to base,
  recompute `monto_a_pagar`, audit via `audit_service`.
- RED→GREEN tests, including the missing PARTIAL-payment sibling of
  `test_ultima_cuota_pagada_con_capital_pendiente_no_cierra`.

### Out of Scope
- New `TipoCuota` member or migrations (credit-closure Non-Goal).
- `_calcular_virtuales` past-term projection (already stops at term).
- Closure rules 9-14, reversal, deferrals, surplus.
- Bug A data backfill (none needed — the lock only blocked valid input).

## Capabilities

### New Capabilities
- None.

### Modified Capabilities
- `payment-carryover`: "Shortfall Disaggregation" gains an exception scenario for
  `cuota_fija` `numero_cuota > numero_cuotas` (no arrastre).
- `credit-closure`: "Closure by Settled State Only" gains a PARTIAL-payment scenario
  beside "Last installment reached with balance outstanding"; recalculation preserves
  the past-term carve-out; new one-off backfill requirement.
- `abono-capital-carryover`: split rejection on an interés cuota names the alternating
  cycle, not settled capital; capital input stays enabled.

## Approach

Exploration Approach 1 (minimal targeted fix). Approach 2 (new enum) rejected: conflicts
with a documented Non-Goal and needs a Postgres enum alter. Approach 3 (frontend
`capital_a_pagar <= 0`) rejected: identical to the buggy predicate.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `backend/app/schemas/pago.py`, `routers/pagos.py` | Modified | `tipo_credito` in row dicts and SELECTs |
| `backend/app/services/pago_service.py:62-135,184,227` | Modified | `_validar_split` message scoping |
| `frontend/src/types/index.ts`, `pages/Pagos/PagosPage.tsx:688-695` | Modified | Field + scoped guard |
| `backend/app/services/credito_service.py:608-654, 879-926` | Modified | Past-term carve-out |
| `backend/app/routers/admin.py` | New, then Removed | Backfill endpoint |
| `openspec/specs/{payment-carryover,credit-closure,abono-capital-carryover}` | Modified | Delta specs |
| `backend/tests/` | New | Partial last-installment, recalculation, split messages, backfill |

## Delivery shape

Two **independent** PRs off `main`, not chained (lesson from #21-#25, #30-#33):
- **PR-A** Bug A (plumbing + guard + message). ~150 lines. Low risk.
- **PR-B** Bug B (carve-out + tests + backfill endpoint). ~300 lines. Medium risk.
- **PR-C** cleanup: delete backfill endpoint after one prod run (pattern #31/#32).

Each is independently revertable. `Chained PRs recommended: No`.

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Carve-out added at one site only | Med | Spec scenario + unit test for both paths |
| Backfill recomputes on wrong base | Med | Use `calcular_*_cuota_fija` on `capital_prestado`; dry-run first |
| Backfill misses/overshoots rows | Low | Predicate scans all credits; idempotent; audited |
| `PagoResponse` consumers break on new field | Low | Additive field; `tsc --noEmit` |
| Pending totals in reports drop for corrected rows | Certain | Intended; note to owner |

## Rollback

Revert each PR alone. No schema change. Backfill touches only unpaid `Pago` components
(audited previous values), never `Credito` balances.

## Dependencies

None.

## Success Criteria

- [ ] `abono_capital` interés cuota: capital input enabled; partial free split accepted.
- [ ] `cuota_fija` interest-only tail: input still locked, message unchanged.
- [ ] Capital targeted on `abono_capital` interés cuota → 422 with cycle-specific message.
- [ ] Partial payment of installment N-of-N → installment N+1 equals base, no arrastre, uncapped.
- [ ] Admin edit on a past-term unpaid cuota keeps base values.
- [ ] Backfill dry-run lists Sanabria's row; apply corrects it; re-run is a no-op.
- [ ] Backend suite green; `npx tsc --noEmit` clean.
