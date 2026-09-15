# Design: Overdue evaluation at momento close

Proposal Engram #1006 (business rules binding). Computed-at-read, no migration, no job, single PR.

## Technical Approach

Momentos partition the calendar into ordered, contiguous ranges (m5 19-24, m1 25-29, m2 30..4, m3 5-13, m4 14-18), so "momento of `fecha_maxima` is closed at `hoy`" is equivalent to `fecha_maxima < inicio(momento(hoy))`. One pure function `fecha_limite_mora(hoy)` returns that bound; SQL consumers compare against it, row builders derive `en_mora` from it, and `vencido` keeps the old `fecha_maxima < hoy` meaning for the visual alert.

## Architecture Decisions

| # | Decision | Choice | Rejected | Rationale |
|---|---|---|---|---|
| 1 | Predicate home/shape | `momentos.py`: `fecha_limite_mora(hoy: date) -> date` (first day of the momento containing `hoy`) and `en_mora(fecha_maxima: date, hoy: date) -> bool = fecha_maxima < fecha_limite_mora(hoy)`. Derived from day thresholds only: day 1-4 -> day 30 of previous month, or day 1 of the current month when the previous month has < 30 days (February); day >= 30 -> 30; 25-29 -> 25; 19-24 -> 19; 14-18 -> 14; 5-13 -> 5. Dec->Jan: Jan 1-4 -> Dec 30 of previous year | Build on `get_periodo_momento`; fix it | `get_periodo_momento(y, 2, "m1")` raises (`date(y,2,29)`) in non-leap years and its Feb m2 start (`ultimo_dia`) overlaps m1. Fixing it changes `reportes.py` m2 filters (out of scope). The new function must agree with `get_momento` (tested pairwise), leaving the reports helper untouched |
| 2 | SQL usage | Each endpoint computes `hoy = hoy_bogota()` (already there) and `limite = fecha_limite_mora(hoy)` once; the predicate `Pago.fecha_maxima < hoy` becomes `Pago.fecha_maxima < limite` at clientes.py:56, :110 (share one `limite` at :48), :199 (own `limite` at :190) and pagos.py:954 | SQL CASE on day-of-month | Constant date bound stays index-friendly and identical across the four sites; zero SQL dialect risk (tests run on SQLite) |
| 3 | `PagoResponse.vencido` / `en_mora` | `bool = False` schema defaults; computed in the router where rows are built (project pattern: `_pago_row_a_dict`, virtual dict, `tipo_credito` precedent). Helper `_flags_mora(fecha_maxima, pagado, hoy) -> dict` returns `{"vencido": not pagado and fecha_maxima < hoy, "en_mora": not pagado and en_mora(fecha_maxima, hoy)}`; `_pago_row_a_dict(row, hoy)` merges it; virtual dict adds both `False`; `/alertas/vencidos` does `PagoResponse.model_validate(p).model_copy(update=_flags_mora(...))`. Other `model_validate(ORM)` sites keep `False` | `model_validator(mode="after")` calling `hoy_bogota()` inside the schema | Schema-level computation hides a clock in a DTO and couples 15 construction sites to time patching. The frontend reloads the list (`cargarPagos(false)`) after every mutation, so mutation responses never feed styling; `/alertas/proximos-vencer` rows are `>= hoy` so `False` is correct |
| 4 | Time injection in tests | `monkeypatch` fixture `fijar_hoy` in `tests/conftest.py`: `monkeypatch.setattr("app.routers.pagos.hoy_bogota", lambda: d)` and same for `app.routers.clientes.hoy_bogota`. Routers keep `from app.utils.fechas import hoy_bogota` and call `hoy_bogota()` once per request | `freezegun` dependency; injectable `hoy` via FastAPI `Depends` | Zero production change and zero new dependency; pytest built-in; patches exactly the symbol the endpoint consumes. A `Depends(get_hoy)` would touch 4 signatures for the same effect |
| 5 | Frontend styling | `PagosPage.tsx`: delete `isVencido` (131); line 532 -> `!p.vencido`, 533 -> `p.vencido && 'bg-red-50'`, 628 -> `p.vencido && 'text-danger font-bold'`, 656 -> `p.en_mora && <span ...>Vencido</span>`. `types/index.ts` `Pago`: `vencido: boolean; en_mora: boolean` (required, backend always emits). Delete `MoraBadge` (`ui/index.tsx:43-49`) and its unused import in `DashboardPage.tsx:4` | Keep `MoraBadge` with an `enMora` prop (proposal) | `MoraBadge` is never rendered anywhere (grep); deleting it removes the last browser-clock predicate with fewer lines than repurposing it |
| 6 | Dashboard / Header / Clientes | No logic change | — | They consume `total_pagos_vencidos`, `pagos` from `/alertas/vencidos` and the `al_dia` query param; semantics move with the backend |

## Data Flow

    hoy_bogota() -> hoy -> fecha_limite_mora(hoy) = limite
        |-- clientes.py x3 ..... Pago.fecha_maxima < limite  -> al_dia filter / override / detail
        |-- /alertas/vencidos .. Pago.fecha_maxima < limite  -> KPI, header badge, list (flags True)
        '-- listar_pagos / aplazados -> _pago_row_a_dict(row, hoy) -> vencido (fm < hoy), en_mora (fm < limite)
                                        _calcular_virtuales -> both False
    frontend: vencido -> bg-red-50 + red date ; en_mora -> "Vencido" badge ; no new Date()

## Interfaces / Contracts

```python
def fecha_limite_mora(hoy: date) -> date: ...   # inicio del momento que contiene `hoy`
def en_mora(fecha_maxima: date, hoy: date) -> bool:
    return fecha_maxima < fecha_limite_mora(hoy)
```

Invariant: `en_mora` implies `vencido` (`limite <= hoy`). Deferred rows carry their new `fecha_maxima`, so no special case. Partial payments: `pagado=False` rows evaluated identically.

## File Changes

| File | Action | Description |
|---|---|---|
| `backend/app/utils/momentos.py` | Modify | `fecha_limite_mora`, `en_mora` |
| `backend/app/schemas/pago.py` | Modify | `vencido: bool = False`, `en_mora: bool = False` |
| `backend/app/routers/pagos.py` | Modify | `_flags_mora`, `_pago_row_a_dict(row, hoy)` + 2 call sites (202, 308), virtual dict, `/alertas/vencidos` bound + flags |
| `backend/app/routers/clientes.py` | Modify | import; `limite` at 48/190; 3 predicates |
| `backend/tests/test_momentos.py` | Modify | `TestFechaLimiteMora`, `TestEnMora` |
| `backend/tests/conftest.py` | Modify | `fijar_hoy` fixture |
| `backend/tests/test_mora_momento_cerrado.py` | Create | endpoint scenarios (`client_factory` pattern from `test_aplazamientos.py`) |
| `frontend/src/types/index.ts`, `pages/Pagos/PagosPage.tsx`, `components/ui/index.tsx`, `pages/Dashboard/DashboardPage.tsx` | Modify | decision 5 |

## Testing Strategy (strict TDD backend, `backend/venv/Scripts/python.exe -m pytest`)

| Layer | Test | Asserts |
|---|---|---|
| Unit | `fecha_limite_mora` per momento: fin and fin+1 for m5/m1/m2/m3/m4 (Mar 2026); Mar 30, 31, Apr 1-4 -> Mar 30; Apr 5 -> Apr 5; Jan 1-4 2026 -> Dec 30 2025; Mar 1-4 2026 -> Mar 1 (Feb 28 days); Mar 1 2028 -> Mar 1 (leap); Feb 28 2026 / Feb 29 2028 -> Feb 25 | bound |
| Unit | `en_mora`: fm 27 vs hoy 28/29 False, 30 True; fm Apr 2 vs Apr 4 False, Apr 5 True; fm Feb 28 vs Mar 1 True; fm Dec 31 vs Jan 4 False, Jan 5 True; property: for every day of 2026-2028, `fecha_limite_mora(d)` is the first day `d'` <= d with `get_momento(d') == get_momento(d)` and `get_mes_momento` equal | agreement with `get_momento` |
| Integration | `/alertas/vencidos`: fm Mar 27 pending; `fijar_hoy(Mar 29)` -> empty, `total_pagos_vencidos == 0`; `fijar_hoy(Mar 30)` -> listed, `en_mora`/`vencido` True; fm Apr 2, hoy Apr 4 empty / Apr 5 listed | close-of-momento, cross-month |
| Integration | `GET /clientes?al_dia=` and `GET /clientes/{id}`: same dates; `al_dia` True on the 29th, False on the 30th; list filter and response override agree | rule 4 |
| Integration | Deferred: `veces_aplazado=1`, fm Apr 10; hoy Apr 13 not listed, Apr 14 listed | rule 3 |
| Integration | Partial: `capital_pagado > 0`, `pagado=False`, fm Mar 27, hoy Mar 30 listed | rule 5 |
| Integration | `GET /pagos` (anio/mes/momento of the row): hoy Mar 28 -> `vencido` True, `en_mora` False; projected row both False; `/pagos/aplazados` carries fields | rule 6/7 plumbing |
| Frontend | `cd frontend && npx tsc --noEmit`; manual: red row without badge inside momento, badge after close | type safety |

Existing `test_alerta_vencidos_excluye_credito_saldado` (fm = yesterday) stays green but becomes vacuous; re-pin it with `fijar_hoy` so the exclusion is still meaningful.

## Threat Matrix

N/A: no routing, shell, subprocess, VCS/PR automation, executable-file classification or process-integration boundary.

## Migration / Rollout

No migration, no data change. Single PR (~150-200 lines). On deploy the dashboard KPI, header badge and "En atraso" filter drop immediately for rows whose momento is still open (intended; tell the owner). Rollback: revert the PR; the two extra response fields are additive and ignored by an older frontend.

## Open Questions

- [ ] None blocking. `get_periodo_momento` February bug is left as-is (reports scope); recommend a follow-up change.

## Amendment (post Judgment Day, 2026-09-15)

Decision 3 was superseded during review (ledger I1/I4): the private `_flags_mora(fecha_maxima, pagado, hoy)`
became the shared `app.utils.momentos.flags_mora(fecha_maxima, pagado, hoy, limite)`, with `limite =
fecha_limite_mora(hoy)` computed once per request. `_pago_row_a_dict(row, hoy, limite)` takes the
precomputed bound, and `GET /creditos/{id}/cuotas` (`historial_cuotas`) also applies the flags via
`model_copy`, so every listing that returns `PagoResponse` carries correct `vencido`/`en_mora`. The
`fijar_hoy` fixture pins `hoy_bogota` in `pagos`, `clientes` and `creditos` routers.
