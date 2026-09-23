# Proposal: Payment Multi-Recipient Split (item 10)

## Intent

Today a `Pago` points to exactly one `cuenta_bancaria_id` — one payment, one recipient. The owner's business rule (engram #1021) requires splitting a single collected payment among multiple recipients: receiver bank accounts and/or clients. When the recipient is a client, no credit should be auto-created (that stays a separate, traditional flow) — the split row is informational/accounting only. Goal: let admins/recaudadores mark and allocate amounts to N destinations per payment, without breaking the existing per-quota financial engine (mora, cierre de crédito, `generar_siguiente_cuota`) or the item 9 receiver ledger.

## Scope

### In Scope
- New `pago_repartos` ledger table (satellite, same pattern as `receptor_movimientos`): `pago_id`, `tipo_destinatario` (`cuenta_bancaria` | `cliente`), `cuenta_bancaria_id`/`cliente_id` (mutually exclusive), `monto`.
- App-layer integrity check: sum of `pago_repartos.monto` for a `Pago` == `capital_pagado + interes_pagado` (tolerance pattern like `_validar_split`'s `TOL`).
- Rewrite `receptor_ledger_service.saldos_por_cuenta` (item 9) to aggregate from `pago_repartos` instead of `Pago.cuenta_bancaria_id` directly — no double counting, no cached totals.
- Replace/extend `PATCH /pagos/{id}/cuenta-bancaria` with a multi-recipient split endpoint; `GET /pagos` filters (`receptor_id`, `cuenta_bancaria_id`) join through `pago_repartos`.
- Alembic migration + historical backfill: one 100%-allocation `pago_repartos` row per already-paid `Pago` with non-null `cuenta_bancaria_id`.
- Explicit rule for `generar_siguiente_cuota` account inheritance when the previous payment had a multi-account split (decision needed — see question round).
- Frontend: extend PagosPage.tsx's existing "Modificar cuenta" modal into a search/select box for multiple recipients (receiver accounts and/or clients) with per-recipient amount entry.
- Client-type split rows never trigger credit creation.

### Out of Scope
- Auto-creating credits for client recipients (stays manual/traditional).
- Changing `_validar_split`'s capital/interest split logic — unrelated concern.
- Retrofitting item 9's receiver ledger UI beyond the aggregation query fix.
- Splitting pending (unpaid) payments retroactively — only paid history gets backfilled.

## Capabilities

### New Capabilities
- `pago-repartos`: multi-recipient split ledger for a payment, covering allocation, integrity validation, and read/filter access.

### Modified Capabilities
- `receptor-ledger` (item 9): `saldos_por_cuenta` aggregation source changes from `Pago.cuenta_bancaria_id` to `pago_repartos`.

## Approach

Satellite ledger table (`pago_repartos`), not N rows of `Pago`. Preserves the "1 Pago = 1 cuota" invariant that mora, `esta_saldado`/`cerrar_credito`, `veces_aplazado`, and reporting all depend on — avoiding the regression risk class seen in PRs #30-#39. Compute-on-read for the ledger, consistent with item 9's no-cache lesson.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `backend/app/models/pago.py` | Modified | New relationship to `pago_repartos`; `cuenta_bancaria_id` kept as legacy/single fallback |
| `backend/app/models/pago_reparto.py` | New | `PagoReparto` model |
| `backend/alembic/versions/` | New | Table creation + historical backfill |
| `backend/app/services/pago_service.py` | Modified | Split write path, integrity check, `generar_siguiente_cuota` inheritance rule |
| `backend/app/services/receptor_ledger_service.py` | Modified | `saldos_por_cuenta` reads from `pago_repartos` |
| `backend/app/routers/pagos.py` | Modified | Split endpoint, filter joins |
| `frontend/src/pages/Pagos/PagosPage.tsx` | Modified | Multi-recipient split box |
| `frontend/src/types/index.ts`, `frontend/src/api/index.ts` | Modified | New types/calls |
| `backend/tests/` | New | Split integrity, ledger aggregation, inheritance rule |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Item 9 ledger regression (double counting/N+1) | Medium | Dedicated aggregation tests mirroring `test_reportes_arrastre.py` |
| `generar_siguiente_cuota` inheritance ambiguity | Medium | Explicit business rule confirmed before design (open question) |
| Split UI has no direct precedent in codebase | Medium | Frontend gets its own reviewed slice |
| >400-line PR budget | High | Chain: (1) model+migration+backfill+ledger rewrite, (2) split endpoint+validation, (3) frontend UI |
| App-layer sum integrity drifting silently | Low | Reuse `_validar_split`'s TOL pattern + dedicated test |

## Rollback Plan

All changes are additive except the `saldos_por_cuenta` query rewrite and the `cuenta-bancaria` endpoint replacement. Each chained PR is revertible independently; migration has a clean `downgrade()` dropping `pago_repartos` only. If the ledger rewrite regresses, revert that PR slice — `Pago.cuenta_bancaria_id` remains untouched as a fallback source.

## Dependencies

- Item 9 (receiver-cash-balance, in prod) — `saldos_por_cuenta` is being rewritten, not replaced from scratch.
- Item 11 (receiver-bank-account-assignment, in prod) — cuenta_bancaria-level assignment already exists and is reused for the receiver side of the split.

## Success Criteria

- [ ] A payment can be split across N recipients (receiver accounts and/or clients) with per-recipient amounts.
- [ ] Split rows sum to the payment's `capital_pagado + interes_pagado` within tolerance, enforced at write time.
- [ ] Client-type split rows never create a credit automatically.
- [ ] `receptor_ledger_service.saldos_por_cuenta` matches pre-change totals for all unsplit historical payments (backfill correctness).
- [ ] `generar_siguiente_cuota` account inheritance behaves per the confirmed rule when the prior payment was split.
- [ ] Each chained PR stays under 400 changed lines.

## Proposal question round

Confirmed by the owner on 2026-09-22:

1. **Next-quota account inheritance**: **no automatic inheritance**. When a payment was split across multiple `cuenta_bancaria` recipients, `generar_siguiente_cuota` does not carry forward any account for the next installment — explicit selection is required.
2. **Split editability**: **directly editable/deletable**. A `pago_repartos` allocation can be edited or deleted in place after the payment is registered — no correction-flow/audit-trail requirement like the receptor ledger's `correccion` pattern. The original (possibly wrong) value is not preserved in history.
3. **Client recipient linkage**: **must link an existing `Cliente`** (search/select) — no free-text recipients.
4. **Filter semantics change**: **confirmed** — `GET /pagos` filtering by `cuenta_bancaria_id`/`receptor_id` becomes "any recipient of this payment includes this account" (join, broader match). This is a deliberate behavior change from today's single-owner filter and must be called out explicitly in the spec.
