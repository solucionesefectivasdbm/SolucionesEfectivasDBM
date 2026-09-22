# Verify Report: receiver-bank-account-assignment

## PR1a - feat/cuenta-bancaria-default (Phases 1-5)

Verdict: PASS WITH WARNINGS

Scope: PR1a only (Phases 1-5, tasks 1.1-5.1). PR1b/PR2a/PR2b/PR3/PR4 not started.

### Test Execution Evidence

- Full suite: cd backend && venv/Scripts/python.exe -m pytest -q -> 456 passed, 11 warnings, 0 failed (independently executed, not trusted from apply-progress claim). Matches the claimed 447 baseline + 9 new.
- Focused suite: cd backend && venv/Scripts/python.exe -m pytest tests/test_cuentas_bancarias_predeterminada.py -v -> 9 passed:
  - test_primera_cuenta_es_predeterminada
  - test_segunda_cuenta_no_es_predeterminada
  - test_admin_cambia_predeterminada_sin_mover_asignaciones
  - test_cuenta_de_otro_receptor_rechazada
  - test_no_admin_no_puede_cambiar_predeterminada[registrador]
  - test_no_admin_no_puede_cambiar_predeterminada[gestor]
  - test_no_admin_no_puede_cambiar_predeterminada[recaudador]
  - test_insertar_segunda_predeterminada_viola_indice_unico
  - test_receptor_response_expone_es_predeterminada

### Task Completion (tasks.md, PR1a scope)

All tasks 1.1-5.1 are checked [x] and each has corresponding code:

| Task | Status | Evidence |
|---|---|---|
| 1.1 migration | PASS | c3d4e5f6a7b8_add_cuenta_bancaria_assignment.py present, imports cleanly, down_revision=b2c3d4e5f6a7 confirmed via direct module import |
| 1.2 models/receptor.py | PASS | es_predeterminada column plus __table_args__ partial unique index present |
| 1.3 models/gestor.py | PASS | nullable cuenta_bancaria_id FK plus cuenta_bancaria relationship present |
| 1.4 models/pago.py | PASS | nullable cuenta_bancaria_id FK column only, no relationship added (diff confirmed) |
| 1.5 regression (447) | PASS | reported and reproduced |
| 2.1 schemas | PASS | CuentaBancariaResponse.es_predeterminada, ReceptorMin, CuentaBancariaResumen present exactly as designed |
| 2.2 service skeleton then 4.1-4.3 full impl | PASS | cuenta_bancaria_service.py implements obtener_cuenta_o_404, es_primera_cuenta, marcar_predeterminada, etiqueta_cuenta |
| 3.1-3.9 RED tests | PASS | all 9 present in test_cuentas_bancarias_predeterminada.py, non-trivial, asserting real DB state post-request |
| 4.4 router | PASS | agregar_cuenta auto-default plus PUT /{receptor_id}/cuentas/{cuenta_id}/predeterminada present |
| 4.5 GREEN | PASS | 9/9 pass |
| 5.1 full regression 456 | PASS | independently reproduced |

### Design Decision Compliance

| # | Decision | Result | Evidence |
|---|---|---|---|
| 1 | Partial unique index, postgresql_where and sqlite_where, in both model __table_args__ and migration | PASS | models/receptor.py Index(..., postgresql_where=text("es_predeterminada"), sqlite_where=text("es_predeterminada")); migration op.create_index(..., postgresql_where=sa.text("es_predeterminada"), sqlite_where=sa.text("es_predeterminada")) both present and matching |
| - | down_revision == b2c3d4e5f6a7, downgrade reverses everything | PASS | Confirmed via direct import (down_revision: b2c3d4e5f6a7) and via alembic downgrade c3d4e5f6a7b8:b2c3d4e5f6a7 --sql: drops ix_pagos_cuenta_bancaria_id, fk_pagos_cuenta_bancaria, pagos.cuenta_bancaria_id, fk_gestores_cuenta_bancaria, gestores.cuenta_bancaria_id, the partial index, and es_predeterminada, full symmetric reversal |
| 4 | Pago has no ORM relationship for cuenta_bancaria | PASS | models/pago.py diff adds only the mapped column, no relationship added |
| 2 | Two-statement default flip (Core update, clear-old then set-new, no ORM flush reliance) | PASS | cuenta_bancaria_service.marcar_predeterminada issues two explicit update(CuentaBancaria) Core statements in that exact order before flush and refresh |
| - | Set-default does not rewrite gestor/pago assignments | PASS | marcar_predeterminada touches only CuentaBancaria rows; verified at runtime by test_admin_cambia_predeterminada_sin_mover_asignaciones asserting gestor.cuenta_bancaria_id equals cuenta_a.id and pago.cuenta_bancaria_id equals cuenta_a.id after the switch |
| - | Default endpoint admin-only, 404 for account of another receptor, audit log written | PASS | require_role admin; marcar_predeterminada does a receptor-scoped lookup, returns 404 if not found (tested); audit_service.registrar_actualizacion_campos called with cambios containing es_predeterminada old and new id on entity receptores, signature matches audit_service.py. Note: on the idempotent repeat call, anterior equals nuevo so registrar_actualizacion_campos correctly skips writing a redundant audit row; not directly asserted by a test but consistent with existing audit_service dedup behavior used elsewhere |
| - | First account auto-default, second not | PASS | agregar_cuenta calls es_primera_cuenta and passes the result as es_predeterminada on creation; both scenarios covered by passing tests |

### Endpoint Method Discrepancy (WARNING)

The spec text (spec.md line 22) states PATCH /receptores/{id}/cuentas/{cuenta_id}/predeterminada, but design.md (Interfaces, decision table, migration and rollout table) and tasks.md (task 4.4, work-unit table) all specify PUT, and the implementation uses PUT (router.put), matching design and tasks. This is a genuine spec-vs-design wording mismatch that was not captured in the tasks.md Spec/Design Reconciliation section (which only reconciled the 422 cascading-filter behavior). It does not break any tested behavior, the endpoint works and is fully covered, but the spec document itself is inconsistent with what was built and should be corrected for future readers and PR2+ implementers.

### receptor_id Untouched Outside Scope

Diff and grep of the staged changeset confirms receptor_id was neither renamed nor removed anywhere; Gestor.receptor, Pago.receptor, Receptor.gestores, Receptor.pagos relationships are all still intact (decision 7 removal is explicitly deferred to PR2a, not present in this diff). No unintended rename occurred.

### Migration Import and Offline Check

- Direct exec of the migration module via importlib succeeded; revision, down_revision, upgrade, downgrade all present and correct.
- alembic upgrade head --sql (offline mode, no live DB or DATABASE_URL required) ran cleanly through the full chain, ending at c3d4e5f6a7b8 with the expected DDL (ALTER TABLE cuentas_bancarias ADD COLUMN es_predeterminada, CREATE UNIQUE INDEX uq_cuentas_bancarias_default_por_receptor ON cuentas_bancarias, both FK adds, the pagos index).
- alembic downgrade c3d4e5f6a7b8:b2c3d4e5f6a7 --sql (offline) confirmed full symmetric reversal (see Design Decision table above).

### Assertion Quality Audit (Strict TDD)

All 9 tests in test_cuentas_bancarias_predeterminada.py were read in full:
- No tautologies, no assertion-free tests, no ghost loops.
- Every test calls the real HTTP endpoint (or a direct DB flush for the index test) and asserts DB state via db_session.refresh plus response body values, real behavioral assertions, not smoke tests.
- test_admin_cambia_predeterminada_sin_mover_asignaciones correctly triangulates 3 scenarios (flip, non-movement of gestor/pago, idempotent repeat) merged into one flow per the apply-progress line-budget note, assertions differ per scenario, no loss of coverage.
- test_no_admin_no_puede_cambiar_predeterminada is parametrized over 3 roles, each independently asserted.

Assertion quality: All assertions verify real behavior, 0 CRITICAL, 0 WARNING.

### Spec Scenario Compliance (Default Bank Account requirement, 5 of 5 scenarios)

| Scenario | Test | Result |
|---|---|---|
| First account is default | test_primera_cuenta_es_predeterminada | PASS |
| Second account is not default | test_segunda_cuenta_no_es_predeterminada | PASS |
| Admin changes the default | test_admin_cambia_predeterminada_sin_mover_asignaciones | PASS |
| Default change does not move assignments | test_admin_cambia_predeterminada_sin_mover_asignaciones (same test, merged) | PASS |
| Account of another receptor rejected | test_cuenta_de_otro_receptor_rechazada | PASS |

Role Gates requirement (admin-only, scoped to this PR endpoint): test_no_admin_no_puede_cambiar_predeterminada with registrador, gestor, recaudador - PASS.

### Issues

CRITICAL: None.

WARNING:
1. Spec text says PATCH .../predeterminada; design/tasks/implementation all use PUT. Functionally correct and fully tested, but spec.md wording should be corrected to avoid confusion in later PRs and implementers.

SUGGESTION: None.

### Final Verdict

PASS WITH WARNINGS - PR1a implementation is complete, all 5 Default Bank Account scenarios are covered by passing, non-trivial tests, design decisions 1, 2, 4 (and the related default/audit/role-gate behaviors) are respected exactly, the migration imports cleanly and both upgrade/downgrade offline SQL generation succeed, and receptor_id is untouched outside scope. The only issue is a documentation-level spec/design method-name mismatch (PATCH vs PUT), not a functional defect.

---

### PR1b - feat/cuenta-bancaria-backfill (Phases 6-8)

Verdict: PASS WITH WARNINGS

Scope: PR1b only (Phases 6-8, tasks 6.1-8.1). Diff inspected via git diff --cached (staged, not committed): backend/app/routers/receptores.py (+183/-2), backend/tests/test_backfill_cuentas_bancarias.py (+365, new file), openspec/changes/receiver-bank-account-assignment/tasks.md (+32/-18). PR2a/PR2b/PR3/PR4 not started (confirmed unchecked in tasks.md).

Test Execution Evidence (independently run twice to check for in-memory-DB state leakage, identical results both times):
- Full suite run 1: cd backend and venv/Scripts/python.exe -m pytest -q -> 471 passed, 11 warnings in 3.88s.
- Full suite run 2 (repeat): 471 passed, 11 warnings in 3.27s. No flakiness, no leakage between runs.
- Matches claimed 460 (PR1a-final baseline including Judgment Day round-1 additions) plus 11 new PR1b tests = 471. PASS.
- Focused: pytest tests/test_backfill_cuentas_bancarias.py -v -> 11 passed, 1 warning in 0.34s. All 11 named: test_receptor_sin_cuentas_obtiene_generica_predeterminada, test_receptor_con_cuentas_sin_default_elige_min_id, test_llena_gestor_y_pago_desde_receptor_id, test_llena_solo_huecos_no_sobrescribe, test_pago_no_pagado_sin_receptor_hereda_de_gestor, test_pagos_pagados_y_borrados_se_llenan_igual, test_dry_run_no_escribe_pero_cuenta_igual, test_segunda_corrida_es_idempotente, test_no_admin_no_puede_ejecutar_backfill[registrador|gestor|recaudador].

Task Completion (tasks.md 6.1-8.1): All checked as complete. Each has matching code: 7.1 table()/column() constructs (_t_receptores, _t_cuentas, _t_gestores, _t_pagos, _t_creditos, _t_clientes) present in receptores.py; 7.2 POST /receptores/admin/backfill-cuentas-bancarias implements steps 1-4b; 7.3 response shape matches exactly the dict documented in the code and design.md Interfaces section. PASS.

Spec Scenario Compliance (Backfill Endpoint requirement, 2/2 scenarios):
- Idempotent re-run -> test_segunda_corrida_es_idempotente: real assertion, second POST call returns all-zero counts and zeroed pendientes. PASS.
- Fills only gaps -> test_llena_solo_huecos_no_sobrescribe: gestor pre-set to account B, pago receptor_id defaults to A; asserts gestor keeps B and pago gets A. Non-tautological, checks real DB state via db_session.refresh. PASS.
- Role Gates scenario (backfill admin-only) -> test_no_admin_no_puede_ejecutar_backfill: 403 plus a follow-up SELECT proving zero accounts were created. PASS.
- All 11 tests read in full: no tautologies, no assertion-free tests, no ghost loops, each asserts real DB state post-refresh or response-body counts. 0 CRITICAL, 0 WARNING on assertion quality.

SQL-only implementation audit (item 3): PASS.
- Uses SQLAlchemy Core table()/column() exclusively for gestores/pagos/receptores/cuentas_bancarias reads and writes inside the endpoint, no ORM model classes referenced for any SELECT/INSERT/UPDATE inside the endpoint body. This is a design requirement (decision 8: survive PR2a/PR4 column and relationship removal until the endpoint itself is deleted in PR4) and is met.
- All id and FK columns declared with SA_UUID(as_uuid=True) (aliased from sqlalchemy.UUID), confirmed on every relevant column() declaration across all six table constructs. Matches task 7.1, required for SQLite/aiosqlite parameter binding of Python uuid.UUID values.
- tipo_cuenta bound via Enum(TipoCuenta, name=tipo_cuenta_enum), identical construction to app/models/receptor.py lines 57-58 ORM column. The generic-account insert uses TipoCuenta.ahorros (the enum member), never a plain string literal. PASS, matches design decision 8 rationale (avoiding a wrong string literal).

Backfill semantics audit (item 4): PASS on all sub-checks.
- Generic accounts only for deleted_at IS NULL receptores: step 2 query filters deleted_at.is_(None) before the NOT EXISTS check. Confirmed in code.
- MIN(id) election only when no default exists: step 1 subquery groups by receptor_id having SUM of es_predeterminada cast to integer equal to zero, so receptors with an existing default never enter the candidate set.
- Never overwrites non-null cuenta_bancaria_id: every gestor and pago UPDATE predicate starts with cuenta_bancaria_id.is_(None). Confirmed by test_llena_solo_huecos_no_sobrescribe.
- Step 4b restricted to unpaid, non-deleted pagos with null receptor_id: predicate is pagado equals False, deleted_at is None, cuenta_bancaria_id is None, receptor_id is None, matching the spec step-4b wording exactly. Confirmed by test_pago_no_pagado_sin_receptor_hereda_de_gestor.
- dry_run defaults to true and performs no writes when true: every write statement and the trailing flush are gated behind not dry_run. All count values are computed via a SELECT COUNT against the same predicate used for the conditional write, so dry_run and apply report identical numbers on first run, confirmed at runtime by test_dry_run_no_escribe_pero_cuenta_igual.

Admin gate and route ordering (item 5): PASS.
- require_role(admin) dependency on the endpoint confirmed, enforced at runtime by the three-way parametrized 403 test.
- Route declared at line 119, strictly before the first parametric route at line 264 and every other parametric route through line 406. Confirmed via a full route-decorator scan of the file. No literal-versus-parametric collision risk exists in this case either way, since no other route matches the two-segment shape with a literal second segment other than cuentas, but the code follows the safer stated convention anyway.

Session-commit semantics (item 6): PASS.
- Endpoint uses await db.flush(), never db.commit(), single flush call gated by not dry_run.
- backend/app/database.py get_db (lines 40-53) wraps the yielded session and calls session.commit() after a successful yield, confirming the documented production behavior that FastAPI commits automatically after a successful request. The endpoint flush is deliberately incomplete on its own and relies on get_db post-yield commit in prod. In tests, the overridden get_db yields the test db_session directly with no wrapping commit, so flush is what makes writes visible without leaking a permanent commit into the session-scoped in-memory SQLite engine. This tradeoff is documented in apply-progress observation 1032 and independently confirmed correct here by re-running the full suite twice with identical pass counts.

Audit log (item 7): Backfill endpoint writes NO audit entry. Neither the spec Backfill Endpoint requirement nor the design File Changes or Interfaces sections mention an audit obligation for this endpoint, in contrast with the Default Bank Account and Individual Payment Account Change requirements which explicitly require audit_service calls. This is a genuine omission by design, not a gap introduced by the implementation, no CRITICAL or WARNING raised.

Response schema shape (item 8): The endpoint returns a plain dict, no Pydantic response_model on the route decorator, no dedicated response schema class. The returned shape matches, key for key, the shape documented in design.md Interfaces section and tasks.md 7.3. This is consistent with the design own Interfaces section, which also describes the response as a bare dict rather than a named schema, and is proportionate for a temporary admin endpoint slated for deletion in PR4. SUGGESTION, not WARNING: a typed BackfillResponse Pydantic model would give OpenAPI-doc and static-typing benefits for the endpoint lifetime, but neither spec nor design requires it and the endpoint is explicitly temporary.

Diff-size note: git diff --cached --stat shows 3 files changed, 562 insertions, 18 deletions. Authored code and tests, excluding the openspec tasks.md diff, is approximately 546 lines, exceeding both the PR1b forecast of about 240 and the general 400-line review budget. This was already flagged by sdd-apply in apply-progress observation 1032 as a known, accepted overage: one atomic deliverable, one temporary admin endpoint plus its required nine-scenario test coverage, no safe split available, no size exception requested. Verify confirms the same numbers independently and does not add a new WARNING for it, deferring to the prior acknowledgment, but flags it again here for visibility at the sdd-verify gate.

Issues found:
- SUGGESTION: no typed Pydantic response model for the backfill endpoint (see item 8 above), not required by spec or design and the endpoint is temporary.
- WARNING (carried over from PR1a, still unresolved): spec.md line 22 still says PATCH for the default-account endpoint where design.md, tasks.md, and the implementation correctly use PUT. Not part of PR1b scope but still outstanding in the spec artifact.

Final Verdict: PASS WITH WARNINGS. 0 CRITICAL. 1 WARNING (carried-over spec wording PATCH versus PUT, pre-existing from PR1a, unrelated to PR1b own code). 1 SUGGESTION (untyped dict response for the temporary backfill endpoint). All 8 requested audit items (tasks-to-code, scenario-to-test, SQL-only and UUID and enum typing, backfill semantics, admin gate plus route ordering, flush versus commit split, audit-log expectation, response shape) PASS or are explicitly non-issues by design or spec silence.

#### Addendum 2026-09-20 - Judgment Day round 2 (post-fix) - commit 1ac43c0

The section above reflects the round-1 staged diff. After the round-1 Judgment Day fix, the following supersede it:

- Default election no longer uses MIN(id): `_cuentas_sin_default_elegidas()` ranks with `row_number() OVER (PARTITION BY receptor_id ORDER BY id) = 1` (PostgreSQL has no min/max aggregate for uuid). Guarded by `test_paso1_no_usa_min_sobre_uuid_en_postgresql` (compiles with `postgresql.dialect()`).
- Steps 3/4a/4b share one predicate object between COUNT and UPDATE that includes `<default scalar subquery> IS NOT NULL`; rows whose default cannot be resolved are neither counted nor written and only surface under `pendientes`. Idempotency (second run all counters 0) is asserted by three tests.
- Step 4b chain (pagos -> creditos -> clientes -> gestores) filters `deleted_at IS NULL` on creditos/clientes/gestores.
- `pendientes` keys are now `gestores_sin_cuenta`, `pagos_sin_cuenta_rellenables`, `pagos_sin_cuenta_no_rellenables`.
- spec.md Backfill Endpoint requirement aligned to the real route `POST /receptores/admin/backfill-cuentas-bancarias` and to the lowest-id election.
- Test evidence: focused file 18 passed; full suite 478 passed, 11 warnings (471 + 7 new).
- Both judges: 6/6 ledger rows RESOLVED, VERDICT APPROVE. New info-level observations (single judge each, non-blocking): dry_run reports 0 for steps 3/4a/4b on a fresh database because those steps depend on steps 1/2/3 having been applied (documented in the endpoint docstring); the correlated scalar subquery is evaluated twice per row (WHERE + SET), acceptable for a one-shot admin endpoint.

Final Verdict (PR1b, post-fix): PASS. 0 CRITICAL, 0 WARNING introduced by PR1b. The carried-over spec wording WARNING (PATCH vs PUT, line 22) remains outstanding from PR1a.

---

## PR2a/PR2b/PR3/PR4 + Full-Chain Final Verification (2026-09-21)

Scope: the remaining chain (cutover, cascading filters/reports, frontend, cleanup) plus
the whole change end-to-end, now that all code is merged to main (PRs #44, #45) and
prod is deployed at alembic head d4e5f6a7b8c9. This section supersedes the PR1a/PR1b
sections above only in the sense that it is the final gate before archive; it does not
retract any prior finding.

### Test Execution Evidence (independently run, not trusted from any prior claim)

- Backend: cd backend && venv/Scripts/python.exe -m pytest -q -> 504 passed, 11 warnings, 0 failed.
- Frontend: cd frontend && npx tsc --noEmit -> 0 errors, clean exit.
- No frontend test runner exists in the repo. Phase 17 (manual checklist) is verified by
  adversarial source-code review, not by executed tests. This is a scope limitation, not
  a defect.

### Task Completion

tasks.md: 113/113 checked, 0 unchecked. Cross-checked against actual code:

| Area | Evidence |
|---|---|
| Models clean of deprecated column | grep receptor_id in models/gestor.py and models/pago.py -> no matches |
| Temp backfill endpoint removed | grep backfill-cuentas-bancarias in routers/receptores.py -> no matches |
| Drop migration present | backend/alembic/versions/d4e5f6a7b8c9_drop_receptor_id_from_gestores_pagos.py exists, down_revision c3d4e5f6a7b8 |
| PR2a/PR2b test files present | test_gestores_cuenta_bancaria.py, test_pagos_cuenta_bancaria.py, test_reportes_por_cuenta.py all exist and pass |
| PR2b 422 cascading-filter guard implemented | routers/pagos.py raises HTTPException 422 when cuenta_bancaria_id does not belong to the given receptor_id |
| PATCH rename | routers/pagos.py has PATCH /{pago_id}/cuenta-bancaria; old /receptor path absent |
| Frontend selector component | frontend/src/components/ui/SelectCuentaBancaria.tsx exists |

### Spec Compliance Matrix (9 requirements, 23 scenarios)

| Requirement | Scenarios | Status |
|---|---|---|
| Default Bank Account | 5/5 pytest | PASS (verified PR1a) |
| Gestor Account Assignment and Propagation | 2/2 pytest | PASS |
| Payment Account Inheritance | 3/3 pytest | PASS |
| Individual Payment Account Change | 2/2 pytest | PASS |
| Cascading Filters on Payment Listing | 4/4 pytest | PASS |
| Report Per-Account Sub-Breakdown | 2/2 pytest | PASS |
| Backfill Endpoint | 2/2 pytest | PASS (verified PR1b, post-fix) |
| Role Gates | 1/1 pytest | PASS |
| Account Visible Wherever the Receptor Was | 3/3 manual | PASS by code review only, no automated runner |

### Deviations From the Plan (explicitly flagged, not omitted)

These are real departures from tasks.md's PR4 prerequisites, flagged so they are not
silently absorbed into a PASS verdict.

1. CRITICAL (process, already materialized, irreversible) - OPS-9 skipped. The final
   safety-net backfill re-run before the drop migration was never executed. PR4
   (chore/cuenta-bancaria-cleanup) was deliberately merged ahead of the "clean prod
   week" prerequisite the plan required, per the explicit owner decision recorded in
   tasks.md's own OPERATIONAL NOTE (2026-09-20). Accepted knowingly by the owner, but
   flagged here so it is visible at the verify gate.

2. CRITICAL (data loss, already occurred, irreversible) - OPS-10 skipped and now
   unverifiable. The pre-drop check that pagos and gestores have zero rows with
   cuenta_bancaria_id NULL and receptor_id NOT NULL was never run. Confirmed by direct
   reading of d4e5f6a7b8c9's downgrade(): it repopulates receptor_id only through
   cuentas_bancarias.receptor_id via the surviving cuenta_bancaria_id, so any row with
   cuenta_bancaria_id NULL can never recover its original receptor_id on a downgrade.
   One active, unpaid payment in prod (client be096997, credit dbe114c4, soft-deleted
   client with an active credit -- the same orphan already flagged at OPS-4) is in
   exactly that state; its original receptor_id is permanently lost. The 14 active
   gestores are all recoverable. This narrows, but does not remove, the rollback
   guarantee the proposal originally promised for PR4.

3. WARNING (retrospective, satisfied) - OPS-10a. FK constraint names were not verified
   in prod before the drop ran, but the migration hardcodes gestores_receptor_id_fkey
   and pagos_receptor_id_fkey; post-hoc inspection confirms both names matched and the
   drop succeeded, leaving only cuentas_bancarias_receptor_id_fkey. No outstanding risk.

4. WARNING (data quality, open, owner-managed) - 6 placeholder "Por definir" accounts
   remain in prod from the backfill. The owner already notified the client; completion
   is externally owned. Matches spec's explicit allowance that generic accounts stay
   visible as-is until edited -- not a spec violation.

5. WARNING (test-evidence gap, structural, not a regression) - Phase 17's manual
   checklist has no automated runner. All 3 manual-tagged spec scenarios were verified
   by adversarial source-code review, not by an executed test, because the repo has no
   frontend test runner at all. Per this skill's Hard Rule that a scenario is compliant
   only when a covering test passed at runtime, these 3 scenarios carry a materially
   weaker guarantee than the 20 pytest-tagged scenarios.

6. Carried-over WARNING from PR1a/PR1b (now closed): spec.md's Default Bank Account
   requirement text was corrected during the PR1b Judgment Day round to match the real
   PUT endpoint and the lowest-id election rule. Re-checked now: no remaining mismatch
   between spec, design, tasks and implementation on this point.

### Design Coherence

All 12 architecture decisions in design.md were implemented as specified (relationship
removal, two-statement default flip, no ORM relationship on Pago.cuenta_bancaria_id,
SQL-Core-only backfill, cascading filter with 422 guard, per-account report nesting,
single grouped SelectCuentaBancaria component). No undocumented deviation was found in
the implemented code itself beyond the operational-sequencing deviations in items 1-2
above, which are process/timing deviations, not code-design deviations.

### Final Verdict (whole change)

PASS WITH WARNINGS, with 2 accepted-but-flagged CRITICAL process/data deviations.

- 0 CRITICAL code defects. All 504 backend tests pass; frontend typechecks clean;
  20/20 pytest-tagged scenarios pass at runtime; 3/3 manual scenarios pass by code
  review only.
- 2 CRITICAL deviations from the plan's own safety gates (OPS-9, OPS-10), both already
  executed/irreversible, both owner-accepted, both narrowly scoped to one already-known
  orphan payment -- process findings for the record, not blockers that further code
  changes could prevent now.
- 4 WARNINGs: OPS-10a retrospectively satisfied (no risk), 6 lingering placeholder
  accounts (owner-managed, spec-permitted), manual-checklist evidence gap (structural,
  pre-existing), and the previously-carried spec wording issue (now closed).
- Recommendation: safe to archive. The deviations are historical facts about how PR4
  was sequenced, not defects that further apply work could fix -- reopening sdd-apply
  would not remediate lost receptor_id data or unexecuted prod backfill windows.
  Archive should carry this report forward as the permanent record of the OPS-9/OPS-10
  deviation and the orphan-payment data loss, per explicit instruction not to omit them.
