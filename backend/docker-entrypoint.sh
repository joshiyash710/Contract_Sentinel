#!/usr/bin/env sh
# ContractSentinel backend container entrypoint.
# Runs DB migrations to head, then execs the CMD (uvicorn). See docs/DEPLOYMENT.md.
set -e

echo "[entrypoint] running alembic migrations..."
alembic upgrade head

echo "[entrypoint] starting: $*"
exec "$@"
