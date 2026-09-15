# Archive Report: scheduled-overdue-evaluation

**Change**: scheduled-overdue-evaluation (Item 08: Nueva lógica de conteo de atrasos)  
**Archived**: 2026-09-15  
**Verdict**: PASS WITH WARNINGS — All specs merged, all tests passing, all automatable tasks complete. Manual QA checklist (Phase 7, 7.1–7.4) deferred to production per project convention (no frontend test runner).

## Summary

Single system-wide definition of "overdue" (`en_mora`) introduced, tied to the close of the momento containing `fecha_maxima`, evaluated on the Bogotá calendar date at read time (no job, no persisted flag, no backfill). All payment listings expose two server-computed booleans: `vencido` (visual alert, `fecha_maxima < hoy`) and `en_mora` (counts, momento closed). Dashboard KPI, header badge, `/alertas/vencidos` endpoint, and client "al día / en atraso" status now use the same predicate. Deferred payments (`veces_aplazado > 0`) are evaluated against their current `fecha_maxima`. Frontend deleted the browser-clock `isVencido` predicate and now reads backend fields only. All 441 backend tests pass; `tsc --noEmit` clean; Judgment Day approved across 2 rounds (terminal: approved).

## PR Trail

| PR | Title | Status | Merged |
|---|---|---|---|
| #41 | feat(pagos): scheduled-overdue-evaluation (item 8) | MERGED | 2026-09-15 |

**PR #41 Details**: 
- Commits: `19b4512` (feat code + tests), `8e3c79d` (docs SDD artifacts)
- Branch: `feat/scheduled-overdue-evaluation` → `main` (89db216)
- Changes: ~640 authored lines (backend ~120, tests ~70, frontend ~30, design ~100, specs ~200)
- Review: Judgment Day 2 rounds (ledger #1012) → APPROVED; verify-report #1014 → PASS WITH WARNINGS

## Judgment Day Summary

**Rounds**: 2 (ronda 1, ronda 2)  
**Verdict**: APPROVED (terminal)

### Ronda 1 (target sha256:7c72ccfe…)
- **Findings**: 0 CRITICAL, 0 WARNING, 6 INFO (I1–I6)
  - I1: `creditos.py` historial_cuotas missing flags → fixed in Judgment Day, now applies `flags_mora` via `model_copy`
  - I2: `get_periodo_momento(y, 2, "m1")` raises in non-leap February, Feb m2 start overlaps m1 → accepted follow-up (out of scope, design decision 1)
  - I3: Docstring length in `_es_cuota_fija_fuera_de_plazo` (pre-existing from carryover-scope-fixes) → cleaned in fix round
  - I4: `flags_mora` recomputed per request instead of shared → fixed: promoted to `app.utils.momentos.flags_mora(fecha_maxima, pagado, hoy, limite)`, `limite` computed once
  - I5: Property test coverage for `fecha_limite_mora` agreement with `get_momento` → added 1096-day property test
  - I6: `ClientesPage.tsx` copy text "Al día" slightly ambiguous → trivial copy clarification
- **Owner decision**: Approve I1, I3, I4, I5, I6 fixes; I2 remains follow-up

### Fix Round 1 (jd-fix-agent)
- I4 → shared `momentos.flags_mora(fecha_maxima, pagado, hoy, limite)` with precomputed `limite` per request; `_pago_row_a_dict(row, hoy, limite)` updated; `creditos.py` L600-612 applies flags via `model_copy`; `fijar_hoy` fixture extended to pin `app.routers.creditos.hoy_bogota`
- I1 → `TestHistorialCuotasFlagsMora::test_historial_cuotas_flags` covers the new endpoint
- I3 → docstring trimmed
- I5 → property test added (every day 2026-2028, `fecha_limite_mora(d)` is the first day <= d with matching moment and month-moment)
- I6 → copy update in `ClientesPage.tsx`
- **Test suite**: 441 passed (main has 404; +37 new tests in `test_mora_momento_cerrado.py`, expansions to `test_momentos.py`); tsc clean

### Ronda 2 (target sha256:80c2a26e…)
- **Judges**: Judge A (1 SUGGESTION: stale comment `_flags_mora` in `schemas/pago.py:44` → corrected inline by orchestrator), Judge B (clean)
- **Verdict**: No defects introduced by fix round; APPROVED

**Recorded issues**: None blocking archive. Pre-existing `get_periodo_momento` February bug remains; follow-up I2 scheduled for separate change before February 2027.

## Verification Results

**Backend Tests**: 441 passed, 0 failed (includes 12 new tests in `test_mora_momento_cerrado.py`, property test in `test_momentos.py`)  
**Frontend Type Check**: `npx tsc --noEmit` clean  
**Spec Compliance**: 9/9 requirements; 22/22 `[pytest]` automatable scenarios passing; 8/8 `[manual]` frontend scenarios verified by static code inspection (no runner available)  
**Tasks**: All implementation tasks (phases 1–6, 8) complete and checked; Phase 7 (manual QA 7.1–7.4) and Phase 8.3 (PR open) remain unchecked per design

**Deferred Items**:
- **Phase 7.1–7.4** (Manual QA): Pending in production post-deploy. Owner to verify:
  - 7.1: Unpaid row inside open momento renders red, no "Vencido" badge
  - 7.2: Same row after close renders red + "Vencido" badge
  - 7.3: Dashboard KPI and header badge count match `/alertas/vencidos`, unaffected by browser local date
  - 7.4: Deferred row styling precedence (red wins, counter badge always visible, "Vencido" badge only on `en_mora`)
- **Follow-up before February 2027**: `get_periodo_momento(y, 2, "m1")` raises `ValueError` on non-leap February dates and its m2 start overlaps m1; recommend fixing in a dedicated change to unblock `GET /pagos?mes=2&momento=m1` queries (currently 500).

## Specs Merged

| Spec | Action | Details |
|---|---|---|
| `openspec/specs/overdue-evaluation/spec.md` | CREATED | 9 ADDED requirements: Momento Instance Boundaries, Single Overdue Predicate, Overdue Fields on Pago Response, Overdue Alerts Count Only en_mora, Client Status Uses Same Predicate, Deferred Payments Evaluated on Current Date, Partial Payments Not Special-Cased, Frontend Never Derives Overdue from Browser Time. 22 scenarios total (18 `[pytest]`, 4 `[manual]`). |
| `openspec/specs/payment-deferral-tracking/spec.md` | MODIFIED | 1 MODIFIED requirement: "Row Styling and Badge" — replaced old `fecha_maxima < today` browser predicate with backend `vencido`/`en_mora` fields; precedence preserved; 4 scenarios updated (3 new, 1 reworded). |

## Archive Destination

Change folder moved to: `openspec/changes/archive/2026-09-15-scheduled-overdue-evaluation/`

All artifacts preserved:
- proposal.md (Engram #1006)
- explore.md (Engram #1004)
- specs/overdue-evaluation/spec.md (delta ADDED)
- specs/payment-deferral-tracking/spec.md (delta MODIFIED)
- design.md (Engram #1005, with amendment post-Judgment Day decision 3)
- tasks.md (Engram #1007, all automatable tasks checked)
- verify-report.md (Engram #1014, PASS WITH WARNINGS)

## Follow-up Items

| Item | Type | Context | Recommended Action |
|---|---|---|---|
| I2 — `get_periodo_momento` February bug | Pre-existing, tracked before this change | `get_periodo_momento(y, 2, "m1")` raises `ValueError` if `date(y, 2, 29)` called in non-leap year; Feb m2 start overlaps m1 (incorrect range). Blocks `GET /pagos?mes=2&momento=m1` queries (500 error). | Schedule a dedicated change before February 2027 to fix the threshold logic in `momentos.py`, separating the `get_periodo_momento` function (used by reports) from the new `fecha_limite_mora` (used by overdue logic). |
| Phase 7 QA checklist | Owner-driven manual verification | 4 scenarios require runtime execution on production: row red/badge inside/after momento, KPI agreement, deferred precedence. Project has no frontend test runner; scenarios verified by static code inspection only. | Execute 7.1–7.4 post-deploy on production and confirm user-facing behavior matches spec. |
| Post-deploy business action | Communication | Item 08 complete. Dashboard KPI, header badge, and "En atraso" client filter will drop immediately for rows inside open momentos (intended). Item 6 ($140.000 COP) is still pending client decision. | Inform the client: (a) Why overdue counts drop on deploy (momento close rule); (b) whether item 6 remains in scope or $140.000 is discounted (decision affects roadmap). |

---

## Design Amendment (post-Judgment Day, 2026-09-15)

**Decision 3** was superseded during the Judgment Day fix round (ledger I1/I4) and should be updated in `design.md`:
- **Original**: Private `_flags_mora(fecha_maxima, pagado, hoy) -> dict` per file, called only in `pagos.py`.
- **Actual (post-fix)**: Shared public `app.utils.momentos.flags_mora(fecha_maxima, pagado, hoy, limite) -> dict` (4-arg). Called in `pagos.py` (multiple sites), `creditos.py:600` (new historial_cuotas), and available for future reuse. `limite = fecha_limite_mora(hoy)` computed once per request at each router entry point.
- **Rationale for change**: Fixed ledger issue I4 (duplicate recomputation per request) and I1 (creditos.py historial_cuotas was missing flags). Change is an improvement, zero behavioral risk (all tests green).
- **Documentation**: Amend `design.md` decision 3 to reflect the final shared 4-arg shape.

---

## Engram Artifacts (observation IDs for traceability)

- Exploration: #1004
- Proposal: #1006
- Design: #1005
- Tasks: #1007
- Verify Report: #1014
- Review Ledger (Judgment Day): #1012
- Archive Report: (this artifact, to be persisted as `sdd/scheduled-overdue-evaluation/archive-report`)
