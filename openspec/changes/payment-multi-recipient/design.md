# Design: Payment Multi-Recipient Split (item 10)

## Technical Approach

Add a satellite table, `pago_repartos`, keyed by `pago_id`. `Pago` rows are never duplicated. The invariant "1 Pago = 1 cuota" stays the same, and so do `_validar_split`, mora, `cerrar_credito` and `generar_siguiente_cuota`'s signature. For a **paid** pago, its active repartos are the only source of truth for where the money went. The item 9 ledger reads from them, still compute-on-read. For a **pending** pago, `Pago.cuenta_bancaria_id` keeps its current meaning: the planned destination that was inherited or assigned.

**Invariant I1**: every `pagado=True` pago with `cuenta_bancaria_id IS NOT NULL` and a total above 0 has at least one active reparto row, and the active rows sum **exactly** to `capital_pagado + interes_pagado`. Every write path maintains I1. The migration backfill establishes it for existing data.

## Architecture Decisions

| Decision | Choice | Rejected | Rationale |
|---|---|---|---|
| Storage | `pago_repartos` satellite table | N `Pago` rows per cuota | Keeps the per-cuota engine intact (the regression class from PRs #30-#39) |
| Write API | `PUT /pagos/{id}/repartos` replaces the whole set atomically | Per-row POST/PATCH/DELETE | The sum invariant cannot hold between separate row calls. Replacing the set covers create, edit and delete (owner decision 2) |
| Row removal | Soft delete (`AuditMixin.deleted_at`) plus one `audit_service.registrar_actualizacion_campos` entry on `pagos` | Physical DELETE; `correccion` rows | Follows the repo rule against physical deletes. There is still no correction flow (decision 2) |
| Sum check | Exact equality of quantized `Decimal` values | `_validar_split`'s `TOL=0.01` | The ledger must match `Pago` totals exactly. TOL only exists because of float inputs |
| When split allowed | Only when `pago.pagado=True` (otherwise 422) | Splitting pending pagos | The amount is unknown before registration. Pending pagos keep using the single planned cuenta |
| Default reparto | Registering a payment creates one row for 100% of the amount to `pago.cuenta_bancaria_id` (if set) | Registration accepts a split in the body | Keeps the registrar flow and the frontend unchanged. The split is done afterwards by the recaudador/admin, as "Modificar cuenta" works today |
| Legacy PATCH `/cuenta-bancaria` | Kept. On a paid pago it replaces the repartos with one 100% row | Removing it | Stays backward compatible and preserves I1 |
| Inheritance (decision 1) | `cuenta_heredable(repartos)` returns the recipient's `cuenta_bancaria_id` ONLY when the reparto has exactly 1 recipient row AND that row is `tipo_destinatario=cuenta_bancaria`. Every other case — 1 recipient of type `cliente`, or 2+ recipients of any type — returns `None` | Treating "1 recipient of any type" as inheriting | Owner decision (confirmed 2026-09-22, refined 2026-09-22 after a Judgment Day finding on PR2): inheritance only fires when the payment's single recipient IS a bank account. A single-cliente-recipient split has no cuenta to inherit, so it behaves like the multi-recipient case, not like the untouched single-cuenta case |
| Client recipient | Required FK to `clientes` and never touches `creditos` | Free text | Decision 3 |
| List filter (decision 4) | Correlated `EXISTS` on active repartos, OR for pending pagos the legacy column | Plain JOIN | A JOIN duplicates rows when two cuentas of one receptor share a pago |
| Backfill location | Inside the Alembic migration (`INSERT … SELECT`) | Temporary admin POST endpoint (AGENTS.md convention) | The ledger rewrite ships in the same deploy. A separate backfill would show zero balances until someone ran it |

## Data Model

`backend/app/models/pago_reparto.py`:

```python
class TipoDestinatario(str, enum.Enum):
    cuenta_bancaria = "cuenta_bancaria"; cliente = "cliente"

class PagoReparto(AuditMixin, Base):
    __tablename__ = "pago_repartos"
    id UUID pk; pago_id FK pagos NOT NULL (index)
    tipo_destinatario Enum(name="tipo_destinatario_reparto_enum") NOT NULL
    cuenta_bancaria_id FK cuentas_bancarias NULL (index); cliente_id FK clientes NULL
    monto Numeric(15,2) NOT NULL
    CHECK ck_pago_repartos_monto_positivo: monto > 0
    CHECK ck_pago_repartos_destinatario: (tipo='cuenta_bancaria' AND cuenta_bancaria_id IS NOT NULL AND cliente_id IS NULL)
                                      OR (tipo='cliente' AND cliente_id IS NOT NULL AND cuenta_bancaria_id IS NULL)
```

`Pago.repartos` relationship with `lazy="noload"`. Loading is always explicit and batched.

Migration `f6a7b8c9d0e1_create_pago_repartos.py` (down_revision `e5f6a7b8c9d0`): create the table, then backfill:

```sql
INSERT INTO pago_repartos (id, pago_id, tipo_destinatario, cuenta_bancaria_id, monto, created_at, updated_at)
SELECT gen_random_uuid(), id, 'cuenta_bancaria', cuenta_bancaria_id, capital_pagado + interes_pagado, now(), now()
FROM pagos WHERE pagado AND cuenta_bancaria_id IS NOT NULL AND capital_pagado + interes_pagado > 0;
```

The `> 0` filter is required because of the CHECK constraint. Zero-amount pagos add nothing to the ledger, so parity holds. `downgrade()` drops the indexes, the table and the enum type (same pattern as item 9).

## Services

- `backend/app/services/pago_reparto_service.py` (new):
  - `crear_reparto_por_defecto(db, pago)` enforces I1 at registration.
  - `reemplazar_repartos(db, pago, items) -> (antes, despues)` validates: pago is paid, at least 1 item, no duplicate recipient, cuentas and clientes exist and are not deleted (one `IN` query each), and the sum equals the amount exactly. It then soft-deletes the active rows, inserts the new ones and applies the inheritance rule.
  - `repartos_por_pago(db, pago_ids)` builds the batched response dict.
- `backend/app/services/pago_service.py`: `_pago_exacto`, `_pago_parcial`, `confirmar_excedente` and `registrar_pago_no_programado` (after the `flush`) call `crear_reparto_por_defecto`. `generar_siguiente_cuota` is **not** changed. At registration time the pago has only one cuenta, so inheritance works as today.
- `backend/app/services/receptor_ledger_service.saldos_por_cuenta`: the `recaudado` query becomes `SUM(PagoReparto.monto) JOIN Pago WHERE PagoReparto.cuenta_bancaria_id IN ids AND PagoReparto.deleted_at IS NULL AND Pago.pagado AND Pago.deleted_at IS NULL GROUP BY PagoReparto.cuenta_bancaria_id`. It stays one query with the same shape, has no N+1, and `cliente` rows are excluded by construction.

## Data Flow

    PUT /pagos/{id}/repartos (admin, recaudador)
      → _get_pago_con_credito(lock=True)        # serializes concurrent edits
      → reemplazar_repartos: validate → soft-delete old → insert new
      → h = cuenta_heredable(new)
          pago.cuenta_bancaria_id := h
          if h is None: next pending cuota (numero_cuota+1, not paid) whose
             cuenta == previous value → set to NULL   # explicit selection required
      → audit_service.registrar_actualizacion_campos(pagos, {"repartos": (antes, despues)})
      → 200 list[RepartoResponse]

If the split is a single cuenta, the next cuota is **not** rewritten. This matches today's PATCH, which never touches existing cuotas.

## Endpoints (`backend/app/routers/pagos.py`)

| Method | Path | Roles | PR |
|---|---|---|---|
| GET | `/pagos/{id}/repartos` | admin, recaudador | 2 |
| PUT | `/pagos/{id}/repartos` body `{repartos: RepartoItem[]}` | admin, recaudador | 2 |
| PATCH | `/pagos/{id}/cuenta-bancaria` (paid pago → single 100% reparto) | unchanged | 1 |
| GET | `/pagos` filters use EXISTS; the page's items get `repartos` from one batched query | unchanged | 2 |

`GET /pagos` filter: `EXISTS(reparto active AND cuenta_bancaria_id IN S) OR (NOT pagado AND Pago.cuenta_bancaria_id IN S)`. For `receptor_id`, S is the receptor's cuentas. For `cuenta_bancaria_id`, S is that single cuenta.

## Interfaces

```python
class RepartoItem(BaseModel):   # model_validator: exactly one id matching tipo
    tipo_destinatario: TipoDestinatario
    cuenta_bancaria_id: UUID | None = None; cliente_id: UUID | None = None
    monto: Decimal = Field(gt=0, decimal_places=2)
class RepartoResponse(RepartoItem): id: UUID; etiqueta: str   # etiqueta_cuenta / client full name
# PagoResponse += repartos: list[RepartoResponse] = []
```

## File Changes

| File | Action | PR |
|---|---|---|
| `backend/app/models/pago_reparto.py`, `models/pago.py`, `models/__init__.py` | Create/Modify | 1 |
| `backend/alembic/versions/f6a7b8c9d0e1_create_pago_repartos.py` | Create | 1 |
| `backend/app/services/pago_reparto_service.py` (default + helpers) | Create | 1 |
| `backend/app/services/pago_service.py`, `receptor_ledger_service.py` | Modify | 1 |
| `backend/app/routers/pagos.py` (PATCH sync) | Modify | 1 |
| `backend/app/schemas/pago_reparto.py`, `schemas/pago.py` | Create/Modify | 2 |
| `backend/app/services/pago_reparto_service.py` (replace + inheritance) | Modify | 2 |
| `backend/app/routers/pagos.py` (GET/PUT, EXISTS filter, batched repartos) | Modify | 2 |
| `backend/app/routers/reportes.py` (revenue grouping moves to `pago_repartos`, one row per cuenta per pago) | Modify | 2 |
| `frontend/src/types/index.ts`, `frontend/src/api/index.ts` | Modify | 3 |
| `frontend/src/components/pagos/RepartoPagoModal.tsx` | Create | 3 |
| `frontend/src/pages/Pagos/PagosPage.tsx` | Modify | 3 |

Frontend: the existing "Modificar cuenta" modal stays the same for pending pagos. For paid pagos it opens `RepartoPagoModal`, which has recipient search (receptor accounts through the existing `SelectCuentaBancaria`, clients through `clientesApi.listar({busqueda})`), per-row `monto` input, a live "asignado / restante" indicator, and a submit button that stays disabled until the remainder is 0. The component is extracted because `PagosPage.tsx` is already over 1000 lines.

## Testing Strategy

| Layer | What |
|---|---|
| Unit (ledger) | Parity: a single-cuenta paid pago gives the same saldo as before. A 2-cuenta split credits each share with no double counting. `cliente` rows are ignored. Soft-deleted repartos, `pagado=False` and deleted pagos are ignored. |
| Unit (service) | Sum is exact (±0.01 rejected). Duplicate recipient rejected. Unknown or deleted cuenta/cliente rejected. Pending pago → 422. Empty set → 422. Inheritance: 2+ recipients (cuenta+cuenta, or cuenta+cliente) clears the untouched next cuota; exactly 1 recipient leaves it alone; a manually changed next cuota is not touched. No `Credito` row is created for client recipients. |
| Integration | The 4 registration paths create the default row (I1). PATCH on a paid pago replaces the repartos. PUT returns 403 for `registrador`. The `GET /pagos` EXISTS filter matches a split pago under both cuentas exactly once, and still matches pending pagos by the legacy column. `reportes.py` attributes a split pago's revenue to each cuenta separately, matching the sum of its repartos. |
| Migration | Backfill SQL is checked manually on staging Postgres: Σ ledger before == after. |

## Threat Matrix

N/A: there is no routing, shell, subprocess, VCS/PR automation, executable-file classification or process-integration boundary. The only adversarial surface is authorization (the role tests above).

## Migration / Rollout

The PRs are sequential. Each targets `main` after the previous one merges (following the "no chained PRs" lesson).

- **PR1 – foundation, about 350 lines**: table, backfill, ledger rewrite, default reparto, PATCH sync. No visible change, and ledger parity is guaranteed.
- **PR2 – split API, about 350 lines**: schemas, GET/PUT, inheritance rule, filter semantics, batched `repartos` in the list, `reportes.py` revenue grouping rewrite.
- **PR3 – frontend, about 350 lines**.

Rollback: revert the PR. PR1's `downgrade()` drops the table and the ledger falls back to the reverted query on `Pago.cuenta_bancaria_id`, which is never modified by the backfill.

## Open Questions — resolved 2026-09-22

- [x] `reportes.py` groups revenue by `Pago.cuenta_bancaria_id`. **Owner decision**: a split pago must appear under EACH cuenta it corresponds to, for the amount that cuenta received from that specific pago. Moves to `pago_repartos` in PR2 (same PR as the ledger/filter rewrite, since both read from the same table).
- [x] Inheritance criterion. **Owner decision (refined 2026-09-22)**: today's inheritance (`generar_siguiente_cuota` carrying `pago.cuenta_bancaria_id` forward) is unchanged ONLY when the payment's single recipient is a `cuenta_bancaria`. It breaks (next cuota gets `None`) in every other case: 2+ recipients of any type (cuenta A + cliente X, cuenta A + cuenta B), AND a single recipient of type `cliente`. See the corrected "Inheritance" row in Key Decisions above.
- [x] Verify that prod Postgres is version 13 or later (`gen_random_uuid()` is built in from 13). Confirmed 2026-09-22: prod runs PostgreSQL 18 (Railway).
- [ ] Moving money between cuentas through a split can leave a cuenta's item 9 balance negative after previous `salida`s. This is the same as today's PATCH (item 9 decision 2), so there is no overdraft check.
