# Design: abono_capital Carry-over Fix

## Technical Approach

Migration-free, mirroring the shipped `cuota_fija` pattern: the pending
interest shortfall is always derivable from a persisted **paid** row
(`interes_a_pagar - interes_pagado`), never stored. `desglosar_arrastre` and
`_siguiente_cuota_fija` are byte-identical after this change. All money is
`Decimal`, quantized `0.01`, `ROUND_HALF_UP`.

Key fact that makes re-derivation safe: paid rows are immutable.
`desvalidar_pago` (pagos.py:704-713) rejects rows with `pagado` or amounts;
`modificar_fecha_pago`/deferrals touch `fecha_maxima` only; `Pago.deleted_at`
is set only when the whole credit is deleted (creditos.py:530);
`recalcular_cuota_actual_si_no_pagada` only rewrites the unpaid row with zero
paid amounts. No code path un-pays a row.

## Architecture Decisions

| # | Decision | Choice | Rejected | Rationale |
|---|---|---|---|---|
| 1 | Carry helper | New pure `arrastre_interes_abono_capital(cuota_pagada: Pago \| None) -> Decimal` in `credito_service.py`, right after `desglosar_arrastre`. Returns `0.00` for `None` or `tipo_cuota == abono`; else `max(0, interes_a_pagar - interes_pagado)` quantized | `tipo_credito` branch inside `desglosar_arrastre` | Different contract: `desglosar_arrastre` splits a caller-supplied total into a `(cap, int)` pair; here the total itself comes from the row and goes 100% to interest. Separate helper keeps the `cuota_fija` path untouched (owner decision) |
| 2 | Case 3 mechanism | **(a) walk-back, finalized.** In `generar_siguiente_cuota`, when `tipo_credito == abono_capital`, `periodicidad != mensual` and `cuota_anterior.tipo_cuota == abono`: `saldo_pendiente = arrastre_interes_abono_capital(await _ultima_cuota_interes_pagada(db, credito.id, cuota_anterior.numero_cuota))`, overriding the caller value (always `0.00` for abono, pago_service.py:252-253) | (b) persisted column | Sound: see "Double-counting proof". No Alembic, no reversal/deferral sync, ~15 lines. (b) would need explicit zeroing plus wiring into #26/#28 paths and blows the budget alone |
| 3 | Walk-back query | `_ultima_cuota_interes_pagada(db, credito_id, antes_de) -> Pago \| None`: `credito_id ==`, `numero_cuota < antes_de`, `tipo_cuota IN (interes, programada)`, `pagado == True`, `deleted_at IS NULL`, `ORDER BY numero_cuota DESC LIMIT 1` | Copy the cuota_fija query at 782-789 | Single async helper reused by cases 3 and 4. `tipo_cuota IN (interes, programada)` skips abono rows (alternating) and `no_programada` rows in one predicate, so the same query serves mensual and alternating cycles |
| 4 | Generator branches | `_siguiente_cuota_abono_capital` stays sync. Mensual: `interes_a_pagar = interes + saldo_pendiente`, `capital_a_pagar = abono`, `monto = cap + int`. Interés successor: `interes_a_pagar = interes + saldo_pendiente`, `monto = interes_a_pagar`. Abono successor: unchanged, `saldo_pendiente` explicitly ignored (comment) | Make the sync helper async | DB access stays in `generar_siguiente_cuota` (already async, holds `db`); the pure helper remains unit-testable without a session |
| 5 | `_pago_parcial` | Replace lines 258-261 with `saldo_a_arrastrar = arrastre_interes_abono_capital(pago)` (`interes_pagado` is set at 230) | Leave duplicate formula | Net -3 lines, one formula, same semantics |
| 6 | Case 4 recalculation | abono_capital branch: after computing base `interes`/`abono`, `previa = await _ultima_cuota_interes_pagada(db, credito.id, actual.numero_cuota)`; `arr_int = arrastre_interes_abono_capital(previa)`. Mensual: `interes += arr_int`, `monto = abono + interes`. Alternating interés: `interes += arr_int`, `monto = interes`. Alternating abono: unchanged | Skip and keep the workaround alive | Same class as the saldo_capital-reset bug; works for both cycles because decision 3's predicate is cycle-agnostic |
| 7 | `_calcular_virtuales` | **No change** | Project the walk-back shortfall onto virtual interés rows | Same rule as predecessor: a virtual row never invents arrastre; the real row is generated correctly when the blocker is paid. Known display underestimate for a virtual interés row behind an unpaid abono blocker is accepted (non-payable, `es_proyectada`). One companion test asserts base values and `cap + int == monto` |
| 8 | Backfill | Temp `POST /pagos/admin/backfill-arrastre-abono-capital` at the end of `pagos.py` (there is no `routers/admin.py`; proposal path corrected), `require_role("admin")`, `dry_run: bool = True` query param, `# TEMPORAL` banner | Include case-3/4 recovery via walk-back | Owner accepted write-offs as residual risk; recovery would need the walk-back on rows whose `monto` is already base and cannot distinguish "never carried" from "carried then dropped" |
| 9 | Message pago_service.py:105-109 | **Deferred** | Inline guard | `_validar_split` receives only `Pago`; cuota_fija Rule-10 rows and abono_capital interés rows are both `TipoCuota.interes` with `capital_a_pagar = 0`, so no one-line `Pago`-only guard exists. Needs a signature change: out of scope |

## Double-counting proof (option a)

Alternating credit, base interest 20.

| Row | Type | Target int | Paid int | Shortfall | Next row source |
|---|---|---|---|---|---|
| 1 | interes | 20 | 10 | 10 | #2 abono: ignores it |
| 2 | abono | 0 | - | 0 | #3: walk-back -> #1 -> 10 -> target 30 |
| 3 | interes | 30 | 25 | 5 | #4 abono |
| 4 | abono | 0 | - | 0 | #5: walk-back -> #3 -> 30-25 = 5 -> target 25 |

Only the **last** paid interest row is consulted; its target already embeds every
earlier carry, so each step carries exactly what is still unpaid. Two
consecutive partial interés rows chain correctly; an overpaid interest
component clamps to 0; first cuota / no prior row yields 0; reversal, deferral
and soft-delete cannot alter the consulted row (see Technical Approach).

## Data Flow

    _pago_parcial ──saldo_pendiente=arrastre_interes_abono_capital(pago)──┐
    _pago_exacto / confirmar_excedente ──0.00──────────────────────────────┤
                                                                           v
    generar_siguiente_cuota(db, credito, cuota_anterior, receptor, saldo_pendiente)
        └─ abono_capital & alternating & anterior.tipo == abono:
               saldo_pendiente = helper(await _ultima_cuota_interes_pagada(...))
        └─ _siguiente_cuota_abono_capital(...)  # sync, folds into interes_a_pagar

    registrar_pago_no_programado / admin edit
        └─ recalcular_cuota_actual_si_no_pagada
               └─ abono_capital: base + helper(await _ultima_cuota_interes_pagada(...))

## File Changes

| File | Action | Description |
|---|---|---|
| `backend/app/services/credito_service.py` | Modify | `arrastre_interes_abono_capital`, `_ultima_cuota_interes_pagada`, walk-back in `generar_siguiente_cuota`, three branches of `_siguiente_cuota_abono_capital`, abono_capital branch of `recalcular_cuota_actual_si_no_pagada` |
| `backend/app/services/pago_service.py` | Modify | Lines 258-261 call the helper |
| `backend/tests/test_credito_service_arrastre_abono_capital.py` | Create | Pure + `db_session` tests (PR-1) |
| `backend/tests/test_pago_service_arrastre.py` | Modify | Add `TestAbonoCapitalMensualArrastreInteres` (AsyncMock db is safe: mensual never queries) |
| `backend/tests/test_pagos_listado.py` | Modify | One abono_capital projector companion test |
| `backend/app/routers/pagos.py` | Modify (PR-2) then Modify (PR-3) | Temp backfill endpoint added, then deleted |
| `backend/tests/test_pagos_backfill_arrastre_abono_capital.py` | Create (PR-2), Delete (PR-3) | Backfill tests |

## Interfaces / Contracts

```python
def arrastre_interes_abono_capital(cuota_pagada: "Pago | None") -> Decimal: ...
async def _ultima_cuota_interes_pagada(db: AsyncSession, credito_id: uuid.UUID, antes_de: int) -> "Pago | None": ...
```

Backfill predicate (idempotent by construction; after the fix `monto == cap + int`):

```sql
p.deleted_at IS NULL AND p.pagado = false AND p.capital_pagado = 0 AND p.interes_pagado = 0
AND p.tipo_cuota IN ('programada','interes')
AND c.tipo_credito = 'abono_capital' AND c.activo = true AND c.deleted_at IS NULL
AND p.monto_a_pagar > p.capital_a_pagar + p.interes_a_pagar + 0.01
```

Per row: `interes_a_pagar = monto_a_pagar - capital_a_pagar` (no walk-back
needed: 100% goes to interest). `monto_a_pagar`, paid amounts and all
`Credito` saldos never written. Audit via
`audit_service.registrar_actualizacion_campos`. Response
`{dry_run, revisados, corregidos, detalle[]}`. Cannot recover: case-3 rows
(monto already base), case-4 rows (monto rewritten), rows settled through the
`pago no programado` workaround.

## Testing Strategy (strict TDD, `backend/venv/Scripts/python.exe -m pytest`)

| Layer | What | Approach |
|---|---|---|
| Unit | Helper: shortfall, overpaid -> 0, `None` -> 0, abono row -> 0 | Pure Decimal, no DB |
| Unit | `_siguiente_cuota_abono_capital` mensual and interés successor fold `saldo_pendiente` into `interes_a_pagar`; abono successor ignores it; invariant | Direct call, pattern of `_mk_pago_anterior` |
| Integration | Case 3 chain (table above) via `PagoService.registrar_pago`; soft-deleted and `no_programada` rows ignored; no prior interés row -> base | `db_session` (aiosqlite), unmocked |
| Integration | Mensual: partial -> exact base + arrastre accepted (422 regression) | `AsyncMock(spec=AsyncSession)` pattern from `test_pago_service_arrastre.py` |
| Integration | Case 4: mensual and alternating interés preserve arrastre after `registrar_pago_no_programado`; alternating abono and cuota #1 unchanged | `db_session` |
| Integration | Projector: virtual abono_capital rows show base, `cap + int == monto` | Listing endpoint |
| Integration | Backfill: qualifying row corrected; dry-run writes nothing; second run no-op; cuota_fija/abono/paid rows untouched; saldos untouched; non-admin 403 | httpx `AsyncClient` |

Constraint: tests that reach the walk-back (anterior `tipo_cuota == abono`)
must use `db_session`; an `AsyncMock` session returns mocks from `execute`.

## Threat Matrix

N/A: no shell, subprocess, VCS/PR automation, executable-file classification
or process-integration boundary. The new admin route is covered by the RBAC test.

## Migration / Rollout

No schema migration. Three **independent** PRs to `main`, in sequence, each
merged before the next branch is cut (lesson from item 4: no stacked PRs):

1. PR-1 fix + tests (~300 lines). Deploy.
2. PR-2 backfill endpoint + tests (~110). Deploy, dry-run, apply once, verify.
3. PR-3 delete endpoint + test (negative diff).

Before PR-1 deploy: tell collectors to stop the "pay base + pago no programado"
workaround; after the fix that workaround double-charges, because the pending
interest is re-derived from the paid row and the no-programado payment does not
settle it. Rollback: revert the commit; rows generated under the fix stay valid.

## Open Questions

- [ ] None blocking. Observation, out of scope: `_calcular_virtuales` divides
      abono_capital interest by `ppm` (pagos.py:510) while the generator uses
      the full monthly `calcular_interes_periodo`; for alternating credits the
      projection underestimates. Candidate follow-up.
