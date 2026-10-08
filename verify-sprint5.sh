#!/usr/bin/env bash
# ============================================================================
# verify-sprint5.sh — verificación del Sprint 5 (identidad desde trafico-system)
#
# Diseño: /home/servidor/forsis-ai-agent/knowledge/phase1/sprint5-identity-design.md
#
# Las pruebas que requieren una contraseña real de tráfico leen la variable
# SPRINT5_TRAF_PASSWORD del entorno. Si no está definida, esas pruebas se
# marcan SKIP — no PASS. Un SKIP honesto es preferible a un PASS simulado.
#
# Restricción permanente: este suite NUNCA imprime ni acepta un hash de tráfico,
# y NUNCA escribe en trafico-system.
# ============================================================================
set -uo pipefail
cd "$(dirname "$0")"

B=https://127.0.0.1:8099
DB=forsis-ai-agent-db
PASS=0; FAIL=0; SKIP=0

check() { # descripcion esperado obtenido
    if [ "$2" = "$3" ]; then
        printf '  ✓ %s\n' "$1"; PASS=$((PASS+1))
    else
        printf '  ✗ %s\n      esperado=%s obtenido=%s\n' "$1" "$2" "$3"; FAIL=$((FAIL+1))
    fi
}
skip() { printf '  ⊘ %s (%s)\n' "$1" "$2"; SKIP=$((SKIP+1)); }

q() { docker exec -i "$DB" psql -U forsis_agent -d forsis_agent -tAc "$1" 2>/dev/null | tr -d '\r'; }

echo "══════ SPRINT 5 · IDENTIDAD DESDE TRAFICO-SYSTEM ══════"

# ---------------------------------------------------------------- 1. migración
echo ""
echo "─── 1. Migración 07 aplicada ───"
check "password_hash es NULL en todas las filas" "0" "$(q "select count(*) from agent_ui_users where password_hash is not null")"
check "la columna password_hash acepta NULL" "YES" "$(q "select is_nullable from information_schema.columns where table_name='agent_ui_users' and column_name='password_hash'")"
check "no queda ninguna cuenta must_change_password" "0" "$(q "select count(*) from agent_ui_users where must_change_password")"
check "forsis_admin fue eliminado" "0" "$(q "select count(*) from agent_ui_users where username='forsis_admin'")"

# ---------------------------------------------------------------- 2. derivación de roles
echo ""
echo "─── 2. Derivación de rol de UI desde el rol de tráfico ───"
rol() { docker exec forsis-ai-agent-app python3 -c "
import sys; sys.path.insert(0,'/app')
from app.web import identity; print(identity.derivar_rol_ui('$1'))" 2>/dev/null; }
check "SUPER USUARIO -> admin"          "admin"     "$(rol 'SUPER USUARIO')"
check "TRÁFICO -> validador"            "validador" "$(rol 'TRÁFICO')"
check "ADMINISTRADOR (QHSE) -> validador" "validador" "$(rol 'ADMINISTRADOR')"
check "FACTURACIÓN -> validador"        "validador" "$(rol 'FACTURACIÓN')"
check "rol desconocido -> validador (fail closed)" "validador" "$(rol 'ROL_INVENTADO')"
check "rol NULL -> validador (fail closed)"      "validador" "$(rol '')"
check "UI_ADMIN_ROLES contiene sólo SUPER USUARIO" "SUPER USUARIO" \
  "$(docker exec forsis-ai-agent-app python3 -c "
import sys; sys.path.insert(0,'/app')
from app.web import identity; print(','.join(sorted(identity.UI_ADMIN_ROLES)))" 2>/dev/null)"

# ---------------------------------------------------------------- 3. anti-enumeración
echo ""
echo "─── 3. Anti-enumeración: no se revela qué usuarios existen ───"
# Se resetean los intentos antes de la prueba para no empezar en lockout
docker exec -i "$DB" psql -U forsis_agent -d forsis_agent -c "update agent_ui_users set failed_attempts=0, locked_until=null where username='validador';" >/dev/null 2>&1
LOGIN() { curl -sk -o /tmp/s5_body.json -w "%{http_code}" -X POST "$B/api/v1/ui/login" \
    -H "Content-Type: application/json" \
    -d "$(python3 -c "import json,sys;print(json.dumps({'username':sys.argv[1],'password':sys.argv[2]}))" "$1" "$2")"; }
# El cuerpo de error viene anidado: {"status":"error","error":{code,message}}.
ERR() { python3 -c "
import json;e=json.load(open('/tmp/s5_body.json')).get('error',{});print(e.get('code','')+'|'+e.get('message',''))" 2>/dev/null; }

CODE_NOEXISTE=$(LOGIN "no_existe_este_usuario_xyz" "loquesea")
ERR_NOEXISTE=$(ERR)
CODE_MALPASS=$(LOGIN "validador" "contrasena_equivocada_xyz")
ERR_MALPASS=$(ERR)
check "usuario inexistente -> 401" "401" "$CODE_NOEXISTE"
check "contraseña incorrecta -> 401" "401" "$CODE_MALPASS"
check "el código es el mismo en ambos casos" "$ERR_NOEXISTE" "$ERR_MALPASS"
check "el mensaje es el generico, sin revelar existencia" \
  "INVALID_CREDENTIALS|Usuario o contraseña incorrectos." "$ERR_MALPASS"
check "no se aprovisiona al fallar" "0" \
  "$(q "select count(*) from agent_ui_users where username='no_existe_este_usuario_xyz'")"

# ---------------------------------------------------------------- 4. acceso real
echo ""
echo "─── 4. Acceso con credenciales reales de tráfico ───"
if [ -z "${SPRINT5_TRAF_PASSWORD:-}" ]; then
    skip "login de un SUPER USUARIO real (traf_username)" "falta SPRINT5_TRAF_PASSWORD"
    skip "el aviso de 'no vinculado' desaparece tras el login" "requiere login real"
    skip "el rol de UI coincide con el de tráfico" "requiere login real"
else
    SPRINT5_TRAF_USERNAME="${SPRINT5_TRAF_USERNAME:-CESAR01}"
    CK=/tmp/s5_ck.txt; rm -f $CK
    CODE=$(curl -sk -c $CK -o /tmp/s5_body.json -w "%{http_code}" -X POST "$B/api/v1/ui/login" \
        -H "Content-Type: application/json" \
        -d "$(python3 -c "import json,sys;print(json.dumps({'username':sys.argv[1],'password':sys.argv[2]}))" \
             "$SPRINT5_TRAF_USERNAME" "$SPRINT5_TRAF_PASSWORD")")
    check "login con contraseña de tráfico -> 200" "200" "$CODE"
    if [ "$CODE" = "200" ]; then
        check "la fila local tiene el mapeo poblado" "$SPRINT5_TRAF_USERNAME" \
          "$(q "select coalesce(traf_username,'') from agent_ui_users where username='$SPRINT5_TRAF_USERNAME'")"
        check "el rol de UI es admin (SUPER USUARIO)" "admin" \
          "$(q "select role from agent_ui_users where username='$SPRINT5_TRAF_USERNAME'")"
        check "NO se persistió el hash de tráfico" "t" \
          "$(q "select password_hash is null from agent_ui_users where username='$SPRINT5_TRAF_USERNAME'")"
        ME=$(curl -sk -b $CK -o /dev/null -w "%{http_code}" "$B/api/v1/ui/me")
        check "el token de sesión sirve /ui/me" "200" "$ME"
        AVISO=$(curl -sk -b $CK "$B/api/v1/ui/me" -o /tmp/s5_me.json -w "%{http_code}")
        check "la identidad aparece mapeada en /ui/me" "True" \
          "$(python3 -c "import json;print(json.load(open('/tmp/s5_me.json')).get('user',{}).get('mapped'))" 2>/dev/null)"
    fi
    rm -f $CK
fi

# ---------------------------------------------------------------- 5. gates
echo ""
echo "─── 5. Gates de acceso (access_forsis / deactivated_at) ───"
cat <<'EOF'
  Estas dos aserciones requieren un usuario de prueba con access_forsis=0 y
  otro con deactivated_at relleno. NO se crean: escribir en trafico.usuarios
  está prohibido por la restricción del proyecto. Se verifican por lectura
  del código de identity.py (gate antes de verificar) y por el test de
  integración del Sprint 6, cuando exista una matriz de permisos que lo exija.
EOF

# ---------------------------------------------------------------- 6. fail closed
echo ""
echo "─── 6. Fail closed ante algoritmo desconocido ───"
ALGO=$(docker exec forsis-ai-agent-app python3 -c "
import sys; sys.path.insert(0,'/app')
from app.web import identity as i
# Un algoritmo fuera del ENUM no tiene verificador: debe rechazar.
print('rechaza' if not i._verificar_password('sha999', 'x', 'y') else 'ACEPTARIA')
print('rechaza' if not i._verificar_password(None, 'x', 'y') else 'ACEPTARIA')
print('rechaza' if not i._verificar_password('', 'x', 'y') else 'ACEPTARIA')" 2>/dev/null)
check "algoritmo desconocido se rechaza"   "rechaza" "$(echo "$ALGO" | sed -n 1p)"
check "algoritmo NULL se rechaza"          "rechaza" "$(echo "$ALGO" | sed -n 2p)"
check "algoritmo vacío se rechaza"         "rechaza" "$(echo "$ALGO" | sed -n 3p)"

# ---------------------------------------------------------------- 7. cero hashes
echo ""
echo "─── 7. El agente no persiste hashes de tráfico ───"
check "ninguna fila local guarda password_hash" "0" \
  "$(q "select count(*) from agent_ui_users where password_hash is not null")"
check "el código no escribe password_hash en el aprovisionamiento" "1" \
  "$(grep -c 'password_hash, display_name' app/web/auth.py)"
check "el SQL de identidad no usa SELECT * FROM" "0" \
  "$(grep -Ei "SELECT\s+\*\s+FROM" app/web/identity.py | grep -vcE "^\s*#")"

# ---------------------------------------------------------------- 8. regresión
echo ""
echo "─── 8. Regresión: las suites anteriores siguen pasando ───"
for s in 1 2 3 4; do
    if [ -f "./verify-sprint$s.sh" ]; then
        if ./verify-sprint$s.sh >/tmp/s_reg.txt 2>&1; then
            COUNT=$(grep -oE '[0-9]+ PASS' /tmp/s_reg.txt | tail -1 | awk '{print $1}')
            [ -z "$COUNT" ] && COUNT=$(grep -E 'PASS: [0-9]+' /tmp/s_reg.txt | tail -1 | awk '{print $2}')
            [ -z "$COUNT" ] && COUNT=$(grep -cE '(✅|✓|\[OK\]|\[PASS\])' /tmp/s_reg.txt)
            printf '  ✓ Sprint %s sin regresiones (%s aserciones)\n' "$s" "$COUNT"; PASS=$((PASS+1))
        else
            printf '  ✗ Sprint %s regresionó\n' "$s"; FAIL=$((FAIL+1))
        fi
    fi
done

echo ""
echo "══════════════════════════════════════════════════════"
printf 'RESULTADO: %d PASS · %d FAIL · %d SKIP\n' "$PASS" "$FAIL" "$SKIP"
[ "$FAIL" = "0" ] || exit 1