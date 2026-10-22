# Exploration: recaudo-registra-montos-registrador-supervisa

Full artifact also in Engram: `sdd/recaudo-registra-montos-registrador-supervisa/explore` (obs #1180).

## Current State

- Role enum value is `recaudador` (backend/app/models/usuario.py:21-22). `require_role` in backend/app/dependencies.py:73.
- Amount registration (admin + registrador) in backend/app/routers/pagos.py: `POST /{id}/registrar` (l.700-705), `POST /{id}/confirmar-excedente` (l.758-763), `POST /no-programado/{credito_id}` (l.1059-1064).
- Check validation/reversion (admin + recaudador): `validar` (l.861), `desvalidar` (l.813), `PATCH fecha` (l.893), `PATCH cuenta-bancaria` (l.949), `GET/PUT repartos` (l.994, 1006).
- Frontend: `canValidarPago` (admin, recaudador) and `canRegistrarPago` (admin, registrador) in frontend/src/store/authStore.ts:85-86; buttons in frontend/src/pages/Pagos/PagosPage.tsx (:525, :783, :794, :809, :827). One shared page serves the semanal and diario variants.
- `registrar` requires `validado_recaudador` (pagos.py:722) and an active credit, then calls `PagoService._pago_exacto` / `_pago_parcial` / `confirmar_excedente` (pago_service.py:199, 247, 321): sets pagado/montos/fecha_pago_real, creates a default 100% `pago_repartos` row, reduces `credito.saldo_capital`/`saldo_intereses` (floor at 0, lossy), may close the credit, and generates cuota N+1 (`generar_siguiente_cuota`, credito_service.py:574).
- Receptor ledger is computed on read (`saldos_por_cuenta`, receptor_ledger_service.py:68) from `pago_repartos` JOIN `Pago` with `pagado=True`; reverting a payment corrects it automatically.
- `desvalidar` reverts only the check and is rejected if the pago is paid or has montos > 0. No amount-reversal logic exists in backend/app.
- No `registrado_por` field on Pago; the only trail is audit_log (indirect, fragile).
- Tests: no 403 tests for `/registrar`; only one router test (test_pagos_cuenta_bancaria.py:394). No frontend tests.

## Cascade facts

- Cuota N+1 is generated only when N is paid, so normally one unpaid programada cuota exists per credit. `no_programada` payments interleave and take `max(numero_cuota)+1`; order reversals by `fecha_pago_real`/`created_at`, not `numero_cuota`.
- Restoring saldos must be by recompute, not inverse (floor at 0, excedente split). `recalcular_saldo_intereses` (credito_service.py:806) is wrong for excedente-to-intereses. History of drift incidents (PRs #30-#33, #36-#39).
- Regla 14 explicit closure zeroes `saldo_intereses` irrecoverably (value survives only in audit_log).
- `recalcular_cuota_actual_si_no_pagada` (credito_service.py:844) re-derives arrastre for the first unpaid cuota with zero montos.

## Approaches

1. **A: LIFO-guarded revert (recommended).** Only the latest registered programada cuota whose N+1 is unpaid with no montos; restore N, soft-delete N+1, recompute saldos, reopen credit if closed, audit. Small and safe; cannot revert older payments without reverting later ones first.
2. **B: Full cascade.** Revert N and all later registered cuotas in reverse order, then recompute. Heavy, high drift/negative-ledger risk.
3. **C: Edit amounts and recompute forward.** Not what was requested; needs the same engine as B.

Identification of who registered: add nullable `registrado_por_id` (+ role) on pagos, no backfill (recommended) vs derive from audit_log.

## Risks

Saldo drift if inverting; regla 14 closure irreversible without audit data; loss of N+1 state (check, aplazamientos); receptor ledger may go negative if money already paid out; numero_cuota ordering vs no_programada; segregation of duties (recaudador validates and registers its own check); migration mechanism ambiguity (AGENTS.md says startup hook, repo uses alembic via start.sh); concurrency (use FOR UPDATE).

## Open business questions (ranked)

1. Revert depth: LIFO-blocked vs full cascade; N+1 deleted/regenerated vs kept/recomputed.
2. Scope: may registrador revert any amount or only those registered by recaudador?
3. Check state after reverting an amount: validated-unpaid or unvalidated?
4. Segregation: may recaudador register on checks validated by others, revert its own, and use no_programado/excedente?
5. Closed credits: reopen on revert? What about regla 14 closures?
6. Receptor ledger: block or allow negative balance if money already paid out?
7. Mandatory reason on reversal?
