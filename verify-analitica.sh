#!/usr/bin/env bash
# =============================================================================
# verify-analitica.sh — Verificación de la capability analítica abierta (Text-to-SQL en Sandbox)
# =============================================================================
set -uo pipefail
cd "$(dirname "$0")"

BASE="https://127.0.0.1:8099"
PASS=0; FAIL=0

TOKEN="$(grep '^FORSIS_AGENT_TOKEN_TRAFICO=' .env | cut -d= -f2-)"
CHTOK="$(grep '^FORSIS_CHANNEL_TOKEN_WIDGET_TRAFICO=' .env | cut -d= -f2-)"

ok()   { PASS=$((PASS+1)); printf '  PASS  %s\n' "$1"; }
bad()  { FAIL=$((FAIL+1)); printf '  FAIL  %s\n' "$1"; }
chk()  { if [ "$2" = "$3" ]; then ok "$1 ($3)"; else bad "$1 (esperado '$3', obtenido '$2')"; fi; }

body() {
  printf '{"message":%s,"channel":"widget-trafico","company":"%s","actor":{"subject":"verify-analitica","subject_type":"trafico_user","roles":["admin"],"authorized":true},"debug":true}' \
    "$(printf '%s' "$1" | python3 -c 'import json,sys;print(json.dumps(sys.stdin.read()))')" "$2"
}

post() {
  curl -sk -o /tmp/va.json -w '%{http_code}' -X POST "$BASE/api/v1/chat" \
    -H "Authorization: Bearer $TOKEN" \
    -H 'X-Forsis-Channel: widget-trafico' \
    -H "X-Forsis-Channel-Token: $CHTOK" \
    -H "Idempotency-Key: va-$1-$(date +%s%N)" \
    -H 'Content-Type: application/json' -d "$2"
}

# Aplana `answer` + todo el texto de `components` en una sola cadena. Las
# cifras viven en el componente estructurado (tabla/card), no en `answer`:
# asertar solo sobre `answer` daria un falso negativo.
jflat() { python3 -c "
import json
d=json.load(open('/tmp/va.json'))
out=[d.get('answer') or '']
for c in (d.get('components') or []):
    out.append(c.get('title') or '')
    out.append(c.get('caption') or '')
    for col in (c.get('columns') or []):
        out.append(col.get('label') or '')
    for r in (c.get('rows') or []):
        out.extend(str(v) for v in r.values())
    for f in (c.get('fields') or []):
        out.append(str(f.get('label') or ''))
        out.append(str(f.get('value') or ''))
print(' | '.join(x for x in out if x))
"; }

jget() { python3 -c "
import json,sys
d=json.load(open('/tmp/va.json'))
cur=d
for k in sys.argv[1].split('.'):
    if cur is None: break
    cur = cur.get(k) if isinstance(cur,dict) else None
print('' if cur is None else (json.dumps(cur,ensure_ascii=False) if isinstance(cur,(dict,list)) else str(cur)))
" "$1" 2>/dev/null; }

echo "============================================================"
echo " VERIFICACIÓN CAPABILITY ANALÍTICA (db.consulta_analitica)"
echo "============================================================"

# --- 1. Verificación en catálogo y sandbox de solo lectura ---
echo
echo "1. Catálogo y permisos PlanGuard"
eval "$(docker exec -i forsis-ai-agent-app python - <<'PY'
from app.capabilities.catalog import catalog_summary, planner_catalog
from app.core.executor.tool_runner import ToolRunner
from app.capabilities.catalog import build_registry
s = catalog_summary()
plan_tools = [c["tool"] for c in planner_catalog()]
print("CAT_TOTAL=%d" % s["total"])
print("HAS_ANALITICA=%s" % ("1" if "db.consulta_analitica" in s["executable"] else "0"))
print("PLAN_ANALITICA=%s" % ("1" if "db.consulta_analitica" in plan_tools else "0"))
PY
)"
chk "db.consulta_analitica registrada y ejecutable" "$HAS_ANALITICA" "1"
chk "db.consulta_analitica expuesta al planner" "$PLAN_ANALITICA" "1"

# --- 2. Facturación mensual en FORSIS ---
echo
echo "2. Consulta ad-hoc: Facturación mensual (FORSIS)"
code=$(post f_oct "$(body '¿cuánto se ha facturado en este mes de octubre?' FORSIS)")
chk "HTTP facturacion oct FORSIS" "$code" "200"
st=$(jget status); chk "status turno" "$st" "ok"
tools=$(jget trace.tools_executed)
case "$tools" in *db.consulta_analitica*) ok "tool analitica ejecutada ($tools)";; *) bad "tool no ejecutada ($tools)";; esac
ans=$(jflat)
case "$ans" in *111,357.80*|*USD*) ok "cifras reales facturacion citadas en respuesta";; *) bad "respuesta sin cifras: ${ans:0:80}";; esac

# --- 3. Multi-tenant / enrutamiento a GERO ---
echo
echo "3. Multi-tenant: Facturación mensual (GERO)"
code=$(post f_oct_gero "$(body '¿cuánto se ha facturado en este mes de octubre?' GERO)")
chk "HTTP facturacion oct GERO" "$code" "200"
st_gero=$(jget status); chk "status turno GERO" "$st_gero" "ok"
ans_gero=$(jflat)
case "$ans_gero" in *600.00*|*USD*) ok "cifras reales de GERO citadas en respuesta";; *) bad "respuesta GERO sin cifras: ${ans_gero:0:80}";; esac

# --- 4. Consulta cuantitativa de guías ---
echo
echo "4. Consulta cuantitativa: Guías por estatus"
code=$(post guias_est "$(body '¿cuántas guías activas hay por estatus?' FORSIS)")
chk "HTTP guias por estatus" "$code" "200"
st_est=$(jget status); chk "status turno guias estatus" "$st_est" "ok"
ans_est=$(jflat)
case "$ans_est" in *"Por Timbrar"*|*"Estatus"*) ok "conteo de estatus generado correctamente";; *) bad "respuesta guias sin estatus: ${ans_est:0:80}";; esac

# --- 5. Coexistencia con listado fijo ---
echo
echo "5. Coexistencia: Selección de guias_listar para listados"
code=$(post ult_guias "$(body 'dame las ultimas 3 guias' FORSIS)")
chk "HTTP ultimas guias" "$code" "200"
tools_guias=$(jget trace.tools_executed)
case "$tools_guias" in *traf.guias_listar*) ok "listado seleccionó traf.guias_listar ($tools_guias)";; *) bad "no selecciono traf.guias_listar: $tools_guias";; esac

echo
echo "============================================================"
echo " RESULTADO: $PASS PASS / $FAIL FAIL  (total $((PASS+FAIL)))"
echo "============================================================"
[ "$FAIL" -eq 0 ] || exit 1
