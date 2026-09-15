# Judgment Day Ledger — carryover-scope-fixes

Native review lifecycle remained in the known ambiguous state (`select_lineage`, 10 orphan candidates); Judgment Day is the owner-accepted substitute (see zero-balance-explicit-closure precedent).

## Round 1 — PR-A (Bug A: abono_capital interés input guard)

```yaml
target_identity: sha256:5de0bc75d8790c1a64f4aa5a765cd6df1edceb786a445f4aeeb9de7b4d73498f
target_scope:
  - backend/app/routers/pagos.py
  - backend/app/schemas/pago.py
  - backend/app/services/pago_service.py
  - backend/tests/test_pago_service.py
  - backend/tests/test_pagos_listado.py
  - frontend/src/pages/Pagos/PagosPage.tsx
  - frontend/src/types/index.ts
round: 1
judges:
  A: opus — 3 findings (0 severe)
  B: sonnet — 0 findings
confirmed: []
suspect: []
contradictions: []
info:
  - id: PRA-INFO-1
    location: backend/app/services/pago_service.py:132
    severity: SUGGESTION
    claim: `tipo_credito is None` raise duplicates the generic raise below it.
    reported_by: [A]
  - id: PRA-INFO-2
    location: backend/tests/test_pago_service.py:1238
    severity: WARNING
    claim: No test drives the `tipo_credito=` kwarg through `_pago_exacto`/`_pago_parcial`/`confirmar_excedente`; dropping the kwarg would keep the suite green.
    reported_by: [A]
  - id: PRA-INFO-3
    location: frontend/src/pages/Pagos/PagosPage.tsx:694
    severity: SUGGESTION
    claim: Guard predicate inlined twice instead of the `soloInteresCuotaFija` const named in design decision 3.
    reported_by: [A]
fix_work_units: []
scoped_rejudgment: not_run
terminal_state: approved
skill_resolution: paths-injected (AGENTS.md forwarded to both judges; judges reported fallback-path because they load it via Read)
verification: backend 394 passed / 0 failed (`backend/tests`); frontend `npx tsc --noEmit` clean
```

**JUDGMENT: APPROVED ✅** — INFO items are follow-ups, not blockers.

## Round 1 — PR-B (Bug B: cuota_fija past-term carve-out, rule 15)

```yaml
target_identity: sha256:6672ada7343e4a7031fba68e2f20016d74cc4e89a34ba1c0c57678b19756f490
target_scope:
  - backend/app/services/credito_service.py
  - backend/tests/test_credito_service.py
  - backend/tests/test_pago_service.py
branch: fix/cuota-fija-post-plazo-sin-arrastre (rebased on main after PR #36)
round: 1
judges:
  A: opus — 3 findings (0 severe)
  B: sonnet — 0 findings
confirmed: []
suspect: []
contradictions: []
info:
  - id: PRB-INFO-1
    location: backend/tests/test_pago_service.py:503
    severity: SUGGESTION
    claim: Docstring says shortfall 2200; fixture yields 2000. Assertions correct.
  - id: PRB-INFO-2
    location: backend/tests/test_credito_service.py:125-149
    severity: SUGGESTION
    claim: Predicate case `numero_cuotas=None` (design row B) not covered.
  - id: PRB-INFO-3
    location: backend/app/services/credito_service.py:662
    severity: SUGGESTION (product awareness, pre-existing)
    claim: Uncapped past-term row may show es_ultimo_pago=True with monto above the real remaining debt; an exact payment of the displayed amount is absorbed by the max() floor. Spec mandates no cap (owner decision). Operator can register a partial payment for the real remainder.
fix_work_units: []
scoped_rejudgment: not_run
terminal_state: approved
verification: backend 404 passed / 0 failed
```

**JUDGMENT: APPROVED ✅**

## Round 1 — PR-B2 (temporary backfill endpoint)

```yaml
target_identity: sha256:bfa13f9f779bc12d1282aaa5348e95e265a75811e6f590df225bf6f999d97195
target_scope:
  - backend/app/routers/pagos.py
  - backend/tests/test_pagos_backfill_cuota_fija_fuera_de_plazo.py
branch: chore/backfill-cuota-fija-fuera-de-plazo (off main)
round: 1
judges:
  A: opus — 6 findings (0 severe)
  B: sonnet — 1 finding (0 severe)
confirmed: []
suspect: []
contradictions: []
info:
  - id: PRB2-INFO-1
    location: backend/app/routers/pagos.py:1069-1078
    severity: WARNING
    reported_by: [A, B]
    claim: `es_ultimo_pago` is rewritten on apply but not included in the audited `cambios` dict.
  - id: PRB2-INFO-2
    location: backend/app/routers/pagos.py:1051
    severity: WARNING
    reported_by: [A]
    claim: Backfill is only durable once PR-B (rule 15) is deployed; running it before would be undone by recalculation. Rollout order: merge/deploy PR-B, then PR-B2, then run backfill.
  - id: PRB2-INFO-3
    location: backend/tests/test_pagos_backfill_cuota_fija_fuera_de_plazo.py:293-322
    severity: WARNING
    reported_by: [A]
    claim: No test asserts audit rows written on apply / absent on dry-run.
  - id: PRB2-INFO-4
    location: backend/tests/test_pagos_backfill_cuota_fija_fuera_de_plazo.py:366-435
    severity: WARNING
    reported_by: [A]
    claim: No exclusion test for rule-14 tail (saldo_capital <= 0), inactive/soft-deleted credits, nor assertion that credit balances stay unchanged.
  - id: PRB2-INFO-5
    location: backend/app/routers/pagos.py:1035-1037
    severity: SUGGESTION
    claim: Guard `numero_cuotas > 0` in WHERE to avoid DivisionByZero on legacy rows.
  - id: PRB2-INFO-6
    location: backend/app/routers/pagos.py:1011-1023
    severity: SUGGESTION
    claim: No row lock; run in a quiet window (one-off admin endpoint).
fix_work_units: []
scoped_rejudgment: not_run
terminal_state: approved
verification: backend 402 passed / 0 failed
```

**JUDGMENT: APPROVED ✅** — WARNING/SUGGESTION rows stay `info`; PRB2-INFO-2 is a rollout-order constraint, honoured by merging PR-B before running the backfill.
