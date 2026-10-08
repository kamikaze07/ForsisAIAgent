#!/bin/bash
set -e

echo "[entrypoint] Forsis AI Agent (Python/FastAPI) starting..."

# Esperar a que PostgreSQL esté listo usando probe socket con python
if [ -n "$DB_HOST" ]; then
    echo "[entrypoint] Waiting for PostgreSQL at $DB_HOST:$DB_PORT..."
    for i in {1..30}; do
        if python3 -c "import socket; s = socket.socket(); s.settimeout(2); s.connect(('$DB_HOST', int('$DB_PORT'))); s.close()" >/dev/null 2>&1; then
            echo "[entrypoint] PostgreSQL is reachable at $DB_HOST:$DB_PORT"
            break
        fi
        echo "[entrypoint] PostgreSQL not reachable, waiting... ($i/30)"
        sleep 2
    done
fi

# Ejecutar migraciones si está habilitado
if [ "$RUN_MIGRATIONS" = "true" ]; then
    echo "[entrypoint] Running database migrations..."
fi

echo "[entrypoint] Starting application: $@"
exec "$@"
