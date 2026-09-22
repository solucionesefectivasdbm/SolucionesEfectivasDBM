# Archive Report: receiver-bank-account-assignment

**Date**: 2026-09-21  
**Change**: `receiver-bank-account-assignment` (item 11, $360.000 COP)  
**Status**: CLOSED ✓

## Executive Summary

Change `receiver-bank-account-assignment` has been successfully archived. All 113 implementation tasks completed, all 23 spec scenarios verified (20 via pytest, 3 via code review), and fully deployed to production (PRs #44, #45). The spec-defined capability now serves as the authoritative source of truth in the main openspec registry.

## Change Artifacts

| Artifact | Location | Engram ID | Status |
|----------|----------|-----------|--------|
| Proposal | `openspec/changes/archive/2026-09-21-receiver-bank-account-assignment/proposal.md` | #1025 | Archived |
| Specification (delta/full) | `openspec/specs/receiver-bank-account-assignment/spec.md` (new principal) | #1026 | Live in main specs |
| Design | `openspec/changes/archive/2026-09-21-receiver-bank-account-assignment/design.md` | #1027 | Archived |
| Tasks | `openspec/changes/archive/2026-09-21-receiver-bank-account-assignment/tasks.md` | #1029 | Archived (113/113 complete) |
| Verify Report | `openspec/changes/archive/2026-09-21-receiver-bank-account-assignment/verify-report.md` | #1033 | Archived |
| Exploration | `openspec/changes/archive/2026-09-21-receiver-bank-account-assignment/explore.md` | (inline) | Archived |
| Archive Report | `openspec/changes/archive/2026-09-21-receiver-bank-account-assignment/archive-report.md` | (this file) | Archived |

## Spec Merge Summary

**Mode**: openspec (hybrid not needed; only one spec domain per change)

**Action**: Delta spec copied directly to new principal location
- **Source**: `openspec/changes/receiver-bank-account-assignment/specs/receiver-bank-account-assignment/spec.md` (delta)
- **Destination**: `openspec/specs/receiver-bank-account-assignment/spec.md` (new principal, no pre-existing spec to merge)
- **Merge strategy**: Full spec copy (no other spec in this domain to reconcile)

**Content**: 9 requirements, 23 scenarios, all mapped with zero gaps

## Implementation Status

### Delivery Plan Execution

| PR | Branch | Status | Prod Deploy | Lines |
|---|---|---|---|---|
| PR1a | feat/cuenta-bancaria-default | ✓ COMPLETE | PR #44 | ~310 |
| PR1b | feat/cuenta-bancaria-backfill | ✓ COMPLETE | PR #44 | ~240 |
| PR2a | feat/cuenta-bancaria-cutover | ✓ COMPLETE | PR #44 | ~415 |
| PR2b | feat/cuenta-bancaria-filtros-reportes | ✓ COMPLETE | PR #44 | ~275 |
| PR3 | feat/cuenta-bancaria-frontend | ✓ COMPLETE | PR #44 | ~255 |
| PR4 | chore/cuenta-bancaria-cleanup | ✓ COMPLETE | PR #45 | ~280 |

**Total delivered**: ~1,775 lines across 6 PRs, feature-branch chain sequenced to main

**Regression**: 504 backend tests pass, frontend tsc clean

### Requirement Compliance (23/23 scenarios)

| Requirement | Scenarios | Method | Result |
|---|---|---|---|
| Default Bank Account | 5 | pytest | 5/5 PASS |
| Gestor Account Assignment and Propagation | 2 | pytest | 2/2 PASS |
| Payment Account Inheritance | 3 | pytest | 3/3 PASS |
| Individual Payment Account Change | 2 | pytest | 2/2 PASS |
| Cascading Filters on Payment Listing | 4 | pytest | 4/4 PASS |
| Report Per-Account Sub-Breakdown | 2 | pytest | 2/2 PASS |
| Backfill Endpoint | 2 | pytest | 2/2 PASS |
| Role Gates | 1 | pytest | 1/1 PASS |
| Account Visible Wherever the Receptor Was | 3 | code review | 3/3 PASS |

**Note on manual scenarios**: No frontend test runner exists in the repository. Phase 17 (manual checklist) scenarios verified by adversarial source-code review of SelectCuentaBancaria.tsx, filter logic in routers/pagos.py, and report nesting in routers/reportes.py.

## Production Verification

**Deployment history**:
- PR #44 merged, all PRs 1a–3 deployed, alembic at `c3d4e5f6a7b8` (add_cuenta_bancaria_assignment)
- Backfill executed (idempotent, dry-run then apply)
- PR #45 merged, PR4 deployed, alembic at `d4e5f6a7b8c9` (drop_receptor_id_from_gestores_pagos)

**State as of 2026-09-21**:
- ✓ `receptor_id` columns removed from `gestores` and `pagos`
- ✓ `cuenta_bancaria_id` FK columns present with proper indexes
- ✓ 0 FK integrity violations in production database
- ✓ 14 active gestores with assigned accounts (100%)
- ✓ 1 orphan payment flagged (client be096997 soft-deleted, credit active) — see Deviations below
- ⚠ 6 placeholder "Por definir" accounts (owner-managed, spec-permitted)
- ✓ Backfill endpoint removed (404 response confirmed via OpenAPI)

## Deviations from Original Plan (Flagged)

The verify-report identifies two accepted-but-critical process deviations, both already irreversible, both owner-approved:

### 1. OPS-9 Skipped: Pre-drop safety-net backfill not re-run

**What**: The final idempotent backfill run before column drop was not executed. PR4 was merged ahead of the planned clean-prod-week gate.

**Why**: Owner decision to merge PR4 together with PR3 hotfixes (PR #45) without waiting for the prod verification window specified in tasks.md's OPERATIONAL NOTE (2026-09-20).

**Impact**: No rows created between PR2 and PR4 exist in prod, so this safety window was not needed operationally. The decision was deliberate and accepted.

### 2. OPS-10 Skipped: Pre-drop verification unverifiable

**What**: The verification that no rows had `cuenta_bancaria_id IS NULL AND receptor_id IS NOT NULL` was never run. This check is now permanently impossible because `receptor_id` no longer exists.

**Why**: Omitted before the drop; the column was removed as planned.

**Impact**: One concrete consequence: the downgrade migration can only repopulate `receptor_id` through `cuentas_bancarias.receptor_id` via `cuenta_bancaria_id`. Any row with `cuenta_bancaria_id IS NULL` cannot recover its original `receptor_id` on downgrade. One active, unpaid payment is in exactly this state (client be096997 soft-deleted, credit dbe114c4 active, account NULL). Its original `receptor_id` is permanently lost and unrecoverable. The 14 active gestores all have `cuenta_bancaria_id` assigned, so they are fully recoverable.

**Mitigation**: The orphan payment is already flagged, and the client is soft-deleted. The credit is active but the payment is unpaid and has no account. This is a data-integrity edge case that the owner accepted.

### 3. OPS-10a Satisfied Retrospectively

**What**: FK constraint names in prod (gestores_receptor_id_fkey, pagos_receptor_id_fkey) were not pre-verified. The migration hardcodes these names.

**Result**: Post-hoc inspection confirms both names matched correctly. Drop migration succeeded without error. Both FKs now removed, only cuentas_bancarias_receptor_id_fkey remains. No outstanding risk.

### 4. Data Quality Flag: Placeholder Accounts

**What**: 6 placeholder "Por definir" accounts remain in prod from the backfill. These are generic defaults for receptores without real account data.

**Status**: Owner already notified the client; completion is owner-managed and externally owned. Spec explicitly permits generic accounts visible as-is until edited.

### 5. Test Evidence Gap: Manual Checklist

**What**: Phase 17 manual checklist (3 scenarios) has no automated runner. All verified by code review.

**Repo limitation**: The repository has no frontend test runner at all (only tsc typechecking).

**Mitigation**: Scenarios verified by adversarial source-code review of SelectCuentaBancaria.tsx implementation, cascading filter logic, and report-nesting code. Non-trivial assertions made via code reading.

## Review Gate Status

**Artifact count**: 7 total (proposal, spec, design, tasks, verify-report, explore, archive-report)

**All artifact status**:
- Proposal ✓ archived, Engram #1025
- Specification ✓ migrated to live specs registry, Engram #1026
- Design ✓ archived, Engram #1027
- Tasks ✓ archived (113/113 complete), Engram #1029
- Verify Report ✓ archived, Engram #1033
- Exploration ✓ archived (inline)
- Archive Report ✓ created (this file)

**Task Completion Gate**: 113/113 tasks checked [x]. No unchecked implementation tasks. OPS-9 and OPS-10 are explicitly marked as skipped in tasks.md and flagged above.

**Spec Reconciliation**: Design decisions 1–12 all implemented as specified. No unintended deviation beyond the two explicitly marked process deviations.

### Native Dispatcher Gate: NOT OBTAINED

This change was archived **without** the native SDD dispatcher seal, by explicit
maintainer decision after the blocker was reported. `gentle-ai sdd-continue`
reported `archive: blocked` with these two reasons, recorded verbatim:

1. `bound compact post-apply gate context changed`
2. `verify evidence cannot enter remediation: missing valid gentle-ai.verify-result/v1 envelope; bounded review transaction is missing`

**Root cause (verified, not inferred)**: binding a review lineage to an SDD change
requires the repository tree to be byte-identical to the receipt's
`candidate_tree`. Both `sdd-verify` and `sdd-archive` write files, and every write
invalidates the binding. The requirement is therefore circular with the available
tooling. Additionally, the verify phase produced `verify-report.md` as prose but
not the machine-readable `gentle-ai.verify-result/v1` envelope, and no CLI command
emits it (`gentle-ai --help` exposes only `sdd-status` and `sdd-continue`, both
read-only).

**What the missing seal does NOT mean**: the implementation was reviewed. Five
bounded review transactions ran over this work, all four 4R lenses on the
high-risk rounds, with two independent scoped fix validations. Lineage
`review-e0cdf1f84a06aa6a` reached `terminal_state: approved` and passed the
`pre-commit`, `pre-push` and `post-apply` gates with `result: allow`; it was
successfully bound to this change via `gentle-ai review bind-sdd`
(binding revision `sha256:8a063c56c098b39a2963b00454b1d4d1c5679b4e253f957f80a13e81fe35a7ee`).
The binding went stale only because the subsequent documentation commit moved the
tree. The code that shipped is reviewed code; what is missing is the final
bookkeeping stamp, not the review itself.

**Honest reading for a future auditor**: treat this archive as complete in content
and unsealed in process. If the dispatcher is ever able to validate it
retroactively, nothing in the record needs to change.

## Archive Structure

```
openspec/changes/archive/2026-09-21-receiver-bank-account-assignment/
├── proposal.md
├── design.md
├── explore.md
├── tasks.md
├── verify-report.md
├── archive-report.md (this file)
└── specs/
    └── receiver-bank-account-assignment/
        └── spec.md
```

**Active location**: `openspec/specs/receiver-bank-account-assignment/spec.md` (new principal spec, live)

## Next Steps

**None.** Change is complete, fully deployed, and archived. No follow-up SDD phases are pending.

**Dependent work**:
- Item 9 (`receiver-cash-balance`) builds on the account FK and can proceed independently
- Item 10 (multi-destination splits) can build on the per-account structure without reopening this change

## Sign-Off

**Archive closed**: 2026-09-21  
**Artifacts persisted**: Engram (proposal #1025, spec #1026, design #1027, tasks #1029, verify #1033) + Filesystem (archive folder + live spec principal)  
**Traceability**: Complete observation ID chain maintained for post-archive reference

---

**Note to future readers**: This change includes two accepted process deviations (OPS-9, OPS-10) and one consequent data-loss scenario (one orphan payment, irreversible). Both are documented above and in the verify-report. The change is safe to close; reopening sdd-apply would not remediate these historical facts. See verify-report.md for full evidence.
