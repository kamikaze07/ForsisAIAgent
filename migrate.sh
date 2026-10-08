#!/usr/bin/env bash
# Forsis AI Agent — migrate.sh
# Aplica los ficheros SQL de docker/db/init en orden lexicográfico.
#
# NOTA (arquitectura-python.md): Alembic es el migrador de referencia del
# proyecto. Este script cubre el esquema base de Fase 1 (SQL puro) y es
# idempotente: todos los ficheros usan IF NOT EXISTS / ON CONFLICT DO NOTHING,
# así que re-ejecutarlo es seguro.
set -euo pipefail

cd "$(dirname "$0")"

if [ -f .env ]; then
  # Carga variables POSTGRES_* ignorando comentarios
  export $(grep -E '^POSTGRES_' .env | xargs)
fi

echo "→ Aplicando migraciones SQL de docker/db/init…"
for f in docker/db/init/*.sql; do
  [ -e "$f" ] || continue
  echo "  - $(basename "$f")"
  docker compose exec -T db psql -v ON_ERROR_STOP=1 \
    -U "${POSTGRES_USER:-forsis_agent}" \
    -d "${POSTGRES_DB:-forsis_agent}" < "$f"
done

echo "OK: migraciones aplicadas."