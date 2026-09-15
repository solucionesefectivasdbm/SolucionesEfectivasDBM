# Archive Report: carryover-scope-fixes

**Change**: carryover-scope-fixes (Carry-over scope fixes: Bug A + Bug B)  
**Archived**: 2026-09-14  
**Verdict**: PASS — All specs merged, all tests passing, all tasks complete.

## Summary

Two independent bugs in abono_capital and cuota_fija installment handling have been fixed and shipped to production. Bug A (false capital-saldado message on abono_capital interés installments) is solved by exposing `tipo_credito` on payment payloads and scoping UI locks to cuota_fija tail only. Bug B (shortfall carry-over inflating past-term cuota_fija installments) is solved by a past-term base-installment rule and one-off backfill correction. All four PRs (A, B, B2, C) have merged on main; all 404 backend tests pass; frontend tsc clean; Judgment Day approved all changes across 3 rounds with info-only follow-ups.

## PR Trail

| PR | Title | Scope | Status |
|---|---|---|---|
| #36 | Bug A: abono_capital interés capital-input scoping | `tipo_credito` on payloads, UI guard cuota_fija tail only, message scoping in split validation | MERGED 2026-09-14 |
| #37 | Bug B rule-15: past-term base-installment predicate | New predicate `_es_cuota_fija_fuera_de_plazo`, applied at both `_siguiente_cuota_fija` and `recalcular_cuota_actual_si_no_pagada`, no arrastre carry past term | MERGED 2026-09-14 |
| #38 | Admin backfill: cuota_fija past-term arrastre correction | Endpoint `POST /pagos/admin/backfill-cuota-fija-fuera-de-plazo`, dry-run + apply mode, audit trail, idempotent, to be deleted after one prod run | MERGED 2026-09-14 |
| #39 | Cleanup: remove backfill endpoint | Deleted `POST /pagos/admin/backfill-cuota-fija-fuera-de-plazo` and its test file per requirement | MERGED 2026-09-14 |

## Production Backfill Evidence (2026-09-14)

**Dry-run (before apply)**: Scanned all unpaid `cuota_fija` past-term rows (numero_cuota > numero_cuotas, capital_pagado = interes_pagado = 0, activo, not deleted). Found 1 qualifying row:
- Credit: CR-003 (Fernando Sanabria)
- Cuota: 3 (of 12, past-term)
- Before: capital_a_pagar 12000.00, interes_a_pagar 5200.00, monto_a_pagar 17200.00
- Base: capital_por_cuota 10000.00, base_interes 3600.00, base_monto 13600.00
- Would correct to: capital_a_pagar 10000.00, interes_a_pagar 3600.00, monto_a_pagar 13600.00

**Apply**: Executed backfill on 1 qualifying row. Audited via `audit_service.registrar_actualizacion_campos`. Fernando Sanabria CR-003 cuota 3 components reset to base; monto re-derived; audit recorded.

**Idempotent re-run (after apply)**: Scanned again. Found 0 qualifying rows (the corrected row now has base components = computed base, so no excess to flag). Second dry-run returned empty list.

## Judgment Day Summary

**Rounds**: 3 (PR-A, PR-B, PR-B2)  
**Verdict**: APPROVED across all rounds

### Findings (info-only)

**PR-A findings**:
- PRA-INFO-1: Duplicate raise in `_validar_split` when both capital-saldado guards and abono-capital message checks fire simultaneously. The guards are complementary; no fix needed but noted for next refactor.
- PRA-INFO-2: Missing kwarg-passthrough test for `_validar_split(tipo_credito=None)` → generic component message. Covered by integration tests but could be explicit unit test.
- PRA-INFO-3: Inline guard predicate `tipo_credito == 'cuota_fija' and tipo_cuota == 'interes'` is open-coded in PagosPage.tsx:689-695. Suggests a utility constant or helper; low urgency.

**PR-B findings**:
- PRB-INFO-1: Docstring for `_es_cuota_fija_fuera_de_plazo` uses 2200+ char explanation. Recommended trim to ~2000 for inline readability.
- PRB-INFO-2: Test case `test_credito_service::test_siguiente_cuota_fija_fuera_de_plazo_keeps_base` uses hardcoded `numero_cuotas=12`. Add explicit test for `numero_cuotas=None` edge case (regression protection).
- PRB-INFO-3: Rule 15 base installment is uncapped; uncapped past-term amount can exceed operator's real-world remainder. Operators aware; should use partial payment for real remainder instead of exact. Document in operator runbook.

**PR-B2 findings** (backfill endpoint — now moot per PR #39 deletion):
- PRB2-INFO-1..6: All info-only (no-op, endpoint removal obsoletes all). Related to backfill filtering, audit timing, dry-run response shape; not applicable to current state.

**No CRITICAL or WARNING findings.** All info-level; no blockers.

## Verification Results

**Backend Tests**: 404 tests passed, 0 failed.  
**Frontend Type Check**: `npx tsc --noEmit` clean.  
**Tasks**: All implementation tasks (phases 1–11 in tasks.md) complete and verified. Unchecked boxes (4.2, 11.2, 12.x, 13.x, 14.1) are manual/orchestrator/archive-time steps per reconciliation in verify-report.md.

## Specs Merged

| Spec | Changes | Details |
|---|---|---|
| `openspec/specs/payment-carryover/spec.md` | 1 MODIFIED, 3 ADDED scenarios | Shortfall Disaggregation: added EXCEPTION (rule 15) carve-out + 3 new past-term scenarios. |
| `openspec/specs/credit-closure/spec.md` | 2 ADDED, 2 MODIFIED, 1 ADDED scenario | Added "Past-term Base Installment" (5 scenarios) and "One-off Past-term Arrastre Backfill" (4 scenarios). Modified "Closure by Settled State Only" (added partial-last-installment scenario) and "Operator-Readable Rejection Messages" (added abono_capital scoping scenario). |
| `openspec/specs/abono-capital-carryover/spec.md` | 1 ADDED, 1 MODIFIED | Added "Interés Installment Is Not Capital-Settled" (5 scenarios). Modified "Projection and Frontend Unchanged" (updated UI scoping text). |

## Archive Destination

Change folder moved to: `openspec/changes/archive/2026-09-14-carryover-scope-fixes/`

All artifacts preserved:
- proposal.md (Engram #993)
- specs/ (payment-carryover, credit-closure, abono-capital-carryover delta specs)
- design.md (Engram #995)
- tasks.md (Engram #996, all tasks implemented)
- verify-report.md (Engram #999, PASS verdict)

## Follow-up Items

Carry forward from Judgment Day info findings for post-archive consideration (optional next cycle):

| Item | Context | Suggested Action |
|---|---|---|
| PRA-INFO-1 | Duplicate guard check in `_validar_split` | Next refactor: consolidate capital-saldado checks into unified predicate. |
| PRA-INFO-2 | Missing explicit unit test for `tipo_credito=None` | Add test_validar_split_with_tipo_credito_none to cover fallback generic message. |
| PRA-INFO-3 | Hardcoded UI guard predicate (PagosPage.tsx:689-695) | Extract to named constant (e.g., `IS_CUOTA_FIJA_INTERES_TAIL`) for reusability and clarity. |
| PRB-INFO-1 | Docstring length (~2200 chars) | Trim to ~2000 chars for readability in IDE tooltips. |
| PRB-INFO-2 | Missing `numero_cuotas=None` edge case test | Add regression test: `test_siguiente_cuota_fija_fuera_de_plazo_numero_cuotas_null`. |
| PRB-INFO-3 | Operator awareness: uncapped past-term amount | Add operator runbook note: use partial payment when real remainder < base_installment. |

---

**Engram Artifacts** (observation IDs for traceability):
- Proposal: #993
- Spec: #994
- Design: #995
- Tasks: #996
- Verify Report: #999
- Archive Report: (this artifact, to be persisted as sdd/carryover-scope-fixes/archive-report)
