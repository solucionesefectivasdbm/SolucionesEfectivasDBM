# Apply Progress: daily-payments-skip-sunday

Full apply history (PR1 Phases 1-4, PR2 Phase 5) is tracked in Engram
`sdd/daily-payments-skip-sunday/apply-progress` (obs #920). This file only
records Phases 6-7, applied after PR1/PR2 merged to main (8d62188).

## Phase 6 — Post-deploy prod audit (2026-09-11)

Ran the read-only audit SQL from design.md against prod (Railway Postgres,
via `DATABASE_PUBLIC_URL`, asyncpg from backend venv — no psql available).

Result: `diario` credits in prod = 1 (inactive), 0 active. Pending daily
cuotas dated Sunday = 0. `POST /creditos/admin/backfill-domingos-diario`
was **not executed** — no candidates, would have returned `revisados: 0`.

Portfolio composition at audit time: mensual 419 activos/318 inactivos,
quincenal 186/290, semanal 15/36, diario 0/1. Found 44 mensual + 17
quincenal pending cuotas dated Sunday — out of scope for this change
(owner rule: only `diario`); flagged as a possible future item.

Full detail: Engram `sdd/daily-payments-skip-sunday/state` (obs #928).

## Phase 7 — Cleanup (this batch, branch chore/remove-backfill-domingos-diario)

Removed the temporary backfill endpoint per AGENTS.md migration convention
(mirrors commit a8a013e from `zero-balance-credit-closure`), since Phase 6
confirmed there was nothing to backfill.

### Files Changed
| File | Action | What |
|------|--------|------|
| backend/app/routers/creditos.py | Modified | Removed `POST /admin/backfill-domingos-diario` (126 lines); removed now-unused imports `TipoCuota` (app.models.pago) and `timedelta` (datetime); kept `es_domingo`, `func`, `audit_service` — still used elsewhere in the file |
| backend/tests/test_backfill_domingos_diario.py | Deleted | Test file for the removed endpoint (360 lines) |
| openspec/changes/daily-payments-skip-sunday/tasks.md | Modified | Marked Phases 6 and 7 tasks `[x]` with prod-audit note (obs #928) |

### Work Unit Evidence
| Evidence | Value |
|---|---|
| Focused test command and result | `backend/venv/Scripts/python.exe -m pytest -q backend/tests` — 305 passed (313 baseline on main − 8 removed backfill-endpoint tests) |
| Runtime harness | N/A — pure deletion of dead code and its test file; no new runtime path introduced |
| Rollback boundary | Revert commit `16fc3c9` (removal); endpoint code remains in git history (PR2 commit `fc120eb`) |

### Commits (branch chore/remove-backfill-domingos-diario, from main@8d62188)
1. `16fc3c9` chore(creditos): eliminar endpoint temporal de backfill domingos diario
2. docs(sdd): cerrar fases 6-7 de daily-payments-skip-sunday (this commit, tasks.md + apply-progress.md)

### Status
All 7 phases complete (tasks.md fully `[x]`). Ready for sdd-verify / PR.
