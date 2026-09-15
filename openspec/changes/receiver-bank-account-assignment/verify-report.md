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
