# Exploration: Payment Deferrals ("Aplazamientos de pago")

Change: `payment-deferrals` · Quote phase 2, item 7 (new feature, $450.000 COP) · Engram #946

## Current State

- `Pago` model (`backend/app/models/pago.py`) has no field distinguishing a deferred/postponed payment from any other date edit. The only date field is `fecha_maxima` (deadline); there is no `fecha_original`, `es_aplazado`, or reason/actor column.
- The only way today to postpone a single installment is `PATCH /pagos/{pago_id}/fecha` (`backend/app/routers/pagos.py:676-701`, schema `ModificarFechaPagoRequest`). It overwrites `fecha_maxima` and writes a generic `audit_log` UPDATE row via `audit_service.registrar_actualizacion_campos`. Nothing records *why* the date changed, so a client-requested deferral is indistinguishable from a clerical correction.
- A different mechanism, `PATCH /creditos/{credito_id}/dias-pago` (`backend/app/routers/creditos.py:335-420`), re-anchors `anchor_dia_1/anchor_dia_2` for a whole credit and cascades to all PENDING cuotas. This is the "cambio de momento" the feature must distinguish from a per-payment deferral: a credit-level schedule change, not a client-driven postponement of one installment.
- Frontend: a single component, `frontend/src/pages/Pagos/PagosPage.tsx`, is reused for `/pagos` (`variante="semanal"`) and `/pagos/diarios` (`variante="diario"`) via `App.tsx` routes. No other page renders a payment table, so "all payment tables" in practice means this one component across variants.
- Row coloring today (`PagosPage.tsx` ~455-464): `es_proyectada` → gray; `isVencido(p)` (client-side: `!pagado && fecha_maxima < now`) → `bg-red-50`; `es_ultimo_pago` → left accent border. `isVencido` is purely date-driven, so a payment whose `fecha_maxima` was pushed forward already stops being red; there is no separate backend mora computation to special-case.
- `GET /pagos` (`listar_pagos`, `pagos.py:92-244`) requires `anio` + `mes`; `momento` optional. It merges real rows with virtual/projected rows, then sorts and paginates in memory. No cross-month query exists today.
- `audit_log` (`backend/app/models/audit_log.py`) is a generic entidad/campo/valor_anterior/valor_nuevo table with no reason field.
- Alembic: only two migrations exist (`d9144df95951_initial.py`, `a1b2c3d4e5f6_add_anchor_days_to_creditos.py`); history appears squashed. Naming: `{hash}_{snake_case_description}.py`.
- Backend tests (pytest): `test_pagos_router.py`, `test_pago_service.py`, `test_pago_service_arrastre.py`, `test_pagos_listado.py`, `test_desvalidar_pago.py`, `test_dias_pago_endpoint.py`. No frontend test runner.
- Specs read for vocabulary: `payment-validation-reversal`, `daily-installment-scheduling`, `payment-carryover`, `credit-closure`.

## Affected Areas

- `backend/app/models/pago.py` — new field(s) (e.g. `es_aplazado`, `motivo_aplazamiento`) + Alembic migration.
- `backend/app/schemas/pago.py` — extend `ModificarFechaPagoRequest` (or add a sibling request) and `PagoResponse`.
- `backend/app/routers/pagos.py` — `modificar_fecha_pago` or a new `POST /pagos/{id}/aplazar` sets the flag with a distinct audit entry; `listar_pagos` needs a cross-period filter/endpoint for the new page.
- `backend/app/services/audit_service.py` — reused as-is.
- `frontend/src/pages/Pagos/PagosPage.tsx` — new row-color class with careful precedence vs. `bg-red-50` / `bg-gray-50`.
- `frontend/src/App.tsx` — new route (e.g. `/pagos/aplazados`): third `variante` or a distinct component.
- `frontend/src/types`, `frontend/src/api/index.ts`, `frontend/src/store/authStore.ts` — new field(s), API call, permission reuse.

## Approaches

1. **Boolean flag + reason on the existing `PATCH /pagos/{id}/fecha` flow.** Add `es_aplazado` and `motivo_aplazamiento` to `Pago`; extend the request with `es_aplazamiento` + `motivo`; new filter/endpoint for the deferred page (`WHERE es_aplazado = true`, relaxed date bounds).
   - Pros: minimal schema (2 columns), reuses endpoint/permissions/audit, small migration.
   - Cons: no multi-deferral history (flag overwritten), thin reason capture.
   - Effort: Low-Medium.
2. **Dedicated `aplazamientos_pago` history table** (`pago_id`, `fecha_anterior`, `fecha_nueva`, `motivo`, `usuario_id`, `fecha_registro`) + cached `es_aplazado` boolean on `Pago`.
   - Pros: full history, repeated deferrals, clean separation of UI state vs. audit.
   - Cons: new table, endpoints, more test surface.
   - Effort: Medium-High.
3. **`tipo_validacion`-style declared field** (`tipo_modificacion_fecha: correccion | aplazamiento`), no reason field.
   - Pros: smallest change, consistent with an existing pattern.
   - Cons: too thin for the stated business need.
   - Effort: Low.

## Recommendation

Approach 1 as the pragmatic default for this scope. Escalate to a hybrid of 1+2 only if the owner confirms a payment must be deferrable multiple times with history. This must be an explicit proposal decision.

## Risks

- Row-color precedence: a deferred payment should probably suppress the red vencido style.
- "Double visualization" has no precedent; `listar_pagos` is month-bound, so the dedicated page could silently miss deferred payments outside the current filter.
- No backfill signal exists: only new deferrals going forward can be tracked (known limitation).
- UX conflation between "Modificar fecha" (correction) and "Aplazar pago" (deferral with reason); needs a clear split.
- Migration risk low (additive nullable columns); check the Alembic head first.

## Ready for Proposal

Yes. Open questions: (a) single flag vs. history table, (b) UX split between correction and deferral, (c) dedicated page as a third `variante` or a new component, (d) reason field: free text vs. fixed options.
