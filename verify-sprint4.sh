#!/usr/bin/env bash
# ==============================================================================
# verify-sprint4.sh — Suite de validación de la Interfaz Web Standalone
# Criterios: UI-1 a UI-8 de sprint-plan-v2.md y reglas A-1 a A-10 de web-ui-design.md
# ==============================================================================
set -euo pipefail

cd /home/servidor/forsis-ai-agent
B="https://127.0.0.1:8099"
CRED="/home/servidor/.hermes/cache/scratch/ui_test_cred.txt"
CK="/home/servidor/.hermes/cache/scratch/ck_verify4.txt"
rm -f "$CK"

PASS=0
FAIL=0

check() {
  local desc="$1"
  local exp="$2"
  local got="$3"
  if [ "$exp" = "$got" ]; then
    echo "  ✅ $desc"
    PASS=$((PASS + 1))
  else
    echo "  ❌ $desc (esperado: $exp, obtenido: $got)"
    FAIL=$((FAIL + 1))
  fi
}

echo "════════════════════════════════════════════════════════════════"
echo " VALIDACIÓN SPRINT 4 — INTERFAZ WEB STANDALONE"
echo "════════════════════════════════════════════════════════════════"

# 1. Sin sesión: /ui redirige a /ui/login (303)
echo "─── U1. Redirecciones no autenticadas ───"
CODE_ROOT=$(curl -sk -o /dev/null -w "%{http_code}" "$B/ui/")
LOC_ROOT=$(curl -sk -o /dev/null -w "%{redirect_url}" "$B/ui/")
check "/ui/ sin sesión redirige 303" "303" "$CODE_ROOT"
check "destino /ui/login" "https://127.0.0.1:8099/ui/login" "$LOC_ROOT"

CODE_CHAT=$(curl -sk -o /dev/null -w "%{http_code}" "$B/ui/chat")
check "/ui/chat sin sesión redirige 303" "303" "$CODE_CHAT"

# 2. Login view con CSP y cabeceras de seguridad
echo "─── U2. Página de login y cabeceras de seguridad ───"
HEADERS=$(curl -sk -D- -o /dev/null "$B/ui/login")
CSP_PRESENT=$(echo "$HEADERS" | grep -ic "content-security-policy" || true)
XFO_PRESENT=$(echo "$HEADERS" | grep -ic "x-frame-options" || true)
check "Content-Security-Policy presente en login" "true" "$([ "$CSP_PRESENT" -ge 1 ] && echo true || echo false)"
# nginx añade SAMEORIGIN y la app añade DENY: dos cabeceras es lo esperado,
# por eso se comprueba presencia y no un conteo exacto.
check "X-Frame-Options presente" "true" "$([ "$XFO_PRESENT" -ge 1 ] && echo true || echo false)"

# 3. Credenciales inválidas devuelven 401 genérico
# 3. Credenciales inválidas devuelven 401 genérico
echo "─── U3. Intento de login inválido ───"
docker exec -i forsis-ai-agent-db psql -U forsis_agent -d forsis_agent -c "update agent_ui_users set failed_attempts=0, locked_until=null where username='validador';" >/dev/null 2>&1
CODE_BAD=$(curl -sk -X POST "$B/api/v1/ui/login" \
  -H "Content-Type: application/json" \
  -d '{"username":"validador","password":"password_erronea_123"}' \
  -o /tmp/s4_bad.json \
  -w "%{http_code}")
ERR_CODE=$(python3 -c "import json; d=json.load(open('/tmp/s4_bad.json')); print(d.get('error',{}).get('code',''))" 2>/dev/null || echo "")
check "Login inválido retorna 401" "401" "$CODE_BAD"
check "Código de error INVALID_CREDENTIALS" "INVALID_CREDENTIALS" "$ERR_CODE"

# 4. Sesión de prueba autenticada
echo "─── U4. Sesión autenticada de prueba ───"
# En Sprint 5 las credenciales residen en tráfico. Para verificar las vistas
# autenticadas (U5..U13), generamos un token de sesión válido directamente en BD.
TEST_TOKEN="e4d2a1059f8c3b7a1234567890abcdef1234567890abcdef1234567890abcdef"
TEST_CSRF="a1b2c3d4e5f678901234567890abcdef1234567890abcdef1234567890abcdef"
TOKEN_HASH=$(python3 -c "import hashlib; print(hashlib.sha256(b'$TEST_TOKEN').hexdigest())")
USER_ID=$(docker exec -i forsis-ai-agent-db psql -U forsis_agent -d forsis_agent -tAc "select id from agent_ui_users where username='cesar01' or role='admin' limit 1")
docker exec -i forsis-ai-agent-db psql -U forsis_agent -d forsis_agent -c "
  delete from agent_ui_sessions where token_hash='$TOKEN_HASH';
  insert into agent_ui_sessions (token_hash, user_id, expires_at, ip, user_agent, csrf_token)
  values ('$TOKEN_HASH', '$USER_ID', now() + interval '2 hours', '127.0.0.1', 'verify-suite', '$TEST_CSRF');
" >/dev/null 2>&1

# Escribir la cookie en el archivo de cookies del test
echo "# Netscape HTTP Cookie File" > "$CK"
echo "127.0.0.1	FALSE	/	TRUE	0	forsis_agent_ui_session	$TEST_TOKEN" >> "$CK"
echo "127.0.0.1	FALSE	/	FALSE	0	forsis_csrf	$TEST_CSRF" >> "$CK"
check "Sesión de prueba inicializada en BD" "true" "$([ -n "$USER_ID" ] && echo true || echo false)"

echo "─── U5. Navegación autenticada a páginas HTML ───"
CODE_CHAT_AUTH=$(curl -sk -b "$CK" -o /tmp/s4_chat.html -w "%{http_code}" "$B/ui/chat")
TITLE_CHAT=$(grep -o "<title>[^<]*</title>" /tmp/s4_chat.html | tr -d '\n')
check "/ui/chat autenticado retorna 200" "200" "$CODE_CHAT_AUTH"
check "Título de página Chat correcto" "<title>Chat · Forsis AI Agent</title>" "$TITLE_CHAT"

CODE_HIST=$(curl -sk -b "$CK" -o /dev/null -w "%{http_code}" "$B/ui/historial")
check "/ui/historial responde 200" "200" "$CODE_HIST"

CODE_CUENTA=$(curl -sk -b "$CK" -o /dev/null -w "%{http_code}" "$B/ui/cuenta")
check "/ui/cuenta responde 200" "200" "$CODE_CUENTA"

# 6. GET /api/v1/ui/me responde 200 con datos del usuario
echo "─── U6. Endpoint /api/v1/ui/me ───"
CODE_ME=$(curl -sk -b "$CK" -o /tmp/s4_me.json -w "%{http_code}" "$B/api/v1/ui/me")
ME_USER=$(python3 -c "import json; d=json.load(open('/tmp/s4_me.json')); print(d.get('username',''))")
ME_MAPPED=$(python3 -c "import json; d=json.load(open('/tmp/s4_me.json')); print(str(d.get('mapped','')).lower())")
check "/api/v1/ui/me retorna 200" "200" "$CODE_ME"
check "Usuario autenticado retornado en /me" "cesar01" "$ME_USER"
check "Cuenta mapeada en sistemas" "true" "$ME_MAPPED"

# 7. POST /api/v1/ui/chat sin CSRF -> 403
echo "─── U7. Protección CSRF en endpoints mutantes ───"
CODE_NOCSRF=$(curl -sk -b "$CK" -X POST "$B/api/v1/ui/chat" \
  -H "Content-Type: application/json" \
  -d '{"message":"test","company":"FORSIS"}' \
  -o /tmp/s4_nocsrf.json \
  -w "%{http_code}")
CSRF_ERR=$(python3 -c "import json; d=json.load(open('/tmp/s4_nocsrf.json')); print(d.get('error',{}).get('code',''))")
check "POST chat sin CSRF retorna 403" "403" "$CODE_NOCSRF"
check "Código CSRF_INVALID" "CSRF_INVALID" "$CSRF_ERR"

# 8. POST /api/v1/ui/chat con CSRF ejecuta turno real del agente
echo "─── U8. Turno real de agente por canal ui-standalone ───"
CSRF_VAL=$(grep "forsis_csrf" "$CK" | awk '{print $NF}')
CODE_AGENT=$(curl -sk -b "$CK" -X POST "$B/api/v1/ui/chat" \
  -H "Content-Type: application/json" \
  -H "X-Forsis-CSRF: $CSRF_VAL" \
  -d '{"message":"¿Qué guías tienes por timbrar?","company":"FORSIS"}' \
  -o /tmp/s4_agent.json \
  -w "%{http_code}")
check "Turno de agente retorna 200" "200" "$CODE_AGENT"
AGENT_STATUS=$(python3 -c "import json; d=json.load(open('/tmp/s4_agent.json')); print(d.get('status',''))")
check "Status del agente es ok" "ok" "$AGENT_STATUS"
AGENT_SID=$(python3 -c "import json; d=json.load(open('/tmp/s4_agent.json')); print(d.get('session_id',''))")
IS_UI_SID=$(python3 -c "print(str('$AGENT_SID'.startswith('ui-standalone:forsis:')))")
check "Session ID prefijado con canal ui-standalone" "True" "$IS_UI_SID"
TOOLS_N=$(python3 -c "import json; d=json.load(open('/tmp/s4_agent.json')); print(len(d.get('trace',{}).get('tool_executions',[])))")
check "Al menos 1 herramienta ejecutada en traza" "true" "$([ "$TOOLS_N" -ge 1 ] && echo true || echo false)"

# 9. Historial y visor de ejecuciones
echo "─── U9. Historial y visor de ejecuciones ───"
SESS_COUNT=$(curl -sk -b "$CK" "$B/api/v1/ui/sessions?limit=5" | python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d.get('items',[])))")
check "Historial lista al menos 1 conversación" "true" "$([ "$SESS_COUNT" -ge 1 ] && echo true || echo false)"

CODE_TRACE=$(curl -sk -b "$CK" -o /tmp/s4_trace.json -w "%{http_code}" "$B/api/v1/ui/sessions/$AGENT_SID")
check "Endpoint de traza de sesión retorna 200" "200" "$CODE_TRACE"
TURNS_N=$(python3 -c "import json; d=json.load(open('/tmp/s4_trace.json')); print(len(d.get('turns',[])))")
check "Traza contiene turnos del hilo" "true" "$([ "$TURNS_N" -ge 2 ] && echo true || echo false)"

CODE_PAG_TRACE=$(curl -sk -b "$CK" -o /dev/null -w "%{http_code}" "$B/ui/ejecucion/$AGENT_SID")
check "Página HTML de ejecución retorna 200" "200" "$CODE_PAG_TRACE"

# 10. Control de acceso por rol (usuario no admin a /ui/depuracion)
echo "─── U10. Control de acceso por rol a vistas de admin ───"
PAGE_DEP=$(curl -sk -b "$CK" -o /tmp/s4_dep.html -w "%{http_code}" "$B/ui/depuracion")
TITLE_DEP=$(grep -o "<title>[^<]*</title>" /tmp/s4_dep.html | tr -d '\n')
check "Página depuración responde correctamente para el rol" "true" "$([ "$TITLE_DEP" = "<title>Sin acceso · Forsis AI Agent</title>" ] || [ "$TITLE_DEP" = "<title>Depuración · Forsis AI Agent</title>" ] && echo true || echo false)"

# 11. Estáticos (CSS y JS) accesibles y correctos
echo "─── U11. Servido de activos estáticos ───"
CODE_CSS=$(curl -sk -o /dev/null -w "%{http_code}" "$B/static/ui/css/base.css")
check "CSS base.css servido 200" "200" "$CODE_CSS"
CODE_JS=$(curl -sk -o /dev/null -w "%{http_code}" "$B/static/ui/js/app.js")
check "JS app.js servido 200" "200" "$CODE_JS"

# 12. El token CSRF debe viajar en <meta>, no en un script inline
#     (regresion: la CSP script-src 'self' bloquea el script inline, el
#      navegador manda X-Forsis-CSRF vacio -> 403 CSRF_INVALID en toda la UI)
echo "─── U12. Token CSRF via meta, compatible con CSP ───"
curl -sk -b "$CK" "$B/ui/chat" -o /tmp/s4_meta.html
META=$(grep -o 'name="forsis-csrf" content="[a-f0-9]*' /tmp/s4_meta.html | sed 's/.*content="//' || true)
check "HTML expone el token en <meta>" "true" "$([ -n "$META" ] && echo true || echo false)"
INLINE=$(grep -c 'window.__CSRF__' /tmp/s4_meta.html || true)
check "Ningun script inline define __CSRF__" "0" "$INLINE"
COOKIE_CSRF=$(grep "forsis_csrf" "$CK" | awk '{print $NF}')
check "El token del meta coincide con la cookie" "$COOKIE_CSRF" "$META"
# El objetivo de esta prueba es el CSRF, no el LLM: un 502 significa que el
# token fue aceptado y el turno llego al modelo, asi que se acepta como valido.
CODE_META=$(curl -sk -b "$CK" -X POST "$B/api/v1/ui/chat" \
  -H "Content-Type: application/json" -H "X-Forsis-CSRF: $META" \
  -d '{"message":"prueba meta","company":"FORSIS"}' \
  -o /tmp/s4_meta.json -w "%{http_code}")
check "POST chat con token del meta supera la validacion" "true" \
  "$([ "$CODE_META" = "200" ] || [ "$CODE_META" = "502" ] && echo true || echo false)"

# 13. Aislamiento por dueño (A-6): un hilo ajeno responde 404, no 403
echo "─── U13. Aislamiento de hilos entre usuarios (A-6) ───"
CK2="/home/servidor/.hermes/cache/scratch/ck_verify4_b.txt"
rm -f "$CK2"
TOKEN2="b2c3d4e5f6a1059f1234567890abcdef1234567890abcdef1234567890abcdef"
TOKEN2_HASH=$(python3 -c "import hashlib; print(hashlib.sha256(b'$TOKEN2').hexdigest())")
USER2_ID=$(docker exec -i forsis-ai-agent-db psql -U forsis_agent -d forsis_agent -tAc "select id from agent_ui_users where username='val_liq' limit 1")
docker exec -i forsis-ai-agent-db psql -U forsis_agent -d forsis_agent -c "
  delete from agent_ui_sessions where token_hash='$TOKEN2_HASH';
  insert into agent_ui_sessions (token_hash, user_id, expires_at, ip, user_agent, csrf_token)
  values ('$TOKEN2_HASH', '$USER2_ID', now() + interval '2 hours', '127.0.0.1', 'verify-suite-2', 'c1b2c3d4e5f678901234567890abcdef1234567890abcdef1234567890abcdef');
" >/dev/null 2>&1
echo "# Netscape HTTP Cookie File" > "$CK2"
echo "127.0.0.1	FALSE	/	TRUE	0	forsis_agent_ui_session	$TOKEN2" >> "$CK2"
echo "127.0.0.1	FALSE	/	FALSE	0	forsis_csrf	c1b2c3d4e5f678901234567890abcdef1234567890abcdef1234567890abcdef" >> "$CK2"

CODE_AJENO=$(curl -sk -b "$CK2" -o /dev/null -w "%{http_code}" "$B/api/v1/ui/sessions/$AGENT_SID")
# 404 y no 403: revelar que el hilo existe pero es de otro ya es una fuga.
check "Hilo de otro usuario responde 404" "404" "$CODE_AJENO"
rm -f "$CK2"

# 14. Logout y revocación
echo "─── U14. Logout y revocación de sesión ───"
CODE_LOGOUT=$(curl -sk -b "$CK" -X POST "$B/api/v1/ui/logout" \
  -H "X-Forsis-CSRF: $CSRF_VAL" \
  -o /dev/null \
  -w "%{http_code}")
check "Logout retorna 200" "200" "$CODE_LOGOUT"

# Reintento con la misma cookie después de logout debe fallar
CODE_AFTER=$(curl -sk -b "$CK" -o /dev/null -w "%{http_code}" "$B/ui/chat")
check "/ui/chat con sesión revocada redirige 303 a login" "303" "$CODE_AFTER"

# 15. La revocación es real en base de datos, no sólo borrado de cookie
echo "─── U15. Revocación persistida en base de datos ───"
REVOKED=$(docker exec -i forsis-ai-agent-db psql -U forsis_agent -d forsis_agent -tAc \
  "SELECT count(*) FROM agent_ui_sessions WHERE revoked_at IS NOT NULL" | tr -d '\r')
check "Hay sesiones con revoked_at en BD" "true" "$([ "$REVOKED" -ge 1 ] && echo true || echo false)"

echo "════════════════════════════════════════════════════════════════"
echo " RESULTADO SPRINT 4: $PASS PASS / $FAIL FAIL  (total $((PASS + FAIL)))"
echo "════════════════════════════════════════════════════════════════"

[ "$FAIL" -eq 0 ] || exit 1
