# Design: Payment Deferrals (`payment-deferrals`)

Proposal: Engram #948 · Decisions (binding): #947 · Exploration: #946. Spec written in parallel; this design binds to the proposal + decisions only.

## Technical Approach

Additive counter `pagos.veces_aplazado` (deferred ⇔ `> 0`). The existing `PATCH /pagos/{id}/fecha` gains `es_aplazamiento: bool = False`; true increments the counter under the existing credit lock and writes a second, distinguishable audit row. A new DB-paginated `GET /pagos/aplazados` serves the cross-period page. Frontend adds a third `variante="aplazados"` to the shared `PagosPage.tsx`, a checkbox in the existing date modal, one row color, and a counter badge.

## Architecture Decisions

| Decision | Choice | Rejected | Rationale |
|---|---|---|---|
| Persistence | `veces_aplazado INT NOT NULL DEFAULT 0` + `CHECK >= 0` | boolean flag; history table | Owner decision 3; no drift between flag and count; follows `ck_creditos_anchor_*` constraint style |
| Mutation entry point | Reuse `modificar_fecha_pago` with body flag | `POST /pagos/{id}/aplazar` | Owner decision 4 (single action); same role gate `require_role("admin","recaudador")`; zero new frontend action |
| Audit distinguishability | `cambios={"fecha_maxima": (old,new), "veces_aplazado": ("n","n+1")}` on deferral; only `fecha_maxima` on correction | Encoding a marker inside `valor_nuevo` | Reuses `registrar_actualizacion_campos` unchanged; a deferral = two rows in the same request, a correction = one; queryable by `campo_modificado = 'veces_aplazado'` |
| Locking | `_get_pago_con_credito(db, pago_id, lock=True)` always | No lock (current behaviour) | Counter is read-modify-write; double-submit must not lose an increment. Same pattern as `desvalidar_pago`. SQLite tests only prove sequential semantics (documented precedent) |
| Listing | New `GET /pagos/aplazados`, DB-level `WHERE/COUNT/OFFSET/LIMIT`, no virtual rows | Flag on `listar_pagos` | `listar_pagos` requires `anio`/`mes` and paginates in memory after merging virtual rows; deferred rows are always real; a flag would either break the mandatory params or force a wide range + in-memory scan |
| Frontend page | Third `variante='aplazados'` of `PagosPage.tsx` | New component | Deferred page needs full action parity (validate, register, date, receptor); a new component duplicates ~500 lines. Only the filter card and the fetch call diverge |
| Row color precedence | `proyectada gray` > `vencido red` > `aplazado violet (pending only)` > zebra; `ultimo_pago` border independent | Deferred over red | Owner decision 6. Paid deferred rows keep zebra; badge always shows count (history) |
| Deferral question | Checkbox in the existing date modal, unchecked by default | Extra confirm step | One modal, one submit; default false preserves current semantics; accidental increments mitigated by explicit label + audit |
| Navigation | Header button "Pagos Aplazados" in regular variant; "Volver a Pagos" in the new variant | Sidebar entry | Matches existing semanal/diario pattern; sidebar `/pagos` stays active by prefix |

## Data Flow

    PagosPage (any variante) ── PATCH /pagos/{id}/fecha {fecha_maxima, es_aplazamiento}
        │                              │ lock credito → refresh pago
        │                              │ reject 422 if es_aplazamiento && pagado
        │                              │ fecha_maxima = new; veces_aplazado += 1 (if flag)
        │                              └ audit rows (1 or 2) ── same transaction
        └── variante=aplazados ── GET /pagos/aplazados?incluir_pagados&page&sort_dir&gestor_id&busqueda
                                       └ SELECT … WHERE veces_aplazado > 0 [AND pagado = false] → COUNT + OFFSET/LIMIT

## File Changes

| File | Action | Description |
|---|---|---|
| `backend/alembic/versions/b2c3d4e5f6a7_add_veces_aplazado_to_pagos.py` | Create | `down_revision='a1b2c3d4e5f6'`; `add_column('pagos', Column('veces_aplazado', Integer, nullable=False, server_default='0', comment=…))` + `ck_pagos_veces_aplazado_no_negativo` (`veces_aplazado >= 0`); downgrade drops constraint then column. Server default kept (harmless) |
| `backend/app/models/pago.py` | Modify | `veces_aplazado: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")` — both defaults so SQLite `create_all` tests and Postgres agree |
| `backend/app/schemas/pago.py` | Modify | `ModificarFechaPagoRequest.es_aplazamiento: bool = False`; `PagoResponse.veces_aplazado: int = 0` (virtual dicts validate unchanged) |
| `backend/app/routers/pagos.py` | Modify | `listar_pagos` select + `_pago_row_a_dict` add `veces_aplazado`; extract `_aplicar_scope_y_busqueda(query, current_user, gestor_id, cliente_id, busqueda)` shared by both listings; new `listar_pagos_aplazados`; `modificar_fecha_pago` logic below |
| `backend/tests/test_aplazamientos.py` | Create | Strict TDD suite (fixtures copied from `test_desvalidar_pago.py`) |
| `frontend/src/types/index.ts` | Modify | `Pago.veces_aplazado: number` |
| `frontend/src/api/index.ts` | Modify | `modificarFecha(pagoId, fecha_maxima, es_aplazamiento = false)`; `listarAplazados(params)` |
| `frontend/src/pages/Pagos/PagosPage.tsx` | Modify | `variante` union + `esAplazados`; filter card, fetch, row class, badge, modal checkbox, header buttons |
| `frontend/src/App.tsx` | Modify | `<Route path="pagos/aplazados" element={<PagosPage variante="aplazados" />} />` |

## Interfaces / Contracts

`modificar_fecha_pago` order of checks (role 403 resolved by `Depends` before the body runs):

    pago, _ = await _get_pago_con_credito(db, pago_id, lock=True)   # 404 covers virtual/projected ids
    if body.es_aplazamiento and pago.pagado:
        raise HTTPException(422, "No se puede aplazar: la cuota ya fue pagada.")
    if body.es_aplazamiento and body.fecha_maxima <= pago.fecha_maxima:
        raise HTTPException(422, "Un aplazamiento debe mover la fecha hacia adelante.")
    fecha_anterior = pago.fecha_maxima; pago.fecha_maxima = body.fecha_maxima
    cambios = {"fecha_maxima": (str(fecha_anterior), str(body.fecha_maxima))}
    if body.es_aplazamiento:
        veces_anterior = pago.veces_aplazado; pago.veces_aplazado = veces_anterior + 1
        cambios["veces_aplazado"] = (str(veces_anterior), str(pago.veces_aplazado))
        logger.info("APLAZAMIENTO OK — pago_id=%s usuario_id=%s veces=%s", …)
    await audit_service.registrar_actualizacion_campos(…, cambios=cambios)

Correction with `pagado=true` stays allowed (unchanged behaviour). A deferral whose new date is equal to or earlier than the current `fecha_maxima` is rejected with 422 (owner decision, Engram #947); corrections keep today's behaviour with no direction check.

`GET /pagos/aplazados` → `PaginatedResponse[PagoResponse]`, `Depends(get_current_user)` (same visibility as `listar_pagos`). Params: `incluir_pagados: bool = False`, `sort_dir: "asc"|"desc" = "asc"`, `gestor_id`, `cliente_id`, `busqueda`, `page ≥ 1`, `page_size 1..50 = 50`. Predicate: `deleted_at IS NULL AND veces_aplazado > 0 AND (pagado OR credito_operativamente_abierto())`, plus `pagado = false` unless `incluir_pagados`; gestor users scoped by `Cliente.gestor_id`. Order: `fecha_maxima <dir>, Cliente.nombre, Cliente.apellidos, Pago.id`. `total` via `select(func.count()).select_from(query.subquery())`.

Frontend row class:

    p.es_proyectada ? 'bg-gray-50 text-gray-400' : zebra,
    !p.es_proyectada && isVencido(p) && 'bg-red-50',
    !p.es_proyectada && !p.pagado && !isVencido(p) && p.veces_aplazado > 0 && 'bg-violet-50',
    p.es_ultimo_pago && 'border-l-4 border-l-accent'

Badge in the Estado cell for `veces_aplazado > 0`: `Aplazado ×{n}` (`bg-violet-100 text-violet-700`, title "Veces aplazado"). Modal: checkbox "¿Es un aplazamiento solicitado por el cliente?" + helper "Marque solo si el cliente pidió mover la fecha; se incrementará el contador." State reset to false on open; toast outcomes: (1) `es_aplazamiento=true` and response `veces_aplazado` increased → "Aplazamiento registrado"; (2) `es_aplazamiento=false` → "Fecha actualizada"; (3) `es_aplazamiento=true` but response `veces_aplazado` did not increase (deploy-skew guard) → error toast "La fecha se actualizó, pero el aplazamiento no fue registrado por el servidor" and still refetch. `variante='aplazados'`: hide Año/Mes/Momento, show "Incluir pagados" checkbox, `filtrosCompletos = true`, title "Pagos Aplazados", empty state "No hay pagos aplazados".

## Testing Strategy (Strict TDD, backend)

| Case (`test_aplazamientos.py`) | Asserts |
|---|---|
| Deferral increments 0→1, then 1→2; date moved; response `veces_aplazado` | counter + date + 200 |
| Body without flag / `es_aplazamiento=false` | counter unchanged, date moved (backward compat) |
| `pagado=true` + flag | 422, detail text, no mutation, zero audit rows |
| `pagado=true` correction | still 200 (unchanged behaviour) |
| Same-date or earlier date + flag | 422, no mutation, zero audit rows; same date without flag → 200 |
| Unknown id (uuid5 virtual) | 404 |
| Role matrix | admin/recaudador 200; registrador/gestor 403, no writes |
| Audit | deferral → 2 rows (`fecha_maxima`, `veces_aplazado` "0"→"1"); correction → 1 row |
| Listing | default excludes `pagado`; `incluir_pagados=true` includes; `veces_aplazado=0` and soft-deleted excluded; two months both present; `total/pages/page_size`; sort asc/desc; gestor scoping; `busqueda`; `page_size>50` → 422 |
| `listar_pagos` | real row carries `veces_aplazado`; virtual row defaults 0 |

Frontend: no runner; manual checklist below. `npx tsc --noEmit` clean.

Line forecast (additions+deletions): migration 35, model 6, schemas 4, router 115, tests 320, types 2, api 10, PagosPage 75, App 2 ≈ **570 code+tests**, within the 800 budget. Openspec artifacts (≈ 300) do not count toward the review budget (orchestrator decision, consistent with prior items).

## Threat Matrix

N/A — no routing, shell, subprocess, VCS/PR automation, executable-file classification, or process-integration boundary.

## Migration / Rollout

Railway runs `alembic upgrade head` on deploy; column is additive with `server_default='0'`, so existing rows read 0 with no backfill and no downtime. Rollback: revert PR; `alembic downgrade -1` drops constraint + column; leaving the column in place is harmless.

Manual frontend verification: (1) correction leaves badge absent; (2) deferral shows `Aplazado ×1`, violet row in weekly/daily/regular; (3) second deferral → `×2`; (4) deferred row whose new date passes turns red, badge persists; (5) paid deferred row: zebra + badge; (6) date button hidden for paid rows; (7) `/pagos/aplazados` lists across months, pending only; "Incluir pagados" toggles; pagination and sort work; (8) gestor user sees only own clients; (9) Back button returns to `/pagos`.

## Open Questions

- [x] Same-date or backward-date deferral → rejected with 422 (owner decision 2026-09-12).
- [x] Openspec artifacts do not count toward the 800-line review budget.
