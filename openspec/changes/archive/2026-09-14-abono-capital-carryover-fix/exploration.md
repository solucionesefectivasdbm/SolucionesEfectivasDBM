# Exploration: abono-capital-carryover-fix

Materialized from Engram `sdd/abono-capital-carryover-fix/explore` (#961) to
complete the hybrid artifact contract. Findings code-verified against `main`
@ `b46505f` (current production).

## Current State

Confirmed by direct code read (`backend/app/services/credito_service.py`,
`backend/app/services/pago_service.py`):

1. **Mensual abono_capital branch** (`_siguiente_cuota_abono_capital`,
   credito_service.py:616-633): `monto_total = interes + abono + saldo_pendiente`,
   but `interes_a_pagar = interes` (base only) and `capital_a_pagar = abono`. So
   `capital_a_pagar + interes_a_pagar != monto_a_pagar` whenever
   `saldo_pendiente > 0`. `PagoService._validar_split` (pago_service.py:96-119)
   caps `interes_pagado <= interes_a_pagar + TOL` in the exact-payment branch ->
   HTTP 422 for any exact payment that includes the arrastre. Same defect shape
   as the pre-fix cuota_fija bug (fixed in 73f8c79).

2. **Alternating (non-monthly) branch, interés successor**
   (credito_service.py:652-668, triggered when
   `cuota_anterior.tipo_cuota != interes`, i.e. previous was abono):
   `monto_total = interes + saldo_pendiente` but `interes_a_pagar = interes`.
   Same 422 defect as case 1.

3. **Alternating branch, abono successor** (credito_service.py:635-651,
   triggered when `cuota_anterior.tipo_cuota == interes`): this branch does not
   reference `saldo_pendiente` at all -- the parameter is silently dropped. This
   is a DIFFERENT and WORSE defect than 1/2: it is not a validation rejection,
   it is silent data loss. Business rule (pago_service.py:252-261) intends
   interest arrastre from a paid `interés` cuota to carry forward; but the very
   next generated cuota after an `interés` cuota is, by alternation, an `abono`
   cuota -- which cannot represent interest at all (`interes_a_pagar` is
   hardcoded `0.00`) and does not forward the pending amount either. So today,
   for quincenal/non-monthly `abono_capital` credits, an interest shortfall
   left after paying an `interés` cuota partially is entirely and irrecoverably
   discarded the moment the next (abono) cuota is generated -- it never reaches
   the following `interés` cuota either, since that generation's
   `cuota_anterior` is the abono cuota, whose own arrastre is always 0 by rule.

4. `desglosar_arrastre` (credito_service.py:156-176) always sends 100% of the
   shortfall to interest only when `cuota_anterior` is None or values are zero
   -- it is otherwise capital-shortfall-first, then interest absorbs the
   residual. That split logic is specific to `cuota_fija` where both capital and
   interest can carry. For `abono_capital`, the business rule is unconditional:
   100% interest, always (capital never carries -- `abono`-type cuotas are
   voluntary per pago_service.py:240-249). Reusing `desglosar_arrastre`
   unmodified would be wrong for case 1 (mensual): the combined cuota has both
   capital and interest components in the same row, so the capital-first logic
   would incorrectly siphon part of the shortfall into capital.

5. `recalcular_cuota_actual_si_no_pagada` abono_capital branch
   (credito_service.py:813-841): rewrites
   `capital_a_pagar`/`interes_a_pagar`/`monto_a_pagar` purely from current base
   values (`interes`, `abono`) with no re-derivation of any pending arrastre --
   mirrors the same class of defect the cuota_fija branch had before task
   4.1/4.2 in the prior change fixed it (credito_service.py:779-809, using
   `desglosar_arrastre` against the previous paid cuota). This function runs
   after every `registrar_pago_no_programado` (pago_service.py:424) and on admin
   credit edits (capital/tasa/abono_minimo), so it currently and silently zeroes
   any pending abono_capital arrastre on the affected credit's current cuota
   every time an admin touches that credit or a receptionist logs an unscheduled
   payment. This is the mechanism behind the observed production workaround:
   paying the cuota without arrastre, then registering the difference as
   `pago no programado`, "works" only because this function then drops the
   arrastre when it re-derives the current cuota's base amounts.

6. `_validar_split`'s message at pago_service.py:105-109 ("Esta cuota es de
   solo interés porque el capital del crédito ya fue saldado") is a
   `cuota_fija`-specific, `capital_a_pagar <= 0` explanation (Rule 13). It fires
   whenever `capital_pagado > capital_a_pagar + TOL` and `capital_a_pagar <= 0`
   -- which is also true for every `abono_capital` INTERÉS-type cuota
   (capital_a_pagar is always 0 there by design, not because capital was
   saldado). If a caller ever tried to overpay capital on an interés-type
   abono_capital cuota, the raised message would be factually wrong for that
   credit type. Pre-existing message-accuracy defect, adjacent to but separate
   from the arrastre bug.

## Affected Areas

- `backend/app/services/credito_service.py:616-633` -- mensual abono_capital
  combined-cuota generation; needs interest-only arrastre folded into
  `interes_a_pagar`.
- `backend/app/services/credito_service.py:652-668` -- alternating branch,
  interés successor; needs the same fix.
- `backend/app/services/credito_service.py:635-651` -- alternating branch,
  abono successor; currently drops `saldo_pendiente` outright -- needs an
  explicit design decision on how a shortfall survives past an intervening
  abono cuota.
- `backend/app/services/credito_service.py:156-176` (`desglosar_arrastre`) --
  not directly reusable for abono_capital as-is; needs either a guard/variant
  that forces 100% interest, or a new small helper (e.g.
  `desglosar_arrastre_abono_capital` or a `tipo_credito`-aware branch).
- `backend/app/services/credito_service.py:813-841`
  (`recalcular_cuota_actual_si_no_pagada`, abono_capital branch) -- needs the
  same "re-derive pending arrastre from previous paid cuota" treatment already
  applied to the cuota_fija branch at lines 779-809.
- `backend/app/routers/pagos.py:509-529` (`_calcular_virtuales`, abono_capital
  projection branch) -- projects base-only amounts with no arrastre, consistent
  with the resolved design for cuota_fija (arrastre lives only on the persisted
  blocking row, never on virtual successors) -- likely NO CHANGE, but must be
  verified once the generator fix lands.
- `backend/app/services/pago_service.py:96-119` (`_validar_split`) -- stays
  unchanged as a guardrail; the fix is to make the caps line up with reality,
  not loosen them. The interés-cuota message at 105-109 is adjacent, minor,
  optional.
- `backend/tests/test_pago_service_arrastre.py`,
  `backend/tests/test_credito_service_arrastre.py` -- both cuota_fija-only;
  need new abono_capital-specific test classes/files covering mensual and
  alternating branches separately.
- `frontend/src/pages/Pagos/PagosPage.tsx:533-534,584-586` -- reads
  `p.capital_a_pagar` / `p.interes_a_pagar` directly from the backend payload;
  no frontend change needed once backend components are correct.
- Prod data -- existing unpaid `abono_capital` cuotas where
  `monto_a_pagar > capital_a_pagar + interes_a_pagar + TOL` need a backfill,
  structurally analogous to the prior one-off admin endpoint
  (`POST /pagos/admin/backfill-arrastre-componentes`, temp addition in
  `backend/app/routers/admin.py`, deleted in a follow-up PR). Rows already
  affected by the case-3 data-loss path or the point-5 write-off path cannot be
  backfilled from `monto_a_pagar`, because `monto_a_pagar` itself is already
  wrong or the money was already collected via a `pago no programado`.

## Approaches

1. **Mirror the cuota_fija pattern with a dedicated abono_capital-aware carry
   helper** -- add a small helper (an abono_capital branch inside
   `desglosar_arrastre` gated by `tipo_credito`, or a separate interest-only
   helper) and wire it into the three generation branches plus the
   `recalcular_cuota_actual_si_no_pagada` abono_capital branch, following the
   re-derivation pattern already proven at lines 779-809.
   - Pros: consistent with the established, shipped pattern; migration-free;
     reuses `Pago`-row re-derivation; minimal new surface; auditable.
   - Cons: must separately resolve the abono-successor data-loss defect (case
     3), which has no cuota_fija analog.
   - Effort: Medium.

2. **Add a persisted `arrastre_pendiente` field on `Credito` (or the blocking
   cuota)** instead of re-deriving from the previous row.
   - Pros: solves case 3 cleanly -- the shortfall survives across an
     intervening abono cuota because it is tracked at credit level.
   - Cons: Alembic migration; contradicts the prior change's rejected approach
     2 for the same audit-trail/migration-risk reasons; higher blast radius;
     likely exceeds the review budget alone.
   - Effort: High.

3. **Fix only cases 1 and 2; defer case 3.**
   - Pros: tightly scoped, smaller diff.
   - Cons: leaves a known silent-data-loss bug for quincenal `abono_capital`
     credits.
   - Effort: Low (scoping decision).

## Recommendation

Approach 1 for cases 1, 2 and the `recalcular_cuota_actual_si_no_pagada` fix,
using an abono_capital-specific 100%-to-interest helper rather than
`desglosar_arrastre` unmodified. Case 3 surfaced as a required owner decision.

Backfill: reuse the prior change's endpoint pattern (temporary admin-only POST,
`audit_service` logging, idempotent guard, deleted after one prod run) scoped to
`tipo_credito == abono_capital`. Rows already written off by case 3 or point 5
cannot be backfilled from `monto_a_pagar`.

## Risks

- Case 3 has no cuota_fija precedent and needs a design decision.
- `recalcular_cuota_actual_si_no_pagada`'s abono_capital branch is what the
  current production workaround depends on; fixing it changes visible behavior
  for collectors using that workaround (desired, but must be flagged).
- Reported pending totals (`reportes.py`) will rise for affected abono_capital
  credits -- intended correctness; abono_capital report path not audited here.
- No existing test coverage for abono_capital arrastre at all; the whole
  surface needs RED tests before any GREEN fix (strict TDD).
- Backfill cannot recover value already silently written off.
- Message-accuracy defect at pago_service.py:105-109 is adjacent, not core.

## Open Questions for Owner

1. Do any quincenal/non-monthly `abono_capital` credits exist in prod?
2. If so: fix case 3 in this change or defer?
3. Confirm backfill scope and mechanism (same temp-endpoint pattern).
4. Confirm the unrecoverable-data note as accepted residual risk vs. manual
   reconciliation.

> Resolution (recorded at propose): all four answered by the owner -- see
> `proposal.md` "Owner decisions". Case 3 is IN SCOPE.

## Ready for Proposal

Yes.
