# Delta for Pagos

## ADDED Requirements

### Requirement: Persistencia de fecha_maxima_original

El sistema DEBE persistir `Pago.fecha_maxima_original` (Date, nullable) al crear cada pago, copiando el valor inicial de `fecha_maxima`. Este campo es inmutable ante aplazamientos puntuales.

#### Scenario: Creación de pago fija el corte original

- GIVEN se crea un nuevo `Pago` con `fecha_maxima` = X
- WHEN el pago se persiste
- THEN `fecha_maxima_original` queda igual a X

#### Scenario: Aplazamiento puntual no modifica el corte original

- GIVEN un `Pago` existente con `fecha_maxima_original` = X
- WHEN se llama `PATCH /pagos/{id}/fecha` para mover `fecha_maxima` a una fecha Y posterior
- THEN `fecha_maxima` queda en Y
- AND `fecha_maxima_original` permanece en X sin cambios

### Requirement: Resincronización en recalculo de plan

Cuando `recalcular_cuotas_futuras` (feature "editar días de pago") re-ancla el calendario de cuotas futuras, el sistema DEBE actualizar `fecha_maxima_original` al nuevo valor de `fecha_maxima`, dado que representa un nuevo plan legítimo y no un aplazamiento puntual.

#### Scenario: Recalculo de días de pago resincroniza el corte

- GIVEN un `Pago` futuro con `fecha_maxima_original` = X
- WHEN `recalcular_cuotas_futuras` reasigna `fecha_maxima` a Z por cambio de días-ancla del crédito
- THEN `fecha_maxima_original` se actualiza a Z

## MODIFIED Requirements

### Requirement: Listado y filtrado por momento

`GET /pagos` y cualquier filtro por momento DEBEN agrupar y filtrar cada pago usando `fecha_maxima_original`, no `fecha_maxima` vigente, para que el pago permanezca en el listado de su momento original aunque haya sido aplazado.
(Previously: el agrupamiento por momento usaba `fecha_maxima` vigente, lo que migraba pagos aplazados a un momento distinto)

#### Scenario: Pago aplazado permanece en su momento original

- GIVEN un `Pago` cuyo momento original es M1 (derivado de `fecha_maxima_original`)
- WHEN se aplaza su `fecha_maxima` a una fecha que cae en el rango de M2
- AND se consulta `GET /pagos` filtrando por momento M1
- THEN el pago sigue apareciendo en el listado de M1

### Requirement: Evaluación de mora por corte del momento original

`en_mora()`, `flags_mora`, `fecha_limite_mora`, `bounds_entrada_mora`, y la evaluación programada por momento (feature ítem 8) DEBEN recibir `fecha_maxima_original` como corte del momento, en vez de `fecha_maxima` vigente. Si la fecha aplazada cae después del cierre derivado de `fecha_maxima_original`, el pago cuenta en mora para ese momento sin importar que la fecha aplazada aún no haya llegado.
(Previously: estas funciones recibían `fecha_maxima` vigente, corriendo el cierre de mora junto con el aplazamiento)

#### Scenario: Pago aplazado más allá del cierre cuenta en mora

- GIVEN un `Pago` con `fecha_maxima_original` = X, cuyo cierre de mora del momento es C (derivado de X)
- WHEN se aplaza `fecha_maxima` a una fecha Y > C, con Y todavía en el futuro respecto a la fecha de evaluación
- AND se evalúa `en_mora()` para ese momento
- THEN el pago se marca en mora, aunque la fecha Y aplazada no haya llegado aún

#### Scenario: Pago no aplazado se evalúa igual que antes

- GIVEN un `Pago` sin aplazamientos, donde `fecha_maxima_original` == `fecha_maxima`
- WHEN se evalúa `en_mora()`
- THEN el resultado es idéntico al comportamiento previo al cambio

### Requirement: Consistencia entre endpoints de mora y cartera

`alertas/vencidos`, los 3 predicados `al_dia` en `clientes.py`, el historial en `creditos.py`, y `reportes/cartera-vencida` DEBEN aplicar el mismo corte basado en `fecha_maxima_original` que `GET /pagos` y `en_mora()`.
(Previously: cada sitio derivaba el corte de `fecha_maxima` vigente de forma independiente)

#### Scenario: Cartera vencida refleja el corte inmutable

- GIVEN un `Pago` aplazado más allá del cierre de su momento original
- WHEN se consulta `GET /reportes/cartera-vencida` para ese momento
- THEN el pago aparece como vencido, igual que en `en_mora()` y `alertas/vencidos`

#### Scenario: Riesgo aceptado — pago pasa de al día a en mora tras el despliegue

- GIVEN un `Pago` marcado "al día" antes del despliegue, aplazado previamente más allá del cierre de su momento original
- WHEN se despliega el cambio y se re-evalúa mora usando `fecha_maxima_original`
- THEN el pago pasa a estar en mora inmediatamente
- AND este comportamiento es esperado y documentado, no un bug

## Backfill Requirements

### Requirement: Reconstrucción de fecha_maxima_original desde audit_log

El sistema DEBE exponer un endpoint temporal POST admin-only que reconstruya `fecha_maxima_original` para pagos existentes, usando el primer `valor_anterior` cronológico de `audit_log` para el campo `fecha_maxima` de ese pago; si no existe fila de auditoría coincidente, DEBE usar como fallback el `fecha_maxima` actual del pago.

#### Scenario: Backfill reconstruye desde auditoría

- GIVEN un `Pago` con múltiples cambios históricos de `fecha_maxima` registrados en `audit_log`
- WHEN se ejecuta el backfill
- THEN `fecha_maxima_original` se fija al primer `valor_anterior` cronológico registrado

#### Scenario: Backfill sin fila de auditoría usa fallback

- GIVEN un `Pago` sin ninguna fila en `audit_log` para el campo `fecha_maxima`
- WHEN se ejecuta el backfill
- THEN `fecha_maxima_original` se fija al valor actual de `fecha_maxima`

### Requirement: Verificación previa al backfill

El sistema DEBE proveer un paso de verificación (conteo) que reporte cuántos pagos no tienen fila coincidente en `audit_log` antes de ejecutar el backfill real, para dimensionar el fallback antes de aplicarlo.

#### Scenario: Conteo previo informa cobertura de auditoría

- GIVEN pagos existentes en la base de datos
- WHEN se ejecuta el paso de verificación
- THEN se retorna el número total de pagos y cuántos de ellos carecerán de fila coincidente en `audit_log` (usarán fallback)
