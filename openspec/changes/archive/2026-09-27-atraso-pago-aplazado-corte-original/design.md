# Design: Mora cut-off by original momento for deferred payments

## Technical Approach

Add `pagos.fecha_maxima_original` (Date, nullable at DB level). Set it once at insert time, keep it unchanged on `PATCH /pagos/{id}/fecha`, and resync it in `recalcular_cuotas_futuras`. The date helpers in `momentos.py` stay pure. Only the column that callers pass in changes, so item-8 evaluation (`fecha_limite_mora(hoy)`, on demand, no cron) is untouched. Existing rows are handled in two layers: the migration fills every row (`= fecha_maxima`), then a temporary admin endpoint rebuilds deferred rows from `audit_log`.

## Architecture Decisions

| Decision | Choice | Rejected | Rationale |
|---|---|---|---|
| D1 Schema mechanism | Alembic revision (`down_revision` = current head, `f6a7b8c9d0e1`, confirm with `alembic heads`) | `lifespan` hook in `main.py` (AGENTS.md rule) | Since the 2026-06-06 incident, `start.sh` runs `alembic upgrade head` on every deploy, and every `pagos` column since then was added through Alembic (`veces_aplazado`, cuenta, repartos). If we also added a hook, two schema owners would drift. AGENTS.md is stale on this point; flag it for update. |
| D2 Initial fill | Same migration: `add_column` nullable, then `UPDATE pagos SET fecha_maxima_original = fecha_maxima WHERE fecha_maxima_original IS NULL` | Leave NULL and use `COALESCE` in readers | After this runs, readers never see NULL. That keeps plain predicates indexable. The update is idempotent. |
| D3 Set on create | SQLAlchemy `before_insert` mapper event on `Pago`: if `fecha_maxima_original is None`, copy `fecha_maxima` | Edit all 9 `Pago(...)` constructors (`credito_service.py` x8, `pago_service.py` x1) | One enforcement point that also covers test fixtures and future creation paths. The listener lives in `models/pago.py`. |
| D4 Deferral | `modificar_fecha_pago` does not touch the column, in both modes (`es_aplazamiento` true or false) | Resync on free correction | Follows the proposal and spec literally. See Open Questions. |
| D5 Re-anchor | `recalcular_cuotas_futuras` sets `cuota.fecha_maxima_original = fecha_actual` together with `fecha_maxima` and `momento` | Leave it stale | A re-anchor is a new legitimate plan (spec). No per-pago audit rows are written; this matches the existing pattern, where the `creditos.anchor_fechas` audit row covers the operation. |
| D6 `momentos.py` | Pure date functions keep their signatures. Docstrings now say the input is the cut-off date (`fecha_maxima_original`). `flags_mora` gains a keyword-only `fecha_maxima_original` | Rename or duplicate the functions | Smallest surface. `limite` is still computed once per request. |
| D7 `vencido` semantics | `en_mora = original < limite`; `vencido = (fecha_maxima < hoy) or en_mora` | `vencido` from the original date | Keeps the rule that `en_mora` implies `vencido` (it held before because `limite <= hoy`), while the UI still shows the new deferred date. |
| D8 Listing | `GET /pagos` filters the month or momento range on `fecha_maxima_original`. Display, sort and tiebreak stay on `fecha_maxima` + `Pago.id` | Use the `Pago.momento` label | A label has no month, so a date range is still needed. |
| D9 Backfill | Temporary `POST /admin/migracion/fecha-maxima-original?dry_run=true` (default dry run), admin-only. It is deleted in a later commit, like the `dfb0cf2` precedent | Backfill inside the Alembic migration | The required verification count has to run and be reviewed before any write happens. |

## Call-site Changes

| Site | Change |
|---|---|
| `routers/pagos.py` `_pago_row_a_dict`, `listar_pagos`, `listar_pagos_aplazados` | Select `Pago.fecha_maxima_original`; the range filter uses it (D8); pass it to `flags_mora` |
| `routers/pagos.py` `alertas_vencidos` | `Pago.fecha_maxima_original < limite`; flags use it. `ORDER BY fecha_maxima_original, Pago.id` |
| `routers/pagos.py` `_calcular_virtuales` | Virtual rows set `fecha_maxima_original = fecha_proy`. Chain resync unchanged |
| `routers/clientes.py` L59, L113, L203 | `Pago.fecha_maxima_original < limite` |
| `routers/creditos.py` `historial_cuotas` | `flags_mora(..., fecha_maxima_original=p.fecha_maxima_original)` |
| `routers/reportes.py` cartera-vencida | `lo <= Pago.fecha_maxima_original < hi` |
| `schemas/pago.py` `PagoResponse` | Add `fecha_maxima_original: Optional[date] = None` |
| `alertas/proximos-vencer` | Unchanged: reminders follow the current date |

## Backfill Algorithm

`services/fecha_original_backfill.py`:

- `resolver_fecha_original(fecha_actual, fecha_pago_real, eventos, ultimo_reanclaje) -> (date, motivo)`: pure and unit-tested.
- `ejecutar(db, usuario_id, ip, dry_run)`: loads the data in 3 batched queries, with no N+1.
  1. Pagos with `deleted_at IS NULL`.
  2. `audit_log` rows where `entidad='pagos'` and `campo_modificado='fecha_maxima'`, `ORDER BY entidad_id, fecha_accion, id`.
  3. `MAX(fecha_accion)` of `entidad='creditos'`, `campo_modificado='anchor_fechas'`, per credito.

Rules:
1. Drop events older than the credito's last re-anchor, unless the pago was paid before that re-anchor. A re-anchor already reset the original date, so older deferrals no longer count.
2. If events remain, use the first remaining `valor_anterior`, parsed with `date.fromisoformat` (`motivo=auditoria`).
3. If none remain, fall back to the current `fecha_maxima` (`motivo=sin_auditoria`, `reanclado`, or `valor_invalido`).

The result is computed only from audit rows and `fecha_maxima`, never from the column itself, so re-running it is idempotent.

Response: `{total_pagos, con_auditoria, a_modificar, aplazados_sin_auditoria (veces_aplazado>0 and no rows), reanclados, valores_invalidos, muestra_ids[:20]}`. In apply mode, each changed row goes through `audit_service.registrar_actualizacion_campos(entidad="pagos", cambios={"fecha_maxima_original": (old, new)})` in the request transaction.

## Data Flow

    create Pago --before_insert--> original = fecha_maxima
    PATCH /fecha ------------------> fecha_maxima only (+audit)
    PATCH /dias-pago -> recalcular -> fecha_maxima + original + momento
    readers --(original < fecha_limite_mora(hoy))--> en_mora / al_dia / cartera

## File Changes

| File | Action |
|---|---|
| `backend/alembic/versions/a7b8c9d0e1f2_add_fecha_maxima_original_to_pagos.py` | Create (column, fill UPDATE, index `ix_pagos_fecha_maxima_original`) |
| `backend/app/models/pago.py` | Modify (column + `before_insert` listener) |
| `backend/app/services/credito_service.py` | Modify (`recalcular_cuotas_futuras`) |
| `backend/app/utils/momentos.py` | Modify (`flags_mora`, docstrings) |
| `backend/app/routers/{pagos,clientes,creditos,reportes}.py` | Modify (call sites above) |
| `backend/app/schemas/pago.py` | Modify |
| `backend/app/services/fecha_original_backfill.py`, `backend/app/routers/admin.py`, `backend/app/main.py` | Create / Create / Modify (temporary) |

## Testing Strategy (strict TDD, pytest async, `create_all` in conftest)

| Layer | Cases |
|---|---|
| Unit `test_momentos.py` | `flags_mora` with original == current (same result as today); deferral that crosses the momento boundary gives `en_mora=True, vencido=True`; deferral inside the same momento gives no mora |
| Unit backfill | Several audit rows (earliest wins); no rows (fallback); unparsable value; events before a re-anchor are ignored; a pago paid before the re-anchor keeps its audit value |
| Integration `test_aplazamientos.py` | PATCH keeps the original; row stays in `GET /pagos?momento=` for the original momento and does not appear in the new one |
| Integration `test_mora_momento_cerrado.py` | `alertas/vencidos`, the 3 `al_dia` sites, and historial all flag a deferred pago that crossed the boundary; a non-crossing deferral is not flagged |
| Integration `test_dias_pago_endpoint.py` | Re-anchor resyncs the original on pending cuotas; paid cuotas stay unchanged |
| Integration `test_reportes_cartera_vencida.py` | A deferred pago counts in the window derived from its original date |
| Integration admin | `dry_run` writes nothing; apply writes the rows plus `audit_log`; a second run gives `a_modificar=0`; non-admin gets 403 |

## Threat Matrix

N/A: no routing, shell, subprocess, VCS/PR automation, executable-file classification, or process-integration boundary.

## Migration / Rollout

1. Deploy: auto-migrate fills the column.
2. Call the dry run and review the counts with the user.
3. Apply.
4. In a later commit, delete `admin.py` and its router registration.

Notify users before deploy: deferred pagos that crossed their momento will switch to en mora (accepted risk).

## Open Questions

- [ ] Should a free correction (`es_aplazamiento=false`) resync the original? The spec currently says no.
- [ ] Semanal/diario next-cuota generation chains from the current (deferred) `fecha_maxima` (`credito_service.py:597`). Existing behavior, out of scope.
