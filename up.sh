#!/usr/bin/env bash
# Forsis AI Agent — up.sh
# Levanta el stack completo (db + app + nginx) y espera a que esté listo.
set -euo pipefail

cd "$(dirname "$0")"

echo "→ Verificando .env (modo 600)…"
if [ ! -f .env ]; then
  echo "FALLO: falta .env. Copia .env.example y rellena los secretos." >&2
  exit 1
fi
chmod 600 .env

echo "→ Verificando redes externas…"
for net in ai-network forsis-comunicaciones; do
  if ! docker network ls --format '{{.Name}}' | grep -qx "$net"; then
    echo "FALLO: la red externa '$net' no existe." >&2
    exit 1
  fi
done

echo "→ docker compose up -d…"
docker compose up -d --build

echo "→ Esperando readiness…"
for i in $(seq 1 60); do
  if docker compose exec -T nginx wget -q -O- http://127.0.0.1:8080/api/v1/ready 2>/dev/null | grep -q '"status":"ok"'; then
    echo "OK: el agente está listo (intento $i)."
    docker compose exec -T nginx wget -q -O- http://127.0.0.1:8080/api/v1/ready
    echo ""
    exit 0
  fi
  sleep 2
done

echo "FALLO: el agente no quedó listo en 120s." >&2
docker compose ps
docker compose logs --tail=50 app
exit 1