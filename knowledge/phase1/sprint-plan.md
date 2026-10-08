# Plan de Sprints — Forsis AI Agent (Fase 1)

**Fecha:** 2026-10-05
**Entregable:** `sprint-plan.md` (2 de 2) — ver también `channels.md`
**Fuentes:** `PHASE-1-BRIEF.md`, `phase1/architecture.md`, `phase1/db-schema.md`,
`phase1/agent-core.md`, `phase1/llm-provider.md`, `phase1/tools-design.md`,
`liquidaciones-security-strategy.md`, `mattermost-*.md`, `prototype-review.md`,
`trafico-system-analysis.md`, `liquidaciones-system-analysis.md`.

> **Credenciales:** ningún valor real en este documento. Todo secreto se referencia como `${VAR}` o
> `[REDACTED]`.
> **Alcance del plan:** Fase 1 = construir el agente y un canal de acceso. **No** incluye corregir los
> sistemas de negocio (eso es Fase A/B de `liquidaciones-security-strategy.md`), salvo el módulo
> `LIQUIDACIONES` del Sprint 8, que es dependencia dura y se declara como tal.

---

## 0. Principio de secuenciación

El orden de los 9 sprints es **obligatorio** y no es una preferencia estética. Cada uno elimina una
incertidumbre que el anterior no podía resolver:

1. **S0 va primero porque es un incendio.** Un token de bot con `system_post_all` sobre 36 canales está
   commiteado en git. Todo lo demás es mejorar un sistema; eso es una credencial filtrada que ya
   funciona en producción. Construir cualquier cosa encima solo le añade superficie.
2. **S1 va segundo porque fija las tres decisiones que cambian el presupuesto**: stack del agente,
   exposición de `8099`, modelo de despliegue. Sin eso, S2-S8 son estimaciones al aire.
3. **S2-S4 son un vertical slice deliberadamente estrecho**: contenedor → endpoint → **una** tool de
   lectura. No hay herramientas de escritura hasta que haya una lectura funcionando de punta a punta.
   Escribir primero es la forma habitual de construir un agente que parece funcionar y no hace nada
   verificable.
4. **El widget va en un solo sistema (trafico-system), no en los dos.** Suspenderlo en
   `liquidaciones-system` es una **decisión de seguridad, no de esfuerzo**: 77 de 95 usuarios tienen
   contraseña vacía (BLOQUEANTE B-C3).
5. **El cableado de `forsis-bot` va después del widget** y **detrás de un feature flag**, porque es el
   cambio sobre un sistema que ya está en producción con 36 usuarios. Cuando llegue, el flag será la
   diferencia entre "un cambio falló" y "un cambio rompió a 36 personas".
6. **Las escrituras van después de las lecturas**, y las de liquidaciones van **al final**, porque
   requieren un módulo de workflow que hoy no existe (BLOQUEANTE B-C10).
7. **El módulo `LIQUIDACIONES` cierra el plan** porque es la dependencia más larga y más frágil
   (B6 en `liquidaciones-security-strategy.md`, flujo de 8 estados).

**Estimación total: 84 días-persona** (≈ 11 semanas de calendario con 1 persona a tiempo completo, o
≈ 5.5 semanas con 2 personas, asumiendo que 2 personas es lo realista para un MVP de 3 meses).

**Supuesto de recursos:** 1 backend/dev (agente + bot), 0.5 frontend (widget), 0.3 del dueño de
`liquidaciones-system` (Sprint 8), 0.2 de TI/red (Sprint 0 y 1). La estimación no incluye la
corrección de los hallazgos de `liquidaciones-security-strategy.md`, que es un proyecto aparte.

---

## Sprint 0 — Sanear credenciales expuestas 🔴

| | |
|---|---|
| **Objetivo** | Cerrar la brecha de credenciales antes de construir nada encima. |
| **Estimación** | **2 d.p.** |
| **Dependencias** | Ninguna. Puede y debe empezar hoy. |
| **Dueño** | Dueño de `forsis-bot` |

### Entregables

1. **Rotación del `BOT_TOKEN`.**
   - Crear un token nuevo para `forsisbot` vía la System Console de Mattermost (API admin:
     `POST /api/v4/users/{bot_id}/tokens` con token de admin).
   - Actualizar `forsis-bot/.env` con el valor nuevo. `docker-compose.yml` **deja de contenerlo**:
     pasa a `${BOT_TOKEN}` leído de `.env`, y `.env` queda en `.gitignore` con
     `.env.example` versionado y valor vacío.
   - Redeploy de `forsis-bot`. Verificar que responde en `#Forsis PR`.
2. **Revocación del token viejo.** Verificar con `docker exec forsis-bot printenv BOT_TOKEN` que el
   valor en runtime **difiere** del que está en el commit `ee300fa`. Un token nuevo en `.env` con el
   viejo aún válido en el servidor no sirve de nada.
3. **Saneo del historial de git** de `forsis-bot`.
   - Herramienta: `git filter-repo --replace-text` (o `BFG`) sustituyendo el valor por
     `***REMOVED***`.
   - **Requiere coordinación con todos los que tengan el repo clonado** (BI-4 de
     `mattermost-integration-strategy.md` §5): si alguien tiene el clone, sigue teniendo el token en
     su disco, y la rotación es la única mitigación que de verdad funciona. El rewrite del historial es
     defensa en profundidad, no el control principal.
   - Alternativa aceptable si el rewrite rompe forks o despliegues: **no** reescribir, documentar el
     incidente, y confiar en la rotación. Decisión del dueño, no del implementador.
4. **Reducción de permisos del bot.** `system_user + system_post_all` es potencia máxima sobre 36
   canales. Evaluar bajar al mínimo que soporte el gateway (probablemente `system_user` +
   `post_public` + los canales que realmente usa). Si `post_public` resulta insuficiente, dejarlo y
   documentarlo como riesgo aceptado — **no** es bloqueante para el MVP.
5. **Auditoría de otros secretos en los `.env` de todos los servicios** que tocará el agente: por
   ejemplo `${FORSIS_AGENT_TOKEN}`, `${FORSIS_AGENT_IDENTITY_SECRET}`, credenciales de la BD del
   agente, la key de Omniroute. Deben existir como `${VAR}` referenciadas desde `.env` en
   `.gitignore`, nunca literales.
6. **Runbook de 8 líneas** en el repo: cómo rotar el token sin downtime (crear → añadir como
   `…_TOKEN_NEXT` → cambiar el `.env` → redeploy → revocar el viejo), que es el mecanismo de §1.4.5 de
   `channels.md`.

### Criterio de aceptación (verificable, por comandos)

```bash
# A1. el token commiteado ya no está en HEAD
git -C forsis-bot show HEAD:docker-compose.yml | grep -c 'eyJ'   # → 0
# A2. …ni en el historial (si se hizo el rewrite)
git -C forsis-bot log -p --all | grep -c 'eyJ'                  # → 0  (o hallazgo documentado)
# A3. el token en runtime NO es el del commit viejo
docker exec forsis-bot printenv BOT_TOKEN | head -c 8; echo      # ≠ valor de ee300fa
# A4. el token viejo está revocado
curl -s -H "Authorization: Bearer <TOKEN_VIEJO>" \
     https://chatforsis.ddns.net/api/v4/users/me | grep -q '"id"' && echo FALLO || echo OK
# A5. .env ignorado, .env.example versionado
git -C forsis-bot check-ignore -q .env && echo OK
git -C forsis-bot ls-files --error-unmatch .env.example >/dev/null && echo OK
# A6. ningún otro secreto literal en los repos que se van a tocar
grep -rIn -E '(password|token|secret|api_key)\s*=\s*["'"'"'][^$][^"'"'"']{12,}' \
     forsis-bot forsis-ai-agent --include='*.yml' --include='*.env' --include='*.py' --include='*.php'
#    → debe devolver solo líneas con ${VAR}
```

### Criterio de reversión

- La rotación **no es reversible por diseño** (por eso va primero). Mitigación: crear el token nuevo
  **sin revocar el viejo**, redeploy, verificar, y solo entonces revocar. Si algo falla en el paso
  intermedio, el token viejo sigue sirviendo y no hay downtime.
- El rewrite del historial **sí es reversible**: `git reflog` + un tag previo. **Por eso se exige un
  tag `pre-scrub` antes de empezar.** Si el rewrite causa problemas, se restaura el tag y se continúa
  con la rotación ya hecha, que es la parte que importa.
- Si el runner de CI/CD de `forsis-bot` lee el secreto del compose, la rotación lo rompe: decidir
  **antes** cómo se inyecta, no descubrirlo en el redeploy.

**No negociable:** si A4 falla, el Sprint 0 no está terminado y el Sprint 6 no puede empezar.

---

## Sprint 1 — Contenedor del agente y base de datos

| | |
|---|---|
| **Objetivo** | Levantar el contenedor del agente con su BD, respondiendo health checks, con las decisiones de stack cerradas. |
| **Estimación** | **8 d.p.** |
| **Dependencias** | Sprint 0 (para el `.env` sin secretos literales) |
| **Dueño** | Agente 1 + TI/red |

### Entregables

1. **Cierre de las tres decisiones de arquitectura** (bloqueantes B-C1 y B-C9):
   - **Stack**: Python/FastAPI (reutiliza `src/agent/` y `src/tools/` del prototipo, y con ello la
    alvaguarda L0-L3 de riesgo ya validada — `prototype-review.md` §8) **vs** PHP/Laravel 11
     (`architecture.md`). **Recomendación: Python**, por el argumento de `agent-core.md` §0 (B-1) —
     reimplementar en PHP el Executor validado es trabajo repetido con más superficie de error. **Pero
     se documenta y decide explícitamente**, porque cambia el presupuesto de S2-S8 en ±15 %.
   - **Exposición de `8099`**: con el proxy same-origin de `channels.md` §2.2, **ningún consumidor del
     MVP necesita el puerto público**. Recomendación: **no publicar `8099`**; si hace falta para
     depuración, restringirlo por `allow` de nginx a IPs internas. Esto cierra B-C1.
   - **Reverse proxy TLS**: nginx del agente con TLS y `server_name` específico, o detrás del nginx
     existente de `forsispr1.ddns.net`. Determina quién emite el certificado.
2. **`docker-compose.yml` del agente** con la topología de `architecture.md` §3 ajustada a la decisión 1:
   - `nginx` (`:8080` interno; `:8099` solo si se aprueba),
   - `php`/`api` (FastCGI `:9000` **o** uvicorn `:8000`),
   - `db` (PostgreSQL del agente, **sin `ports:`** — `architecture.md` §3.3),
   - `nginx` en `default` + `forsis-agent_net`; `db` solo en `default`.
3. **Esquema de BD aplicado** (`db-schema.md`): `sessions`, `messages`, `plans`, `audit_log`,
   `idempotency_keys` (nuevo, `channels.md` §1.8), `channel_identity_map` (nuevo, `channels.md` §3.5).
4. **Migración y seed.** Migración idempotente y re-ejecutable; un `seed` con la fila del agente en
   `channel_identity_map` por cada uno de los 36 miembros de `Forsis PR` que se vaya a dar de alta (§3.5
   de `channels.md` — alta manual, explícita).
5. **`GET /api/v1/health` y `GET /api/v1/ready`** operativos y distinguishable. `ready` verifica BD y
   Omniroute — es lo que consultará el circuit breaker de `forsis-bot` (Sprint 6).
6. **`firma del planner` operativa**: hash SHA-256 del código del planner + system prompt, re-computado
   en cada arranque y comparado con el valor de la versión desplegada, expuesto en `/ready`
   (`llm-provider.md` §3.4, V-4). Detecta deriva silenciosa entre desarrollo y producción, que es el
   fallo que más caro resulta cuando el combo "Forsis" enruta a un proveedor distinto.
7. **Red `forsis-agent_net` creada** (`channels.md` §3.8), lista y con el agente unido. Todavía sin
  consumidores externos.
8. **Scripts operativos**: `up.sh`, `down.sh`, `logs.sh`, `migrate.sh`, `verify-firma.sh`.

### Criterio de aceptación

```bash
# A1. health y ready responden y se distinguen
curl -sf http://localhost:8080/api/v1/health | grep -q '"status":"ok"' && echo OK
curl -sf http://localhost:8080/api/v1/ready    | grep -q '"db":"ok"'   && echo OK
curl -s  http://localhost:8080/api/v1/ready    | grep -q '"llm":"ok"'  && echo OK
# A2. la BD NO está expuesta al host
ss -lntp | grep -q ':5432' && echo "FALLO: BD expuesta" || echo OK
# A3. las tablas del esquema existen
docker exec <contenedor-db> psql -U <user> -d <db> -tAc \
  "select count(*) from information_schema.tables where table_name in
   ('sessions','messages','plans','audit_log','idempotency_keys','channel_identity_map')"  # → 6
# A4. el contenedor sobrevive un reinicio del host Docker
docker compose restart && sleep 5 && curl -sf http://localhost:8080/api/v1/health && echo OK
# A5. la firma del planner coincide
./verify-firma.sh --esperado <hash-del-despliegue>   # exit 0
# A6. la red existe y tiene al menos un miembro
docker network inspect forsis-agent_net --format '{{len .Containers}}'   # → ≥ 1
# A7. no hay secretos literales
docker compose config | grep -E 'POSTGRES_PASSWORD|TOKEN|SECRET' | grep -v '\${' && echo FALLO || echo OK
```

### Criterio de reversión

`docker compose down -v && git revert <commit> && ./up.sh`. El agente no tiene consumidores en este
sprint, así que el reverso es limpio y sin impacto en nadie. **La red `forsis-agent_net` no se borra**
en el reverso (es inocua sin miembros); borrarla sí, una vez que ningún servicio la referencia.

**Riesgo del sprint:** si la decisión de stack (1) se pospone, todo el sprint se vuelve a hacer. Por eso
es entregable y no un supuesto.

---

## Sprint 2 — `OmnirouteProvider` + endpoint `POST /api/v1/chat`

| | |
|---|---|
| **Objetivo** | Un turno completo de extremo a extremo: mensaje de texto → respuesta de texto. Sin herramientas todavía. |
| **Estimación** | **12 d.p.** |
| **Dependencias** | Sprint 1 |
| **Dueño** | Agente 2 (LLM) + Agente 1 (contrato) |

### Entregables

1. **`OmnirouteProvider`** (`llm-provider.md` §2): cliente OpenAI-compatible contra
   `http://<host>:20130/v1`, combo `Forsis`, con:
   - techo duro de 60 s por llamada vía `ThreadPoolExecutor` + `future.result()`
     (el cuelgue real de >50 min documentado en `llm-provider.md` §2.2 es el motivo: el timeout HTTP
     solo no basta),
   - **3 intentos de formato**: system prompt explícito de JSON → `_salvage_json` (capa 2) →
     reintento con provider mas específico (capa 3),
   - **fail-closed** (capa 4): JSON que no valida ⇒ `LlmJsonInvalidError`, nunca un dict vacío fingiendo
     que no hay nada que hacer,
   - caché semántica de Omniroute (0.03 s) respetada y measurable.
2. **V-1 primero: medir el JSON mode antes que nada.** `llm-provider.md` §3 midió 70 % / 80 %. El
   provider debe llevar sus propias métricas de éxito por capa **desde el primer día**, porque sin
   ellas no se puede distinguir "el agente falló" de "el modelo devolvió algo raro".
3. **Contrato `POST /api/v1/chat` completo** (`channels.md` §1), sin tools:
   - validación fail-closed con `extra="forbid"`, `company` **obligatoria sin default**,
   - `answer` **nunca null**, ni en error,
   - enum de `status` completo,
   - `trace` siempre presente con `llm_model_real`,
   - códigos HTTP de §1.6, incluidos `502` no-reintentable,
   - `Idempotency-Key` funcional contra la tabla de S1.
4. **Techo de turno de 120 s** en el servicio, con `504 TURN_TIMEOUT` al vencer.
5. **Plantilla determinista de `TemplateComposer`** (`agent-core.md` §4.2 D-4) para cuando el LLM
   del composer falle. Sin ella, una caída de Omniroute en el último paso pierde la respuesta entera.
6. **`AgentService` mínimo**: validar → `SessionStore` → `IntentRouter` → `Planner` → (sin Executor)
   → `TemplateComposer` → `AuditLog` → `SessionStore.save`.

### Criterio de aceptación

```bash
# A1. turno de texto completo, con la forma exacta de channels.md §1.5
curl -s -X POST http://localhost:8080/api/v1/chat \
  -H "Authorization: Bearer ${FORSIS_AGENT_TOKEN_TEST}" \
  -H "X-Forsis-Channel: mattermost" -H "Content-Type: application/json" \
  -H "Idempotency-Key: test-$(uuidgen)" -d '{
    "message":"hola","channel":"mattermost","company":"FORSIS",
    "actor":{"subject":"test01","subject_type":"mattermost_user",
             "display_name":"Test","roles":[],"authorized":true}}' \
  | python3 -m json.tool
# → status:"ok", answer no vacío, session_id no vacío, trace.llm_model_real no vacío

# A2. las 6 validaciones fail-closed
#     company ausente         → 422
#     campo extra             → 422
#     message > 4000 chars    → 413
#     token inválido          → 401
#     actor.authorized=false  → 403
#     X-Forsis-Channel ≠ token→ 403

# A3. idempotencia: dos POST idénticos → respuestas idénticas byte a byte
for i in 1 2; do curl -s ... -H "Idempotency-Key: k-123" -d @body.json \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["trace"]["plan_id"])'; done
# → los DOS Impressionan el MISMO plan_id   (prueba de que no se re-ejecutó)

# A4. Omniroute caído → 502 con retryable:false (NO 500, NO silencio)
#     (se baja Omniroute o se apunta a un puerto muerto)
curl -s ... | python3 -c 'import json,sys; d=json.load(sys.stdin)
  assert d["status"]=="error" and d["error"]["code"]=="LLM_UNAVAILABLE"
  assert d["error"]["retryable"] is False and d["answer"]  # → OK

# A5. el turno respeta el techo
#     (se inyecta un prompt que provoque el peor caso medido) → < 125 s, y 504 si se excede

# A6. métricas de formato por capa disponibles y con datos
curl -s http://localhost:8080/api/v1/metrics 2>/dev/null | grep -E 'llm_json_ok|llm_salvage|llm_failclosed'
```

### Criterio de reversión

`docker compose up -d --build` con la versión anterior (tag semver) y el flag de la variable de entorno
`AGENT_V1=old`. Sin consumidores externos, el reverso es un redeploy. **Preservar los artefactos de
diagnóstico de los tests A2-A5** (responses completas) en un directorio de resultados de test: son la
evidencia de que el contrato se respeta, y se necesitan en el Sprint 4.

**Riesgo:** si el JSON mode no supera V-1 (≥ 95 %) al final de este sprint, **no se avanza a tools**.
El Sprint 3 depende de que el plan sea JSON válido; con 70 % de fiabilidad, un plan malformado se
convierte en un tool inexistente o, peor, en un tool equivocada. La mitigación de 4 capas reduce el
daño, no lo elimina a este nivel de fiabilidad.

---

## Sprint 3 — Vertical slice: primera tool de lectura end-to-end

| | |
|---|---|
| **Objetivo** | La primera capacidad real del agente: una tool **de solo lectura** consultando trafico-system, traversing todo el pipeline. |
| **Estimación** | **10 d.p.** |
| **Dependencias** | Sprint 2 |
| **Dueño** | Agente 3 (tools) + Agente 1 |

### Entregables

1. **Herramienta de lectura #1.** La elección debe ser la de menor riesgo y mayor valor demostrativo.
   Recomendación: `traf.guias_listar` (filtrar por cliente/estatus/fecha) — es lectura pura, sin
   escritura, y responde a la pregunta que apertura cualquier conversación ("¿qué está pendiente?").
   Si `trafico-system` no expone un endpoint REST adecuado, **la lectura va por conexión de solo
   lectura a su base de datos** (`architecture.md` §5 ya lo contempla para liquidaciones) — leer su
   propio endpoint HTTP desde el agente es la opción A de `liquidaciones-security-strategy.md` §1 y
   también la aquí.
2. **Conexión de solo lectura** si es por BD: usuario con `SELECT` únicamente, sobre una réplica si
   existe. **El agente nunca escribe en la BD de un sistema de negocio en Fase 1.**
3. **`CapabilityDefinition` completo** (`tools-design.md` §2): `name`, `params_schema` (JSON Schema
   estricto), `required_permissions`, `risk_class: "L1"`, `timeout: 30`, `description` y
   `ejemplos` para el prompt.
4. **`Executor`** (`agent-core.md` §4.1): validación del plan contra `params_schema`, resolución de
   permisos desde el catálogo RBAC real de trafico-system, invocación, captura del resultado.
5. **`PlanGuard`**: gate 5 (permisos) operativo. Gates 1-4 y 6-7 implementados como *stubs que
   pasan* para poder ejercitar el pipeline, con `assert` que falla ruidosamente si un gate no está.
6. **`ChatResponse.components` poblado** con el resultado estructurado (tarjeta de guía), para que el
   widget y Mattermost tengan algo que renderizar y no solo texto plano.
7. **Guardas de riesgo activas** (`tools-design.md` §1): tools L1 permitidas; **L2 y L3 registradas en
   el catálogo pero rechazadas en ejecución**, con `status: "denied"`. Esto se prueba en el sprint,
   no se asume.
8. **Métricas de tool**: latencia por tool, tasa de error, count por `risk_class`.

### Criterio de aceptación

```bash
# A1. turno real end-to-end que ejecuta la tool
curl -s -X POST http://localhost:8080/api/v1/chat -H "…token…" -d '{
  "message":"¿qué guías tiene pendientes el cliente 412?",
  "channel":"widget-trafico","company":"FORSIS",
  "actor":{"subject":"op01","subject_type":"trafico_user","display_name":"Op",
           "roles":["TRAFICO_OPERACION"],"authorized":true}}' \
  | python3 -c 'import json,sys; d=json.load(sys.stdin)
    assert d["status"]=="ok"
    assert any(t.startswith("traf.") for t in d["trace"]["tools_executed"])
    assert d["components"]        # el resultado viene estructurado'
# → PASS. Un turno de texto no basta: tiene que haber ejecutado una tool de verdad.

# A2. el resultado de la tool COINCIDE con la fuente
#     contrastar contra una consulta directa a la BD de trafico-system
#     → los ids de guía devueltos son los mismos y en el mismo orden

# A3. un tool L3 en el plan es RECHAZADO, no ejecutado
curl ... -d '{"message":"borra la guía 90822", ...}' \
  | python3 -c 'import json,sys; d=json.load(sys.stdin)
    assert d["status"]=="denied" and not d["trace"].get("tools_executed")'
# → PASS, y `audit_log` registra el intento

# A4. un actor sin el permiso requerido NO puede usar la tool
#     mismo mensaje, actor con roles=[] → status "denied" o clarification, y tools_executed vacío

# A5. la tool que devuelve 500 NO tumba el turno
#     (se inyecta un fallo en la fuente) → status "degraded" con answer honesta, NO silencio

# A6. el timeout de 30 s de la tool se respeta
#     (se inyecta una fuente lenta) → < 35 s, con `error` de la tool en la traza

# A7. el audit_log contiene el turno completo
docker exec <db> psql -U <u> -d <db> -tAc \
  "select count(*) from audit_log where created_at > now() - interval '10 minutes'"  # → > 0
```

### Criterio de reversión

Quitar la tool del catálogo (`tools-design.md` §2: catálogo versionado, se revierte el registro) y
desplegar la versión anterior. **La conexión de solo lectura se deja en pie** (no destructiva), pero
el usuario `db` se revoca si molesta. El vertical slice no toca ningún sistema de negocio, así que el
reverso es local al agente.

**Nota de alcance:** este sprint **no** añade herramientas de escritura a propósito. La primera
escritura real llega en el Sprint 7, y para liquidaciones en el Sprint 8. Resistir la tentación de meter
aquí la primera escritura es la diferencia entre un sprint reversible y uno que requiere migración de
datos para deshacerse.

---

## Sprint 4 — Widget embebido en `trafico-system` (un solo sistema)

| | |
|---|---|
| **Objetivo** | El canal 1 funcionando para usuarios reales de un sistema, con identidad, permisos y estados de UI correctos. |
| **Estimación** | **12 d.p.** |
| **Dependencias** | Sprint 3 (sin un turno con tool real, el widget solo puede mostrar texto) |
| **Dueño** | Frontend 0.5 + Agente 1 + TI del dueño de trafico-system |

### Entregables

1. **`forsis-ai-widget.js`** (`channels.md` §2.6): JS vanilla, IIFE, sin build step, sin dependencias.
   Shadow DOM, `all:initial`, `z-index` calculado, CSS inline. Los 8 estados de UI de §2.8.
2. **`ai_chat_proxy.php`** en `trafico-system`: lee `$_SESSION`, resuelve `company` desde el
   CompanyContext, firma el JWT de identidad (HS256, `exp` 60 s), evalúa la allowlist, y hace el
   reenvío con `Bearer ${FORSIS_AGENT_TOKEN_TRAFICO}`. **Pass-through**: devuelve el JSON del agente
   sin reinterpretarlo.
3. **Ruta `POST /api/ai/chat`** en el nginx de trafico-system. `client_max_body_size 64k`.
4. **Inyección** en el layout compartido (`.env`: `FORSIS_AI_WIDGET_ENABLED`, `FORSIS_AI_WIDGET_ALLOWLIST`),
   **con `defer`**, solo para sesión válida, con el `data-channel="widget-trafico"`.
5. **Unión de redes**: `trafico-php` se une a `forsis-agent_net` (`channels.md` §3.8). **Solo el
   proxy**; el agente alcanza trafico-system por `forsis-comunicaciones`.
6. **Resolución de B-C2** (¿existe un layout único?) y B-C5 (¿hay CSP?) antes de integrar, para no
   descubrirlo a mitad de sprint.
7. **Inventario de navegadores** de los usuarios de trafico-system (resuelve B-C4).
8. **`sessionStorage`** para `session_id` y estado del panel; **nada** más se persiste en el cliente.

### Criterio de aceptación (verificable en un navegador real)

```
# A1. Isolation de estilos (el test más importante de este sprint)
Abrir una página de trafico-system con el widget abierto, verificar en DevTools:
  - getComputedStyle sobre un <div> del anfitrión unaffected por el CSS del widget
  - un selector del anfitrión (p.ej. ".btn-primary") NO colorea elementos dentro del shadow root
  - NO aparecen estilos del widget fuera del shadow root
# → PASS. Si falla, el widget está dentro de un iframe o hay que replegarse a prefijo + iframe.

# A2. Identidad: el token del agente NO está en el navegador
DevTools → Network → /api/ai/chat → Request Headers: NO debe aparecer Authorization
  → PASS si no aparece

# A3. Sesión
Cerrar sesión en trafico-system → recargar → el widget NO aparece (no hay script inyectado).
Iniciar sesión → aparece.

# A4. La empresa llega desde el servidor
Con empresa = GERO en sesión, la respuesta del agente trae datos de GERO.
→ PASS si la respuesta refleja GERO sin que el widget haya enviado "GERO" nunca.

# A5. Los 8 estados de UI se alcanzan de verdad
  pensando:      enviar un turno con tool real (S3) → ver los puntos + el hint a los 15 s
  respuesta:     ver la tarjeta de `components` renderizada
  clarificación: preguntar algo con dato faltante (p.ej. cliente) → ver los chips
  dry-run:       (no aplica aún — no hay tools L2; Sprint 7) → BLOQUEADO por diseño
  confirmación:  (idem) → BLOQUEADO por diseño
  denegado:      preguntar con un actor sin permisos → candado
  degradado:     parar Omniroute después de la tool → nota al pie
  error:         parar Omniroute antes de la tool → burbuja roja + trace_id visible
# → 6 de 8 PASS en este sprint; los 2 restantes se aceptan en el Sprint 7.

# A6. No hay CORS ni preflight
Network: la petición /api/ai/chat NO tiene preflight OPTIONS, status 200 directo.
# → PASS. Si hay un OPTIONS, se rompió la decisión de proxy same-origin.

# A7. Allowlist fail-closed
FORSIS_AI_WIDGET_ALLOWLIST="" → el endpoint devuelve 403 para TODO (incluido el propio admin).
# → PASS

# A8. Aislamiento de empresa: sesión GERO no puede leer datos de FORSIS
con company=FORSIS en la sesión, pedir datos de un cliente que solo existe en GERO
→ status denied, 0 filas devueltas
```

### Criterio de reversión

**Trivial y completo:** `FORSIS_AI_WIDGET_ENABLED=false` + `docker compose restart php`. Sin redeploy de
código, el script deja de inyectarse y el sistema queda **exactamente** como hoy. Ese es el motivo de
que el flag sea de entorno y no de código.

El otro camino de reversión es quitar la línea del layout; el archivo `forsis-ai-widget.js` puede
quedarse desplegado sin efecto. La unión de red (`forsis-agent_net` en `trafico-php`) es inocua sin el
script inyectado, así que **no se desune** en el reverso: hacerlo y volver a hacerlo no compra nada.

**Riesgo del sprint:** si B-C2 resulta que no hay layout único, la estimación se duplica a ~20 d.p. y se
debe replantear antes de empezar, no a mitad.

---

## Sprint 5 — Cableado de `forsis-bot` detrás de feature flag

| | |
|---|---|
| **Objetivo** | El canal 2 funcionando en Mattermost, reversible en un cambio de variable de entorno. |
| **Estimación** | **9 d.p.** |
| **Dependencias** | Sprints 2 y 3 (necesita `POST /api/v1/chat` con tools). **Sprint 0 obligatorio.** |
| **Dueño** | Dueño de `forsis-bot` + Agente 1 |

### Entregables

1. **`ejecutar_agente()`** en `actions.py`, sustituyendo `ejecutar_agy()`
   (`mattermost-integration-strategy.md` §4.2, con las 9 correcciones de `channels.md` §3.4).
   `DELEGATE_TO_AGENT=false` ⇒ el bot usa el `subprocess` de `agy` exactamente como hoy.
2. **Adaptación de los call sites**: `main.py:429` y `main.py:442` (`respuesta_agy[:900]`) →
   despacho por `status`, con chunking de §3.7 en vez de truncado silencioso.
3. **`FORSIS_AGENT_URL` / `FORSIS_AGENT_TOKEN` / `FORSIS_AGENT_TIMEOUT_S=130`** en el `.env` del bot.
4. **`channel_identity_map` poblada** para los usuarios de la lista blanca de pilotaje, con alta
   **manual y explícita** (`channels.md` §3.5).
5. **Unión de red**: `forsis-bot` se une a `forsis-agent_net` (`channels.md` §3.8). Tres líneas.
6. **Resolución de B-C6**: verificar si el servidor Mattermost alcanza un endpoint HTTP del bot
   (interactive buttons) o aplicar el fallback textual.
7. **Manejo de `429`** y `Retry-After` desde el primer día (B-C8), **lectura de `MaxPostSize` real**
   al arrancar (B-C7), y cola FIFO por canal con ≤ 1 post/s.
8. **Circuit breaker**: 5 fallos consecutivos ⇒ 60 s de pausa con respuesta honesta.
9. **Typing indicator** vía `POST /users/me/typing` cada 4 s.
10. **Prueba del flag en ambos sentidos**, en un canal de prueba.

### Criterio de aceptación

```bash
# A1. el flag funciona en AMBOS sentidos
docker exec forsis-bot env DELEGATE_TO_AGENT=false
# → "mentciona al bot" ejecuta `agy` como hoy. Verificado por log: "delegando a agy".
docker exec forsis-bot env DELEGATE_TO_AGENT=true
# → "menciona al bot" llama a /api/v1/chat. Verificado por log: "delegando al agente".

# A2. el trace_id conecta los dos procesos (mismo id en ambos logs)
docker logs forsis-bot --since 1m | grep -o 'trace=[0-9a-f-]\{8\}' | head -1
# → el mismo prefijo aparece en el access log del agente con ese trace_id
grep "$TRACE_PREFIX" <log-del-agente>   # → la misma request aparece

# A3. idempotencia: NO se puede duplicar un turno por reconexión del WebSocket
#    (se fuerza una desconexión del WebSocket mientras el turno está en vuelo)
docker restart forsis-bot
# → el usuario ve UNA respuesta por mensaje, nunca dos. PASS/FAIL binario.

# A4. usuario fuera de la allowlist: NADA cambia
AGY_USUARIOS_AUTORIZADOS="" → mención → "no autorizado". El agente ni se contacta.
# → PASS (fail-closed intacto; §1.4 punto 3)

# A5. usuario en la allowlist pero SIN fila en channel_identity_map
# → "No tengo tu identidad registrada. Pide a TI que te dé de alta."
# → PASS, y el access log del agente muestra 0 requests para ese turno

# A6. el bot nunca publica el token del agente
docker exec forsis-bot printenv | grep -c AGENT_TOKEN   # 1 (está, es normal)
docker logs forsis-bot --since 1h | grep -c '<valor-del-token>'   # → 0. Nunca en logs.

# A7. el agente caído degrada a un mensaje honesto, no a silencio
#    (se para el contenedor del agente) → mención → respuesta con "temporalmente fuera de
#    servicio" en < 10 s (por el circuit breaker), NO 130 s de espera
# → PASS

# A8. mensaje largo → chunking, nunca truncado silencioso
#    (pregunta que devuelva > 3500 chars) → 2-3 posts numerados (1/2), (2/2), sin pérdida
# → PASS
```

### Criterio de reversión

```bash
# Un comando, sin redeploy, vuelve el bot a su comportamiento actual:
docker exec forsis-bot env DELEGATE_TO_AGENT=false && docker restart forsis-bot
```

Esa es la razón de que este sprint exista detrás de un flag y no como un cambio directo. **El
criterio de reversión de este sprint se prueba en el mismo sprint**, antes de darlo por terminado: se
activa, se verifica, se desactiva, y se registra que el estado `false` produce el comportamiento
legacy. Un flag nunca probado en su camino de vuelta no es un flag.

Rollback adicional: `git revert` del commit de `actions.py` devuelve el `subprocess` a `agy`.

**Nota de secuencia:** el Sprint 5 va **antes** de las escrituras a propósito. Si el canal 2 va bien
con solo lecturas, tenemos un agente útil y seguro en producción antes de que exista una sola
escritura. Si va mal, se revierte sin haber tocado nada del workflow de liquidaciones.

---

## Sprint 6 — Tools de escritura con gate humano

| | |
|---|---|
| **Objetivo** | La primera escritura real, con dry-run forzado y aprobación humana, en un sistema cuyo gate de entrada ya exista. |
| **Estimación** | **12 d.p.** |
| **Dependencias** | Sprint 5. **Requiere Sprint 0 cerrado** (un token con `system_post_all` filtrado no puede coexistir con escrituras). |
| **Dueño** | Agente 3 (tools) + Dueño del sistema destino |

### Entregables

1. **Selección del primer destino de escritura.** **Recomendación: `trafico-system`**, no
   liquidaciones. Razón: el Sprint 8 existe precisamente porque liquidaciones necesita un módulo de
   workflow nuevo (B-C10), mientras que una escritura en trafico-system puede apoyarse en un flujo de
   solicitudes existente. **Elegir liquidaciones aquí saltaría el Sprint 8 y pondría escrituras en el
   sistema con 77 contraseñas vacías (B-C3).**
2. **`PlanGuard` completo**, con los 7 gates activos (`agent-core.md` §4.1):
   - gate 6: dry-run forzado para L2 — **fail-closed, sin excepción ni flag que lo desactive**,
   - `run_id` correlacionando dry-run y commit,
   - **gate 7: confirmación humana** para toda L2, con el `confirmation_id` y TTL de 5 min de
     `channels.md` §1.9.
3. **`POST /api/v1/chat/confirm`** completo, con idempotencia, `exp` y verificación de que quien
   confirma es quien originó.
4. **Herramienta L2 #1** en trafico-system, con `required_permissions` tomados del RBAC real
   (nunca inventados). `risk_class: "L2"`. **`ejemplos` de NO hacer** (`tools-design.md` §2), porque una
   L2 mal invocada tiene consecuencia real.
5. **Estados de UI restantes** en el widget (los 2 que quedaban pendientes en A5 del Sprint 4):
   `dry-run` y `confirmación requerida` con cuenta atrás y doble clic seguro.
6. **Confirmación en Mattermost**: botones interactivos si B-C6 se resolvió; si no, confirmación
   textual reutilizando la maquinaria `acciones_pendientes` que el bot ya tiene.
7. **`tools-design.md` §1.1 reconsiderado**: el bypass del revisor ("crear es rápido, revisar es
   lento") se cierra. **La creación de solicitudes por el agente requiere su propio rol en el
   workflow**, no el de quien solo debe *revisar*. Este es el punto donde se evita que el agente
   inunde el buzón del revisor.
8. **L3 documentada como no implementada**: registrada en el catálogo, rechazada en ejecución,
   con `assert` de que no se puede invocar.

### Criterio de aceptación

```bash
# A1. el dry-run NO muta nada
#    pedir la escritura → status confirmation_required
# → y una comprobación independiente en el sistema de destino confirma 0 filas nuevas
# → PASS (esta es la prueba que más importa del sprint)

# A2. el gate humano es real: sin confirmación no hay efecto
#    pedir la escritura, NO confirmar, esperar 10 s → 0 filas nuevas
# → PASS

# A3. la confirmación produce exactamente UN efecto
#    confirmar con la UI, con doble clic rápido → exactamente 1 fila nueva
#    (idempotencia de channels.md §1.8)
# → PASS

# A4. un tercero no puede confirmar
#    (en Mattermost: otro usuario del hilo hace clic en el botón) → 403, sin efecto
# → PASS

# A5. la confirmación expira
#    pedir, esperar 6 min, confirmar → 410 CONFIRMATION_EXPIRED, 0 filas nuevas
# → PASS

# A6. el executor RECHAZA una L2 sin dry-run (fail-closed)
#    (se inyecta un plan con tool L2 y sin dry-run previo en la traza)
# → status denied + aserción en logs. PASS/FAIL binario, no negociable.

# A7. un actor sin el permiso requerido NO puede ejecutar la L2
# → status denied, audit_log registra el intento, 0 filas nuevas

# A8. L3 rejected, siempre
curl ... '{"message":"borra la guía 90822", ...}'
# → status denied. Y `grep 'L3' <audit_log>` muestra el intento, nunca la ejecución.

# A9. los 8 estados del widget se alcanzan ahora (los 2 pendientes del Sprint 4)
# → 8/8 PASS

# A10. la reversión del Sprint 5 sigue funcionando
docker exec forsis-bot env DELEGATE_TO_AGENT=false && docker restart forsis-bot
# → el bot vuelve a `agy`, que NO tiene estas tools. El usuario no pierde nada de antes.
# → PASS
```

### Criterio de reversión

Tres niveles, todos probados en el sprint:

1. **Kill switch del agente:** `FORSIS_WRITES_ENABLED=false` ⇒ toda tool L2 se responde `denied`.
   Un redeploy, sin tocar código.
2. **Vuelta del canal 2 a `agy`:** `DELEGATE_TO_AGENT=false` (el Sprint 5). Los usuarios de
   Mattermost vuelven al comportamiento previo, y como `agy` no tiene estas tools, no se pierde
   ninguna capacidad.
3. **Rollback de código:** `git revert` del commit de la tool. **Requiere migración**: si la tool
   escribió datos, el revert de código **no** deshace los datos. Esto es lo que hace que el dry-run y
   el gate humano sean obligatorios y no opcionales: la reversión a nivel de datos solo existe por
   diseño (el revisor humano rechaza).

**Riesgo:** si el gate 6 (dry-run forzado) se vuelve a hacer opcional "para ir más rápido", este
sprint pierde su razón de existir. La aserción de A6 es la que lo impide.

---

## Sprint 7 — Hardening, observabilidad y piloto con usuarios

| | |
|---|---|
| **Objetivo** | Que el sistema sea operable en producción con usuarios reales, y que los dos canales estén iguales en calidad. |
| **Estimación** | **9 d.p.** |
| **Dependencias** | Sprints 4, 5, 6 |
| **Dueño** | Todos |

### Entregables

1. **Métricas y alertas**: p50/p95/p99 de latencia por etapa (planner/tools/composer), tasa de error
   por `error_code`, tasa de `llm_salvage` y `llm_failclosed`, turnos por canal, herramientas invocadas
   por `risk_class`, confirmaciones pendientes por antigüedad.
2. **Alertas con umbrales**: latencia p95 > 60 s; `LLM_UNAVAILABLE` > 5 en 5 min; circuit breaker
   abierto; BD del agente no conectada; **cualquier `audit_log` con un `L3` intentado**.
3. **Revisión de los V-1…V-5** de `llm-provider.md` §3.4. V-5 (revisión de llamadas reales de
   producción) es el que cierra la pregunta de la fiabilidad del JSON mode con datos propios.
4. **Límites de rate** implementados (20/hora y 5/min por actor, 4 turnos concurrentes) con
   `Retry-After` correcto.
5. **Runbooks**: qué hacer si (a) cae Omniroute, (b) cae la BD del agente, (c) el agente genera
   respuestas incorrectas, (d) hay que desactivar escrituras de urgencia, (e) hay que revertir el
   canal 2.
6. **Piloto con usuarios reales**: 5-8 usuarios de trafico-system (widget) y 5-8 del equipo
   `Forsis PR` (Mattermost), 2 semanas. Sin liquidaciones (B-C3).
7. **Backups de la BD del agente** con prueba de restauración (no basta con tener el backup).
8. **Documentación de usuario final**: qué sabe hacer, qué no, y qué hacer cuando se equivoca.
9. **Decisión sobre el widget en `liquidaciones-system`**, ahora con datos: ¿pasaron A1 y A2 de
   `liquidaciones-security-strategy.md`? Si no, **no se despliega** y se documenta la decisión.

### Criterio de aceptación

- Los 5 runbooks existen, son ejecutables por otra persona y se **probaron** (al menos un drill real
  del caso (a) y del caso (d)).
- El backup se restauró en un entorno limpio con éxito, una vez.
- El piloto corre 2 semanas con: tasa de error < 5 %, al menos 3 turnos/usuario/día, y **cero**
  escrituras no autorizadas en `audit_log`.
- `grep -c 'risk_class":"L3"' audit_log` = 0 en todo el periodo, y `grep -c 'L3.*denied' audit_log` > 0
  (o sea: los intentos se niegan y se registran).
- Ambas capturas de la tasa de `llm_salvage` existen, y hay una decisión documentada sobre si la
  fiabilidad del JSON mode es suficiente para la Fase 2.

### Criterio de reversión

`FORSIS_AGENT_ENABLED=false` global (una variable) apaga ambos canales: el widget deja de inyectarse y
el bot responde "el asistente no está disponible". **Se ensaya antes de dar el sprint por cerrado.**
Revertir a `Forsis PR` a `AGY_USUARIOS_AUTORIZADOS=""` deja Mattermost exactamente como antes de la
Fase 1 — ese es el estado de referencia y debe estar documentado como tal.

---

## Sprint 8 — Módulo `LIQUIDACIONES` del workflow de solicitudes

| | |
|---|---|
| **Objetivo** | Cerrar el circuito de valor: el agente puede *pedir* autorización de una liquidación mediante el flujo oficial, y un humano la autoriza. |
| **Estimación** | **12 d.p.** |
| **Dependencias** | Sprint 6 (gate humano probado) + **B-C10 resuelto** (el módulo `LIQUIDACIONES` no existe) + **B-C3 resuelto** para el widget de liquidaciones. |
| **Dueño** | Dueño de `liquidaciones-system` (0.3 d.p./semana) + Agente 3 |

> **Por qué es el último y por qué no se puede adelantar:** el workflow `solicitudes_cancelacion`
> tiene hoy 4 módulos (`CAJA_CHICA`, `TARJETA_DEUDOR`, `RECEPCION_GUIAS`, más el propio
> `SOLICITUD_CANCELACION`) y **no tiene `LIQUIDACIONES`** (`liquidaciones-security-strategy.md` §2,
> verificado en `solicitud_cancelacion.php:390`). Sin ese módulo, el agente no puede ni **pedir**
> aprobación para la acción más valiosa del sistema. No es una tool más: es un módulo nuevo en un
> workflow de 8 estados, con su plantilla de notificación, su cola de revisor y su transición de
> estado. Adelantarlo antes del Sprint 6 pondría escrituras sin gate humano probado.

### Entregables

1. **Módulo `LIQUIDACIONES`** en el workflow, siguiendo el patrón de los 4 módulos existentes:
   plantilla de notificación, entrada en la cola del revisor, transición de estado, registro.
2. **Rol dedicado para la creación de solicitudes** (punto 7 del Sprint 6 aplicado aquí):
   el agente crea solicitudes, no las autoriza. Un `SUPER USUARIO` las autoriza.
3. **Herramienta `liq.autorizar_liquidacion` de la clase correcta.** **Recomendación: NO registrar
   ninguna L3 en Fase 1.** Registrar `liq.solicitud_crear` (L2) y, opcionalmente, una L2 de solo
   lectura/consulta del estatus. `autorizar_liquidacion` sería L3 y
   `tools-design.md` §1 dice que L3 no se registra como invocable en el MVP.
4. **`status: confirmation_required` funcionando contra el módulo real**: el agente pide, el
   revisor humano autoriza o rechaza, y el estado se refleja.
5. **Idempotencia hasta el sistema dueño.** `liquidaciones-security-strategy.md` §8 advierte que
   `autorizar_liquidacion` no tiene idempotencia más allá del check `estatus = '<Por Autorizar>'`.
   Cada tool de escritura lleva su **propia** clave de idempotencia en el payload hacia liquidaciones,
   no solo la del turno (`channels.md` §1.8).
6. **Verificación de B-C11**: `solicitud_cancelacion?action=crear` no valida `priv`. Si sigue así en
   la fecha del sprint, la tool de creación **no se despliega** hasta que se corrija (o se despliega
   con un gate de permisos propio en el agente, que es peor).
7. **Estado deWidget en `liquidaciones-system`** — **solo si B-C3 se resolvió.** Sin las correcciones
   A1+A2 de la Fase A, el widget no se despliega ahí y el sprint se cierra solo con el canal Mattermost.

### Criterio de aceptación

```
# A1. el flujo completo funciona con un humano real en medio
"@forsisbot autoriza la liquidación de la guía X" (a un actor autorizado)
 → status confirmation_required, con el resumen y el dry-run
 → el SUPER USUARIO confirma
 → 1 fila creada en el módulo LIQUIDACIONES, 1 fila en audit_log, 0 duplicados
# → PASS

# A2. un NO-autorizado no puede ni siquiera pedirlo
 → status denied en el primer turno, sin turno de Planner, sin tocar el workflow
# → PASS

# A3. el revisor ve la solicitud sin inundación
 → en 2 semanas de piloto: ≤ 5 solicitudes/día en su cola, 0 duplicados de la misma solicitud
# → PASS (es la métrica del hallazgo #5)

# A4. el rechazo es un camino de primera clase
 → el revisor rechaza → la solicitud queda en estado rechazada, con motivo, y el agente lo refleja
   en el hilo si se le pregunta
# → PASS

# A5. idempotencia extremo a extremo
 → el mismo turno, reenviado 3 veces (con la misma Idempotency-Key) → 1 sola fila
# → PASS

# A6. B-C3 y B-C11 resueltos, o el widget no se desplega
 → si A1+A2 de liquidaciones-security-strategy.md no están: NO hay widget en liquidaciones,
   y el sprint lo documenta como decisión, no como retraso.
```

### Criterio de reversión

1. **Retirar la tool del catálogo** (versionado en `tools-design.md` §2) ⇒ el agente vuelve a no
   poder proponer liquidaciones. Efecto inmediato, sin redeploy de los sistemas de negocio.
2. **`FORSIS_WRITES_ENABLED=false`** ⇒ el agente sigue respondiendo preguntas de consulta, no propone
   nada.
3. **Módulo `LIQUIDACIONES`**: vive dentro del workflow existente, así que revertir es poner su
   estado a inactivo. **Las solicitudes ya creadas no se deshacen** — y por diseño: las creó un
   humano, las revisó un humano, y el revisor puede rechazarlas.

---

## 2. Tabla consolidada

| Sprint | Objetivo | d.p. | Bloquea a | Criterio de reversión en una línea |
|---|---|---|---|---|
| **0** 🔴 | Sanear credenciales expuestas | 2 | Todo el canal 2 | No reversible por diseño; mitigado creando-antes-de-revocar |
| **1** | Contenedor del agente + BD + 3 decisiones | 8 | S2 | `down -v` + revert (sin consumidores) |
| **2** | `OmnirouteProvider` + `POST /api/v1/chat` | 12 | S3, S5 | redeploy a versión anterior |
| **3** | Vertical slice: 1 tool de lectura | 10 | S4, S5 | quitar la tool del catálogo |
| **4** | Widget en `trafico-system` | 12 | S7 | `FORSIS_AI_WIDGET_ENABLED=false` |
| **5** | `forsis-bot` detrás de feature flag | 9 | S6, S7 | `DELEGATE_TO_AGENT=false` + restart |
| **6** | Tools de escritura con gate humano | 12 | S7, S8 | `FORSIS_WRITES_ENABLED=false` |
| **7** | Hardening, observabilidad, piloto | 9 | S8 | `FORSIS_AGENT_ENABLED=false` global |
| **8** | Módulo `LIQUIDACIONES` del workflow | 12 | — | retirar la tool + módulo a inactivo |
| | **TOTAL** | **84** | | |

**Reparto de la capacidad:** 44 d.p. de agente/backend (S1,S2,S3,S5,S6), 12 de widget (S4), 9 de
operación (S7), 12 de integración con el dueño del sistema (S8), 2 de seguridad (S0), 5 de decisión y
red (S1). El Sprint 0 no es negociable y no escala: son 2 días que evitan que un token con alcance
sobre 36 canales siga válido mientras se construye un agente que le habla a 36 personas.

---

## 3. Riesgos

| # | Riesgo | Prob. | Impacto | Mitigación | Sprint |
|---|---|---|---|---|---|
| **R1** 🔴 | **`BOT_TOKEN` commiteado sigue válido.** Cualquiera con el repo publica como `forsisbot` en los 36 canales de `Forsis PR` | Alta (ya ocurrió) | **Crítico**: exposición de todos los canales internos | **Es el Sprint 0.** Rotar → verificar revocado (A4) → rewrite de historial como defensa secundaria → reducir permisos. **Ningún sprint del canal 2 empieza antes.** Si A4 falla, el plan se detiene | 0 |
| **R2** 🔴 | **JSON mode del combo "Forsis" al 70 % / 80 %.** Un plan malformado = un tool inexistente o, peor, un tool **equivocada** — y a partir del Sprint 6, un tool de escritura | **Alta, medida** | Crítico a partir de S6 | 4 capas (system prompt → salvage → reintento con provider mas específico → fail-closed) + métricas por capa desde el día 1 + **gate de fail-closed que se puede probar (A6 del S6)** + V-1 (medir con el esquema real) antes de S3. **Contingencia: si V-1 no llega a ≥ 95 %, el Sprint 6 no se ejecuta y el MVP se queda en solo lectura** | 2, 6 |
| **R3** 🔴 | **Módulo `LIQUIDACIONES` no existe** (B-C10). El agente no puede ni pedir aprobación de la acción más valiosa | Alta (verificada) | Alto | Sprint 8 dedicado. **Decisión previa requerida del dueño de liquidaciones en el Sprint 1** — si no lo aprueba, el objetivo de valor del proyecto se replantea y se documenta. No se puede "salvar" con una tool | 8 |
| **R4** 🔴 | **77 de 95 usuarios de liquidaciones con contraseña vacía y `priv` vacío** (B-C3). El widget heredaría una autenticación pública | Alta (verificada) | Crítico si se despliega ahí | El widget se despliega en **trafico-system primero** (S4). En liquidaciones: allowlist **nominal**, nunca "cualquier sesión". Decisión explícita de **no** desplegar hasta que A1+A2 estén hechos | 4, 8 |
| **R5** | **`solicitud_cancelacion?action=crear` no valida `priv`** (B-C11). El agente escribe en una cola sin gate de entrada | Media (verificada) | Medio | Condición de entrada del Sprint 8: se verifica antes de desplegar la tool de creación. No es un riesgo que el agente pueda mitigar por sí mismo | 8 |
| **R6** | **Puertos y redes**: el agente y el bot no comparten red; los sistemas de negocio no publican puertos al host. Sin red común, nada se integra | Alta (verificada) | Alto | `forsis-agent_net` dedicada en el Sprint 1, el bot se une en el S5, `trafico-php` en el S4. Solo 3 líneas de compose en total, pero **es un paso explícito de cada sprint**, no un supuesto | 1, 4, 5 |
| **R7** | **Doble despliegue (bot + agente)**: dos procesos, dos despliegues, dos fuentes de fallo | Alta (aceptada) | Medio | `trace_id` compartido en los dos canales (`channels.md` §1.2), endpoints `health`/`ready`, circuit breaker en el bot, `DELEGATE_TO_AGENT` como kill switch | 5, 7 |
| **R8** | **La decisión de stack (B-C9) se pospone** y el Sprint 2 se rehace | Media | Alto | Es un entregable del Sprint 1, con recomendación argumentada y consecuencias en el presupuesto (± 15 %). No es una investigación: es una decisión con fecha | 1 |
| **R9** | **`POST /v1/chat/completions` de Omniroute responde 200 sin `Authorization` en `0.0.0.0:20130`** (B-C13). Cualquiera con red al host consume el presupuesto del combo | Media (verificada) | Medio | No bloquea el MVP, pero el presupuesto de tokens es compartido y real. Reportar al dueño de Omniroute en el Sprint 1 y verificar en el Sprint 7 si se cerró | 1, 7 |
| **R10** | **Turnos largos**: p95 ~25 s, techo 120 s. El usuario se va y repite el mensaje | Alta | Medio | Idempotencia-Key en ambos canales (`mm:{post_id}` en MM, ULID en el widget) + hint de UI a los 15 s + botón de cancelar honesto (cancela la espera, no promete cancelar el turno) | 2, 4, 5 |
| **R11** | **Duplicación de acciones por desconexión del WebSocket** de MM: el post se reprocesa y se ejecuta dos veces | Media | **Alto a partir de S6** | `Idempotency-Key: mm:{post_id}` (el `post_id` es inmutable, así que la deduplicación es estructural, no estadística) + dedup existente del bot + aserción A3 del Sprint 5 que **falla binariamente** si se duplica | 5, 6 |
| **R12** | **Inundación del buzón del revisor** por solicitudes creadas por el agente (`tools-design.md` §1.1: "crear es rápido, revisar es lento") | Media | Medio | Rol dedicado para crear (≠ para autorizar) + idempotencia de extremo a extremo (S8, entregable 5) + dry-run obligatorio + métrica explícita "solicitudes/día en la cola del revisor ≤ 5" como criterio de aceptación | 6, 8 |
| **R13** | **Permisos del bot demasiado amplios** (`system_post_all` sobre 36 canales) si R1 se "resuelve" solo con rotación | Media | Alto | Reducción de permisos en el Sprint 0 (entregable 4). Si no es viable, queda documentado como riesgo aceptado con dueño nombrado — **no** como algo resuelto | 0 |
| **R14** | **Equipo pequeño (≈1 dev + 0.5 front) y 84 d.p. de trabajo**: la tentación de recortar el Sprint 0 o el gate humano | Media | **Crítico** | Sprint 0 y el gate de dry-run son **no negociables** y están marcados como tales. Lo que se recorta, si acaso, es el Sprint 4 en liquidaciones (que ya está excluido) o el Sprint 8 (que se documenta como no-entregado). **Better late than unsafe** | todos |
| **R15** | **Falsa sensación de que el agente "funciona"**: responde con-sounding texto y sin datos reales, y nadie lo nota hasta que se toma una decisión con él | Media | Alto | Un turno sin tool real se considera **fallo** (A1 del Sprint 3, que exige `tools_executed` no vacío). Pilotar solo después del Sprint 6, y con métricas de `degraded` y `no_capability` a la vista | 3, 7 |
| **R16** | **CSP o un layout inexistente bloquean el widget** (B-C2, B-C5) y la estimación del Sprint 4 se duplica | Media | Medio | Resolver **antes** de empezar el Sprint 4, no a mitad. Si no hay layout único, replantear el sprint antes de invertir los días | 4 |
| **R17** | **Los botones de confirmación de MM no son alcanzables** (B-C6): el servidor Mattermost no tiene ruta al bot | Media | Bajo | Fallback **ya diseñado**: confirmación textual con la maquinaria `acciones_pendientes` existente. Decisión en el Sprint 5, no un bloqueo | 5 |
| **R18** | **Costo de tokens**: ~4 000 tokens inyectados por llamada (`llm-provider.md` §2.3), combo compartido, sin auth en Omniroute | Media | Medio | Rate limits por actor (S7), caché semántica de Omniroute respetada, y R9 reportado | 7 |

---

## 4. Lo que este plan NO cubre

Para que no se lea como más de lo que es:

- **La corrección de `liquidaciones-system`** (8 endpoints sin gate, MD5 sin salt, 77 contraseñas
  vacías, `action=crear` sin `priv`). Es la **Fase A/B** de
  `liquidaciones-security-strategy.md` y es un proyecto **separado y previo** a cualquier escritura
  del agente sobre ese sistema. El Sprint 8 asume que al menos A1, A2 y B6 están hechos.
- **L3 (acciones irreversibles)**. Ninguna. `autorizar_liquidacion` como tool L3 no se registra en la
  Fase 1 (`tools-design.md` §1). Que exista un módulo de workflow para la solicitud **no** convierte la
  autorización en L2.
- **Voz, imágenes, adjuntos, multi-idioma.**
- **El agente ejecutando acciones en nombre de un usuario sin que ese usuario las haya pedido**
  (proactividad,.recordatorios). Fuera de alcance hasta que el gate humano tenga historial.
- **Streaming** — decisión argumentada en `channels.md` §1.10, con condición de reapertura.
- **El widget en `liquidaciones-system`** hasta que B-C3 se resuelva.

---

## 5. Definición de "listo" del MVP

El proyecto está cuando, y solo cuando:

1. El Sprint 0 está cerrado y verificado por comando (A1-A6).
2. `POST /api/v1/chat` cumple el contrato de `channels.md` §1, incluidas las 6 validaciones fail-closed.
3. Un turno con una tool de lectura real atraviesa los dos canales y el resultado **coincide con la
   fuente** (A2 del Sprint 3).
4. El widget funciona en `trafico-system` con Shadow DOM aislado y sin token en el navegador.
5. `forsis-bot` delega al agente detrás de un flag, con `trace_id` correlacionado en ambos procesos, y
   el flag probado **en los dos sentidos**.
6. La primera escritura L2 existe con dry-run forzado, gate humano e idempotencia, **probados los tres**.
7. Cero escrituras no autorizadas en `audit_log` durante 2 semanas de piloto.
8. El módulo `LIQUIDACIONES` existe, o la decisión de no hacerlo está documentada con su motivo.
9. Los runbooks existen y **al menos dos se han ejecutado en drill**.
10. El agente se puede apagar entero con una variable de entorno, y eso se ha probado.

---

Generado: 2026-10-05 — Fase 1. Entregable hermano: `channels.md`.
Ningún código de `forsis-bot`, `trafico-system` ni `liquidaciones-system` fue modificado: este plan
**especifica** el trabajo, no lo ejecuta.
