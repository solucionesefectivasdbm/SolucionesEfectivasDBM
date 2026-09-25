# Proposal: Corte de mora por momento original en pagos aplazados

## Intent

Ningún punto del backend usa `Pago.momento` (fijado una sola vez al crear el pago) para listar o evaluar mora; todo deriva el momento y el cierre de mora desde `Pago.fecha_maxima` ACTUAL, campo que el aplazamiento (`PATCH /pagos/{id}/fecha`) sobreescribe. Resultado: un pago aplazado migra al listado del nuevo momento y su corte de mora también se corre, ocultando atrasos reales. Se necesita un dato inmutable que preserve el momento y el cierre originales.

## Scope

### In Scope
- Columna `fecha_maxima_original` (Date, nullable) en `Pago`, fijada al crear el pago.
- `PATCH /pagos/{id}/fecha` (aplazamiento) NO toca esta columna.
- `recalcular_cuotas_futuras` (feature "editar días de pago") SÍ resincroniza esta columna — no es un aplazamiento, es un re-anclaje de plan.
- `momentos.py` (`en_mora`, `flags_mora`, `fecha_limite_mora`, `bounds_entrada_mora`) recibe `fecha_maxima_original` en los callers que evalúan mora/listado por momento.
- Callers a migrar: `GET /pagos`, `GET /pagos/alertas/vencidos`, 3 sitios `al_dia` en `clientes.py`, historial en `creditos.py`, `GET /reportes/cartera-vencida`.
- Migración Alembic vía `startup_create_tables` (patrón idempotente del proyecto).
- Backfill de pagos históricos aplazados: reconstruir desde `audit_log` (primer `valor_anterior` cronológico de `fecha_maxima` por pago); sin registro disponible → fallback a `fecha_maxima` actual, sin bloquear ni marcar para revisión manual.

### Out of Scope
- Reportes de recaudo real (`reportes.py` ingresos) que usan `fecha_maxima` para ventana de cobro efectivo — no es evaluación de mora, queda igual.
- Cambiar la etiqueta `momento` (m1..m5) o agregar cron — se mantiene el patrón "sin cron, cálculo al vuelo" del ítem 8.

## Capabilities

### New Capabilities
None.

### Modified Capabilities
- `pagos`: el cierre de mora y la pertenencia al momento de un pago se determinan por `fecha_maxima_original`, no por `fecha_maxima` vigente.
- `reportes`: `cartera-vencida` usa el mismo corte inmutable.

## Approach

Persistir `fecha_maxima_original` en `Pago`, fijada al crear el pago. Reutilizar las funciones ya probadas de `momentos.py` pasándoles este campo en lugar de `fecha_maxima` en todo cálculo de mora/momento. `recalcular_cuotas_futuras` la resincroniza porque representa un nuevo calendario legítimo, no un aplazamiento a solicitud del cliente. Backfill vía `audit_log`, con fallback documentado para pagos sin rastro de auditoría.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `backend/app/models/pago.py` | New | columna `fecha_maxima_original` |
| `backend/app/routers/pagos.py` (~877-930, ~246-335, ~1139-1197) | Modified | aplazamiento no toca la columna; listado y alertas usan la columna |
| `backend/app/utils/momentos.py` | Modified | callers de mora reciben la columna original |
| `backend/app/routers/clientes.py` (3 sitios `al_dia`) | Modified | mismo predicado con columna original |
| `backend/app/routers/creditos.py` | Modified | historial usa columna; `recalcular_cuotas_futuras` la resincroniza |
| `backend/app/routers/reportes.py` (~414-456) | Modified | `cartera-vencida` usa columna original |
| Migración Alembic / `main.py` | New | columna + backfill |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Cambio retroactivo de mora: pagos hoy protegidos por aplazamiento pasarán a mora al desplegar (mismo patrón que ítem 8) | High (esperado) | Avisar explícitamente antes del deploy; documentado como comportamiento pedido, no bug del fix |
| Backfill incompleto si algún aplazamiento no generó fila en `audit_log` | Medium | Fallback a `fecha_maxima` actual para ese pago puntual, sin bloquear (decisión ya tomada) |
| Regresión cruzada con "editar días de pago" si `recalcular_cuotas_futuras` no resincroniza la columna | Medium | Requisito explícito de diseño/tests: verificar resincronización en ese flujo |

## Rollback Plan

Revertir el PR de columna+lógica; la columna nueva es aditiva (nullable) y no rompe lecturas previas. Si el backfill produjo datos incorrectos en prod, se puede re-ejecutar el backfill (idempotente, solo lee `audit_log`/`fecha_maxima` y sobreescribe la columna nueva) sin tocar `fecha_maxima` vigente.

## Dependencies

- `audit_log` con historial completo de cambios a `fecha_maxima` para el backfill.

## Success Criteria

- [ ] Un pago aplazado sigue apareciendo en el listado de su momento original.
- [ ] Un pago aplazado que cruza el cierre del momento original cae en mora en ese momento.
- [ ] `recalcular_cuotas_futuras` resincroniza `fecha_maxima_original` sin quedar atado a un momento obsoleto.
- [ ] `cartera-vencida` refleja el mismo corte inmutable.
- [ ] Backfill corrido en prod sin bloqueos por pagos sin auditoría.

## Proposal question round

Sin bloqueos: las reglas de negocio ya fueron decididas con el usuario antes de esta fase. Puntos menores para confirmar en spec/design, no re-discutir intención:
1. ¿El backfill se expone como endpoint temporal admin-only (patrón ya usado) o como script/migración de datos ejecutada una vez?
2. ¿Se corre una query de verificación en prod antes del backfill para contar cuántos pagos con `veces_aplazado > 0` no tienen fila coincidente en `audit_log` (para dimensionar el riesgo del fallback)?
