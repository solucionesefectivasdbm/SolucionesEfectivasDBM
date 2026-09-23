# Proposal: Reportes — Cartera Vencida + filtro por intervalo de días (fusión items 13+14)

> Exploration: `explore.md` / Engram `sdd/reportes-cartera-vencida-y-rango-fechas/explore` (#1090).
> Owner decisions: business rules below are binding. Execution mode: interactive.

## Intent

Phase 2 items 13+14, fused. Item 13 (recaudo diario/distribución as a separate report)
was discarded; item 14 (cartera vencida) survives. Today `GET /reportes` only supports
filtering by momento (año+mes+momento) and never references mora/overdue — it is purely
"cuotas due inside this window, split by paid/pending". There is no way to see overdue
balance ("cartera vencida") by gestor, nor to filter any report by an arbitrary date
range instead of a fixed momento. Success: the existing Ingresos report gains an
interval filter mode without changing its current structure; a new Cartera Vencida
report reuses the `overdue-evaluation` mora predicate over either a momento or an
arbitrary interval, broken down by gestor.

## Business rules (binding)

1. **Event-based, not snapshot**: "vencido dentro del rango" means the cuota's
   `fecha_entrada_mora` (day after the `fin` of the momento containing its
   `fecha_maxima`) falls inside the filtered window — NOT "what is overdue as of a
   cutoff date". A new pure utility `fecha_entrada_mora(fecha_maxima) -> date` is added
   to `backend/app/utils/momentos.py`, built on `get_momento`/`get_mes_momento`/
   `get_periodo_momento`, mirroring `overdue-evaluation`'s edge-case coverage (m2
   cross-month, February boundaries).
2. **Live, not historical**: the report is recomputed at read time from current data,
   consistent with the project's existing pattern (never persist derived state — same
   reasoning as the abandoned `Cliente.al_dia`). No historical `fecha_entrada_mora`
   persistence, no backfill. Accepted consequence: a cuota that entered mora inside a
   past window but was later deferred (`payment-deferral-tracking`) to a date no longer
   overdue will NOT reappear when re-querying that past window later — deferral
   evaluates only against the cuota's current `fecha_maxima`, with no history of prior
   dates.
3. **Breakdown scope**: Cartera Vencida includes a por-gestor breakdown (same
   aggregation style as Ingresos) but NO por-receptor breakdown — these are unreceived
   payments, so no receptor applies.
4. **Two filter modes for both report types**: "Por momento" (año+mes+momento, exactly
   as today, via `MOMENTOS` dropdown) or "Por intervalo de días" (`fecha_desde`/
   `fecha_hasta`), reusing the naming precedent from `backend/app/routers/auditoria.py`.
5. **Architecture**: two separate backend endpoints — `GET /reportes/ingresos`
   (generalized with interval support, structure unchanged) and
   `GET /reportes/cartera-vencida` (new) — sharing a date-window-resolution helper
   (momento → dates, or interval passthrough). Chosen over a single endpoint with a
   hybrid/discriminated-union response schema, per exploration's Approach 2, to keep
   `reportes.py` from growing an even messier shared schema and to follow the project's
   existing pattern of focused endpoints (e.g. `/pagos/alertas/vencidos` vs the general
   listing).

## Scope

### In Scope
- `backend/app/utils/momentos.py`: `fecha_entrada_mora(fecha_maxima)` + unit tests
  covering m2 cross-month and February boundaries (mirroring `overdue-evaluation`).
- Shared date-window-resolution helper (momento or interval → `fecha_inicio,fecha_fin`)
  in `backend/app/routers/reportes.py`.
- `GET /reportes/ingresos`: existing query/response generalized to accept either momento
  params or `fecha_desde`/`fecha_hasta`; response shape unchanged.
- `GET /reportes/cartera-vencida`: new endpoint, filters unpaid cuotas whose
  `fecha_entrada_mora` falls in the window, totals + por-gestor breakdown, no
  por-receptor.
- Frontend `ReportesPage.tsx`: report-type selector (Ingresos / Cartera Vencida) and
  filter-mode selector (Por momento / Por intervalo) for both types.
- `frontend/src/api/index.ts`: typed calls for both endpoints and both filter modes.
- Spec delta to `openspec/specs/overdue-evaluation/spec.md` (removes/updates the
  "no report changes" Non-Goal) and new/modified capability spec(s) for reportes.

### Out of Scope (non-goals)
- Historical/immutable snapshot reconstruction of past overdue state — report is
  always live-recomputed (rule 2).
- Performance optimization for wide date intervals — same Python-side load-all-then-
  aggregate pattern as today's `/alertas/vencidos` and `/reportes`; acceptable at
  current scale, flagged for future review if data volume grows.
- Changes to momento ranges, closure rules, deferral semantics, or the day-anchored
  "fechas de pago fijas mensuales" feature itself.
- Item 13 (separate recaudo diario/distribución report) — discarded, not part of this
  change.

## Capabilities

### New Capabilities
- `cartera-vencida-report`: new endpoint/report showing overdue balance by gestor,
  filterable by momento or date interval, using event-based `fecha_entrada_mora`.

### Modified Capabilities
- `overdue-evaluation`: removes/updates the "no report changes" Non-Goal; documents
  `fecha_entrada_mora` as a new derived-date utility consumed by reporting.
- (research needed in sdd-spec) whichever existing capability documents `GET /reportes`
  today — gains interval filter mode alongside momento mode, response shape unchanged.

## Approach

Add `fecha_entrada_mora` to `momentos.py`, unit-tested at momento boundaries the same
way `overdue-evaluation` was. Factor a small window-resolution helper in `reportes.py`
used by both endpoints so momento-vs-interval logic lives in one place. `/reportes/
ingresos` keeps its current aggregation code, only the window resolution changes.
`/reportes/cartera-vencida` filters `Pago.pagado==False` with `fecha_entrada_mora`
inside the window (computable in SQL as `fecha_maxima < fin_ventana AND fecha_maxima >=
` window-equivalent bound, same style as `fecha_limite_mora` in `/alertas/vencidos`),
then aggregates totals and por-gestor. Frontend adds two selectors to the existing
`ReportesPage.tsx` and branches which API function to call; `MOMENTOS` dropdown is
reused unchanged for the momento mode.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `backend/app/utils/momentos.py` | Modified | `fecha_entrada_mora(fecha_maxima)` |
| `backend/app/routers/reportes.py` | Modified | window-resolution helper; `/ingresos` generalized; new `/cartera-vencida` |
| `frontend/src/pages/Reportes/ReportesPage.tsx` | Modified | report-type + filter-mode selectors |
| `frontend/src/api/index.ts` | Modified | typed calls for both endpoints/modes |
| `frontend/src/utils/formatters.ts` (`MOMENTOS`) | Unchanged | reused as-is |
| `openspec/specs/overdue-evaluation/spec.md` | Modified | Non-Goal removed/updated |
| `backend/tests/` | New | `fecha_entrada_mora` boundary tests, `/cartera-vencida` integration |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| `fecha_entrada_mora` mishandles Feb / m2 cross-month like `fecha_limite_mora` had to guard against | Med | Reuse `get_momento`/`get_mes_momento`, not raw `get_periodo_momento`; mirror `overdue-evaluation`'s 7-scenario boundary tests |
| Users interpret Cartera Vencida as an immutable historical record | Low-Med | Document "live report" behavior in UI copy/spec; confirmed accepted by owner (rule 2) |
| Day-anchored `fecha_maxima` (fixed monthly payment dates) interacts unexpectedly with `fecha_entrada_mora` on an arbitrary interval | Low | Flagged as an assumption to verify explicitly in sdd-design/sdd-spec, not silently assumed safe |
| Wide interval query loads large unpaid backlog into Python | Low | Same pattern as existing `/alertas/vencidos`/`/reportes`; accepted, not optimized now |

## Rollback Plan

Revert the PR(s). No schema change, no data migration, no persisted derived state —
both endpoints compute everything at read time.

## Dependencies

- `overdue-evaluation` (momento utilities, mora predicate style).
- `payment-deferral-tracking` (defines why the report is live, not historical).

## Success Criteria

- [ ] `fecha_entrada_mora` unit-tested at m2 cross-month and February boundaries.
- [ ] `/reportes/ingresos` momento mode produces identical output to today's `/reportes`.
- [ ] `/reportes/ingresos` interval mode filters correctly on `fecha_desde`/`fecha_hasta`.
- [ ] `/reportes/cartera-vencida` returns totals + por-gestor only (no por-receptor), for
      both momento and interval modes.
- [ ] A cuota deferred out of mora does not reappear when re-querying a past window.
- [ ] `ReportesPage.tsx` exposes both selectors without breaking the existing Ingresos view.

## Proposal question round

Owner-confirmed business rules (1–5 above) already resolve the core product decisions
raised in exploration. Two items remain flagged as assumptions for design/spec to
verify, not silently assumed safe (silence = accepted for now):
1. The day-anchored fixed monthly payment dates feature is orthogonal to
   `fecha_entrada_mora` (both operate on `fecha_maxima` the same way today) — to be
   confirmed during sdd-design/sdd-spec.
2. Wide-interval performance is explicitly out of scope for optimization in this change.
