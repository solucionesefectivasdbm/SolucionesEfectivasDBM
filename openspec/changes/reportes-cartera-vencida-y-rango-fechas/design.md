# Design: Reportes — Cartera Vencida + filtro por intervalo de días

## Technical Approach

Two focused admin-only endpoints in `backend/app/routers/reportes.py` share one window resolver. `/reportes/ingresos` is the existing handler, extended to accept an interval. `/reportes/cartera-vencida` is new. It turns the event rule "`fecha_entrada_mora` falls in the window" into a plain SQL range on `fecha_maxima`, built from the existing `fecha_limite_mora`. No new table, column or migration. Everything is computed at read time.

## Architecture Decisions

| # | Decision | Rejected alternative | Rationale |
|---|----------|----------------------|-----------|
| D1 | Keep `GET /reportes` as a hidden alias for `/reportes/ingresos`. Both decorators sit on the same handler, and the alias uses `include_in_schema=False`. | Rename the route and rewrite the 3 existing test files | The existing `test_reportes*.py` files keep passing unchanged and act as the regression proof for momento mode. |
| D2 | Add `resolver_ventana(anio, mes, momento, fecha_desde, fecha_hasta) -> (date, date)` in `reportes.py`. On invalid input it raises `HTTPException(422)`. | Put it in `utils/momentos.py` | It checks HTTP inputs, so it belongs in the router. `momentos.py` stays pure date logic. |
| D3 | Add a pure `fecha_entrada_mora(fm)` to `momentos.py`. It computes `get_periodo_momento(*get_mes_momento(fm), get_momento(fm))[1] + 1 day`. | Derive it from `fecha_limite_mora` | It reuses the momento-range code that is already tested, as the proposal requires. It is the canonical definition and the oracle for tests. |
| D4 | Filter cartera vencida in SQL: `fm >= fecha_limite_mora(inicio - 1d) AND fm < fecha_limite_mora(fin_efectivo)` | Load every unpaid cuota and filter per row in Python | The mora-entry date only moves forward as `fecha_maxima` moves forward. So "entry date in [I, F]" is the same as `limite(I-1) <= fm < limite(F)`. This is the same shape as `/alertas/vencidos`, indexable, with no N+1. An exhaustive test proves the equivalence (see Testing). |
| D5 | `fin_efectivo = min(fecha_fin, hoy_bogota())`. If `inicio > hoy`, return an empty report. | Allow future windows | A cuota whose entry date is still in the future is not in mora yet. With the clamp, every row also satisfies `en_mora(fm, hoy)`, which matches `/alertas/vencidos`. |
| D6 | Cartera uses the same guards as `/alertas/vencidos`: `pagado==False`, `deleted_at IS NULL`, `credito_operativamente_abierto()` | Ingresos' unguarded query | A settled or closed credit is not collectable cartera. Ingresos stays unchanged. |
| D7 | Pending amount = `(capital_a_pagar - capital_pagado) + (interes_a_pagar - interes_pagado)`, summed as `Decimal` and converted to `float` only when the response is built | `/alertas/vencidos`' `monto_a_pagar - pagado` formula | The per-gestor columns then match Ingresos' "pendiente" columns. AGENTS.md requires `Decimal` for money. |
| D8 | Build the per-gestor breakdown from one query: `select(Pago, Gestor)` with an outer join on `Cliente.gestor_id`. Sort by `(gestor_nombre, gestor_id)`. Cuotas without a gestor count in the totals but are left out of the breakdown. | Copy Ingresos' N+1 loop | Avoids 3 queries per row and gives a deterministic order. Leaving gestor-less cuotas out matches how Ingresos behaves today. |
| D9 | Ingresos response: `anio/mes/momento` become `Optional`. New additive fields `fecha_inicio/fecha_fin`, always filled. | A separate response model | In momento mode every existing key keeps its value, so current consumers are unaffected. |
| D10 | Frontend: `ReportesPage` holds filter state and calls the API. It renders `IngresosReporteView` or `CarteraVencidaReporteView`. The report is cleared when the report type changes. | Keep one monolithic page | Container/presentational split. The two response shapes never mix. |

## Validation rules (`resolver_ventana`)

- Momento mode requires all three of `anio`, `mes` (1–12) and `momento` (m1..m5). An invalid `momento` returns 422. Today it causes a `ValueError` and a 500.
- Interval mode requires both `fecha_desde` and `fecha_hasta`, with `fecha_desde <= fecha_hasta`.
- Using both modes in one request returns 422. Using neither returns 422. A partial momento or partial interval returns 422.

## Data Flow

    query params ─→ resolver_ventana ─→ (inicio, fin)
                         │
       ingresos: fecha_maxima BETWEEN inicio AND fin ─→ existing aggregation
       cartera:  bounds_entrada_mora(inicio, min(fin,hoy)) ─→ SQL range + guards
                         ─→ Decimal totals + por_gestor

## Interfaces / Contracts

```python
# utils/momentos.py
def fecha_entrada_mora(fecha_maxima: date) -> date: ...
def bounds_entrada_mora(inicio: date, fin: date) -> tuple[date, date]:
    """(lo, hi) such that inicio <= fecha_entrada_mora(fm) <= fin  <=>  lo <= fm < hi."""
    return fecha_limite_mora(inicio - timedelta(days=1)), fecha_limite_mora(fin)

class CarteraVencidaGestor(BaseModel):
    gestor_id: str; gestor_nombre: str; cantidad_cuotas: int
    total_vencido: float; total_capital_vencido: float; total_intereses_vencidos: float

class CarteraVencidaResponse(BaseModel):
    fecha_inicio: date; fecha_fin: date            # fecha_fin already clamped
    anio: int | None; mes: int | None; momento: str | None
    cantidad_cuotas: int
    total_vencido: float; total_capital_vencido: float; total_intereses_vencidos: float
    por_gestor: list[CarteraVencidaGestor]         # no por_receptor
```

```ts
// api/index.ts
type FiltroReporte = { anio: number; mes: number; momento: string }
                   | { fecha_desde: string; fecha_hasta: string }
reportesApi.ingresos(params: FiltroReporte)       // GET /reportes/ingresos
reportesApi.carteraVencida(params: FiltroReporte) // GET /reportes/cartera-vencida
```

The frontend `Reporte` type in `types/index.ts` is out of date: it has `total_intereses` and no pending fields. Replace it with `ReporteIngresos` (the real shape) and `ReporteCarteraVencida`.

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `backend/app/utils/momentos.py` | Modify | Add `fecha_entrada_mora`, `bounds_entrada_mora` |
| `backend/app/routers/reportes.py` | Modify | `resolver_ventana`, the `/ingresos` route plus the alias, `/cartera-vencida` and its schemas |
| `backend/tests/test_momentos.py` (or existing) | Modify | Boundary tests and the equivalence test |
| `backend/tests/test_reportes_cartera_vencida.py` | Create | Integration tests |
| `backend/tests/test_reportes_intervalo.py` | Create | Interval mode and 422 validation |
| `frontend/src/api/index.ts`, `types/index.ts` | Modify | Typed calls and types |
| `frontend/src/pages/Reportes/*` | Modify/Create | Selectors and the two view components. Date inputs follow the `AuditoriaPage` pattern (`type="date"`, `YYYY-MM-DD` string state). |

## Testing Strategy (Strict TDD, backend: `backend/venv/Scripts/python.exe -m pytest`)

| Layer | What | Approach |
|-------|------|----------|
| Unit | `fecha_entrada_mora` | RED first. Cover m3 (entry on day 14), day 31 (entry on day 5 of next month), day 3 of March (entry Mar 5), Feb 28 non-leap (entry Mar 1), Feb 29 leap (entry Mar 1), Dec 30 (entry Jan 5), Jan 2 (entry Jan 5). |
| Unit | Equivalence of `bounds_entrada_mora` | Loop over every `fm` and window endpoint across 2025-01..2028-12 (leap year included). Assert the bounds predicate equals `inicio <= fecha_entrada_mora(fm) <= fin`. |
| Integration | `resolver_ventana` via the endpoints | Test each 422 case. The existing `/reportes` tests must stay green without edits. |
| Integration | cartera | Cover: window membership, paid cuotas excluded, soft-deleted excluded, closed credit excluded, future clamp, deferred cuota not in past window, per-gestor sums and order, no `por_receptor` key. |
| Frontend | — | No test infra. Verify with `npx tsc --noEmit` and a manual check. |

Suggested slicing (400-line budget): PR1 = momentos utilities, resolver and interval mode for ingresos. PR2 = cartera endpoint. PR3 = frontend.

## Threat Matrix

N/A: this change has no routing, shell, subprocess, VCS/PR automation, executable-file classification or process-integration boundary. Both endpoints are read-only and admin-only.

## Migration / Rollout

No migration is required. Nothing derived is persisted, and there are no audit writes (read-only, so `audit_service` does not apply). The alias keeps old clients working during the frontend deploy.

## Open-item resolutions

- **Day-anchored fixed payment dates**: these are independent of this change. `fecha_maxima` is still a plain date, and `fecha_entrada_mora` depends only on it. There is one concrete edge. A day 30/31 anchor clamped to Feb 28/29 falls in Feb m1, not m2, so it enters mora Mar 1 instead of Mar 5. That is correct under the current `fecha_maxima` and is covered by the Feb unit cases.
- **overdue-evaluation Non-Goal delta**: this is handled in sdd-spec and is only referenced here.

## Open Questions

- [ ] Spec must encode D5 (clamp to today) and D8 (gestor-less cuotas count in totals only) as scenarios.
