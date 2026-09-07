# Design: Carry-over Payment Registration

## Technical Approach

Keep the carry-over migration-free and derive its per-component split at generation
time from the already-persisted previous cuota. One pure helper
(`desglosar_arrastre`) becomes the single source of truth and is reused by the
generator, the projector, the credit-edit recalculation, and the backfill. No new
column, no Alembic revision, no frontend change.

All money fields are `Numeric(15, 2)` → `Decimal` (`backend/app/models/pago.py:52-64`).
No float appears anywhere in this design.

## The derivation

Given the previous `cuota_fija` cuota and the `saldo_pendiente` the caller already
computes (`pago_service.py:223-250`):

```python
_Q = Decimal("0.01")

def desglosar_arrastre(
    cuota_anterior: Pago | None, saldo_pendiente: Decimal
) -> tuple[Decimal, Decimal]:
    """Returns (arrastre_capital, arrastre_interes); sums EXACTLY to saldo_pendiente."""
    total = (saldo_pendiente or Decimal("0.00")).quantize(_Q, rounding=ROUND_HALF_UP)
    if cuota_anterior is None or total <= Decimal("0.00"):
        return Decimal("0.00"), Decimal("0.00")
    falta_cap = (cuota_anterior.capital_a_pagar - cuota_anterior.capital_pagado).quantize(
        _Q, rounding=ROUND_HALF_UP
    )
    arr_cap = min(max(falta_cap, Decimal("0.00")), total)   # clamp into [0, total]
    return arr_cap, (total - arr_cap)                        # interest absorbs the residual
```

Interest is the **residual**, never an independent subtraction. That is what makes
the sum reconcile exactly to `saldo_pendiente` (and therefore
`capital_a_pagar + interes_a_pagar == monto_a_pagar`) with zero rounding drift, and
it self-heals legacy rows whose components do not yet sum to `monto_a_pagar`.

### Chained-partial arithmetic (3 steps) — no double counting

Base cuota: capital 100.00 + interest 20.00 = 120.00.

| Step | Cuota (cap / int / monto) | Paid (cap / int) | `faltante` | `falta_cap` | arrastre (cap / int) | Next cuota |
|---|---|---|---|---|---|---|
| 1 | 100 / 20 / 120 | 50 / 10 | 60 | 50 | 50 / 10 | 150 / 30 / **180** |
| 2 | 150 / 30 / 180 | 90 / 10 | 80 | 60 | 60 / 20 | 160 / 40 / **200** |
| 3 | 160 / 40 / 200 | 160 / 40 | 0 | — | 0 / 0 | 100 / 20 / 120 |

`monto` always equals `cuota_base + faltante` (120+60=180, 120+80=200), identical to
today's `monto_total` at `credito_service.py:427`. No double counting: the previous
arrastre already lives *inside* cuota #2's components, and the step-2 shortfall is
measured against those inflated components minus what was paid, so each step only
carries what is still unpaid.

Component-overpay edge (partials allow a free split): cuota 150/30/180 paid 160/0 →
`falta_cap = -10` → clamped to 0 → arrastre 0/20, next cuota 100/40/140 = 120+20. Still exact.

## Architecture Decisions

| Decision | Choice | Rejected alternative | Rationale |
|---|---|---|---|
| Where the split lives | Pure helper `desglosar_arrastre` in `credito_service.py`, public | New `services/arrastre.py` module | `pagos.py` already imports `_periodos_por_mes` from `credito_service`; same-module keeps the diff small and follows the existing import pattern |
| Interest computation | Residual (`total - arr_cap`) | Independent `interes_a_pagar - interes_pagado`, then reconcile | Residual guarantees exact reconciliation by construction; independent subtraction can drift when a component was overpaid |
| `_validar_split` | **Unchanged** (`pago_service.py:99-108`) | Relax caps when the total matches | The ceiling MOVES because the cap reads `pago.capital_a_pagar` / `pago.interes_a_pagar`, which now *include* the arrastre. Ordinary non-arrastre cuotas keep the identical, unweakened guardrail |
| Projector | Reuse `calcular_capital_cuota_fija` / `calcular_interes_cuota_fija` + `desglosar_arrastre` in `_calcular_virtuales` | Copy the formula a third time | Removes the drift source; base math can never diverge from the generator again |
| Backfill | One-off admin-only POST in `pagos.py`, deleted in a follow-up commit | Alembic data migration | AGENTS.md "Migraciones" rule; migration failures are logged but do not abort startup |

## Signature change

```python
# credito_service.py:406 — cuota_anterior added as 2nd positional, mirroring
# _siguiente_cuota_abono_capital (line 444), which already takes it there.
def _siguiente_cuota_fija(
    credito: Credito,
    cuota_anterior: Pago,          # NEW
    numero: int,
    fecha_maxima: date,
    momento: str,
    receptor_id: uuid.UUID | None,
    saldo_pendiente: Decimal,
) -> Pago:
```

Body: `arr_cap, arr_int = desglosar_arrastre(cuota_anterior, saldo_pendiente)`, then
`capital_a_pagar = capital_por_cuota + arr_cap`, `interes_a_pagar = interes + arr_int`,
and `monto_a_pagar = capital_a_pagar + interes_a_pagar` (replacing
`cuota_base + saldo_pendiente` at line 427 — arithmetically identical, but the
invariant is now enforced by construction).

Call sites: the definition (`credito_service.py:406`) and the single dispatch inside
`generar_siguiente_cuota` (`credito_service.py:397-399`), which already holds
`cuota_anterior`. The three `pago_service` callers (lines 187, 255, 322) are
**unchanged** — `generar_siguiente_cuota`'s public signature does not move.
`_siguiente_cuota_abono_capital` (line 444) is **not touched** (decision 3); its
interest-only carry-over rule stays exactly as documented at lines 453-463.

## Rounding / money semantics

- Every intermediate is `Decimal`, quantized `Decimal("0.01")`, `ROUND_HALF_UP` —
  the project-wide convention (AGENTS.md, Python rules).
- `TOL = Decimal("0.01")` in `pago_service.py:29` is unchanged and still absorbs
  one-cent rounding in `_validar_split`.
- Reconciliation invariant, asserted in tests:
  `capital_a_pagar + interes_a_pagar == monto_a_pagar` for every generated
  `cuota_fija` cuota. The residual assignment makes it exact, not tolerance-based.

## Payment-edit path audit (finding)

`recalcular_cuota_actual_si_no_pagada` (`credito_service.py:557-641`, invoked when an
Admin edits capital/tasa/abono) **overwrites** `capital_a_pagar`, `interes_a_pagar`
and `monto_a_pagar` of the current unpaid cuota with base values — it would silently
erase a pending arrastre. This is the same class as the historical
`saldo_capital`-reset-on-edit production bug, so it is fixed here: for `cuota_fija`
it re-derives the arrastre from the immediately previous **paid** cuota
(`saldo_pendiente = max(0, prev.monto_a_pagar - prev.capital_pagado - prev.interes_pagado)`)
through the same helper and re-adds it. Already-registered payments, `Pago.capital_pagado`,
`Pago.interes_pagado` and `Credito.saldo_capital` / `saldo_intereses` are never written
by this change. `recalcular_cuotas_futuras` (line 644) and `modificar_fecha_pago`
(`pagos.py:620`) touch dates only — safe, no change.

## Projector (`_calcular_virtuales`, pagos.py:241-439)

Virtual rows only exist when a blocking unpaid cuota exists (`bloqueador_map`,
lines 328-335). A partially paid cuota is set `pagado=True` and immediately produces a
**real** next row, so a blocker always has `capital_pagado = interes_pagado = 0` and its
own (possibly arrastre-inflated) components are already persisted and displayed.
Consequently the projector must **not** invent an unrealized arrastre: successors are
projected with `saldo_pendiente = Decimal("0.00")`.

The real defect fixed here is the third copy of the base formula at lines 372-379
(`capital_prestado / numero_cuotas`, `capital_prestado * tasa / ppm`). It is replaced by
calls to `calcular_capital_cuota_fija` / `calcular_interes_cuota_fija` plus
`desglosar_arrastre`, so the projector, the generator and the recalculation share one
arithmetic path and `monto = capital_a_pagar + interes_a_pagar` holds in the payload too.

## Backfill endpoint (temporary)

```
POST /pagos/admin/backfill-arrastre-componentes
Depends(require_role("admin"))
```
Declared at the end of `pagos.py` under a `# TEMPORAL — eliminar tras la ejecución`
banner. No collision with `POST /{pago_id}/registrar`: the second segment differs.

Selection predicate (the idempotency mechanism itself):

```sql
p.deleted_at IS NULL AND p.pagado = false
AND c.tipo_credito = 'cuota_fija' AND c.activo = true AND c.deleted_at IS NULL
AND p.monto_a_pagar > p.capital_a_pagar + p.interes_a_pagar
```

After correction `monto_a_pagar = capital_a_pagar + interes_a_pagar`, so a second run
selects zero rows — running twice cannot double-inflate. Per row:
`saldo_pendiente = monto_a_pagar - (capital_a_pagar + interes_a_pagar)`, split via
`desglosar_arrastre` against the immediately previous paid cuota
(`max(numero_cuota) < p.numero_cuota`, `pagado=true`, `deleted_at IS NULL`).
Rows with no previous paid cuota are **skipped and reported**, never guessed.
`monto_a_pagar`, `capital_pagado`, `interes_pagado` and all `Credito` saldos are never
written. Each mutation goes through `audit_service.registrar_actualizacion_campos`
(AGENTS.md). Response: `{revisados, corregidos, omitidos, detalle[]}`.
Follow-up commit deletes the endpoint, its schema and its test.

## File Changes

| File | Action | Description |
|---|---|---|
| `backend/app/services/credito_service.py` | Modify | Add `desglosar_arrastre`; `_siguiente_cuota_fija` signature + component distribution; arrastre-preserving `recalcular_cuota_actual_si_no_pagada` |
| `backend/app/routers/pagos.py` | Modify | `_calcular_virtuales` uses the shared helpers; temporary admin backfill endpoint |
| `backend/tests/test_credito_service_arrastre.py` | Create | Unit + unmocked generation tests |
| `backend/tests/test_pago_service_arrastre.py` | Create | Unmocked chained-partial and guardrail tests |
| `backend/tests/test_pagos_listado.py` | Modify | Projector companion test |
| `backend/app/services/pago_service.py` | Unchanged | Caps and `TOL` stay as the guardrail |
| `frontend/` | Unchanged | Decision 7 |

## Testing Strategy (Strict TDD — RED first)

Root cause of the shipped defect: all 9 payment tests mock
`generar_siguiente_cuota` with `return_value=None`
(`test_pago_service.py:106,125,142,162,179,239,273,308,333`), so arrastre was never
exercised end to end. **Those 9 tests stay as-is** — they isolate split/branch logic and
rewriting them would inflate the diff without adding coverage — and get **unmocked
companions** in the two new files.

| Layer | What to test | Approach |
|---|---|---|
| Unit | `desglosar_arrastre`: both short, capital overpaid → clamp, `total=0`, `cuota_anterior=None` | Pure `Decimal` equality, no DB |
| Unit | `_siguiente_cuota_fija` distributes 100% to the shortfall component; `cap+int == monto` | Direct call, real `Pago` |
| Integration | **Chained 3-step**: partial → partial → exact full arrastre accepted; asserts the table above and final `saldo_capital`/`saldo_intereses` | `PagoService.registrar_pago`, **no mock**, aiosqlite |
| Integration | Regression: exact arrastre-inclusive payment no longer 422 | Real router call |
| Integration | Guardrail: non-arrastre cuota, `capital_pagado > capital_a_pagar` in `exacto` still raises `ValueError` | Unmocked |
| Integration | `abono_capital` mensual + quincenal unchanged (no component inflation) | Unmocked |
| Integration | `recalcular_cuota_actual_si_no_pagada` preserves the arrastre | Unmocked |
| Integration | Projector: virtual successor of an arrastre-carrying blocker shows base, `cap+int == monto` | Listing endpoint |
| Integration | Backfill: corrects a legacy-shaped row; second run is a no-op; no-prior-cuota row skipped; saldos untouched; non-admin → 403 | httpx `AsyncClient` |

Command: `cd backend && python -m pytest` (Windows: `backend/venv/Scripts/python.exe -m pytest`).
Frontend gate: `cd frontend && npx tsc --noEmit` (no code change expected).

## Threat Matrix

N/A — no shell command, subprocess, VCS/PR automation, executable-file classification,
or process-integration boundary. The only new boundary is one authenticated HTTP route,
covered by the `require_role("admin")` RBAC RED test above.

## Migration / Rollout

No schema migration. Deploy → run the backfill POST once as admin → verify affected
credits accept an exact arrastre payment → follow-up commit deletes the endpoint.
Rollback = revert the commit; rows generated while the fix was live keep correct,
payable components.

## Open Questions

- [ ] None blocking. Note for the owner: a partially paid **last** cuota closes the
      credit (`_verificar_cierre_credito`, `pago_service.py:355-360`), so its shortfall
      is dropped rather than carried — pre-existing behavior, owned by corrective item #3.
