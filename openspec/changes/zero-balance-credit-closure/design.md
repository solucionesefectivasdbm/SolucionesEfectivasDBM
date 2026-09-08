# Design: Zero-Balance Credit Closure

## Technical Approach

Closure is a single **settled** predicate with **one writer** of `activo = False`,
and that writer never touches `saldo_capital` or `saldo_intereses`. Debt forgiveness
is removed *by construction*, not by a guard. Under rules 9/10 "settled" is
two-dimensional for `cuota_fija` (capital **and** interest), so the installment
generator gains an interest-only tail. Three helpers land in `credito_service.py`
(the established shared-helper home — `pago_service.py` and the routers already import
from it; the reverse would cycle).

**No Alembic revision.** `activo` exists, and the interest-only installment reuses the
existing `TipoCuota.interes` enum value. This is not merely tidy: `tipo_cuota` is a
native PG enum (`Enum(TipoCuota, name="tipo_cuota_enum")`, `models/pago.py:49-51`), so
inventing a new member would require `ALTER TYPE ... ADD VALUE` — a migration the
guardrail forbids. Reuse is mandatory, and it is also semantically exact.

Naming note: the brief says `_pago_completo`; the real function is `_pago_exacto`
(`pago_service.py:162`).

## Canonical closure primitives

```python
# credito_service.py — pure, sync, no db, no await
def esta_saldado(credito: Credito) -> bool:
    """Regla 9: cuota_fija exige capital E interés en cero."""
    if credito.saldo_capital > Decimal("0.00"):
        return False
    if credito.tipo_credito == TipoCredito.cuota_fija:
        return credito.saldo_intereses <= Decimal("0.00")
    return True   # abono_capital: saldo_intereses es invariantemente 0.00 (regla 3)

def cerrar_credito(credito: Credito) -> bool:
    """ÚNICO escritor de activo=False por saldado. NUNCA escribe saldos."""
    if not credito.activo:
        return False
    credito.activo = False
    return True

def credito_operativamente_abierto():          # predicado SQL — regla 6 + regla 9
    return and_(
        Credito.activo == True,
        or_(
            Credito.saldo_capital > 0,
            and_(Credito.tipo_credito == TipoCredito.cuota_fija,
                 Credito.saldo_intereses > 0),
        ),
    )
```

`esta_saldado` branches on `tipo_credito` rather than testing both balances
unconditionally. `recalcular_saldo_intereses:584` already pins `saldo_intereses` to
`0.00` for `abono_capital`, so a naive `and` would behave identically today — but the
explicit branch documents rule 3, cannot regress `abono_capital` if that invariant ever
drifts, and states the intent at the point of decision.

`_verificar_cierre_credito` (`pago_service.py:337-364`) is **deleted**. With the
`numero_cuotas` branch gone its `db` and `cuota_actual` params are unused, so the
replacement is sync and drops three `await`s.

| Call site | Replacement |
|---|---|
| `_pago_exacto:184`, `_pago_parcial:252`, `confirmar_excedente:319` | `if esta_saldado(credito): cerrar_credito(credito)` |
| `registrar_pago_no_programado:419-422` | `if esta_saldado(credito): cerrar_credito(credito); return pago` |
| `creditos.py` PATCH | **no call** — rule 2 |
| confirm endpoint / backfill | `cerrar_credito(credito)` directly |

The unscheduled path keeps its early return **keyed on `esta_saldado`, not on
`cerrar_credito`'s return value**. Using the boolean would change semantics for an
already-inactive credit: it would fall through into `recalcular_saldo_intereses`,
which that path deliberately skips today.

## Rule 10 — the interest-only tail

`generar_siguiente_cuota:415` currently returns `None` at `saldo_capital <= 0`. Rule 10
makes that guard wrong. It becomes:

```python
if esta_saldado(credito):
    return None
```

Generation now stops on the *settled* predicate, not on capital alone. Inside
`_siguiente_cuota_fija`, when `saldo_capital <= 0` and `saldo_intereses > 0`:

```python
interes_base = calcular_interes_cuota_fija(          # CONSTANTE, no depende del saldo
    credito.capital_prestado, credito.tasa_interes_mensual, credito.periodicidad,
)                                                     # = capital_prestado * tasa / ppm
interes_a_pagar = min(interes_base, credito.saldo_intereses)   # TOPE
if interes_a_pagar <= Decimal("0.00"):                # degenerado: tasa o capital = 0
    interes_a_pagar = credito.saldo_intereses         # cobra el remanente de una vez
capital_a_pagar = Decimal("0.00")
monto_a_pagar   = interes_a_pagar
tipo_cuota      = TipoCuota.interes
```

### The cap is required — but not for the stated reason

The coordinator's reading is right that the cap is mandatory, and wrong about the
failure mode. `_aplicar_reduccion_saldos` (`pago_service.py:52-55`) floors
`saldo_intereses` at `0.00` through `max(...)`, so **the balance can never go
negative.** The real hazard of an uncapped final installment is that it **demands more
interest than the client owes** — e.g. `saldo_intereses = 5,000` with
`interes_base = 20,000` bills 20,000, the client pays 20,000, and the 15,000 excess is
silently swallowed by the `max()` floor. Overcharge, not corrupt state. That is worse
than a visible error, and it is the mirror image of the debt-forgiveness bug this
change removes.

Because `calcular_interes_cuota_fija` reads `capital_prestado` (the original principal,
not the running balance — this is the simple-interest model, not French amortization),
`interes_base` is a **constant** for the life of the credit. The cap therefore only ever
binds on the final installment.

**No carryover on interest-only installments** (`saldo_pendiente = 0`), consistent with
rule 5. None is needed: an underpaid interest-only installment leaves `saldo_intereses`
correspondingly higher, and the next installment recomputes
`min(interes_base, saldo_intereses)` from that balance. The balance *is* the ledger, so
the shortfall self-heals with no arrastre bookkeeping.

### Termination proof

Generation is **event-driven, not a loop**: `generar_siguiente_cuota` is called once per
registered payment, so no installment appears without an operator action. Given that:

1. Every interest-only installment charges `d = min(interes_base, saldo_intereses) > 0`.
2. A full payment reduces `saldo_intereses` by exactly `d`, so the tail is at most
   `ceil(saldo_intereses / interes_base)` installments.
3. A partial payment reduces it by `interes_pagado ≥ 0` — monotone non-increasing, and
   strictly decreasing whenever any interest is actually paid.
4. `interes_base == 0` (`tasa = 0` or `capital_prestado = 0`): the degenerate guard bills
   the whole remaining `saldo_intereses` in **one** installment. Terminates in 1.
5. `saldo_intereses < 0` (only reachable by a legacy or direct write — never by
   `_aplicar_reduccion_saldos`): `esta_saldado` tests `<= 0`, so the credit is settled
   and generation returns `None` immediately. No tail.

`saldo_intereses` is monotone non-increasing under every path and is floored at 0, so an
infinite tail is impossible.

### `_validar_split` accepts a zero-capital installment — verified, not assumed

Checked against `pago_service.py:78-120`, and there is a shipping precedent:
`TipoCuota.interes` installments with `capital_a_pagar = Decimal("0.00")` already exist
in production for `abono_capital` non-monthly credits
(`credito_service.py:536-546`). Trace for an interest-only installment paid exactly
(`capital_pagado = 0`, `interes_pagado = monto`): `diferencia = 0 <= TOL` selects the
exact branch; `capital_pagado > capital_a_pagar + TOL` is `0 > 0.01` → False;
`interes_pagado > interes_a_pagar + TOL` is `monto > monto + 0.01` → False. **Accepted.**
The partial branch returns before any component ceiling. No change to `_validar_split`.

**One real 422 risk, same class as the item-1 bug.** If the registrar enters *any*
`capital_pagado > 0.01` on an interest-only installment, the exact branch raises
`ValueError` → 422, because `capital_a_pagar` is 0. That is the *correct* guardrail —
there is no capital to pay — but the UI must not let it happen: the capital input is
locked to 0 when `tipo_cuota === 'interes'`. Required RED test.

## Architecture Decisions

| Decision | Choice | Rejected | Rationale |
|---|---|---|---|
| Settled predicate | `esta_saldado`, branching on `tipo_credito` | unconditional `capital <= 0 and intereses <= 0` | Documents rule 3 at the decision point; cannot regress `abono_capital` if the `saldo_intereses = 0` invariant drifts |
| Interest-only installment type | Reuse `TipoCuota.interes` | new enum member `solo_interes` | `tipo_cuota_enum` is a native PG enum; a new member needs `ALTER TYPE` = migration = guardrail stop. Reuse is also semantically exact and already renders in the frontend |
| Final-installment interest | Capped at `min(interes_base, saldo_intereses)` | uncapped `interes_base` | Uncapped overcharges the client on the last installment; the `max()` floor hides it rather than erroring |
| Interest-only carryover | None (`saldo_pendiente = 0`) | reuse `desglosar_arrastre` | The balance is already the ledger; the cap re-derives the shortfall next period. Arrastre would double-count |
| Rule 6 read predicate | Shared SQL helper `credito_operativamente_abierto()` | (a) inline per read site (b) derived column | (b) needs a migration. (a) is six copies of one rule — the exact drift class behind both `recalcular_*` prod bugs. Mirrors the `desglosar_arrastre` / `_periodos_por_mes` precedent. `hybrid_property` rejected: zero precedent, and AGENTS.md forbids importing new conventions unilaterally |
| `es_ultimo_pago` | `saldo_capital <= capital_a_pagar and saldo_intereses <= interes_a_pagar` | `saldo_capital <= capital_a_pagar`; or `numero >= numero_cuotas` | Display-only flag. The capital-only form would stamp "Última" on an installment followed by the interest-only tail; the count form stamps it on installments 13, 14, 15… forever |
| Confirm on closed credit | **422 rejection** (rule 11) | silent idempotent 200 | Explicit, auditable transitions. Endpoint is deliberately NON-idempotent |
| Backfill | Temporary admin POST in `creditos.py`, removed in a follow-up PR | Alembic data migration | AGENTS.md "Migraciones"; identical to the archived arrastre backfill |

`es_ultimo_pago` unifies both installment shapes in one expression: on an interest-only
installment `saldo_capital = 0 <= 0 = capital_a_pagar` holds trivially, so the flag
reduces to `saldo_intereses <= interes_a_pagar` — true exactly when the cap binds.
Applies at `credito_service.py:458` and `:669`. No frontend change.

## Read sites — enumerated by search, re-confirmed under rule 9

`rg "activo"` over `backend/app`, `Credito` occurrences only. Only the predicate *body*
changed; every site verdict below is unchanged.

| # | Site | Change |
|---|---|---|
| 1 | `creditos.py:101-106` `resumen-cartera` | **Apply** `credito_operativamente_abierto()` |
| 2 | `pagos.py:279` `_calcular_virtuales` | **Apply** |
| 3 | `pagos.py:128-147` real rows of `GET /pagos` | **Apply, unpaid rows only** |
| 4 | `creditos.py:57-58` `?solo_activos=true` | **Keep `activo == True`** — the operator must still find the credit to confirm it |
| 5 | `clientes.py:291` delete-client guard | **Keep** — else a client could be deleted while an unconfirmed credit is formally open |
| 6 | `creditos.py:234`, `:319`, `pagos.py:476` mutation guards | **Keep** — `activo` is still the write authority |
| 7 | `pagos.py:766`, `:796` overdue/upcoming alerts | **Apply** |
| 8 | `reportes.py` | **None** — proven zero `Credito.activo` references |

Rule 9 makes site 1 strictly *more* correct: `resumen-cartera` sums
`saldo_capital + saldo_intereses`, and a capital-settled credit with outstanding
interest now correctly stays in the portfolio contributing that interest, instead of
vanishing while still collectible.

**Finding the brief's list missed (still load-bearing).** `/pagos/diarios` is not a
backend route — the frontend page calls `GET /pagos` (`pagos.py:89`), whose real-row
query (lines 128-147) has **no** `Credito.activo` filter at all; only
`_calcular_virtuales` does. Filtering site 2 alone does not satisfy rule 6. Sites 5 and
7 were likewise absent from the brief.

## `recalcular_*` anti-pattern audit (explicit verdict)

- `recalcular_saldo_intereses` — **not affected.** Not on any closure path; closure now
  writes neither balance. It remains the authority that keeps `saldo_intereses` at
  `0.00` for `abono_capital`, which `esta_saldado` relies on.
- `recalcular_cuota_actual_si_no_pagada` — **affected, and it does bite.** Called at
  `creditos.py:286` right after the admin zeroes the balance, it rewrites the pending
  installment's amounts from scratch. Under rule 10 it must also produce the
  interest-only shape when `saldo_capital <= 0 < saldo_intereses`, or an admin edit would
  silently convert an interest-only installment back into a capital one. **In scope**
  (lines 624-669). Its broader state-loss shape stays out of scope, recorded as a risk.
- `recalcular_cuotas_futuras` — dates only; untouched.

## New endpoints

```
POST /creditos/{credito_id}/cerrar     require_role("admin","recaudador","registrador")
```
Validation order: 404 not found / soft-deleted → **422 `activo == False`** ("el crédito
ya está cerrado", rule 11) → 422 `not esta_saldado(credito)` (message names the
outstanding component: capital or interés) → `cerrar_credito` →
`audit_service.registrar_actualizacion_campos(cambios={"activo": ("True","False")})`.
No body; returns `CreditoResponse`. 422 matches the codebase's existing state-conflict
convention (`"No se puede modificar un crédito cerrado"`, `"Esta cuota ya fue pagada"`).
`gestor` gets 403 from `require_role`. A double click produces one close and one 422 —
never two audit rows.

```
POST /creditos/admin/backfill-cierre-saldo-cero   require_role("admin")   # TEMPORAL
```
Selection: `activo = true AND deleted_at IS NULL AND NOT credito_operativamente_abierto()`
— i.e. the settled predicate in SQL, so an interest-bearing credit is **not** swept.
That predicate is itself the idempotency mechanism: after the run it matches zero rows.
Deliberately bypasses confirmation (rule 8). No explicit commit — `get_db`
(`database.py:40-53`) commits on clean generator exit. One audit entry per credit.
Response `{revisados, cerrados, ids[]}`. The `admin` segment cannot collide with the
UUID route. Follow-up PR deletes endpoint + test.

## Frontend (minimal)

- `types/index.ts`: `pendiente_de_cierre: boolean` on `Credito`.
- `api/index.ts`: `creditosApi.cerrar(id)`.
- `CreditosPage.tsx:296`: third badge state ("Saldado — pendiente de cierre") plus, for
  the three allowed roles, a button opening the existing `ConfirmDialog`.
- `PagosPage.tsx` registration form: **lock `capital_pagado` to 0 and disable the input
  when `tipo_cuota === 'interes'`** — prevents the 422 traced above. This also hardens
  the pre-existing `abono_capital` interest installments, which have the same shape.

Gate: `cd frontend && npx tsc --noEmit`.

## Testing Strategy (Strict TDD — RED first)

The two existing closure tests (`test_pago_service.py:288-336`) patch
`generar_siguiente_cuota` unconditionally — the same blind spot that hid the arrastre
bug. `test_cierre_al_alcanzar_ultima_cuota` asserts the **deleted** behavior and must be
rewritten, not preserved.

| Layer | What | How |
|---|---|---|
| Unit | `esta_saldado`: `cuota_fija` with capital 0 + interest > 0 → **not** settled; `abono_capital` with capital 0 → settled | Pure `Decimal`, no DB |
| Unit | `cerrar_credito` never writes either balance; second call returns `False` | Pure |
| Unit | Interest-only installment: `capital_a_pagar == 0`, `interes_a_pagar == min(base, saldo)`, `tipo_cuota == interes` | Direct `_siguiente_cuota_fija` |
| Unit | Cap binds on the final installment — client is never billed above `saldo_intereses` | Direct call |
| Unit | Degenerate `tasa = 0` with residual interest → one installment for the remainder | Direct call |
| Unit | `es_ultimo_pago` false on an installment followed by the interest-only tail; true only on the settling one | Direct call |
| Integration | Capital settles but interest remains → `activo` stays `True`, an interest-only installment **is** generated | **Unmocked**, aiosqlite |
| Integration | Paying the interest-only tail to zero → `activo` becomes `False`, no further installment | Unmocked |
| Integration | Full payment on the final installment with residual capital → same-value installment, **no carryover** (rule 5) | Unmocked |
| Integration | Under-paid final installment never zeroes `saldo_capital` | Unmocked |
| Integration | Exact payment of an interest-only installment does **not** 422; `capital_pagado > 0` on one **does** | Router call |
| Integration | `registrar_pago_no_programado` settles → closes, early return preserved | Unmocked |
| Integration | Admin PATCH to zero → `activo` stays `True`, `pendiente_de_cierre` true | httpx |
| Integration | `recalcular_cuota_actual_si_no_pagada` keeps the interest-only shape after an admin edit | Unmocked |
| Integration | Settled credit absent from `resumen-cartera` / `GET /pagos` (real **and** virtual); capital-zero-but-interest-bearing credit still **present** | httpx |
| Integration | Confirm: each allowed role 200; `gestor` 403; not settled 422; **already closed 422** (rule 11); audit row written | httpx |
| Integration | Backfill: settled closed, interest-bearing untouched, second run zero, non-admin 403 | httpx |

Command: `cd backend && python -m pytest` (Windows: `backend/venv/Scripts/python.exe -m pytest`).

## Threat Matrix

N/A — no shell, subprocess, VCS/PR automation, or executable-file classification. The
only new boundary is two authenticated HTTP routes, covered by the RBAC RED tests.

## Line forecast vs the 400-line budget

| File | Δ | PR |
|---|---|---|
| `services/credito_service.py` | ~65 | 1 |
| `services/pago_service.py` | ~40 | 1 |
| `backend/tests/*` (closure + interest-only) | ~265 | 1 |
| `routers/creditos.py` (confirm + backfill) | ~85 | 2 |
| `routers/pagos.py` (read filters) | ~10 | 2 |
| `schemas/credito.py` | ~12 | 2 |
| `backend/tests/*` (read paths + endpoints) | ~35 | 2 |
| `frontend/` | ~58 | 2 |
| **Total** | **~570** | |

**400-line budget risk: High. Chained PRs recommended: Yes. Decision needed before
apply: No** — rule 12 already fixes the strategy.

**The seam still holds**, and rules 9/10 did not move it — they only made PR 1 heavier:

- **PR 1 → `main` (~370)** — settled predicate, `_verificar_cierre_credito` deletion,
  four call sites, the interest-only tail, `es_ultimo_pago`, backend tests. Touches no
  read path and no admin path, so it cannot create the rule-6 state. Independently
  deployable; fixes debt forgiveness and rule 9/10 on its own. Rollback = revert.
- **PR 2 → PR 1's branch (~200)** — rule-6 read filters (sites 1, 2, 3, 7),
  `pendiente_de_cierre`, confirm endpoint, backfill, frontend.

Chain strategy `stacked-to-main` per rule 12. PR 1 at ~370 is inside the 400-line budget
but close to it; if RED tests overshoot, the natural third slice is to lift the
interest-only tail (`credito_service.py` + its tests, ~180) into its own PR ahead of the
closure-primitive work, since the tail is a self-contained generator change.

## Migration / Rollout

No schema migration and no new enum member. Merge PR 1 → merge PR 2 → deploy → run the
backfill POST once as admin → verify `resumen-cartera` drops and that capital-settled,
interest-bearing credits remain → follow-up PR deletes the backfill endpoint.

## Open Questions

- [ ] None blocking.
- [ ] Owner note: reopening / payment reversal (quote item 5) stays blocked — no inverse
      of `cerrar_credito` exists, and `cerrar_credito` is now the only writer, which is
      where that primitive would land.
- [ ] Owner note: rule 10 lengthens the collection cycle for `cuota_fija` credits whose
      interest was under-collected. Expect installment counts above `numero_cuotas` and a
      higher collection volume — the same reporting shape as corrective item 1.
