#!/usr/bin/env bash
# Forsis AI Agent — logs.sh
#   ./logs.sh          → logs de todos los servicios, follow
#   ./logs.sh app      → sólo app
#   ./logs.sh -n 200   → últimas 200 líneas, sin follow
set -euo pipefail

cd "$(dirname "$0")"

FOLLOW="-f"
LINES=""

while [ $# -gt 0 ]; do
  case "$1" in
    -n) LINES="--tail=$2"; FOLLOW=""; shift 2 ;;
    *)  SERVICE="$1"; shift ;;
  esac
done

if [ -n "${SERVICE:-}" ]; then
  docker compose logs $LINES $FOLLOW "$SERVICE"
else
  docker compose logs $LINES $FOLLOW
fi