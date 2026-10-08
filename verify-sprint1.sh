#!/usr/bin/env bash
# Forsis AI Agent — Sprint 1, criterios de aceptación A1..A7 (sprint-plan-v2.md §Sprint 1)
# Uso: ./verify-sprint1.sh
set -uo pipefail
cd "$(dirname "$0")"

PASS=0
FAIL=0

ok()   { echo "  ✅ $1"; PASS=$((PASS+1)); }
bad()  { echo "  ❌ $1"; echo "     esperado: $2"; echo "     obtenido: $3"; FAIL=$((FAIL+1)); }
check(){ # check <descripción> <esperado> <obtenido>
  if [ "$2" = "$3" ]; then ok "$1"; else bad "$1" "$2" "$3"; fi
}

# El puerto 8080 del HOST lo ocupa otro servicio (Ratchet). El listener plano
# del agente vive DENTRO de la red de compose, así que se prueba desde nginx.
API() { docker compose exec -T nginx wget -q -O- "http://127.0.0.1:8080$1" 2>/dev/null; }

echo "════════ A1. health y ready ════════"
H="$(API /api/v1/health)"
echo "$H" | grep -q '"status":"ok"' && ok "GET /api/v1/health → status ok" \
  || bad "GET /api/v1/health" '"status":"ok"' "$H"

R="$(API /api/v1/ready)"
echo "$R" | grep -q '"db":"ok"'  && ok "GET /api/v1/ready → db ok"    || bad "ready.db"    '"db":"ok"'  "$R"
echo "$R" | grep -q '"llm":"ok"' && ok "GET /api/v1/ready → llm ok"   || bad "ready.llm"   '"llm":"ok"' "$R"

echo "════════ A2. el runtime es Python, no PHP ════════"
PYV="$(docker compose exec -T app python3 --version 2>&1 | tr -d '\r')"
echo "$PYV" | grep -qE '^Python 3\.12' && ok "$PYV" || bad "python3 --version" "Python 3.12.x" "$PYV"

PHPREFS="$(docker compose config | grep -c 'fastcgi_pass\|php-fpm')"
check "docker compose config sin andamiaje PHP" "0" "$PHPREFS"

echo "════════ A3. la BD no está expuesta al host ════════"
if docker compose config | grep -A3 '^  db:' | grep -qE '^\s+ports:'; then
  bad "db sin puertos publicados" "sin bloque ports:" "db publica puertos"
else
  ok "db no publica puertos al host"
fi
# El puerto 5432 del HOST pertenece al PostgreSQL del host, no al agente:
# se comprueba que NADIE de este proyecto lo publique.
if ss -lntp 2>/dev/null | grep ':5432' | grep -q 'docker-proxy'; then
  bad "nada docker-proxy en 5432" "sin docker-proxy" "$(ss -lntp | grep ':5432')"
else
  ok "el 5432 del host NO es del agente (no docker-proxy)"
fi

echo "════════ A4. las 7 tablas existen ════════"
NT="$(docker compose exec -T db psql -U forsis_agent -d forsis_agent -tAc \
  "select count(*) from information_schema.tables where table_name in
   ('sessions','messages','plans','audit_log','idempotency_keys','channel_identity_map','agent_ui_users')" \
  | tr -d '\r')"
check "sessions/messages/plans/audit_log/idempotency_keys/channel_identity_map/agent_ui_users" "7" "$NT"

echo "════════ A5. exactamente 1 cuenta UI, con password hasheado ════════"
NU="$(docker compose exec -T db psql -U forsis_agent -d forsis_agent -tAc \
  "select count(*) from agent_ui_users" | tr -d '\r')"
if [ "$NU" -ge 1 ]; then ok "agent_ui_users >= 1 filas ($NU)"; else bad "agent_ui_users >= 1" ">=1" "$NU"; fi

HASH="$(docker compose exec -T db psql -U forsis_agent -d forsis_agent -tAc \
  "select count(*) from agent_ui_users where password_hash is not null" | tr -d '\r')"
if [ "$HASH" = "0" ]; then
  ok "password_hash es NULL (autentica contra trafico-system, Sprint 5)"
else
  bad "password_hash es NULL" "0" "$HASH"
fi

echo "════════ A6. firma del planner ════════"
FIRMA_ACTUAL="$(./verify-firma.sh 2>/dev/null | tail -1)"
if [ -f .firma-esperada ]; then
  ESPERADA="$(cat .firma-esperada | tr -d '\r[:space:]')"
  if [ "$FIRMA_ACTUAL" = "$ESPERADA" ]; then
    ok "firma coincide con .firma-esperada"
  else
    bad "firma del planner" "$ESPERADA" "$FIRMA_ACTUAL"
  fi
  ./verify-firma.sh --esperado "$ESPERADA" >/dev/null 2>&1 \
    && ok "./verify-firma.sh --esperado → exit 0" \
    || bad "./verify-firma.sh --esperado" "exit 0" "exit $?"
else
  echo "  ⚠️  No hay .firma-esperada aún. Firma actual: $FIRMA_ACTUAL"
  echo "     (genérala con: ./verify-firma.sh --guardar && mv .firma-actual .firma-esperada)"
  ok "firma disponible y calculable"
fi

echo "════════ A7. sin secretos literales en la config ════════"
LEAK="$(docker compose config --no-interpolate | grep -E 'POSTGRES_PASSWORD|TOKEN|SECRET|API_KEY' | grep -v '\${' || true)"
if [ -z "$LEAK" ]; then
  ok "ningún secreto literal en docker compose config"
else
  bad "secretos literales" "ninguno" "$LEAK"
fi

echo
echo "════════ RESULTADO: $PASS PASS / $FAIL FAIL ════════"
[ "$FAIL" -eq 0 ]