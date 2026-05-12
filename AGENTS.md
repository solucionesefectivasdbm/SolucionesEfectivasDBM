# Code Review Rules

## Python (Backend)
- Use SQLAlchemy 2.x async patterns (`AsyncSession`, `await db.execute(...)`).
- All monetary calculations must use `Decimal`, never `float`.
- For paginated endpoints, `ORDER BY` MUST include a deterministic tiebreaker
  (typically the primary key) to avoid inconsistent pagination when multiple
  rows share the leading ordering columns.
- Soft deletes are handled via `deleted_at IS NULL` filters.
- Audit every mutation through `audit_service.registrar_*` helpers; do not
  insert into `audit_log` directly.
- Never log raw passwords or `password_hash` values.

## TypeScript (Frontend)
- Prefer `const` and `let`; never `var`.
- Use functional React components with named exports.
- The access token lives in the Zustand store (memory only) — never in
  `localStorage` or `sessionStorage`.
- All API calls go through the shared axios instance with `withCredentials: true`.

## Migrations
- Schema changes that need to apply to existing rows must be added to the
  `startup_create_tables` hook in `backend/app/main.py` with an idempotent
  check (e.g. `information_schema.columns` lookup before `ALTER TABLE`).
- One-time data migrations should be exposed as a temporary admin-only POST
  endpoint, executed once, then removed in a follow-up commit.

## Commits
- Use conventional commit messages in Spanish (matching project history).
- Group related backend + frontend changes in a single commit when they
  represent one logical change.
