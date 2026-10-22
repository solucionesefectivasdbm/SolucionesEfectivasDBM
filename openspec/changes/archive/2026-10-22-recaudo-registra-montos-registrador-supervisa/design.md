# Design: Recaudo registers amounts, Registrador reverts amounts

## Technical Approach

Approach A (LIFO-guarded). Role gates are one-line `require_role` edits. Revert is `PagoService.revertir_monto` (service mutates, router audits — existing pattern), backed by pure helpers in `credito_service`. No schema change, no migration.

## Architecture Decisions

| # | Topic | Choice | Rejected | Rationale |
|---|-------|--------|----------|-----------|
| D1 | Endpoint | `POST /pagos/{pago_id}/revertir-monto`, body optional `{motivo: str \| null}` (max 500), returns `PagoResponse` | `DELETE /pagos/{id}/monto`; `PATCH` | Mirrors `desvalidar`/`registrar` verb-style; DELETE with body is fragile in axios |
| D2 | Balance recompute | **Schedule-anchored delta**: `new = stored + (R(paid \ {P}) − R(paid))`, where `R(S) = max(0, base − Σ reduccion_efectiva(S))` | Full replay `R(paid \ {P})`; naive inverse `stored + paid amounts` | Floor-aware (nonneg reductions: sequential floor == floor of sum, so exact). Full replay would silently overwrite legacy drift (edit path and `recalcular_saldo_intereses` are excedente-unaware); inverse breaks on floor clipping |
| D3 | Regla 14 interest | On **reopen** (credit `activo=False`), `saldo_intereses = R(paid \ {P})` (full replay, cuota_fija base formula; 0 for abono_capital) | Restore from `audit_log`; anchored delta | Closure zeroed the interest; anchored delta would lose it. No audit dependency |
| D4 | Excedente helpers | New pure `reduccion_efectiva(pago)` mirroring `confirmar_excedente` (destino authoritative: capital → `capital_a_pagar+exc`, intereses → `interes_a_pagar+exc`, else `capital_pagado/interes_pagado`) | Fix `recalcular_saldo_intereses` / edit recompute | Confirmed: existing helpers sum `interes_pagado`/`capital_pagado`, wrong for excedente. Changing them alters edit and no-programado flows — follow-up, out of scope |
| D5 | Restored cuota amounts | Keep N's stored `*_a_pagar`/`es_ultimo_pago` (registration never mutates them); do **not** call `recalcular_cuota_actual_si_no_pagada` for scheduled targets | Re-derive via recompute (spec wording) | Exact round trip; recompute's prior-cuota lookup does not exclude `no_programada` and can drop arrastre. **Spec amendment needed** |
| D6 | `no_programada` target | Soft-delete the pago itself (+repartos), then call `recalcular_cuota_actual_si_no_pagada` (inverse of forward path) | Restore to validated-unpaid | It was never validated; an unpaid `no_programada` row would pollute the schedule. **Spec amendment needed** |
| D7 | Reopen | New `reabrir_credito(credito)` — sole writer of `activo False→True`; called when `activo=False` | Reopen only if `not esta_saldado` | `cerrar_credito` is the only `False` writer and runs only at/after the last payment, so under LIFO any closure is caused by P |
| D8 | Audit | Existing helpers only: `registrar_actualizacion_campos` (pago fields + `motivo_reversion` pseudo-field, credit saldos/activo), `registrar_eliminacion` (successor / no_programada) | New `audit_service` helper | Sufficient; no audit_service change |

## Data Flow

    router: require_role(admin, registrador) → 403 first
      → _get_pago_con_credito(lock=True)        # credit FOR UPDATE + refresh
      → SELECT pagos of credit FOR UPDATE (order numero_cuota, id)
      → guards (422, no writes): pagado; LIFO; successor
      → PagoService.revertir_monto → ResultadoReversion(cambios)
           repartos soft-delete → restore/soft-delete P → soft-delete N+1
           → saldos (D2/D3) → reabrir (D7) → [no_programada: recompute cuota]
      → audit (D8) → PagoResponse

**Guards** (ordered, `logger.warning` like `_rechazar_desvalidar`):
1. `pago.pagado == False` → "no amount to revert" (covers double call).
2. LIFO: exists other paid, non-deleted pago with `(fecha_pago_real, created_at, id)` greater than P's → "revert later payments first". `created_at` works as tiebreak: N+1 is created when N is paid; `no_programada` is created at registration.
3. Successor (scheduled P only): unpaid non-deleted non-`no_programada` cuotas with `numero_cuota > P.numero_cuota`; >1 → inconsistent; any with montos → reject; 0 → skip (settled closure / final).

**Receptor ledger**: no write; reparto soft-delete removes contribution on read; negative balance allowed.

## File Changes (est. changed lines)

| File | Action | Lines |
|------|--------|-------|
| `backend/app/routers/pagos.py` | 3 role gates; `revertir-monto` endpoint + guards + audit | 3 + ~90 |
| `backend/app/services/pago_service.py` | `revertir_monto`, `ResultadoReversion` | ~90 |
| `backend/app/services/credito_service.py` | `reduccion_efectiva`, `saldos_por_cronograma`, `reabrir_credito` | ~60 |
| `backend/app/services/pago_reparto_service.py` | public `soft_delete_repartos_de_pago` wrapper | ~6 |
| `backend/app/schemas/pago.py` | `RevertirMontoRequest` | ~6 |
| `frontend/src/store/authStore.ts` | `canRegistrarPago` + recaudador; `canRevertirMonto` | ~3 |
| `frontend/src/api/index.ts` | `revertirMonto(id, motivo?)` | ~3 |
| `frontend/src/pages/Pagos/PagosPage.tsx` | button (`!es_proyectada && canRevertirMonto && pagado`), confirm modal w/ optional motivo, `handleRevertirMonto` cloned from `handleDesvalidar` | ~110 |
| `backend/tests/test_registro_roles.py` | New: role matrix 3 endpoints | ~110 |
| `backend/tests/test_saldos_cronograma.py` | New: unit tests D2–D4 | ~150 |
| `backend/tests/test_revertir_monto.py` | New: endpoint scenarios | ~300 |

## Interfaces

```python
def reduccion_efectiva(pago: Pago) -> tuple[Decimal, Decimal]: ...
def saldos_por_cronograma(credito: Credito, pagados: list[Pago]) -> tuple[Decimal, Decimal]: ...
def reabrir_credito(credito: Credito) -> bool: ...
async def revertir_monto(db, pago, credito, pagos_credito: list[Pago]) -> ResultadoReversion: ...
```

## Testing Strategy (Strict TDD, RED first)

| Layer | What | Approach |
|-------|------|----------|
| Unit | `reduccion_efectiva` (exacto/parcial/excedente both destinos/no_programada); `saldos_por_cronograma` floor; anchored delta with injected drift | pure pytest, Decimal |
| Integration | role matrices; guards (unpaid, double call, LIFO incl. no_programada, successor with montos); round trips cuota_fija/abono_capital/excedente/floor; settled + regla 14 reopen; repartos soft-deleted + re-register recreates one; ledger decrease/negative; desvalidar after revert; audit + motivo; rejections write no audit | httpx ASGI + SQLite fixtures as `test_desvalidar_pago.py`; round trip = snapshot before registrar → registrar → revert → compare |
| Concurrency | serialization | not provable on SQLite (ignores FOR UPDATE); sequential double-call only |
| Frontend | visibility, toast, refetch | manual checklist |

## Threat Matrix

N/A — no routing, shell, subprocess, VCS/PR automation, executable-file classification, or process-integration boundary (plain authenticated HTTP endpoint).

## Migration / Rollout

No migration. PR1 roles (~120), PR2a helpers + service + unit tests (~310), PR2b endpoint + integration tests (~400, split tests if over), PR3 frontend (~115). Sequential, fresh branches off main.

## Open Questions

- [ ] Confirm spec amendments for D5 (no recompute for scheduled targets) and D6 (no_programada soft-deleted).
- [ ] Backdated `no_programada` (`fecha_pago_real` user-supplied) can sort before a later-registered scheduled payment; accepted per spec ordering?
