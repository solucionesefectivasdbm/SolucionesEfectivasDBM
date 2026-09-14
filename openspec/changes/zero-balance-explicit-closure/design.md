# Design: Zero-balance explicit closure (rule 14)

> Delta on `archive/2026-09-11-zero-balance-credit-closure/design.md`. Everything not
> mentioned here is unchanged: `esta_saldado`, `cerrar_credito`,
> `credito_operativamente_abierto`, the four `pago_service.py` call sites, rule 10 tail.

## Technical Approach

Rule 14 is an **operator-driven exception**, so it lives entirely on the explicit
confirm path. One new pure predicate (`puede_cerrar_con_interes_pendiente`) is the
single source of truth for the state, reused by the router branch, the response field,
and the service precondition — no client-side balance arithmetic. One new writer
(`cerrar_credito_con_interes_pendiente`) zeroes `saldo_intereses` and then delegates
`activo = False` to `cerrar_credito`, which stays byte-identical. Payment routes and
schemas are untouched; the frontend re-fetches the credit after a successful payment
and reads the backend field.

## Architecture Decisions

| Decision | Choice | Rejected | Rationale |
|---|---|---|---|
| Opt-in transport | Optional JSON body `CerrarCreditoRequest { cerrar_con_interes_pendiente: bool = False }`, declared `body: Optional[CerrarCreditoRequest] = Body(default=None)` | query param; required body | Codebase precedent `validar_pago` (`pagos.py:743`). `Body(default=None)` keeps no-body callers (existing tests, current frontend) working; `{}` and `null` also resolve to no flag. Name avoids "condonar" (owner, #892) and matches service/field names |
| State predicate | `puede_cerrar_con_interes_pendiente(credito)` in `credito_service.py`, next to `esta_saldado` | inline `and` in router + frontend | One rule, three consumers; the drift class the predecessor design already refused |
| Interest writer | New `cerrar_credito_con_interes_pendiente(credito) -> Decimal` calling `cerrar_credito` | `condonar_interes` param on `cerrar_credito` (3b) | `cerrar_credito` docstring and `test_cerrar_credito_no_escribe_saldos` remain literally true |
| Flag on a fully-settled credit | Ignored — normal close, one audit row | 422 "flag not applicable" | The list button reuses one modal; punishing a harmless flag adds a rejection with no business meaning |
| Audit | One `registrar_actualizacion_campos` call, `cambios={"activo": ("True","False"), "saldo_intereses": (str(prev), "0.00")}` | two calls | Helper loops fields → **two rows**, same transaction. Values are `str` so the `anterior != nuevo` skip behaves |
| Frontend detection | Read `puede_cerrar_con_interes_pendiente` from `GET /creditos/{id}` after payment | re-derive `cuota_fija && capital<=0 && interes>0` in TS | Field already exists for the list; zero duplicated logic (AGENTS.md: backend owns computed values) |
| Prompt UI | Shared presentational `ConfirmarCierreInteresPendiente` in `components/ui/` inside `<Modal>` with two named actions | `window.confirm`; per-page inline JSX | Two named actions, not OK/Cancel; same copy on two pages; existing `Modal` + `ConfirmarCreacion` precedent |

## Data Flow

    PagosPage ──POST pago──▶ pagos.py (unchanged) ──▶ 200
        │ success
        ├──GET /creditos/{id}──▶ _credito_response ──▶ puede_cerrar_con_interes_pendiente
        │                                                    │ true
        ▼                                                    ▼
    <ConfirmarCierreInteresPendiente>  "Seguir cobrando" → close dialog (no request)
        │ "Cerrar crédito"
        ▼
    POST /creditos/{id}/cerrar {cerrar_con_interes_pendiente: true}
        ▼
    confirmar_cierre_credito ─▶ cerrar_credito_con_interes_pendiente ─▶ cerrar_credito
                              └▶ registrar_actualizacion_campos (activo + saldo_intereses)

## Interfaces / Contracts

```python
# schemas/credito.py
class CerrarCreditoRequest(BaseModel):
    cerrar_con_interes_pendiente: bool = False

class CreditoResponse(BaseModel):
    ...
    pendiente_de_cierre: bool = False
    puede_cerrar_con_interes_pendiente: bool = False   # new

# services/credito_service.py — pure, sync
def puede_cerrar_con_interes_pendiente(credito: Credito) -> bool:
    """Regla 14: activo, cuota_fija, saldo_capital <= 0, saldo_intereses > 0.
    Mutuamente excluyente con esta_saldado por construcción."""

def cerrar_credito_con_interes_pendiente(credito: Credito) -> Decimal:
    """Regla 14: ÚNICO camino que escribe saldo_intereses al cerrar. Precondición:
    puede_cerrar_con_interes_pendiente(credito), si no ValueError. Captura el valor
    previo, fija 0.00, delega activo=False a cerrar_credito. Retorna el valor previo."""
```

`cerrar_credito` docstring: "ÚNICO escritor **físico** de `activo=False`. NUNCA escribe
saldos; la única excepción acotada es `cerrar_credito_con_interes_pendiente`, que
escribe `saldo_intereses` antes de delegar aquí (regla 14)."

`_credito_response`: add `resp.puede_cerrar_con_interes_pendiente =
puede_cerrar_con_interes_pendiente(credito)`. This is the sole constructor site
(`creditos.py:41`; six routes call it; no other `CreditoResponse.model_validate` in
`backend/app`).

### Router — validation order and `detail` copy (rule 13)

| # | Condition | Result |
|---|---|---|
| 1 | not found / soft-deleted | 404 `"Crédito no encontrado"` (unchanged) |
| 2 | `not activo` | 422 `"Este crédito ya está cerrado; el cierre no se puede confirmar dos veces."` (unchanged) |
| 3 | `saldo_capital > 0` **and** flag | 422 `"No se puede cerrar con interés pendiente: el crédito aún tiene capital pendiente de {saldo_capital}. Este cierre solo aplica cuando el capital está en cero."` (new) |
| 4 | `saldo_capital > 0` | 422 existing "…aún tiene capital pendiente de X [y interés pendiente de Y]." (unchanged) |
| 5 | `esta_saldado` | `cerrar_credito`; audit `activo` only; 200 (flag ignored) |
| 6 | `puede_cerrar_con_interes_pendiente` and flag | `cerrar_credito_con_interes_pendiente`; audit both fields; 200 |
| 7 | otherwise (interest pending, no flag) | 422 existing "…aún tiene interés pendiente de Y." (unchanged) |

Capital is checked (3-4) before the flag is honored (6), so the flag can never bypass
capital. `abono_capital` never reaches row 6: with capital > 0 it stops at 3/4, with
capital <= 0 it is settled (row 5).

### Frontend

- `types/index.ts`: `puede_cerrar_con_interes_pendiente: boolean` on `Credito`.
- `api/index.ts`: `cerrar: (id: string, data?: { cerrar_con_interes_pendiente: boolean }) => api.post<Credito>(`/creditos/${id}/cerrar`, data)` — `undefined` sends no body.
- `components/ui/ConfirmarCierreInteresPendiente.tsx` (export via `ui/index.tsx`):
  props `{ isOpen, credito: Credito | null, onCerrar, onSeguir, loading }`; renders
  `<Modal title="Cerrar crédito con interés pendiente">`, text
  `Crédito con saldo de capital en 0 pero interés pendiente de ${formatCOP(saldo_intereses)}. ¿Desea cerrarlo o seguir cobrando el interés pendiente?`,
  buttons `btn-ghost` "Seguir cobrando" (calls `onSeguir` only) and `btn-primary`
  "Cerrar crédito".
- `CreditosPage.tsx`: badge chain becomes Cerrado → `pendiente_de_cierre` (unchanged) →
  `puede_cerrar_con_interes_pendiente` → `<span className="badge-info" title="Capital en cero; el interés restante puede cerrarse o seguir cobrándose">Capital saldado · interés pendiente</span>` → Activo. Close button gate:
  `c.activo && (c.pendiente_de_cierre || c.puede_cerrar_con_interes_pendiente)`, same
  roles. Clicking on an interest-pending credit opens the new dialog instead of the
  existing `ConfirmDelete` modal; `onCerrar` calls `creditosApi.cerrar(id, { cerrar_con_interes_pendiente: true })`, toasts, `cargar()`.
- `PagosPage.tsx`: helper `verificarCierreInteresPendiente(creditoId)` → `creditosApi.obtener`, sets `creditoCierre` state when the field is true; errors swallowed (payment already succeeded; the list still offers the action). Called after success in `handleRegistrar` (non-decision branch, `pagoSeleccionado.credito_id`), `handleConfirmarExcedente` (same id), `handleNoProgramado` (`npCreditoId`). "Cerrar crédito" → `creditosApi.cerrar(id, {...true})`, toast, `cargarPagos(false)`; "Seguir cobrando" → clear state only.
- Backend `detail` rendered verbatim via `mensajeError` / `e.response?.data?.detail` (rule 13).

## File Changes

| File | Action | Description |
|---|---|---|
| `backend/app/schemas/credito.py` | Modify | `CerrarCreditoRequest`; `puede_cerrar_con_interes_pendiente` |
| `backend/app/services/credito_service.py` | Modify | predicate + writer; `cerrar_credito` docstring |
| `backend/app/routers/creditos.py` | Modify | body param, rows 3/5/6 branch, response field |
| `backend/tests/test_pago_service.py` | Modify | unit tests next to existing `cerrar_credito` tests |
| `backend/tests/test_creditos_router.py` | Modify | flag matrix in `TestConfirmarCierre` + response-field tests |
| `frontend/src/types/index.ts`, `api/index.ts` | Modify | field; optional body |
| `frontend/src/components/ui/ConfirmarCierreInteresPendiente.tsx`, `ui/index.tsx` | Create/Modify | shared two-action dialog |
| `frontend/src/pages/Creditos/CreditosPage.tsx` | Modify | badge, gate, dialog wiring |
| `frontend/src/pages/Pagos/PagosPage.tsx` | Modify | post-payment re-fetch + dialog |

## Testing Strategy (Strict TDD — RED first, backend)

| Layer | What | How |
|---|---|---|
| Unit | `puede_cerrar_con_interes_pendiente`: true only for active `cuota_fija` cap 0 / int > 0; false for settled, closed, cap > 0, `abono_capital` | Pure `Decimal` |
| Unit | Writer: zeroes `saldo_intereses`, `activo` False, returns previous; `ValueError` on cap > 0 / `abono_capital` / inactive | Pure |
| Unit | `cerrar_credito` existing tests untouched and green | — |
| Router | No body, `{}`, `{flag:false}` on cap 0 / int > 0 → 422, existing interest message | httpx |
| Router | Flag + cap 0 / int > 0 → 200, `saldo_intereses == "0.00"`, `activo` False, **two** `AuditLog` rows (`activo`, `saldo_intereses` with `valor_anterior` = previous) | httpx + `db_session` |
| Router | Flag + cap > 0 (`cuota_fija` and `abono_capital`) → 422, detail contains "capital" and the amount | httpx |
| Router | Flag + settled → 200, one audit row; flag + closed → 422 | httpx |
| Router | Roles: 3 allowed roles × flag path 200; `gestor` 403 | parametrize |
| Router | Response field: true on GET `/creditos/{id}` and list for the state; false after close and for settled credits; `pendiente_de_cierre` unchanged | httpx |
| Regression | Payment leaving cap 0 / int > 0 keeps `activo` True (existing integration test from predecessor) | already present |
| Frontend | `cd frontend && npx tsc --noEmit` | no runner |

Command: `backend/venv/Scripts/python.exe -m pytest` (Windows).

## Threat Matrix

N/A — no routing, shell, subprocess, VCS/PR automation, executable-file classification,
or process-integration boundary. The only boundary is the existing authenticated route
gaining an optional body, covered by the RBAC and capital-bypass RED tests.

## Migration / Rollout

No migration; no data backfill. Single PR to `main` (`stacked-to-main`). Revised
forecast ~335 lines (shared dialog component added): **400-line budget risk: Medium.
Chained PRs recommended: No. Decision needed before apply: No.** Rollback: revert; zeroed
interest is recoverable from the `saldo_intereses` audit row.

## Non-goals (restated)

Payment-path auto-close; `abono_capital`; enriching payment responses / `no-programado`
bare `PagoResponse`; reopening a closed credit.

## Open Questions

- [ ] None blocking.
