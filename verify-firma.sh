#!/usr/bin/env bash
# Forsis AI Agent — verify-firma.sh
#
# Criterio A6 del Sprint 1: la firma SHA-256 del Planner (código + system
# prompt) debe coincidir con la del despliegue de referencia. Detecta deriva
# entre la versión probada en el HITO GO/NO-GO y la que está corriendo.
#
#   ./verify-firma.sh                          → imprime la firma actual
#   ./verify-firma.sh --esperado <hash>       → exit 0 si coincide, 1 si no
#   ./verify-firma.sh --guardar               → guarda la firma en .firma-actual
set -euo pipefail

cd "$(dirname "$0")"

ESPERADO=""
ACCION="mostrar"

while [ $# -gt 0 ]; do
  case "$1" in
    --esperado) ESPERADO="$2"; ACCION="verificar"; shift 2 ;;
    --guardar)  ACCION="guardar"; shift ;;
    *) echo "Argumento desconocido: $1" >&2; exit 2 ;;
  esac
done

# La firma se calcula DENTRO del contenedor: es el código que realmente corre.
FIRMA="$(docker compose exec -T app python3 -c \
  'from app.api.health import calcular_firma_planner; print(calcular_firma_planner())' \
  | tr -d '\r')"

if [ -z "$FIRMA" ]; then
  echo "FALLO: no se pudo calcular la firma (¿está el contenedor app arriba?)." >&2
  exit 1
fi

case "$ACCION" in
  guardar)
    echo "$FIRMA" > .firma-actual
    echo "Firma guardada en .firma-actual: $FIRMA"
    ;;
  verificar)
    if [ "$FIRMA" = "$ESPERADO" ]; then
      echo "OK: la firma del Planner coincide con el despliegue de referencia."
      echo "     $FIRMA"
      exit 0
    else
      echo "FALLO: DERIVA DETECTADA en el Planner." >&2
      echo "     esperado: $ESPERADO" >&2
      echo "     actual:   $FIRMA" >&2
      exit 1
    fi
    ;;
  mostrar)
    echo "$FIRMA"
    ;;
esac