# Design: Carry-over scope fixes (Bug A + Bug B)

Proposal Approach 1 (Engram #993). Migration-free. All money `Decimal`, `0.01`, `ROUND_HALF_UP`.

## Technical Approach

- **Bug A**: expose `tipo_credito` on list payloads only, scope the UI lock and the backend rule-13 message to `cuota_fija`. Backend `_validar_split` stays the authority; the UI guard is a convenience.
- **Bug B**: one pure predicate `_es_cuota_fija_fuera_de_plazo(credito, numero)` decides "past-term" at BOTH shape-deciding sites (`_siguiente_cuota_fija`, `recalcular_cuota_actual_si_no_pagada`). Past-term successor = base capital + base interest, no arrastre, uncapped, `programada` (rule 15). Rule 14 tail (`saldo_capital <= 0`) keeps precedence.
- **Backfill**: temp admin endpoint, same shape as PR #31/#32, deleted in PR-C.

## Architecture Decisions

| # | Decision | Choice | Rejected | Rationale |
|---|---|---|---|---|
| 1 | `PagoResponse.tipo_credito` | `Optional[TipoCredito] = None` (import `app.models.credito.TipoCredito`) | Required field; `@property` on `Pago` | `PagoResponse.model_validate(<ORM Pago>)` runs in `registrar`, `confirmar-excedente`, `desvalidar`, `validar`, `fecha`, `receptor`, `no-programado`, `creditos/{id}/cuotas`, `alertas`. `Pago` has no `tipo_credito`; a required field 500s them all; a relationship property lazy-loads in async (`MissingGreenlet`). Only list rows feed `pagoSeleccionado`, so populating list + virtual rows is sufficient |
| 2 | Population | `Credito.tipo_credito.label("tipo_credito")` appended to both SELECTs (`listar_pagos`, `listar_aplazados`, `Credito` already joined); `_pago_row_a_dict` adds `"tipo_credito": row.tipo_credito`; `_calcular_virtuales` dict adds `"tipo_credito": credito.tipo_credito` | Extra query per row | Zero extra round-trips; virtual rows already hold `credito` |
| 3 | Frontend guard | `Pago.tipo_credito?: TipoCredito \| null`; `const soloInteresCuotaFija = pagoSeleccionado.tipo_credito === 'cuota_fija' && pagoSeleccionado.tipo_cuota === 'interes'` drives `disabled` and the hint (PagosPage.tsx:689-695). Null -> input enabled (fail-open) | `capital_a_pagar <= 0` | Identical to buggy predicate (exploration approach 3). Fail-open is safe: backend rejects invalid exact splits with the correct message. Covers `/pagos/diarios` (same component) |
| 4 | `_validar_split` signature | Add keyword `tipo_credito: "TipoCredito \| None" = None` (last param). All THREE call sites pass `tipo_credito=credito.tipo_credito`: `_pago_exacto` (185), `_pago_parcial` (227), `confirmar_excedente` (299). No other callers (grep: only tests) | Pass `credito` | Keeps the helper pure/unit-testable with `make_pago`; default keeps `test_pago_service_arrastre.py` compiling |
| 5 | Message branching (`capital_a_pagar <= 0` on exact split) | `cuota_fija` -> existing rule-13 text ("...capital ... ya fue saldado"). `abono_capital` -> "Esta cuota es la de interés del ciclo; el capital de este crédito no está saldado, pero en un pago exacto debe registrarse en la cuota de abono. Para abonar capital aquí, registre un pago parcial." `None` -> generic component/tolerance message | Same text for all | Message must be factually true per credit type; `None` never occurs in production paths |
| 6 | Carve-out placement in `_siguiente_cuota_fija` | After `saldo_capital <= 0` return, before base computation: `if _es_cuota_fija_fuera_de_plazo(credito, numero): arr_cap = arr_int = 0` else `desglosar_arrastre(...)`. Same `es_ultima` formula (`saldo_capital <= capital_a_pagar and saldo_intereses <= interes_a_pagar`), `tipo_cuota=programada` | Before tail check | Rule 14 (capital settled) dominates rule 15; a past-term row with capital settled must still be interest-only |
| 7 | `saldo_a_arrastrar` ownership | `_pago_parcial` UNCHANGED; still passes `faltante`; generator ignores it when past-term | Zero at caller | Generator already ignores `saldo_pendiente` for the tail and abono successors; recalculation has no caller-supplied value, so the generator/recalc pair is the single source of truth via the shared predicate |
| 8 | `recalcular_cuota_actual_si_no_pagada` | In the `elif cuota_fija and numero_cuotas` branch: when `_es_cuota_fija_fuera_de_plazo(credito, actual.numero_cuota)` skip the walk-back query and use `arr_cap = arr_int = 0`; rest unchanged | Query then discard | Avoids a useless DB call; keeps rule-14 branch (line 860) first |
| 9 | Predicate | `def _es_cuota_fija_fuera_de_plazo(credito, numero) -> bool: return credito.tipo_credito == cuota_fija and credito.numero_cuotas is not None and numero > credito.numero_cuotas` (next to `desglosar_arrastre`) | Inline twice | Exploration risk: two sites diverging again |
| 10 | Backfill | `POST /pagos/admin/backfill-cuota-fija-fuera-de-plazo`, `require_role("admin")`, `dry_run: bool = Query(True)`, `# TEMPORAL` banner at end of `pagos.py` | Hardcode credit id | Must scan ALL qualifying rows |

## Data Flow

    listar_pagos / listar_aplazados ─SELECT +Credito.tipo_credito─> _pago_row_a_dict ─> PagoResponse(tipo_credito)
    _calcular_virtuales ────────────"tipo_credito": credito.tipo_credito─┘            └─> Pago (frontend) -> guard

    _pago_parcial(faltante) -> generar_siguiente_cuota -> _siguiente_cuota_fija
        ├─ saldo_capital <= 0 ............ _siguiente_cuota_fija_solo_interes (rule 14, unchanged)
        ├─ _es_cuota_fija_fuera_de_plazo . base cap + base int, arrastre 0 (rule 15)  <- NEW
        └─ else ......................... base + desglosar_arrastre (unchanged)
    admin edit -> recalcular_cuota_actual_si_no_pagada -> same three-way branch

## Interfaces / Contracts

Backfill predicate (SQL): `p.deleted_at IS NULL AND p.pagado = false AND p.capital_pagado = 0 AND p.interes_pagado = 0 AND p.tipo_cuota = 'programada' AND c.tipo_credito = 'cuota_fija' AND c.numero_cuotas IS NOT NULL AND p.numero_cuota > c.numero_cuotas AND c.saldo_capital > 0 AND c.activo = true AND c.deleted_at IS NULL`.
Python filter: `capital_a_pagar > base_cap + TOL or interes_a_pagar > base_int + TOL` with `base_cap = calcular_capital_cuota_fija(capital_prestado, numero_cuotas)`, `base_int = calcular_interes_cuota_fija(capital_prestado, tasa_interes_mensual, periodicidad)`.
Write (apply only): `capital_a_pagar = base_cap`, `interes_a_pagar = base_int`, `monto_a_pagar = base_cap + base_int`, `es_ultimo_pago` recomputed; `Credito` saldos never written. Audit: `audit_service.registrar_actualizacion_campos(db, "pago", pago.id, current_user.id, ip, cambios)`.
Response: `{dry_run, revisados, corregidos, detalle: [{pago_id, credito_id, numero_credito_cliente, numero_cuota, antes: {capital, interes, monto}, despues: {...}}]}`. Idempotent: corrected rows equal base and drop out.

## File Changes

| File | PR | Action |
|---|---|---|
| `backend/app/schemas/pago.py` | A | `tipo_credito: Optional[TipoCredito] = None` |
| `backend/app/routers/pagos.py` | A | two SELECTs, `_pago_row_a_dict`, virtual dict |
| `backend/app/services/pago_service.py` | A | `_validar_split` param + branching; three call sites |
| `frontend/src/types/index.ts`, `frontend/src/pages/Pagos/PagosPage.tsx` | A | type field; guard |
| `backend/tests/test_pago_service.py`, `backend/tests/test_pagos_listado.py` | A | tests |
| `backend/app/services/credito_service.py` | B | predicate; two carve-outs |
| `backend/tests/test_credito_service.py`, `backend/tests/test_pago_service.py` | B | tests |
| `backend/app/routers/pagos.py`, `backend/tests/test_pagos_backfill_fuera_de_plazo.py` | B create / C delete | endpoint + tests |
| `openspec/specs/{payment-carryover,credit-closure,abono-capital-carryover}/spec.md` | A/B | delta specs |

## Testing Strategy (strict TDD, `backend/venv/Scripts/python.exe -m pytest`)

| PR | Test (file) | Asserts |
|---|---|---|
| A | `TestValidarSplit` (`test_pago_service.py`): existing rule-13 test passes `tipo_credito=cuota_fija`; new `abono_capital` exact split with capital -> `ValueError` without "saldado", contains "abono"; `None` -> generic message; partial split on abono interés cuota passes | messages scoped |
| A | `test_pago_service.py` integration: `registrar_pago` partial on `abono_capital` interés cuota with capital > 0 accepted (AsyncMock db) | regression |
| A | `test_pagos_listado.py`: real row and virtual row carry `tipo_credito`; `/pagos/aplazados` row carries it | plumbing |
| B | `test_credito_service.py`: `_es_cuota_fija_fuera_de_plazo` (cuota_fija N+1 true, N false, abono_capital false, `numero_cuotas=None` false); `_siguiente_cuota_fija` numero 13/12 with `saldo_pendiente=5000` -> base values, `monto == cap + int`, `programada`; capital settled + past-term -> `interes` tail (rule 14 precedence); `recalcular_cuota_actual_si_no_pagada` past-term row after partial previous row keeps base (`db_session`, pattern `TestRecalcularCuotaActualSoloInteres`) | rule 15 |
| B | `test_pago_service.py`: `test_ultima_cuota_pagada_parcial_con_capital_pendiente_genera_base` sibling of line 449 (pay 8000+3600 on 12/12 -> cuota 13 = 10000/3600/13600) | Sanabria case |
| B | `test_pagos_backfill_fuera_de_plazo.py` (`client_factory` pattern from `test_desvalidar_pago.py`): dry-run lists row, writes nothing; apply corrects + audit row; re-run no-op; regular/paid/abono_capital/base rows untouched; non-admin 403 | backfill |
| A | frontend: `cd frontend && npx tsc --noEmit` | type safety |

## Threat Matrix

N/A: no routing, shell, subprocess, VCS/PR automation, executable-file classification or process-integration boundary. Admin route covered by the RBAC test.

## Migration / Rollout

No schema change. Three independent PRs off `main`, each merged before the next branch is cut: PR-A Bug A (~170 lines incl. tests, Low); PR-B Bug B + backfill (~330, Medium: ~120 fix+tests, ~210 endpoint+tests); PR-C delete endpoint + test (negative, Low). After PR-B deploy: dry-run, verify Sanabria row listed, apply once, re-run no-op, then PR-C. Rollback: revert a PR alone; backfill touches only unpaid `Pago` components, audited.

## Open Questions

- [ ] None blocking. PR-B is near the 400 budget; if `sdd-tasks` forecasts High, split the backfill into its own PR (mirrors PR #31/#32).
