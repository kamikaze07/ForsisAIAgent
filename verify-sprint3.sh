#!/usr/bin/env bash
# =============================================================================
# verify-sprint3.sh — Verificación de los criterios de aceptación del Sprint 3
# (sprint-plan-v2.md §Sprint 3). Ejecuta pruebas REALES contra el stack vivo:
# HTTP por nginx:8099 y el sandbox SQL dentro del contenedor del agente.
#
# Uso:  ./verify-sprint3.sh
# Salida: líneas PASS/FAIL + resumen. Código 0 solo si todo PASA.
# =============================================================================
set -uo pipefail
cd "$(dirname "$0")"

BASE="https://127.0.0.1:8099"
APP="forsis-ai-agent-app"
PASS=0; FAIL=0

TOKEN="$(grep '^FORSIS_AGENT_TOKEN_TRAFICO=' .env | cut -d= -f2-)"
CHTOK="$(grep '^FORSIS_CHANNEL_TOKEN_WIDGET_TRAFICO=' .env | cut -d= -f2-)"

ok()   { PASS=$((PASS+1)); printf '  PASS  %s\n' "$1"; }
bad()  { FAIL=$((FAIL+1)); printf '  FAIL  %s\n' "$1"; }
chk()  { if [ "$2" = "$3" ]; then ok "$1 ($3)"; else bad "$1 (esperado '$3', obtenido '$2')"; fi; }

# Cuerpo de petición. $1 = mensaje, $2 = roles JSON, $3 = company
body() {
  printf '{"message":%s,"channel":"widget-trafico","company":"%s","actor":{"subject":"verify-sprint3","subject_type":"trafico_user","roles":%s,"authorized":true},"debug":true}' \
    "$(printf '%s' "$1" | python3 -c 'import json,sys;print(json.dumps(sys.stdin.read()))')" "$3" "$2"
}

post() {  # $1 etiqueta, $2 cuerpo -> imprime HTTP code, deja JSON en /tmp/s3.json
  curl -sk -o /tmp/s3.json -w '%{http_code}' -X POST "$BASE/api/v1/chat" \
    -H "Authorization: Bearer $TOKEN" \
    -H 'X-Forsis-Channel: widget-trafico' \
    -H "X-Forsis-Channel-Token: $CHTOK" \
    -H "Idempotency-Key: s3-$1-$(date +%s%N)" \
    -H 'Content-Type: application/json' -d "$2"
}

jget() { python3 -c "
import json,sys
d=json.load(open('/tmp/s3.json'))
cur=d
for k in sys.argv[1].split('.'):
    if cur is None: break
    cur = cur.get(k) if isinstance(cur,dict) else None
print('' if cur is None else (json.dumps(cur,ensure_ascii=False) if isinstance(cur,(dict,list)) else cur))
" "$1" 2>/dev/null; }

echo "============================================================"
echo " VERIFICACIÓN SPRINT 3 — Primera tool real + sandbox SQL"
echo "============================================================"

# --- A0: salud del stack -----------------------------------------------------
echo
echo "A0. Stack operativo"
for c in forsis-ai-agent-app forsis-ai-agent-db forsis-ai-agent-nginx; do
  st=$(docker inspect -f '{{.State.Health.Status}}' "$c" 2>/dev/null || echo ausente)
  chk "contenedor $c healthy" "$st" "healthy"
done

# --- A1: sandbox read-only (R-1..R-5) ---------------------------------------
echo
echo "A1. Sandbox SQL de solo lectura (R-1..R-5)"
docker exec -i "$APP" python - <<'PY' > /tmp/s3_sandbox.txt 2>&1
from app.infrastructure.db.readonly_pool import ro_pool
from app.infrastructure.db.sql_guard import assert_read_only
from app.core.exceptions import SqlNotAllowedError
res = {}
# R-1: identidad del usuario read-only en ambos destinos
for t in ("sicret_pr", "trafico"):
    try:
        rows, _ = ro_pool.query(t, "SELECT CURRENT_USER() AS u", max_rows=1)
        res["ident_" + t] = "forsis_agent_ro" in str(rows[0]["u"])
    except Exception:
        res["ident_" + t] = False
# R-2: transacción read-only impuesta por el servidor
for t in ("sicret_pr", "trafico"):
    res["ro_" + t] = bool(ro_pool.verify_read_only(t).get("enforced"))
# R-3: allowlist del parser
bloqueados = ["INSERT INTO guias (num_guia) VALUES ('X')", "UPDATE guias SET estatus='x'",
              "DELETE FROM guias", "DROP TABLE guias", "SELECT 1; DROP TABLE guias",
              "SELECT /*!32302 1 */ 1", "TRUNCATE guias", "GRANT ALL ON *.* TO 'x'@'%'"]
n = 0
for s in bloqueados:
    try:
        assert_read_only(s)
    except SqlNotAllowedError:
        n += 1
res["guard_bloqueados"] = (n == len(bloqueados))
permitidos = ["SELECT 1", "SHOW TABLES", "DESCRIBE guias"]
m = 0
for s in permitidos:
    try:
        assert_read_only(s); m += 1
    except SqlNotAllowedError:
        pass
res["guard_permitidos"] = (m == len(permitidos))
# R-4: LIMIT obligatorio
rows, meta = ro_pool.query("sicret_pr", "SELECT num_guia FROM guias ORDER BY num DESC", max_rows=3)
res["limit_forzado"] = (len(rows) == 3 and meta["truncated"] is True)
for k, v in res.items():
    print("%s=%s" % (k, "OK" if v else "NO"))
PY
for k in ident_sicret_pr ident_trafico ro_sicret_pr ro_trafico guard_bloqueados guard_permitidos limit_forzado; do
  v=$(grep -E "^$k=" /tmp/s3_sandbox.txt | cut -d= -f2)
  chk "$k" "${v:-ausente}" "OK"
done

# --- A2: catálogo y PlanGuard (en proceso) ----------------------------------
echo
echo "A2. Catálogo versionado y PlanGuard (7 gates)"
docker exec -i "$APP" python - <<'PY' > /tmp/s3_guard.txt 2>&1
from app.capabilities.catalog import catalog_summary, planner_catalog
from app.capabilities.catalog import build_registry
from app.core.executor.tool_runner import ToolRunner
r = build_registry(); run = ToolRunner(r)
s = catalog_summary()
print("catalog_total=%s" % ("OK" if s["total"] >= 3 else "NO"))
print("planner_solo_lectura=%s" % ("OK" if all(c.get("risk_class") == "L0" for c in planner_catalog()) else "NO"))
# L3 denegada
o = run.run("traf.factura_cancelar", {"uuid":"a"*36,"motivo_sat":"02"}, "FORSIS", ["admin"])
print("l3_denegada=%s" % ("OK" if o.status == "denied" and o.guard["failed_gate"] == "permisos" else "NO"))
print("l3_no_ejecutada=%s" % ("OK" if o.data is None else "NO"))
# L2 denegada
o = run.run("traf.guia_liberar", {"num_guia":"PR-1","motivo":"prueba guarda"}, "FORSIS", ["admin"])
print("l2_denegada=%s" % ("OK" if o.status == "denied" else "NO"))
# RBAC
o = run.run("traf.guias_listar", {"limit":1}, "FORSIS", ["rol_inexistente"])
print("rbac_denegado=%s" % ("OK" if o.status == "denied" and o.guard["missing_permissions"] == ["trafico.guias.read"] else "NO"))
# capability inexistente
o = run.run("traf.no_existe", {}, "FORSIS", ["admin"])
print("inexistente=%s" % ("OK" if o.error_code == "CAPABILITY_NOT_FOUND" else "NO"))
# params inválidos
o = run.run("traf.guias_listar", {"parametro_inventado":"x"}, "FORSIS", ["trafico"])
print("params_invalidos=%s" % ("OK" if o.error_code == "TOOL_PARAMS_INVALID" else "NO"))
# inyección por order_by
o = run.run("traf.guias_listar", {"order_by":"; DROP TABLE guias"}, "FORSIS", ["trafico"])
print("order_by_cerrado=%s" % ("OK" if o.status != "ok" else "NO"))
# ejecución real
o = run.run("traf.guias_listar", {"limit":3}, "FORSIS", ["trafico"])
print("ejecucion_real=%s" % ("OK" if o.status == "ok" and o.data["row_count"] == 3 else "NO"))
print("rows_no_vacias=%s" % ("OK" if o.data["rows"] and o.data["rows"][0].get("num_guia") else "NO"))
print("trazabilidad_fuente=%s" % ("OK" if o.data["source"]["database"] == "sicrePR" else "NO"))
PY
chk "catálogo tiene >=3 capabilities" "$(grep -E '^catalog_total=' /tmp/s3_guard.txt | cut -d= -f2)" "OK"
for k in planner_solo_lectura l3_denegada l3_no_ejecutada l2_denegada rbac_denegado inexistente \
         params_invalidos order_by_cerrado ejecucion_real rows_no_vacias trazabilidad_fuente; do
  v=$(grep -E "^$k=" /tmp/s3_guard.txt | cut -d= -f2)
  chk "$k" "${v:-ausente}" "OK"
done

# --- A3: end-to-end por HTTP -------------------------------------------------
echo
echo "A3. Turno completo por HTTPS (nginx:8099)"
code=$(post e2e1 "$(body 'dame las ultimas 3 guias' '["trafico"]' FORSIS)")
chk "HTTP consulta de guías" "$code" "200"
st=$(jget status); chk "status del turno" "$st" "ok"
tools=$(jget trace.tools_executed)
case "$tools" in *traf.guias_listar*) ok "tool ejecutada ($tools)";; *) bad "tool no ejecutada ($tools)";; esac
ans=$(jget answer)
case "$ans" in *PR-*) ok "respuesta cita folios reales";; *) bad "respuesta sin folios: ${ans:0:70}";; esac
comps=$(jget components)
case "$comps" in *type*) ok "components poblados";; *) bad "components vacíos";; esac
tl=$(jget trace.latency_ms.tools)
if [ "${tl:-0}" -gt 0 ] 2>/dev/null; then ok "latencia de tools reportada (${tl}ms)"; else bad "latencia de tools = ${tl:-vacía}"; fi

# A3b: smalltalk sigue sin llamar tools (no hay regresión del Sprint 2)
code=$(post e2e2 "$(body 'hola' '["trafico"]' FORSIS)")
chk "HTTP smalltalk" "$code" "200"
t2=$(jget trace.tools_executed); chk "smalltalk sin tools" "$t2" "[]"

# A3c: actor sin permiso → turno denegado, no error 500
code=$(post e2e3 "$(body 'dame las ultimas 3 guias' '["rol_inexistente"]' FORSIS)")
chk "HTTP actor sin permiso" "$code" "200"
st3=$(jget status); chk "status denied" "$st3" "denied"

# A3d: empresa GERO enruta a otra base
code=$(post e2e4 "$(body 'dame las ultimas 2 guias' '["trafico"]' GERO)")
chk "HTTP empresa GERO" "$code" "200"

# --- A4: métricas ------------------------------------------------------------
echo
echo "A4. Métricas de tool expuestas"
curl -sk -o /tmp/s3.json "$BASE/api/v1/metrics" -H "Authorization: Bearer $TOKEN"
for k in tool_calls tool_ok tool_denied tool_calls_l0 sql_queries; do
  v=$(jget "counters.$k")
  if [ -n "$v" ]; then ok "counters.$k presente ($v)"; else bad "counters.$k ausente"; fi
done
lat=$(jget derived.tool_latency)
case "$lat" in *traf.guias_listar*) ok "derived.tool_latency con la capability";; *) bad "tool_latency sin datos";; esac

# --- A5: knowledge/ fuera del runtime ---------------------------------------
echo
echo "A5. knowledge/ no existe en el contenedor (B-5)"
if docker exec "$APP" test -d /app/knowledge 2>/dev/null; then
  bad "knowledge/ está montado en el contenedor"
else
  ok "knowledge/ ausente del runtime"
fi

echo
echo "============================================================"
echo " RESULTADO: $PASS PASS / $FAIL FAIL  (total $((PASS+FAIL)))"
echo "============================================================"
[ "$FAIL" -eq 0 ] || exit 1
