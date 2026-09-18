#!/usr/bin/env bash
# ==============================================================================
# Arya OS - Production Docker Entrypoint Script
# Handles automated database migrations (fail-fast) and starts Uvicorn.
# ==============================================================================
set -euo pipefail

echo "=========================================================="
echo "Starting Project Arya OS (Environment: ${APP_ENV:-production})"
echo "=========================================================="

# 1. Automated Database Migrations
AUTO_MIGRATE="${AUTO_RUN_MIGRATIONS:-true}"
if [ "${AUTO_MIGRATE}" = "true" ] || [ "${AUTO_MIGRATE}" = "1" ]; then
    echo "[entrypoint] Running database migrations (alembic upgrade head)..."
    if ! alembic upgrade head; then
        echo "[entrypoint] ERROR: Database migration failed! Aborting startup to prevent running on inconsistent schema." >&2
        exit 1
    fi
    echo "[entrypoint] Database migrations applied successfully."
else
    echo "[entrypoint] Automated migrations skipped (AUTO_RUN_MIGRATIONS=${AUTO_MIGRATE})."
fi

# 2. Check writable storage path
STORAGE_PATH="${STORAGE_LOCAL_PATH:-/app/data/storage}"
mkdir -p "${STORAGE_PATH}"

# 3. If specific command arguments were provided, execute them (e.g. bash or pytest)
if [ $# -gt 0 ]; then
    echo "[entrypoint] Executing custom command: $@"
    exec "$@"
fi

# 4. Start Production Application Server (Uvicorn)
HOST="${BACKEND_HOST:-0.0.0.0}"
PORT="${BACKEND_PORT:-8000}"
WORKERS="${UVICORN_WORKERS:-1}"
TIMEOUT_KEEP_ALIVE="${UVICORN_TIMEOUT_KEEP_ALIVE:-65}"
TIMEOUT_GRACEFUL_SHUTDOWN="${UVICORN_TIMEOUT_GRACEFUL_SHUTDOWN:-60}"

echo "[entrypoint] Starting Uvicorn server on ${HOST}:${PORT} (workers=${WORKERS}, keep-alive=${TIMEOUT_KEEP_ALIVE}s, shutdown-timeout=${TIMEOUT_GRACEFUL_SHUTDOWN}s)..."
exec uvicorn app.main:app \
    --app-dir backend \
    --host "${HOST}" \
    --port "${PORT}" \
    --workers "${WORKERS}" \
    --timeout-keep-alive "${TIMEOUT_KEEP_ALIVE}" \
    --timeout-graceful-shutdown "${TIMEOUT_GRACEFUL_SHUTDOWN}"
