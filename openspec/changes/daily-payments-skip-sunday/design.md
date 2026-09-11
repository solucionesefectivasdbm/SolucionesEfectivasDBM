# Design: Daily Payments Skip Sunday

## Technical Approach

One calendar rule in one place. `siguiente_fecha_maxima` (`backend/app/utils/fechas.py:63`)
is the only date-stepping function; its four callers are confirmed by search:
`generar_siguiente_cuota` (`credito_service.py:487`), `recalcular_cuotas_futuras`
(`:871`), the edit-days router (`creditos.py:396`) and the projector (`pagos.py:460`).
Adding a Sunday-aware `_siguiente_diario` helper to the diario branch corrects generation,
recalculation and projection at once. Sunday start dates are rejected at credit creation.
Pending production rows are re-walked by a temporary admin endpoint that reuses
`recalcular_cuotas_futuras`. No Alembic revision, no schema change.

```python
# fechas.py
def es_domingo(fecha: date) -> bool:
    return fecha.weekday() == 6          # Monday=0 .. Sunday=6

def _siguiente_diario(fecha_anterior: date) -> date:
    """Next diario due date: +1 day; Sunday is never a collection day -> Monday."""
    siguiente = fecha_anterior + timedelta(days=1)
    return siguiente + timedelta(days=1) if es_domingo(siguiente) else siguiente

# siguiente_fecha_maxima — diario branch only; semanal keeps +7 verbatim
if p == Periodicidad.diario:
    return _siguiente_diario(fecha_anterior)
return fecha_anterior + timedelta(days=7)   # semanal
```

The step is strictly increasing, so "never two installments on the same day" holds by
construction and `numero_cuota` is untouched (count unchanged, credit ends later).

## Architecture Decisions

| Decision | Choice | Rejected | Rationale |
|---|---|---|---|
| Rule location | `_siguiente_diario` helper wired into the diario branch | inline `+1` then `if weekday==6` | Mirrors `_siguiente_mensual`/`_siguiente_quincenal`; unit-testable; semanal branch stays literally untouched |
| Sunday-start rejection | Router-level `HTTPException(422, detail=<str>)` in `crear_credito` (`creditos.py:159`) before the client lookup, using `es_domingo` | `ValueError` in `CreditoCreate.validar_reglas_negocio` | Evidence: no `RequestValidationError` handler exists in `backend/app`, so a Pydantic error returns `detail` as a list with a `"Value error, "` prefix; `CreditosPage.tsx:130` passes `detail` straight to `toast.error`, which cannot render a list. Router 422 with a string reaches the toast verbatim with zero frontend change, matching the codebase's existing state-conflict 422 convention (`"Editar días no aplica..."`) |
| User-facing message | `"Los créditos diarios no pueden iniciar un domingo (el domingo no es día de cobro). Seleccione otra fecha inicial de pago."` | silent shift to Monday | Owner rule 2 (Engram #913): reject, never correct silently |
| Edit path | No change needed | validator on `CreditoUpdate` | `CreditoUpdate` exposes only capital/tasa/abono_minimo; `PATCH /dias-pago` rejects diario with 422 (`creditos.py:354`). No path can move `fecha_inicial_pago` or `periodicidad` after creation |
| Projection parity | Projector resyncs `fecha_proy` to the persisted `fecha_maxima` whenever `n` is an existing row | (a) keep walking from `fecha_inicial_pago`; (b) start at max persisted row | (a) drifts: every historically paid Sunday row (kept by owner rule 3) makes the from-start chain one day later than the generator, so `/pagos/diarios` virtual rows would be wrong for every legacy daily credit. (b) drops gap-filling semantics. Resync is ~8 lines and a no-op for chain-consistent credits (mensual/quincenal/semanal) |
| Backfill engine | Reuse `recalcular_cuotas_futuras` directly from the new endpoint | new walker; going through `PATCH /dias-pago` | Function is periodicidad-agnostic and filters `pagado=False AND deleted_at IS NULL`, so paid rows are never touched. The dias-pago guard rejecting diario stays as is |
| Backfill selection | All active daily credits with at least one pending row; report only rows whose date changed | only credits with a pending Sunday row | Re-walk is a pure function of (last paid date | `fecha_inicial_pago`), hence idempotent; selecting everything removes a second predicate that could disagree with the walker |
| Legacy Sunday first cuota | Backfill computes `desde_fecha = fecha_inicial_pago` shifted by `+1` when `es_domingo` and no row is paid | leave cuota #1 on Sunday | Success criterion "no pending daily installment on Sunday". `credito.fecha_inicial_pago` itself is not rewritten (informational; projector no longer depends on it once resync lands) |

## Data Flow

    crear_credito ──es_domingo(fecha_inicial_pago)?──▶ 422 (string detail) ──▶ toast
         │ no
         ▼
    crear_primera_cuota (fecha_maxima = fecha_inicial_pago, unchanged)
         │ pay
         ▼
    generar_siguiente_cuota ──▶ siguiente_fecha_maxima ──▶ _siguiente_diario (Sat→Mon)
                                        ▲                          ▲
    _calcular_virtuales (resync at persisted rows) ────────────────┘
    recalcular_cuotas_futuras ◀── POST /creditos/admin/backfill-domingos-diario

`recalcular_cuotas_futuras` semantics (verified `credito_service.py:845-871`): assigns
`desde_fecha` to the FIRST pending row, then walks forward; paid rows are excluded by
the query. Caller convention (`creditos.py:385-396`): `desde_fecha =
siguiente_fecha_maxima(max paid fecha_maxima)` or `fecha_inicial_pago` if none paid.
Post-fix the paid-anchor case is Sunday-safe automatically; the no-paid case needs the
explicit shift above. No change to the function itself.

## File Changes

| File | Action | Description |
|---|---|---|
| `backend/app/utils/fechas.py` | Modify | `es_domingo`, `_siguiente_diario`, diario branch, docstring update |
| `backend/app/routers/creditos.py` | Modify | Sunday guard in `crear_credito`; temporary `POST /creditos/admin/backfill-domingos-diario` (`require_role("admin")`) |
| `backend/app/routers/pagos.py` | Modify | `_calcular_virtuales`: select `Pago.fecha_maxima`, map `cid -> {numero_cuota: fecha_maxima}`, resync before advancing |
| `backend/tests/test_fechas_ancla.py` | Modify | Flip `test_4_2_b` (Jan-31-2026 Sat → Feb-02 Mon); new diario cases |
| `backend/tests/test_creditos_router.py` | Modify | Sunday 422 + message; Monday-Saturday 201; mensual Sunday 201; edit path cannot introduce Sunday |
| `backend/tests/test_pagos_listado.py` | Modify | diario virtual rows never on Sunday; resync parity after a paid Sunday row |
| `backend/tests/test_credito_service_arrastre.py` | Modify | Sat→Mon generation with carried-over shortfall (regression) |
| `backend/tests/test_backfill_domingos_diario.py` | Create | Backfill: corrected, idempotent, paid untouched, non-diario untouched, 403 non-admin |

## Interfaces / Contracts

```
POST /creditos/admin/backfill-domingos-diario      require_role("admin")   # TEMPORAL
Selection: Credito.periodicidad == diario AND activo AND deleted_at IS NULL
           AND EXISTS pending Pago (pagado=False, deleted_at IS NULL)
Per credit: desde_fecha per convention above -> recalcular_cuotas_futuras -> diff dates
Audit: audit_service.registrar_actualizacion_campos(cambios={"fecha_maxima_domingos": (n_antes, n_despues)}) per corrected credit
Response: {"revisados": int, "creditos_corregidos": int, "cuotas_corregidas": int,
           "ids": [uuid], "cambios": [{"credito_id", "numero_cuota", "antes", "despues"}]}
Second run: cuotas_corregidas == 0. No explicit commit (get_db commits on clean exit).
```

Read-only audit query to run in prod BEFORE the backfill (deliverable):

```sql
SELECT c.id, c.numero_credito_cliente, p.numero_cuota, p.fecha_maxima
FROM pagos p JOIN creditos c ON c.id = p.credito_id
WHERE c.periodicidad = 'diario' AND c.activo AND c.deleted_at IS NULL
  AND p.pagado = false AND p.deleted_at IS NULL
  AND EXTRACT(DOW FROM p.fecha_maxima) = 0
ORDER BY c.id, p.numero_cuota;
```

## Testing Strategy (Strict TDD — RED first)

| Layer | What | How |
|---|---|---|
| Unit | Sat→Mon; Mon..Sat unchanged (+1); Sunday input → Mon (defensive); multi-week cascade (7 steps from Mon land on next Mon, 6 collection days); Dec-2026 year boundary; `test_4_2_b` flipped; semanal Sat→Sat unchanged | `test_fechas_ancla.py`, in-memory `Credito` |
| Unit | `es_domingo` true only for weekday 6 | pure |
| Integration | `generar_siguiente_cuota` after a Saturday cuota with partial payment → Monday, arrastre amounts unchanged | `test_credito_service_arrastre.py`, unmocked aiosqlite |
| Integration | `POST /creditos` diario on Sunday → 422 with exact message; Saturday → 201; mensual on Sunday → 201; `PATCH /{id}` cannot change start date | httpx |
| Integration | `/pagos?periodicidad=diario` virtual rows: none on Sunday; after a paid Sunday row + Monday pending, virtual n+1 is Tuesday (parity with generator) | `test_pagos_listado.py` |
| Integration | Backfill: pending Sunday + cascade corrected; paid Sunday row kept; semanal/mensual untouched; second run zero; `gestor` 403; legacy no-paid Sunday cuota #1 → Monday | new test file |

Command: `cd backend && python -m pytest` (Windows: `backend/venv/Scripts/python.exe -m pytest`); frontend gate `npx tsc --noEmit` (no frontend edits expected).

## Threat Matrix

N/A — no routing, shell, subprocess, VCS/PR automation, executable-file classification, or process-integration boundary. New surface is one authenticated admin route covered by the RBAC RED test.

## Migration / Rollout

No schema migration. Merge → deploy → run the audit query (record output) → run the backfill POST once as admin and keep the JSON response as audit record → re-run audit query (expect zero rows) → follow-up PR deletes endpoint + its test (AGENTS.md convention, same as `remove-cierre-saldo-cero-backfill`). Rollback = revert; pending dates recoverable by re-walking with the reverted function.

## Line forecast vs the 400-line budget

| Area | Δ |
|---|---|
| `fechas.py` | ~20 |
| `creditos.py` (guard + backfill) | ~65 |
| `pagos.py` (resync) | ~10 |
| Tests (5 files) | ~250 |
| **Total** | **~345** |

400-line budget risk: Medium. Chained PRs recommended: No. Decision needed before apply: No.
Fallback seam if RED tests overshoot: PR 1 = rule + rejection + projection resync + tests; PR 2 = backfill endpoint + test. Cleanup PR is a separate follow-up regardless.

## Open Questions

- [ ] None blocking.
- [ ] Follow-up (out of scope): `CreditosPage.tsx:130` does not flatten list-shaped `detail` from Pydantic validators (unlike `:206-207`); pre-existing schema errors such as the quincenal second-date rule are affected today.
