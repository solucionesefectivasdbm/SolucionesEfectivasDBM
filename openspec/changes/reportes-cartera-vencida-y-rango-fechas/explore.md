# Exploration: Reportes — Cartera Vencida + filtro por intervalo de días (fusión items 13+14)

Change: `reportes-cartera-vencida-y-rango-fechas` — fusión de item 13 (recaudo diario/distribución,
descartado como reporte separado) e item 14 (cartera vencida) sobre la sección Reportes existente.

## Current State

**Frontend** `frontend/src/pages/Reportes/ReportesPage.tsx`: un solo modo de filtro
(año + mes + momento, dropdown `MOMENTOS` de `frontend/src/utils/formatters.ts:55-61`,
values `m1..m5`). Llama `reportesApi.generar({anio, mes, momento})` →
`GET /reportes` (`frontend/src/api/index.ts:162-165`, tipado `{anio,mes,momento}` sin
soporte de rango). Renderiza: 3 tarjetas de totales (recaudado/pendiente/esperado con
sub-desglose capital/intereses), tabla "Desglose por Gestor", tabla "Desglose por
Receptor" con `por_cuenta` anidado.

**Backend** `backend/app/routers/reportes.py` (único endpoint `GET /reportes`, ~300
líneas): resuelve `fecha_inicio, fecha_fin = get_periodo_momento(anio, mes, momento)`,
trae TODOS los `Pago` con `fecha_maxima` en ese rango (`deleted_at IS NULL`), separa
`pagados`/`pendientes` en Python, agrega por gestor y por receptor/cuenta (usando
`PagoReparto` para el lado recaudado desde item 10, y `Pago.cuenta_bancaria_id` legacy
para el lado pendiente). **No referencia `vencido`/`en_mora`/mora en absoluto** — es
puramente "cuotas cuyo vencimiento cae en esta ventana", partidas por estado de pago.
El grep confirma: `reportes.py` no aparece entre los archivos que mencionan
atraso/mora/overdue. Esto coincide con el Non-Goal explícito de `scheduled-overdue-evaluation`:
"...changes to momento ranges, closure rules, or deferral semantics" y "report changes"
quedaron fuera de esa change.

**Capacidad `overdue-evaluation`** (`openspec/specs/overdue-evaluation/spec.md`,
implementada en `backend/app/utils/momentos.py` + `backend/app/routers/pagos.py`):
- `get_momento(fecha)`, `get_mes_momento(fecha)`, `get_periodo_momento(anio,mes,momento)`
  ya existen y dan el rango (inicio,fin) de un momento.
- `fecha_limite_mora(hoy)` = primer día del momento que contiene `hoy`.
- `en_mora(fecha_maxima, hoy) = fecha_maxima < fecha_limite_mora(hoy)`.
- `flags_mora(fecha_maxima, pagado, hoy, limite)` retorna `{vencido, en_mora}`.
- Todo se computa EN LECTURA (read-time), NUNCA persistido, sin job/cron. No existe
  columna `en_mora`/`estado_atraso` en BD, ni fecha de "entrada a mora" almacenada.
- Consumido hoy en: `/pagos` (listado principal), `/pagos/alertas/vencidos`
  (`backend/app/routers/pagos.py:1126-1170`): query SQL directa
  `Pago.pagado==False AND Pago.fecha_maxima < limite AND deleted_at IS NULL AND
  credito_operativamente_abierto()`, con scoping por gestor. Esto confirma que
  `en_mora` a nivel SQL es simplemente `fecha_maxima < limite` cuando `pagado=False`
  — no requiere cómputo Python fila-por-fila para filtrar.
- **No existe hoy ninguna función `fecha_entrada_mora(fecha_maxima)`** (fecha en que
  una cuota impaga entra en mora = día siguiente al `fin` del momento que contiene su
  `fecha_maxima`). Es derivable trivialmente con las utilidades existentes
  (`get_momento` + `get_mes_momento` + `get_periodo_momento` → `fin + 1 día`), pero
  hay que añadirla.

**Precedente de filtro por rango de fechas**: `backend/app/routers/auditoria.py:25-26,44-47`
ya acepta `fecha_desde`/`fecha_hasta` (Query opcionales, `date`) y filtra
`>=`/`<=` directo sobre una columna. Es el nombre/patrón a reutilizar para el nuevo
modo "por intervalo de días" en `/reportes` (en vez de reinventar naming).

**Deferrals** (`openspec/specs/payment-deferral-tracking/spec.md`): un pago aplazado
se evalúa SOLO contra su `fecha_maxima` ACTUAL — no hay historial de fechas anteriores
(solo el contador `veces_aplazado`, sin fecha original, sin tabla de historial, "no
backfill" es Non-Goal explícito). Implicación directa para el nuevo reporte: si una
cuota entró en mora en agosto y luego fue aplazada a una fecha futura y sigue impaga,
su `fecha_entrada_mora` recalculada ya NO cae en la ventana de agosto — el reporte de
"cartera vencida por intervalo" es inherentemente un snapshot "vivo" (recalculado con
el estado actual de `fecha_maxima`), no una reconstrucción histórica fiel de cuándo
cada cuota entró en mora la primera vez. Esto es coherente con el patrón ya adoptado
por el proyecto (computar en vivo, nunca persistir estado derivado — ver
`Cliente.al_dia` abandonado por la misma razón), pero debe confirmarse explícitamente
con el owner como regla de negocio aceptada, no asumida.

## Affected Areas
- `backend/app/routers/reportes.py` — único endpoint hoy; necesita nuevo modo de
  filtro (intervalo) para el reporte existente y una rama/endpoint nuevo para cartera
  vencida.
- `backend/app/utils/momentos.py` — añadir `fecha_entrada_mora(fecha_maxima) -> date`
  (o equivalente), reusando `get_momento`/`get_mes_momento`/`get_periodo_momento`.
- `frontend/src/pages/Reportes/ReportesPage.tsx` — añadir selector tipo de reporte
  (Ingresos/Cartera Vencida) y selector modo de filtro (Por momento / Por intervalo).
- `frontend/src/api/index.ts:162-165` — tipar `reportesApi.generar` con params
  opcionales de intervalo, o añadir función(es) nueva(s) según approach elegido.
- `frontend/src/utils/formatters.ts:55-61` (`MOMENTOS`) — reutilizable sin cambios
  para el modo "Por momento" en ambos tipos de reporte.
- `openspec/specs/overdue-evaluation/spec.md` — probablemente necesita spec delta si
  se generaliza el predicado (hoy documenta explícitamente "no report changes" como
  Non-Goal; esta change lo contradice y debe declararlo).
- `backend/app/routers/auditoria.py` — no se modifica, solo referencia de patrón
  `fecha_desde`/`fecha_hasta`.

## Approaches

1. **Un solo endpoint `GET /reportes` extendido** con params opcionales
   `tipo_reporte` ('ingresos'|'cartera_vencida'), `modo_filtro` ('momento'|'intervalo'),
   `fecha_desde`/`fecha_hasta` (modo intervalo) junto a `anio`/`mes`/`momento`
   (modo momento). El backend resuelve la ventana de fechas una vez y bifurca: rama
   "ingresos" reutiliza la query actual sin cambios estructurales (solo generaliza el
   rango); rama "cartera_vencida" filtra `Pago.pagado==False AND fecha_maxima` dentro
   de la ventana equivalente de `fecha_entrada_mora`, agregando totales + por_gestor
   (sin por_receptor).
   - Pros: un solo endpoint y una sola página frontend extendida; centraliza la
     resolución de ventana de fechas.
   - Cons: `reportes.py` ya tiene ~300 líneas y crecería más; el schema de respuesta
     necesita campos opcionales o discriminated union (Pydantic) para dos formas de
     reporte distintas, ensuciando el modelo actual `ReporteResponseExtendido`.
   - Effort: Medium.

2. **Dos endpoints separados** (`GET /reportes/ingresos` generalizado con intervalo,
   `GET /reportes/cartera-vencida` nuevo), con un helper compartido para resolver la
   ventana de fechas (momento vs intervalo) y `fecha_entrada_mora`. Una sola página
   frontend con tabs/selector que llama al endpoint correspondiente según
   `tipo_reporte`.
   - Pros: sigue el patrón ya usado en el proyecto de endpoints granulares por
     propósito (ej. `/pagos/alertas/vencidos` separado del listado principal);
     schemas de respuesta limpios y tipados por separado; testeable independiente.
   - Cons: dos rutas nuevas/modificadas en vez de una; frontend debe decidir qué
     función de API invocar según el selector (trivial).
   - Effort: Medium (similar al approach 1, ligeramente más archivos pero más limpio).

## Recommendation
Approach 2. Es más consistente con el estilo ya establecido en el repo (endpoints
focalizados, ej. `/pagos/alertas/vencidos` vs el listado general) y evita forzar un
schema de respuesta híbrido en `ReporteResponseExtendido`. El helper de resolución de
ventana (momento → fechas, o intervalo directo) se comparte entre ambos endpoints.

## Risks
- **Regla de negocio central sin confirmar en código**: "vencido dentro del rango" es
  evento (fecha de entrada a mora cae en la ventana), no snapshot a una fecha de
  corte. No existe hoy ninguna función que calcule "fecha de entrada a mora"; hay que
  crearla y validar sus bordes (m2 cruce de mes, febrero) igual que se hizo para
  `overdue-evaluation` (spec.md tiene 7 escenarios `[pytest]` de bordes de momento).
- **Deferrals rompen la trazabilidad histórica**: una cuota aplazada fuera de mora ya
  no aparecerá en el reporte del período original en que entró en mora por primera
  vez, porque el sistema no persiste la fecha original (Non-Goal explícito de
  `payment-deferral-tracking`). Confirmar con el owner si esto es aceptable (reporte
  "vivo", no histórico inmutable) antes de proponer.
- **¿Por-gestor tiene sentido igual para cartera vencida?** Probablemente sí (mismo
  patrón de agregación, conteo/monto en mora por gestor), pero por-receptor NO aplica
  (son cuotas no recibidas, sin receptor). Confirmar explícitamente en la propuesta.
- **Interacción con "fechas de pago fijas mensuales" (item feature-fechas-pago-fijas-mensuales)**:
  no se investigó en detalle si el anclaje de fecha_maxima al día del mes cambia algo
  en el cómputo de `fecha_entrada_mora` sobre un intervalo arbitrario; parece
  ortogonal (opera sobre `fecha_maxima` igual que hoy) pero debe verificarse en la
  fase de spec/design.
- **Performance sobre intervalos amplios**: `/alertas/vencidos` ya carga todos los
  pagos impagos en mora a Python (mismo patrón que `reportes.py` usa para todo). Un
  intervalo muy amplio (ej. "todo el año") podría escanear un backlog grande de cuotas
  impagas; aceptable al mismo nivel que el código actual, pero flag para revisión de
  design si el volumen de datos crece.
- Non-Goal de `overdue-evaluation` dice explícitamente "no report changes" — esta
  change lo contradice a propósito y debe declararlo como spec delta, no como
  violación silenciosa.

## Ready for Proposal
Sí, mismo patrón que `scheduled-overdue-evaluation`: capturar las reglas de negocio
pendientes (fecha de entrada a mora, tratamiento de aplazamientos, alcance del
desglose por-gestor en cartera vencida, approach 1 vs 2) como "Business rules
(binding)" en `proposal.md` tras confirmación del owner.
