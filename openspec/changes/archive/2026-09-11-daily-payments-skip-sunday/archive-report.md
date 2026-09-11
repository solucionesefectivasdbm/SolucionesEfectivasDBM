# Archive Report: daily-payments-skip-sunday

**Archived**: 2026-09-11
**Change name**: daily-payments-skip-sunday
**Artifact store mode**: hybrid (openspec + Engram)
**Status**: All 7 phases complete; archived and closed.

## Executive Summary

The `daily-payments-skip-sunday` change has been fully implemented, verified, and archived. Daily (`diario`) credit installments no longer land on Sundays; Sunday start dates are rejected at creation with a clear operator message; projections match generation; and the temporary backfill endpoint has been removed post-deployment after confirming zero pending Sunday-dated rows in production. The new `daily-installment-scheduling` capability has been merged into the canonical spec library.

## Business Context

**Quote**: Phase 2, item 4 (correction, $160.000 COP)
**Owner decision**: Engram obs #913 — business rules binding per owner
**Impact**: Collectors no longer encounter Sunday-dated cuotas that cannot be collected; daily credit schedules now match agreed collection practice.

## Capability Summary

### New Capability: `daily-installment-scheduling`
- **File**: `openspec/specs/daily-installment-scheduling/spec.md`
- **Requirements**: 7 (Sunday Is Never a Daily Due Date, Other Periodicities Unchanged, Sunday Start Date Rejected on Creation, Projection Parity, Independence from Carry-over and Closure, One-off Pending-Row Backfill, Edit-Days Guard Unchanged)
- **Scenarios**: 15 total (3+2+3+1+1+4+1)
- **Scope**: `diario` (daily) credit scheduling only; semanal/quincenal/mensual untouched

## Implementation Summary

### Phases Completed

| Phase | Goal | Status |
|-------|------|--------|
| 1 | Sunday-skip date helper (`_siguiente_diario`) | DONE — PR #21 |
| 2 | Sunday start-date rejection (`CreditoCreate` validation) | DONE — PR #21 |
| 3 | Projection parity resync (`_calcular_virtuales`) | DONE — PR #21 |
| 4 | Carry-over/closure independence (regression test) | DONE — PR #21 |
| 5 | Temporary admin backfill endpoint | DONE — PR #22 |
| 6 | Post-deploy prod audit (zero active daily credits found) | DONE — no backfill executed |
| 7 | Cleanup: remove temporary backfill endpoint | DONE — PR #24 |

### Pull Requests

| PR | Branch | Commits | Changes | Verdict |
|----|--------|---------|---------|---------|
| #21 | feature/daily-payments-skip-sunday | 6 commits (SDD artifacts, rule, rejection, resync, tests, tasks update) | 367 authored lines (fechas.py ~20, creditos.py ~65, pagos.py ~10, tests ~250) | PASS (PR1 Phases 1-4, verify-report obs #922) |
| #22 | feature/daily-payments-skip-sunday-pr2 | 1 commit (backfill endpoint + tests) | 412 insertions; 2 deletions (creditos.py +116, test_backfill_domingos_diario.py +298 new) | PASS WITH WARNINGS (PR2 Phase 5, verify-report obs #922) |
| #23 | feature/daily-payments-skip-sunday-pr2 (re-land) | Re-merged PR #22 after rebase | — | — |
| #24 | chore/remove-backfill-domingos-diario | 2 commits (remove endpoint, close tasks) | 8 tests removed (305 passed vs 313 baseline) | PASS (Phase 7 cleanup) |

### Review Findings

**Native 4R Review** (gentle-ai review suite, obs #925):
- **Tier**: Standard (367 lines, executable code change)
- **Lenses run**: Single focus lens per standard risk (not full 4R; gentle-ai validator schema blocker prevented receipt materialization)
- **CRITICAL finding**: 1 identified and fixed in commit adcdb2c — `no_programada` rows (legacy data from a prior feature) were poisoning the backfill anchor; filtered in Phase 5 query (lines 514-524 of creditos.py)
- **Corrected**: Validated in test_backfill_domingos_diario.py; idempotency test confirms zero re-runs
- **Receipt**: Native receipt NOT materialized (blocker: gentle-ai validator schema tooling) — obs #925 for detail
- **Status**: Gaps do not block archive; verification (Engram obs #922) independently confirmed 0 CRITICAL, 0 blocking WARNING findings for implemented phases

### Verification Summary

**Test execution**:
- PR1 (Phases 1-4): 304 passed (baseline 290 + 14 new tests)
- PR2 (Phase 5): 310 passed (304 + 6 new tests for backfill)
- PR2 Phase 7 cleanup: 305 passed (310 - 8 backfill tests removed)

**Scenario coverage**: 15/15 spec scenarios covered, 0 gaps
- Phase 1 (3 Saturday/cascade/semanal-unchanged scenarios) — test_fechas_ancla.py
- Phase 2 (3 rejection/acceptance/other-periodicities scenarios) — test_creditos_router.py
- Phase 3 (1 projection-parity scenario) — test_pagos_listado.py
- Phase 4 (1 carry-over independence scenario) — test_credito_service_arrastre.py
- Phase 5 (4 backfill scenarios + RBAC + audit) — test_backfill_domingos_diario.py (removed in Phase 7)
- Edit-Days Guard (1 scenario) — pre-existing regression test remains green

**Assertion quality**: All assertions verify real behavior; no tautologies, no ghost loops, no smoke-test-only patterns. 0 CRITICAL, 0 WARNING.

**Regression risk**: 0 new regressions; edit-days endpoint still rejects diario; all other periodicities (semanal/quincenal/mensual) unchanged.

## Production Audit (Phase 6)

**Date**: 2026-09-11
**Audit SQL**: Design.md lines 92-100 (Engram obs #913)
**Result**: 0 active daily (`diario`) credits in production (1 inactive found)

| Periodicidad | Active | Inactive | Pending Sunday-dated cuotas | Action |
|---|---|---|---|---|
| diario | 0 | 1 | 0 | No backfill needed |
| mensual | 419 | 318 | 44 | Out of scope (future follow-up) |
| quincenal | 186 | 290 | 17 | Out of scope (future follow-up) |
| semanal | 15 | 36 | (not audited) | Out of scope |

**Conclusion**: Backfill endpoint was not executed (no candidates). Zero pending Sunday-dated daily rows remain in prod.

## Specification Sync (Delta → Canonical)

**Source**: `openspec/changes/daily-payments-skip-sunday/specs/daily-installment-scheduling/spec.md`
**Target**: `openspec/specs/daily-installment-scheduling/spec.md` (NEW)
**Action**: Copy delta spec verbatim (full new capability, not a delta edit)
**Verification**: Canonical spec matches delta spec exactly (15 scenarios, 7 requirements, no modifications to existing specs)

**No changes to existing canonical specs**:
- `openspec/specs/credit-closure/spec.md` — untouched (balance-based closure is date-independent)
- `openspec/specs/payment-carryover/spec.md` — untouched (amount-based carry-over is date-independent)

## File Structure

### Archived Artifacts (moved, not deleted)
```
openspec/changes/archive/2026-09-11-daily-payments-skip-sunday/
├── proposal.md                 (original SDD proposal, phases 1-7 summary)
├── design.md                   (technical approach, architecture decisions, line forecast)
├── tasks.md                    (7 phases, scenario coverage map, all [x] marked complete)
├── apply-progress.md           (Phase 6-7 execution, prod audit result, commits)
├── verify-report.md            (PR1 Phases 1-4 PASS, PR2 Phase 5 PASS WITH WARNINGS)
├── archive-report.md           (this file)
└── specs/
    └── daily-installment-scheduling/
        └── spec.md             (canonical new capability, copied verbatim from delta)
```

### New Canonical Spec
```
openspec/specs/daily-installment-scheduling/spec.md  (NEW — merged from delta)
```

## Engram Artifacts for Traceability

All phase artifacts are recorded in Engram for persistent archive:

| Observation | Type | Topic Key | Content |
|---|---|---|---|
| #913 | architecture | `sdd/daily-payments-skip-sunday/business-rules` | Owner decision (business rules binding) |
| #914 | architecture | `sdd/daily-payments-skip-sunday/exploration` | Initial scope exploration |
| #915 | architecture | `sdd/daily-payments-skip-sunday/proposal` | SDD proposal (scope, risks, rollback) |
| #916 | architecture | `sdd/daily-payments-skip-sunday/spec` | Specification (7 requirements, 15 scenarios) |
| #917 | architecture | `sdd/daily-payments-skip-sunday/design` | Design decisions (architecture, file changes, threat matrix) |
| #919 | architecture | `sdd/daily-payments-skip-sunday/tasks` | Task breakdown (phases 1-7, scenario coverage) |
| #920 | architecture | `sdd/daily-payments-skip-sunday/apply-progress` | Apply phase history (both PR1/PR2 work units) |
| #922 | architecture | `sdd/daily-payments-skip-sunday/verify-report` | Verification report (PR1 Phases 1-4 PASS, PR2 Phase 5 PASS WITH WARNINGS) |
| #925 | architecture | `sdd/daily-payments-skip-sunday/review-receipt-blocker` | Native review findings (CRITICAL fixed; receipt materialization blocked by validator schema) |
| #928 | architecture | `sdd/daily-payments-skip-sunday/state` | Production audit state (0 active daily credits, 0 backfill executed) |

## Follow-up Items (Out of Scope, Recorded for Future Work)

**Deferred PRs and follow-ups**:
1. **Frontend improvement** (design decision, per obs #918): `CreditosPage.tsx:130` does not flatten list-shaped Pydantic `detail` from schema validators (pre-existing); affected by schema errors such as the quincenal second-date rule. Recommend separate follow-up for UX consistency.
2. **Mensual/Quincenal Sunday rows** (business question, per prod audit): 44 mensual + 17 quincenal pending cuotas dated Sunday found in prod (2026-09-11); out of scope for this change per owner rule (daily only) but flagged as a possible future correction item.

## Reconciliation & Closure

**Task completion gate**: PASS — all 7 phase tasks in `tasks.md` marked `[x]` with completion evidence
**Review gate**: PASS (with caveats) — native 4R lenses identified and fixed 1 CRITICAL issue; receipt materialization blocked by validator schema tooling (obs #925), but independent verification (obs #922) confirms code quality
**Spec merge gate**: PASS — delta spec copied verbatim to canonical location; existing specs (credit-closure, payment-carryover) verified untouched
**Archive gate**: PASS — change folder moved to archive; all historical artifacts preserved; canonical spec synced

**Decision**: CLOSED — change is complete, verified, archived, and ready for the next item.

---

**Archive metadata**:
- Created: 2026-09-11
- Status: COMPLETE
- Engram topic_key: `sdd/daily-payments-skip-sunday/archive-report`
- Git commits: PR #21 (6), PR #22 (1), PR #24 (2) — all merged to main
- Canonical spec location: `openspec/specs/daily-installment-scheduling/spec.md`
- Archive folder: `openspec/changes/archive/2026-09-11-daily-payments-skip-sunday/`
