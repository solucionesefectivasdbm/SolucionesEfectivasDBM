#!/bin/sh
# Startup: self-healing DB migration, then launch the API.
#
# Context: the production DB was originally bootstrapped via
# Base.metadata.create_all() and never stamped by Alembic, so its
# alembic_version table is empty. A plain `alembic upgrade head` therefore
# replays the initial migration and fails with DuplicateTable on the existing
# tables. To recover, if there is no Alembic version yet we stamp the baseline
# (records it as applied WITHOUT re-creating tables); then upgrade applies only
# the genuinely pending migrations. On every later boot the version already
# exists, so we skip the stamp and `upgrade head` is a no-op.
#
# Migration failures are logged but do NOT abort startup: uvicorn always boots
# so the container stays reachable (logs/SSH) for diagnosis.

echo "[start] checking alembic state..."
if python -m alembic current 2>/dev/null | grep -q .; then
  echo "[start] alembic already stamped, skipping baseline stamp"
else
  echo "[start] no alembic version found -> stamping baseline d9144df95951"
  python -m alembic stamp d9144df95951 || echo "[start] WARNING: baseline stamp failed"
fi

echo "[start] running alembic upgrade head..."
python -m alembic upgrade head || echo "[start] WARNING: alembic upgrade failed, starting app anyway"

echo "[start] launching uvicorn..."
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
