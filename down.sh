#!/usr/bin/env bash
# Forsis AI Agent — down.sh
# Para el stack. NO borra volúmenes ni datos salvo que se pase --purge.
#
#   ./down.sh            → detiene contenedores, conserva datos
#   ./down.sh --purge    → ALSO borra volúmenes (DESTRUCTIVO: se pierde la BD)
set -euo pipefail

cd "$(dirname "$0")"

if [ "${1:-}" = "--purge" ]; then
  echo "PELIGRO: --purge borra la BD del agente y su storage. ¿Confirmas? (sí/NO)"
  read -r answer
  if [ "$answer" != "sí" ] && [ "$answer" != "si" ] && [ "$answer" != "yes" ]; then
    echo "Cancelado."
    exit 1
  fi
  docker compose down -v
  echo "Stack y volúmenes eliminados."
else
  docker compose down
  echo "Stack detenido. Los volúmenes (BD) se conservan."
fi