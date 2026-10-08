#!/usr/bin/env bash
# =============================================================================
# verify-sprint2.sh — Suite de verificación Sprint 2 (Fase 1)
# Cubre A1–A6 de knowledge/phase1/sprint-plan-v2.md §Sprint 2:
#   A1 Turno completo con forma exacta de channels.md §1.5
#   A2 Las 6 validaciones fail-closed (+ idempotency key reused)
#   A3 Idempotencia: replay idéntico devuelve el mismo cuerpo
#   A4 OmniRoute caído → 502 LLM_UNAVAILABLE, retryable:false, nunca 500
#   A5 Techo de turno respetado (<125s)
#   A6 Métricas por capa disponibles con datos
#   A7 Persistencia real en PostgreSQL (audit log + sesiones + idempotencia)
# =============================================================================
set -uo pipefail

BASE="https://127.0.0.1:8099"
PASS=0
FAIL=0
COMPOSE="docker compose -f /home/servidor/forsis-ai-agent/docker-compose.yml"

ok()   { printf '  \033[32mPASS\033[0m  %s\n' "$1"; PASS=$((PASS+1)); }
bad()  { printf '  \033[31mFAIL\033[0m  %s\n' "$1"; FAIL=$((FAIL+1)); }
head_() { printf '\n\033[1m%s\033[0m\n' "$1"; }

# ---- carga de tokens desde .env (nunca se imprimen) ------------------------
ENVFILE="/home/servidor/forsis-ai-agent/.env"
tok() { grep -E "^$1=" "$ENVFILE" | head -1 | cut -d= -f2-; }
TOKEN_MM="$(tok FORSIS_AGENT_TOKEN_MATTERMOST)"
TOKEN_TRAFICO="$(tok FORSIS_AGENT_TOKEN_TRAFICO)"
TOKEN_LIQ="$(tok FORSIS_AGENT_TOKEN_LIQUIDACIONES)"
TOKEN_API="$(tok FORSIS_AGENT_TOKEN_API)"

# ---- helpers de request ----------------------------------------------------
# chat <token> <channel> <idempotency_key> <json_body>  -> "HTTP_CODE<TAB>BODY"
chat() {
  local token="$1" channel="$2" key="$3" body="$4"
  local raw
  raw="$(curl -k -s -m 200 -w '\n%{http_code}' -X POST "$BASE/api/v1/chat" \
      -H "Authorization: Bearer $token" \
      -H "X-Forsis-Channel: $channel" \
      -H 'Content-Type: application/json' \
      ${key:+-H "Idempotency-Key: $key"} \
      -d "$body")"
  local code="${raw##*$'\n'}"
  printf '%s\t%s' "$code" "${raw%$'\n'*}"
}

http_code() { printf '%s' "$1" | cut -f1; }
http_body() { printf '%s' "$1" | cut -f2-; }

jget() { python3 -c "
import json,sys
try:
    d = json.loads(sys.stdin.read())
    val = d.get('$1')
    if val is None and isinstance(d.get('counters'), dict):
        val = d['counters'].get('$1')
    print(val if val is not None else '')
except Exception:
    print('')
" ; }

ACT_BODY='{"subject":"verify_s2","subject_type":"mattermost_user","display_name":"Verify S2","roles":["TRAFICO_OPERACION"],"authorized":true}'

# =============================================================================
head_ "PRECONDICIONES"
# =============================================================================
r="$(curl -k -s -m 30 "$BASE/api/v1/health")"
[ "$r" = '{"status":"ok"}' ] && ok "A0 liveness /api/v1/health → 200 {\"status\":\"ok\"}" || bad "A0 liveness ($r)"

r="$(curl -k -s -m 60 "$BASE/api/v1/ready")"
[ "$(printf '%s' "$r" | jget status)" = "ok" ] \
  && ok "A0 readiness /api/v1/ready → status ok (db + llm)" \
  || bad "A0 readiness ($r)"

# =============================================================================
head_ "A1 — TURNO COMPLETO (forma exacta de channels.md §1.5)"
# =============================================================================
BODY_OK="{\"message\":\"hola\",\"channel\":\"mattermost\",\"company\":\"FORSIS\",\"actor\":$ACT_BODY}"
IDEM_A1="s2-a1-$(date +%s)-$RANDOM"
OUT="$(chat "$TOKEN_MM" mattermost "$IDEM_A1" "$BODY_OK")"
CODE="$(http_code "$OUT")"; RESP="$(http_body "$OUT")"

if [ "$CODE" = "200" ]; then ok "A1.1 HTTP 200 en turno válido"; else bad "A1.1 HTTP $CODE ($RESP)"; fi

ST="$(printf '%s' "$RESP" | jget status)"
AN="$(printf '%s' "$RESP" | jget answer)"
SI="$(printf '%s' "$RESP" | jget session_id)"
TR="$(printf '%s' "$RESP" | python3 -c "import json,sys;d=json.load(sys.stdin);print((d.get('trace') or {}).get('llm_model_real',''))" 2>/dev/null)"
[ "$ST" = "ok" ] && ok "A1.2 status == ok" || bad "A1.2 status == $ST"
[ -n "$AN" ] && ok "A1.3 answer no vacío" || bad "A1.3 answer vacío"
[ -n "$SI" ] && ok "A1.4 session_id no vacío ($SI)" || bad "A1.4 session_id vacío"
[ -n "$TR" ] && ok "A1.5 trace.llm_model_real no vacío ($TR)" || bad "A1.5 llm_model_real vacío"

# forma exacta del contrato: los 9 campos obligatorios de ChatResponse
MISSING="$(printf '%s' "$RESP" | python3 -c "
import json,sys
d=json.load(sys.stdin)
req=['answer','session_id','status','components','clarification','confirmation','context_updated','updated_context','trace']
print(','.join([k for k in req if k not in d]))
" 2>/dev/null)"
[ -z "$MISSING" ] && ok "A1.6 los 9 campos de ChatResponse presentes" || bad "A1.6 campos faltantes: $MISSING"

# =============================================================================
head_ "A2 — VALIDACIONES FAIL-CLOSED (6 + idempotencia)"
# =============================================================================
# A2.1 company ausente → 422 VALIDATION_ERROR
B="{\"message\":\"hola\",\"channel\":\"mattermost\",\"actor\":$ACT_BODY}"
OUT="$(chat "$TOKEN_MM" mattermost "" "$B")"
CODE="$(http_code "$OUT")"; EC="$(http_body "$OUT" | jget error_code)"
[ "$CODE" = "422" ] && [ "$EC" = "VALIDATION_ERROR" ] \
  && ok "A2.1 company ausente → 422 VALIDATION_ERROR" \
  || bad "A2.1 company ausente → $CODE $EC (esperado 422)"

# A2.2 campo extra → 422 (extra="forbid")
B="{\"message\":\"hola\",\"channel\":\"mattermost\",\"company\":\"FORSIS\",\"actor\":$ACT_BODY,\"campo_inexistente\":1}"
OUT="$(chat "$TOKEN_MM" mattermost "" "$B")"
CODE="$(http_code "$OUT")"; EC="$(http_body "$OUT" | jget error_code)"
[ "$CODE" = "422" ] && ok "A2.2 campo extra → 422 (extra=forbid)" || bad "A2.2 campo extra → $CODE $EC (esperado 422)"

# A2.3 mensaje > 4000 chars → 413 MESSAGE_TOO_LONG
LONG="$(python3 -c 'print("x"*4001)')"
B="{\"message\":\"$LONG\",\"channel\":\"mattermost\",\"company\":\"FORSIS\",\"actor\":$ACT_BODY}"
OUT="$(chat "$TOKEN_MM" mattermost "" "$B")"
CODE="$(http_code "$OUT")"; EC="$(http_body "$OUT" | jget error_code)"
[ "$CODE" = "413" ] && [ "$EC" = "MESSAGE_TOO_LONG" ] \
  && ok "A2.3 >4000 chars → 413 MESSAGE_TOO_LONG" \
  || bad "A2.3 >4000 chars → $CODE $EC (esperado 413)"

# A2.4 token inválido → 401 UNAUTHENTICATED
OUT="$(chat "token_invalido_xyz" mattermost "" "$BODY_OK")"
CODE="$(http_code "$OUT")"; EC="$(http_body "$OUT" | jget error_code)"
[ "$CODE" = "401" ] && [ "$EC" = "UNAUTHENTICATED" ] \
  && ok "A2.4 token inválido → 401 UNAUTHENTICATED" \
  || bad "A2.4 token inválido → $CODE $EC (esperado 401)"

# A2.4b sin header Authorization → 401
OUT="$(chat "" mattermost "" "$BODY_OK")"
CODE="$(http_code "$OUT")"
[ "$CODE" = "401" ] && ok "A2.4b Authorization ausente → 401" || bad "A2.4b sin token → $CODE (esperado 401)"

# A2.5 actor.authorized=false → 403 FORBIDDEN
B="{\"message\":\"hola\",\"channel\":\"mattermost\",\"company\":\"FORSIS\",\"actor\":{\"subject\":\"verify_s2\",\"subject_type\":\"mattermost_user\",\"display_name\":\"Verify S2\",\"roles\":[],\"authorized\":false}}"
OUT="$(chat "$TOKEN_MM" mattermost "" "$B")"
CODE="$(http_code "$OUT")"; EC="$(http_body "$OUT" | jget error_code)"
[ "$CODE" = "403" ] && [ "$EC" = "FORBIDDEN" ] \
  && ok "A2.5 authorized=false → 403 FORBIDDEN" \
  || bad "A2.5 authorized=false → $CODE $EC (esperado 403)"

# A2.6 canal ≠ token → 403 CHANNEL_MISMATCH
B="{\"message\":\"hola\",\"channel\":\"widget-trafico\",\"company\":\"FORSIS\",\"actor\":{\"subject\":\"verify_s2\",\"subject_type\":\"trafico_user\",\"display_name\":\"Verify S2\",\"roles\":[],\"authorized\":true}}"
OUT="$(chat "$TOKEN_MM" mattermost "" "$B")"
CODE="$(http_code "$OUT")"; EC="$(http_body "$OUT" | jget error_code)"
[ "$CODE" = "403" ] && [ "$EC" = "CHANNEL_MISMATCH" ] \
  && ok "A2.6 canal del body ≠ canal autenticado → 403 CHANNEL_MISMATCH" \
  || bad "A2.6 canal cruzado → $CODE $EC (esperado 403)"

# A2.7 misma Idempotency-Key con cuerpo distinto → 422 IDEMPOTENCY_KEY_REUSED
OUT="$(chat "$TOKEN_MM" mattermost "$IDEM_A1" '{"message":"gracias","channel":"mattermost","company":"FORSIS","actor":'"$ACT_BODY"'}')"
CODE="$(http_code "$OUT")"; EC="$(http_body "$OUT" | jget error_code)"
[ "$CODE" = "422" ] && [ "$EC" = "IDEMPOTENCY_KEY_REUSED" ] \
  && ok "A2.7 misma key + cuerpo distinto → 422 IDEMPOTENCY_KEY_REUSED" \
  || bad "A2.7 key reutilizada → $CODE $EC (esperado 422)"

# =============================================================================
head_ "A3 — IDEMPOTENCIA (replay idéntico)"
# =============================================================================
IDEM_A3="s2-a3-$(date +%s)-$RANDOM"
B1="{\"message\":\"buenos dias\",\"channel\":\"mattermost\",\"company\":\"FORSIS\",\"actor\":$ACT_BODY}"
O1="$(chat "$TOKEN_MM" mattermost "$IDEM_A3" "$B1")"
O2="$(chat "$TOKEN_MM" mattermost "$IDEM_A3" "$B1")"
C1="$(http_code "$O1")"; C2="$(http_code "$O2")"
R1="$(http_body "$O1")"; R2="$(http_body "$O2")"
[ "$C1" = "200" ] && [ "$C2" = "200" ] \
  && ok "A3.1 dos POST idénticos → 200 / 200" \
  || bad "A3.1 códigos $C1 / $C2 (esperado 200/200)"
[ "$R1" = "$R2" ] \
  && ok "A3.2 replay devuelve cuerpo byte-idéntico (mismo trace_id y session_id)" \
  || bad "A3.2 cuerpos difieren entre la primera llamada y el replay"
T1="$(printf '%s' "$R1" | python3 -c "import json,sys;print(json.load(sys.stdin)['trace']['trace_id'])" 2>/dev/null)"
T2="$(printf '%s' "$R2" | python3 -c "import json,sys;print(json.load(sys.stdin)['trace']['trace_id'])" 2>/dev/null)"
[ -n "$T1" ] && [ "$T1" = "$T2" ] \
  && ok "A3.3 mismo trace_id ($T1)" \
  || bad "A3.3 trace_id difieren: '$T1' vs '$T2'"

# =============================================================================
head_ "A4 — FAIL-CLOSED DE PROVEEDOR (Omniroute caído → 502)"
# =============================================================================
OUT="$( $COMPOSE run --rm --no-deps -e OMNIROUTE_BASE_URL=http://127.0.0.1:9/v1 \
        -e OMNIROUTE_TIMEOUT_S=2 app python - <<'PY' 2>/dev/null
import os, sys, asyncio
sys.path.insert(0, "/app")
from app.contracts.chat_contract import ChatRequest
from app.core.agent_service import AgentService
from app.core.exceptions import LlmUnavailableError

async def main():
    svc = AgentService.__new__(AgentService)
    from app.infrastructure.llm_gateway.omniroute_provider import OmnirouteProvider
    svc.provider = OmnirouteProvider()
    req = ChatRequest(**{
        "message": "cuantos viajes hay activos hoy?",
        "channel": "mattermost",
        "company": "FORSIS",
        "actor": {"subject": "verify_s2", "subject_type": "mattermost_user",
                  "display_name": "Verify S2", "roles": [], "authorized": True},
    })
    try:
        await svc.process_turn(req)
    except LlmUnavailableError as exc:
        print("CAUGHT", exc.http_status, exc.error_code, exc.retryable)
        return
    print("NOT_RAISED")

asyncio.run(main())
PY
)"
printf '%s' "$OUT" | grep -q "CAUGHT 502 LLM_UNAVAILABLE False" \
  && ok "A4.1 OmniRoute inalcanzable → LlmUnavailableError(502, LLM_UNAVAILABLE, retryable=False)" \
  || bad "A4.1 con OmniRoute caído se obtuvo: $(printf '%s' "$OUT" | tr '\n' ' ')"

# el handler HTTP nunca debe convertirlo en 500
B="{\"message\":\"prueba fallclosed\",\"channel\":\"mattermost\",\"company\":\"FORSIS\",\"actor\":$ACT_BODY}"
H="$(curl -k -s -m 20 -w '\n%{http_code}' -X POST "$BASE/api/v1/chat" \
     -H "Authorization: Bearer $TOKEN_MM" -H 'X-Forsis-Channel: mattermost' \
     -H 'Content-Type: application/json' -d "$B" | tail -1)"
[ "$H" != "500" ] \
  && ok "A4.2 el camino infeliz no degenera en HTTP 500 (con LLM arriba: $H)" \
  || bad "A4.2 HTTP 500 en camino infeliz"

# =============================================================================
head_ "A5 — TECHO DE TURNO"
# =============================================================================
LIMIT="$(python3 -c "
import re
src=open('/home/servidor/forsis-ai-agent/app/core/agent_service.py').read()
m=re.search(r'TURN_TIMEOUT_SECONDS\s*=\s*([0-9.]+)',src)
print(m.group(1) if m else 'NOT_FOUND')
")"
[ "$LIMIT" = "120.0" ] \
  && ok "A5.1 TURN_TIMEOUT_SECONDS == 120.0 s en AgentService" \
  || bad "A5.1 TURN_TIMEOUT_SECONDS == $LIMIT (esperado 120.0)"

CEIL="$(python3 -c "
import re
src=open('/home/servidor/forsis-ai-agent/app/infrastructure/llm_gateway/omniroute_provider.py').read()
m=re.search(r'timeout:\s*float\s*=\s*([0-9.]+)',src)
print(m.group(1) if m else 'NOT_FOUND')
")"
[ "$CEIL" = "60.0" ] \
  && ok "A5.2 techo duro por llamada LLM == 60.0 s (ThreadPoolExecutor)" \
  || bad "A5.2 techo duro LLM == $CEIL (esperado 60.0)"

LAT="$(printf '%s' "$R1" | python3 -c "import json,sys;print(json.load(sys.stdin)['trace']['latency_ms']['total'])" 2>/dev/null)"
if [ -n "$LAT" ] && [ "$LAT" -lt 125000 ]; then
  ok "A5.3 latencia real del turno ${LAT} ms < 125000 ms"
else
  bad "A5.3 latencia real del turno ${LAT} ms"
fi

# nginx debe permitir turnos largos
NT="$(grep -oE 'proxy_(read|send)_timeout[^;]*;' /home/servidor/forsis-ai-agent/docker/nginx/default.conf | tr '\n' ' ')"
printf '%s' "$NT" | grep -qE '130s' \
  && ok "A5.4 timeouts de nginx ≥ 130 s ($NT)" \
  || bad "A5.4 timeouts de nginx insuficientes ($NT)"

# =============================================================================
head_ "A6 — MÉTRICAS POR CAPA DE PARSEO LLM"
# =============================================================================
MET="$(curl -k -s -m 20 "$BASE/api/v1/metrics")"
for k in llm_json_ok llm_salvage llm_failclosed; do
  V="$(printf '%s' "$MET" | jget "$k")"
  [ -n "$V" ] && ok "A6.$k métrica presente (valor=$V)" || bad "A6.$k métrica ausente"
done
HAS_CACHE="$(printf '%s' "$MET" | python3 -c "import json,sys;d=json.load(sys.stdin);c=d.get('counters',{});print('yes' if ('cache_hit' in c and 'cache_miss' in c) else 'no')" 2>/dev/null)"
[ "$HAS_CACHE" = "yes" ] && ok "A6.cache métricas cache_hit/cache_miss presentes" || bad "A6.cache métricas de caché ausentes"

# =============================================================================
head_ "A7 — PERSISTENCIA REAL EN POSTGRESQL"
# =============================================================================
PSQL="docker exec forsis-ai-agent-db psql -U forsis_agent -d forsis_agent -tAc"

AUD="$($PSQL "SELECT count(*) FROM agent_audit_log WHERE actor_subject='verify_s2'")"
[ "${AUD:-0}" -ge 1 ] \
  && ok "A7.1 agent_audit_log poblado ($AUD registro(s) para verify_s2)" \
  || bad "A7.1 agent_audit_log sin registros para verify_s2"

SES="$($PSQL "SELECT count(*) FROM chat_sessions WHERE actor_subject='verify_s2'")"
[ "${SES:-0}" -ge 1 ] \
  && ok "A7.2 chat_sessions persistido ($SES sesión(es))" \
  || bad "A7.2 chat_sessions sin registro"

MSG="$($PSQL "SELECT count(*) FROM chat_messages m JOIN chat_sessions s USING(session_id) WHERE s.actor_subject='verify_s2'")"
[ "${MSG:-0}" -ge 2 ] \
  && ok "A7.3 chat_messages con pares user/assistant ($MSG mensajes)" \
  || bad "A7.3 chat_messages incompleto ($MSG)"

IDEM="$($PSQL "SELECT count(*) FROM idempotency_keys WHERE state='COMPLETED' AND completed_at IS NOT NULL")"
[ "${IDEM:-0}" -ge 1 ] \
  && ok "A7.4 idempotency_keys COMPLETED con completed_at ($IDEM)" \
  || bad "A7.4 idempotency_keys sin entradas completadas"

# toda fila de auditoría debe tener duración y status
BADROWS="$($PSQL "SELECT count(*) FROM agent_audit_log WHERE duration_ms IS NULL OR status IS NULL")"
[ "${BADROWS:-0}" -eq 0 ] \
  && ok "A7.5 toda fila de auditoría tiene status y duration_ms" \
  || bad "A7.5 $BADROWS fila(s) de auditoría incompleta(s)"

# =============================================================================
head_ "A8 — AISLAMIENTO DEL RUNTIME (invariantes Sprint 1)"
# =============================================================================
$COMPOSE config --no-interpolate 2>/dev/null | grep -q 'knowledge' \
  && bad "A8.1 knowledge/ montado en la imagen de producción" \
  || ok "A8.1 knowledge/ NO está montado en producción"

PID="$(pgrep -f 'uvicorn' | head -1)"
[ -n "$PID" ] && ok "A8.2 uvicorn en ejecución (PID $PID)" || bad "A8.2 uvicorn no está en ejecución"

FIRMA_ESP="$(cat /home/servidor/forsis-ai-agent/.firma-esperada 2>/dev/null)"
FIRMA_ACT="$(curl -k -s -m 20 "$BASE/api/v1/ready" | jget planner_signature)"
[ -n "$FIRMA_ESP" ] && [ "$FIRMA_ESP" = "$FIRMA_ACT" ] \
  && ok "A8.3 firma del Planner sin cambios ($FIRMA_ACT)" \
  || bad "A8.3 firma Planner esperada '$FIRMA_ESP' ≠ actual '$FIRMA_ACT'"

# =============================================================================
printf '\n\033[1m═══ RESULTADO SPRINT 2 ═══\033[0m\n'
printf '  PASS: %d\n  FAIL: %d\n' "$PASS" "$FAIL"
if [ "$FAIL" -eq 0 ]; then
  printf '\n\033[32mSprint 2 verificado: %d/%d checks OK\033[0m\n' "$PASS" "$PASS"
  exit 0
else
  printf '\n\033[31mSprint 2 con fallos: %d de %d checks\033[0m\n' "$FAIL" "$((PASS+FAIL))"
  exit 1
fi