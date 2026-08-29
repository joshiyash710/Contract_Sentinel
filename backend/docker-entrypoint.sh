#!/usr/bin/env sh
# ContractSentinel backend container entrypoint.
# Runs DB migrations to head, then execs the CMD (uvicorn). See docs/DEPLOYMENT.md.
set -e

echo "[entrypoint] running migrations (Turso-aware)..."
# Feature 053: use the Turso-aware helper (builds sqlite+libsql:// when TURSO_DATABASE_URL is set) —
# NOT the bare alembic CLI, which would use alembic.ini's local-sqlite placeholder URL on Turso.
python -c "import app.config as c; from app.runner.migrations import upgrade_to_head; upgrade_to_head(c.JOB_STORE_DB_PATH)"

echo "[entrypoint] starting: $*"
exec "$@"
