# Code Review Rules

Reglas que reflejan los patrones reales del proyecto. No introducir convenciones
nuevas sin alinear primero al resto del codebase.

## Python (Backend)
- Usar SQLAlchemy 2.x async (`AsyncSession`, `await db.execute(...)`).
- Todo cálculo financiero del backend usa `Decimal`, nunca `float`.
- En endpoints paginados, el `ORDER BY` debe terminar en una columna única
  (típicamente la PK) como tiebreaker, para evitar paginación inconsistente.
- Soft delete vía `deleted_at IS NULL`.
- Toda mutación pasa por los helpers de `audit_service.registrar_*`; nunca
  insertar en `audit_log` directamente.
- Nunca loguear `password` crudo ni `password_hash`.

## TypeScript (Frontend)
- Las páginas usan `export default function PageName()` (es el patrón
  establecido — no migrar a named exports a menos que se refactorice todo).
- Componentes funcionales con hooks.
- Estado global con Zustand; el access token vive SOLO en memoria del store.
- Llamadas a API a través de la instancia compartida de axios.
- `parseFloat` es aceptable para entrada de UI (formularios), pero el
  resultado canónico de cálculos vive en el backend con `Decimal`. El frontend
  solo muestra/lee valores ya calculados.
- `catch (e: any)` con manejo a través de `e.response?.data?.detail` es el
  patrón establecido para errores de axios.

## Migraciones
- Cambios de esquema que apliquen a filas existentes van en el hook
  `startup_create_tables` de `backend/app/main.py` con check idempotente
  (`information_schema.columns` antes de `ALTER TABLE`).
- Migraciones de datos puntuales se exponen como endpoint temporal admin-only
  POST, se ejecutan una vez, y se eliminan en un commit posterior.

## Commits
- Mensajes en español, en línea con el historial del repo.
- Agrupar cambios relacionados de backend y frontend en un solo commit.
