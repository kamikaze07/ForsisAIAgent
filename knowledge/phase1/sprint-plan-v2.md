# Plan de Sprints v2 — Forsis AI Agent (Fase 1)

**Fecha:** 2026-10-05
**Entregable:** `sprint-plan-v2.md` — sustituye en vigencia a `sprint-plan.md` (que queda como
registro histórico, **no se modifica**).
**Motivo de la revisión:** `ADR-001-stack-y-secuencia.md` (decisión del usuario, 2026-10-05):
(1) stack = Python 3.12 + FastAPI, (2) validación con UI web propia antes de integrar en los
sistemas de negocio o en Mattermost.
**Fuentes:** `ADR-001-stack-y-secuencia.md`, `PHASE-1-BRIEF.md`, `phase1/architecture.md` (capa de
runtime obsoleta — ver §0), `phase1/db-schema.md`, `phase1/agent-core.md`, `phase1/llm-provider.md`,
`phase1/tools-design.md`, `phase1/permissions.md`, `phase1/channels.md`,
`liquidaciones-security-strategy.md`, `mattermost-*.md`, `sprint-plan.md` (v1, histórico).

> **Credenciales:** ningún valor real en este documento. Todo secreto se referencia como `${VAR}` o
> `[REDACTED]`.
> **No se modifica código** de `forsis-bot`, `trafico-system` ni `liquidaciones-system`. Este plan
> especifica el trabajo, no lo ejecuta.
> **Dependencias documentales abiertas al escribir este plan:** `phase1/web-ui-design.md` y
> `phase1/architecture-python.md` estaban en construcción por otro agente en paralelo y **no
> existían** en el momento de redactar este documento. El Sprint 4 (UI standalone) y el Sprint 1
> (arquitectura Python) quedan marcados **BLOQUEANTE-DOC** hasta que esos documentos existan y se
> incorporen; mientras tanto este plan diseña su alcance a partir de `channels.md` (contrato y
> estados de UI) y de `architecture.md` (topología, advirtiendo que su capa de runtime cambia de
> PHP a Python).

---

## 0. Qué cambió respecto a `sprint-plan.md` y por qué

| Cambio | v1 (histórico) | v2 (este documento) | Por qué |
|---|---|---|---|
| **Stack** | Pendiente de decidir en Sprint 1 (Python recomendado, PHP alternativa) | **Decidido: Python 3.12 + FastAPI** (ADR-001 Decisión 1) | Se reutilizan ~2.500 líneas del prototipo (Planner, Executor, Registry, Capability, contratos Pydantic). El andamiaje PHP (`docker/php/`, `fastcgi_pass`) queda obsoleto y no se construye. |
| **Bloqueante B-C9 (stack)** | Bloqueaba el Sprint 2 | **Resuelto.** Ya no bloquea nada | Era la decisión más cara en presupuesto (±15%); ahora es un hecho, no una incertidumbre. |
| **Orden: UI antes de canales de producción** | El widget (S4) y Mattermost (S5) eran los primeros "canales reales"; no existía una UI propia | **Nuevo Sprint 4: UI web standalone** (login propio + chat + reportes + confirmaciones), inmediatamente después del vertical slice (S3) | ADR-001 Decisión 2: el núcleo, el provider y la primera tool se validan sin tocar ningún sistema en producción ni exponer el agente a 36 canales de Mattermost. |
| **Hito de validación** | No existía como gate formal | **Nuevo: HITO GO/NO-GO** tras el Sprint 4, con aprobación explícita del usuario (Cesar) en persona | Condición explícita de ADR-001: "solo con esa validación se habilitan los sprints de integración". Sin este hito, S5-S9 (v2) podían empezar sin que nadie hubiera usado el agente de verdad. |
| **Widget embebido en trafico-system** | Sprint 4 | **Sprint 5**, y ahora requiere el HITO aprobado además de S3 | Es un canal adicional sobre un contrato que ya fue ejercitado por un humano real en la UI standalone, reduciendo el riesgo de desplegar algo no probado sobre un sistema en producción. |
| **Cableado de `forsis-bot` / Mattermost** | Sprint 5 | **Sprint 6**, y ahora requiere el HITO aprobado | Mismo argumento: no se cablea un agente no validado a 36 canales. |
| **Sanear `BOT_TOKEN`** | Sprint 0, bloqueante de todo el canal 2, primero en el plan | **Sale de la ruta crítica.** Se convierte en tarea de seguridad independiente **SEC-1**, con fecha límite: **antes de que empiece el Sprint 6** | ADR-001: "deja de estar en la ruta crítica… pero sigue siendo un incidente de seguridad abierto". Ya no bloquea S1 (que ahora puede empezar el día 1), pero sigue siendo obligatorio antes de reactivar Mattermost. |
| **Módulo `LIQUIDACIONES`** | Sprint 8 (último) | **Sprint 9** (sigue siendo el último), ahora también detrás del HITO | Sin cambios en su lógica interna; solo se recorre un número porque se insertó el Sprint 4. |
| **Tools de escritura con gate humano** | Sprint 6 | **Sprint 7**, detrás del HITO | Sin cambios de contenido; renumerado. |
| **Hardening / piloto** | Sprint 7 | **Sprint 8**, detrás del HITO | Sin cambios de contenido; renumerado. |
| **Estimación total** | 84 d.p. | **95 d.p.** (+12 por el Sprint 4 nuevo, −1 en el Sprint 1 porque el stack ya no se decide) | La UI standalone es trabajo nuevo que v1 no tenía: login propio, pantalla de chat, de reportes y de confirmaciones, sin reutilizar ningún layout existente. |
| **`db-schema.md`** | Sin tabla de usuarios propios del agente | **Nuevo entregable del Sprint 4**: tabla `agent_ui_users` (cuentas propias para la UI standalone) — no existía en v1 porque no había UI propia | Antes de v2 no hacía falta: los únicos consumidores eran sistemas externos vía `channel_identity_map`. |

**Lo que NO cambió:** la taxonomía de riesgo L0-L3 (`tools-design.md`), los 7 gates del `PlanGuard`
(`agent-core.md`), el contrato `POST /api/v1/chat` (`channels.md` §1), la decisión de NO exponer el
puerto `8099`, la prohibición de registrar tools L3, el orden "lecturas antes que escrituras", y el
Sprint `LIQUIDACIONES` como el último del plan por la misma razón de v1 (el módulo no existe).

---

## 1. Principio de secuenciación v2

1. **S1 ya no espera una decisión de stack — la ejecuta.** Python/FastAPI está decidido (ADR-001).
   El Sprint 1 puede empezar el día 1, en paralelo con el saneo de `BOT_TOKEN` (SEC-1, que ya no lo
   bloquea).
2. **S2-S3 son el mismo vertical slice estrecho de v1**: endpoint → una tool de lectura. Sigue sin
   haber escritura hasta mucho después.
3. **S4 es nuevo y es la bisagra del plan.** Es la primera vez que un humano (el usuario, Cesar) usa
   el agente de principio a fin — con su propio login, sin pasar por ningún sistema de negocio ni
   por Mattermost. Es deliberadamente la superficie más pequeña posible: una UI propia, aislada, sin
   consumidores que puedan verse afectados si algo falla.
4. **El HITO GO/NO-GO es un punto de control real, no un trámite.** Nada de S5 en adelante empieza
   sin la aprobación explícita y documentada del usuario. Si el usuario pide cambios tras probar la
   UI, esos cambios se hacen **antes** de tocar trafico-system o Mattermost, porque es infinitamente
   más barato iterar sobre una UI standalone que sobre un widget ya embebido o un bot ya cableado a
   36 personas.
5. **El widget (S5) y Mattermost (S6) mantienen el orden relativo que tenían en v1 entre sí** (widget
   primero, en un solo sistema; Mattermost detrás de un feature flag) — ADR-001 no cambia esa
   relación, solo los empuja a ambos detrás del HITO.
6. **Las tareas de seguridad fuera de la ruta crítica no desaparecen: se vuelven tareas con fecha
   límite explícita**, no bloqueantes del día 1. Esto es un cambio de *cuándo* se hacen, no de *si*
   se hacen — ver §4.
7. **El módulo `LIQUIDACIONES` sigue cerrando el plan**, por la misma razón que en v1: el workflow no
   tiene ese módulo hoy (B-C10/B-02), es la dependencia más larga, y además ahora depende también del
   HITO.

**Estimación total: 95 días-persona** (≈ 12 semanas de calendario con 1 persona a tiempo
completo, o ≈ 6.5 semanas con 2 personas). +11 d.p. netos sobre v1: +12 por el Sprint 4 (UI
standalone, que no existía) y −1 en el Sprint 1 (el stack ya no se decide, se ejecuta).

**Supuesto de recursos:** 1 backend/dev (agente + bot), 0.5 frontend (UI standalone + widget), 0.3
del dueño de `liquidaciones-system` (Sprint 9), 0.2 de TI/red. La estimación no incluye la
corrección de los hallazgos de `liquidaciones-security-strategy.md` (tareas SEC-2 de §4), que es un
proyecto aparte.

---

## 2. HITO GO/NO-GO — punto de control explícito

```
S1 → S2 → S3 → S4 (UI standalone) → ███ HITO GO/NO-GO ███ → S5 → S6 → S7 → S8 → S9
                                      (usuario valida en persona)
```

| | |
|---|---|
| **Qué se valida** | El agente completo (núcleo, `OmnirouteProvider`, Planner/Executor/PlanGuard, auditoría) a través de la UI web standalone, con al menos una tool de lectura real contra `trafico-system`. |
| **Quién valida** | El usuario (Cesar), en persona, usando la UI con su propia cuenta. |
| **Cómo se registra la decisión** | Acta breve (fecha, versión del agente probada —hash de la firma del planner de S1—, lista de observaciones, decisión GO / GO-con-condiciones / NO-GO) guardada en el repo de conocimiento, p. ej. `knowledge/phase1/hito-go-nogo.md`. **Sin ese archivo, no hay evidencia de que el hito ocurrió**, y S5 no puede declararse "iniciado" en ningún reporte de avance. |
| **Qué pasa si es GO-con-condiciones** | Las condiciones se convierten en tareas del backlog de S4 (se reabre ese sprint) o en un sprint S4-bis corto, **nunca** se difieren silenciosamente a S5 en adelante. |
| **Qué pasa si es NO-GO** | S5-S9 no empiezan. Se reevalúa el Planner/Prompt/UX en una iteración adicional sobre S2-S4 antes de volver a pedir el hito. |
| **Qué NO se evalúa aquí** | El widget embebido, Mattermost, ni el módulo LIQUIDACIONES — ninguno existe todavía en este punto del plan. El hito es sobre el núcleo del agente y su UX de chat/confirmación, no sobre los canales de integración. |

---

## 3. Sprints

### Sprint 1 — Contenedor del agente (Python/FastAPI) + base de datos

| | |
|---|---|
| **Objetivo** | Levantar el contenedor del agente en Python 3.12 + FastAPI con su BD, respondiendo health checks. |
| **Estimación** | **7 d.p.** (−1 d.p. vs v1: ya no hay que *decidir* el stack, solo ejecutarlo) |
| **Dependencias** | Ninguna. Puede empezar el día 1, en paralelo con SEC-1 (§4). |
| **Dueño** | Agente 1 + TI/red |
| **Estado de bloqueo** | **BLOQUEANTE-DOC parcial**: requiere `phase1/architecture-python.md` para la topología de contenedores en Python. Si no existe al iniciar el sprint, se deriva de `architecture.md` §3 sustituyendo la capa `php-fpm`/`fastcgi_pass` por `uvicorn`/FastAPI, y se documenta la sustitución como supuesto a validar. |

#### Entregables

1. **Migración del andamiaje de `architecture.md` de PHP a Python**, explícitamente:
   - se **elimina** del alcance: `docker/php/Dockerfile`, `docker/php/entrypoint.sh`, el servicio
     `php` (FastCGI) del compose y el `fastcgi_pass` de nginx;
   - se **añade**: imagen Python 3.12, `uvicorn` (o `gunicorn -k uvicorn.workers.UvicornWorker`)
     sirviendo FastAPI en `:8000` interno, `requirements.txt`/`pyproject.toml` fijando versiones.
2. **Reutilización del núcleo del prototipo** (`/home/servidor/forsis-agent`, ~2.500 líneas): Planner,
   Executor, Registry, `CapabilityDefinition`, contratos Pydantic, `PromptBuilder`,
   `TemplateComposer`, corrigiendo el bug conocido del prototipo (`agent-core.md` §1.2) sin
   propagarlo.
3. **Dos decisiones que siguen abiertas** (el stack ya no es una de ellas):
   - **Exposición de `8099`**: con el proxy same-origin de `channels.md` §2.2, ningún consumidor del
     MVP necesita el puerto público. **Recomendación: no publicarlo**; si hace falta para depuración,
     restringir por `allow` de nginx a IPs internas (cierra B-C1).
   - **Reverse proxy TLS**: nginx del agente con TLS propio, o detrás del nginx existente de
     `forsispr1.ddns.net`. Determina quién emite el certificado.
4. **`docker-compose.yml` del agente** (Python): `nginx` (`:8080` interno; `:8099` solo si se
   aprueba), `agent-api` (uvicorn `:8000`), `db` (PostgreSQL, **sin `ports:`**).
5. **Esquema de BD aplicado** (`db-schema.md`, agnóstico al lenguaje — no cambia): `sessions`,
   `messages`, `plans`, `audit_log`, `idempotency_keys`, `channel_identity_map`.
6. **Nueva tabla `agent_ui_users`** (adelanto del Sprint 4, se crea aquí porque es parte del mismo
   esquema): cuentas propias para la UI standalone — `id`, `username`, `password_hash`
   (argon2/bcrypt, nunca MD5), `display_name`, `role` (`admin`/`validador`), `created_at`,
   `last_login_at`, `is_active`. **No** vinculada a `channel_identity_map` (eso es para sistemas
   externos); es la identidad nativa del agente.
7. **Migración y seed** idempotentes; seed de `channel_identity_map` **vacío en este sprint** (no
   hay consumidores de Mattermost todavía) y seed de `agent_ui_users` con **una** cuenta inicial
   para el usuario validador (contraseña provista fuera de banda, nunca en este repo).
8. **`GET /api/v1/health` y `GET /api/v1/ready`**, distinguibles; `ready` verifica BD y Omniroute.
9. **Firma del planner** (hash SHA-256 del código + system prompt) expuesta en `/ready`
   (`llm-provider.md` V-4/§3.4) — detecta deriva entre versión probada en el HITO y producción.
10. **Red `forsis-agent_net` creada**, agente unido. Sin consumidores externos todavía.
11. **Scripts operativos**: `up.sh`, `down.sh`, `logs.sh`, `migrate.sh`, `verify-firma.sh`.

#### Criterio de aceptación

```bash
# A1. health y ready
curl -sf http://localhost:8080/api/v1/health | grep -q '"status":"ok"' && echo OK
curl -sf http://localhost:8080/api/v1/ready    | grep -q '"db":"ok"'   && echo OK
curl -s  http://localhost:8080/api/v1/ready    | grep -q '"llm":"ok"'  && echo OK
# A2. runtime es Python, no PHP
docker exec <contenedor-agent-api> python3 --version   # → Python 3.12.x
docker compose config | grep -c 'fastcgi_pass\|php-fpm'  # → 0 (no queda andamiaje PHP)
# A3. la BD no está expuesta al host
ss -lntp | grep -q ':5432' && echo "FALLO: BD expuesta" || echo OK
# A4. las 7 tablas existen (6 de v1 + agent_ui_users)
docker exec <db> psql -U <u> -d <db> -tAc \
  "select count(*) from information_schema.tables where table_name in
   ('sessions','messages','plans','audit_log','idempotency_keys','channel_identity_map','agent_ui_users')"  # → 7
# A5. hay exactamente una cuenta de UI sembrada, con password hasheado (no en claro)
docker exec <db> psql -U <u> -d <db> -tAc "select count(*) from agent_ui_users"  # → 1
docker exec <db> psql -U <u> -d <db> -tAc "select password_hash from agent_ui_users limit 1" | grep -qE '^\$2|^\$argon2' && echo OK
# A6. firma del planner
./verify-firma.sh --esperado <hash-del-despliegue>   # exit 0
# A7. sin secretos literales
docker compose config | grep -E 'POSTGRES_PASSWORD|TOKEN|SECRET' | grep -v '\${' && echo FALLO || echo OK
```

#### Criterio de reversión

`docker compose down -v && git revert <commit> && ./up.sh`. Sin consumidores en este sprint, el
reverso es limpio. La red `forsis-agent_net` no se borra (inocua sin miembros).

**Riesgo del sprint:** si `architecture-python.md` no existe para cuando este sprint empiece, la
topología se deriva de `architecture.md` por sustitución directa de capa; se documenta la derivación
como supuesto y se revisa en cuanto el documento exista, sin bloquear el inicio del sprint.

---

### Sprint 2 — `OmnirouteProvider` + endpoint `POST /api/v1/chat`

*(Sin cambios de contenido respecto al Sprint 2 de v1 — el stack ya estaba fijado como Python en
esa sección de v1 vía la decisión recomendada; ADR-001 la hace definitiva. Se repite íntegro por
completitud del documento v2.)*

| | |
|---|---|
| **Objetivo** | Un turno completo de extremo a extremo: mensaje de texto → respuesta de texto. Sin herramientas todavía. |
| **Estimación** | **12 d.p.** |
| **Dependencias** | Sprint 1 |
| **Dueño** | Agente 2 (LLM) + Agente 1 (contrato) |
| **Estado de bloqueo** | Ninguno nuevo. Hereda B-C12/B-2 (JSON mode 70-80%), mitigado por diseño, no resuelto. |

#### Entregables

1. **`OmnirouteProvider`**: cliente OpenAI-compatible contra `http://<host>:20130/v1` (puerto
   verificado — `omniroute-config.md`, NO usar 20129 ni 20131), combo `Forsis`, con:
   - techo duro de 60 s por llamada (`ThreadPoolExecutor` + `future.result()`),
   - 3 intentos de formato (system prompt JSON → `_salvage_json` → reintento con provider más
     específico),
   - fail-closed: JSON inválido ⇒ `LlmJsonInvalidError`, nunca un dict vacío,
   - caché semántica de Omniroute respetada y medible.
2. **V-1 medido desde el día 1** (`llm-provider.md` §3.4): 200 llamadas con prompt de Planner real y
   catálogo completo, métricas por capa (`llm_json_ok`, `llm_salvage`, `llm_failclosed`) desde el
   arranque.
3. **Contrato `POST /api/v1/chat` completo** (`channels.md` §1), sin tools: validación fail-closed
   con `extra="forbid"`, `company` obligatoria sin default, `answer` nunca null, enum de `status`
   completo, `trace` con `llm_model_real`, códigos HTTP de §1.6, `Idempotency-Key` funcional.
4. **Techo de turno de 120 s**, `504 TURN_TIMEOUT` al vencer.
5. **`TemplateComposer` determinista** (`agent-core.md` §4.2 D-4) para cuando el LLM del composer
   falle.
6. **`AgentService` mínimo**: validar → `SessionStore` → `IntentRouter` → `Planner` → (sin Executor)
   → `TemplateComposer` → `AuditLog` → `SessionStore.save`.

#### Criterio de aceptación

```bash
# A1. turno completo, forma exacta de channels.md §1.5
curl -s -X POST http://localhost:8080/api/v1/chat \
  -H "Authorization: Bearer ${FORSIS_AGENT_TOKEN_TEST}" -H "X-Forsis-Channel: mattermost" \
  -H "Content-Type: application/json" -H "Idempotency-Key: test-$(uuidgen)" -d '{
    "message":"hola","channel":"mattermost","company":"FORSIS",
    "actor":{"subject":"test01","subject_type":"mattermost_user",
             "display_name":"Test","roles":[],"authorized":true}}' \
  | python3 -m json.tool
# → status:"ok", answer no vacío, session_id no vacío, trace.llm_model_real no vacío

# A2. las 6 validaciones fail-closed (company ausente→422, extra→422, >4000 chars→413,
#     token inválido→401, actor.authorized=false→403, canal≠token→403)

# A3. idempotencia: dos POST idénticos con la misma Idempotency-Key → mismo plan_id

# A4. Omniroute caído → 502 LLM_UNAVAILABLE, retryable:false, nunca 500 ni silencio

# A5. techo de turno respetado (<125s, 504 si se excede)

# A6. métricas de formato por capa disponibles con datos
curl -s http://localhost:8080/api/v1/metrics | grep -E 'llm_json_ok|llm_salvage|llm_failclosed'
```

#### Criterio de reversión

`docker compose up -d --build` con la versión anterior y `AGENT_V1=old`. Sin consumidores
externos, el reverso es un redeploy. Preservar los artefactos de diagnóstico A2-A5.

**Riesgo:** si V-1 no supera 95% al final de este sprint, no se avanza a tools de escritura más
adelante (regla heredada de v1, ahora aplicada también como condición del HITO en §2).

---

### Sprint 3 — Vertical slice: primera tool de lectura end-to-end

*(Sin cambios de contenido respecto al Sprint 3 de v1. Se repite íntegro.)*

| | |
|---|---|
| **Objetivo** | La primera capacidad real del agente: una tool de solo lectura consultando trafico-system, recorriendo todo el pipeline. |
| **Estimación** | **10 d.p.** |
| **Dependencias** | Sprint 2 |
| **Dueño** | Agente 3 (tools) + Agente 1 |
| **Estado de bloqueo** | Depende de B-05 (grants read-only aplicados y verificados, `permissions.md`) y B-03 (usuario de servicio creado) — ambos **BLOQUEANTE** hasta verificación en vivo. |

#### Entregables

1. **Herramienta de lectura #1**: `traf.guias_listar`/`traf.guias_buscar` (filtrar por
   cliente/estatus/fecha) — lectura pura, mayor valor demostrativo (`tools-design.md` §5.1).
2. **Conexión de solo lectura** (usuario `SELECT` únicamente, sobre réplica si existe). El agente
   **nunca** escribe en la BD de un sistema de negocio en Fase 1.
3. **`CapabilityDefinition` completo**: `name`, `params_schema` JSON Schema estricto,
   `required_permissions`, `risk_class: "L0"` o `"L1"` según la tabla de `tools-design.md` §1,
   `timeout: 30`, `description`, `ejemplos`.
4. **`Executor`**: validación del plan contra `params_schema`, resolución de permisos desde el
   catálogo RBAC real, invocación, captura del resultado.
5. **`PlanGuard`**: gate 5 (permisos) operativo. Gates 1-4 y 6-7 como stubs que pasan, con `assert`
   ruidoso si un gate falta.
6. **`ChatResponse.components` poblado** con el resultado estructurado.
7. **Guardas de riesgo activas**: L0/L1 permitidas; **L2 y L3 registradas pero rechazadas** en
   ejecución, con `status: "denied"` probado, no asumido.
8. **Métricas de tool**: latencia, tasa de error, count por `risk_class`.

#### Criterio de aceptación

```bash
# A1. turno real que ejecuta la tool
curl -s -X POST http://localhost:8080/api/v1/chat -H "…token…" -d '{...}' \
  | python3 -c 'import json,sys; d=json.load(sys.stdin)
    assert d["status"]=="ok"
    assert any(t.startswith("traf.") for t in d["trace"]["tools_executed"])
    assert d["components"]'
# A2. el resultado COINCIDE con una consulta directa a la BD (mismos ids, mismo orden)
# A3. un tool L3 es RECHAZADO, no ejecutado, y queda en audit_log
# A4. un actor sin permiso NO puede usar la tool
# A5. una tool que devuelve 500 NO tumba el turno → status "degraded"
# A6. el timeout de 30s de la tool se respeta
# A7. audit_log contiene el turno completo
```

#### Criterio de reversión

Quitar la tool del catálogo versionado y desplegar la versión anterior. La conexión read-only se
deja en pie (no destructiva).

**Nota de alcance:** sin escrituras a propósito. La primera escritura llega en el Sprint 7.

---

### Sprint 4 — UI web standalone (login propio + chat + reportes + confirmaciones) 🆕

| | |
|---|---|
| **Objetivo** | Una interfaz web propia del agente, aislada de trafico-system y liquidaciones-system, que permite al usuario validar el agente de punta a punta antes de integrarlo en ningún sistema o en Mattermost. |
| **Estimación** | **12 d.p.** |
| **Dependencias** | Sprint 3 (sin una tool real, la UI solo muestra texto) |
| **Dueño** | Frontend 0.5 + Agente 1 |
| **Estado de bloqueo** | **BLOQUEANTE-DOC**: requiere `phase1/web-ui-design.md` para el alcance detallado de pantallas y criterios de aceptación de UX. No existía al escribir este plan. Mientras no exista, el alcance mínimo de este sprint es el definido abajo, derivado de `channels.md` §1.9 y §2.8 (flujo de confirmación y estados de UI, que son agnósticos del canal) y de `phase1/channels.md` §0 (el agente no tiene lógica de canal: esta UI es, técnicamente, un tercer *Channel Adapter* igual de delgado que el widget o el bot). **Si `web-ui-design.md` aparece durante el sprint, sus criterios de aceptación de UX se incorporan sin reabrir la arquitectura** (login, proxy, almacenamiento de sesión no cambian). |

#### Entregables

1. **Login propio del agente**, independiente de las sesiones de trafico-system y
   liquidaciones-system: formulario usuario/contraseña contra `agent_ui_users` (Sprint 1, entregable
   6), cookie de sesión HTTPOnly + `Secure` + `SameSite=Lax`, hashing argon2/bcrypt, **sin
   "recordarme"** en esta fase, bloqueo tras N intentos fallidos (anti fuerza bruta elemental).
2. **Pantalla de chat**, implementando el mismo contrato `POST /api/v1/chat` que consumirán después
   el widget y Mattermost — es la prueba de que el contrato es agnóstico del canal
   (`channels.md` §0). Reutiliza los **9 estados de UI** de `channels.md` §2.8 (pensando, respuesta,
   aclaración, dry-run, confirmación requerida, denegado, sin capacidad, degradado, error) —
   aplicables todos aquí porque, a diferencia del widget (Sprint 5, que al principio solo tiene
   lecturas), la UI standalone puede ejercitar también los 2 estados de escritura (dry-run,
   confirmación) de forma **simulada contra un stub**, ya que no hay tools L2 reales hasta el
   Sprint 7. Esto permite validar la UX de confirmación **antes** de que exista una escritura real.
3. **Pantalla de reportes**: listado de `sessions`/`messages`/`audit_log` del propio usuario (y, para
   rol `admin`, de todos), con filtro por fecha y `status`. Es la superficie que permite al usuario
   revisar lo que el agente hizo sin tener que leer la BD a mano.
4. **Pantalla de confirmaciones pendientes**: lista de `status: confirmation_required` abiertas
   (aunque en este sprint no haya tools L2 reales, la pantalla y el flujo de `POST
   /api/v1/chat/confirm` se construyen y se prueban contra el stub del punto 2).
5. **Sin Shadow DOM, sin same-origin-proxy**: a diferencia del widget (Sprint 5), esta UI es la
   aplicación principal de su propio origen (`https://agent.forsis.<dominio>` o subruta dedicada),
   servida directamente por el propio agente. No hereda ninguna de las restricciones de integración
   de `channels.md` §2.1-2.2 (eso es específico de insertarse dentro de otro sistema).
6. **`trace_id` visible** en toda respuesta de error, igual que en el widget (`channels.md` §2.8),
   porque es la misma pieza de UX que se reutilizará allí.
7. **Registro explícito de qué NO cubre este sprint**: no hay widget embebido en ningún sistema de
   negocio, no hay Mattermost, no hay tools de escritura reales — todo eso es posterior al HITO.

#### Criterio de aceptación

```
# A1. login funciona y es independiente de los otros sistemas
Login con la cuenta sembrada en Sprint 1 → sesión creada → cerrar sesión de trafico-system
(si estuviera abierta) no afecta esta sesión, y viceversa.
# → PASS si son cookies de dominio/ruta distintos y no comparten almacenamiento.

# A2. intentos fallidos se bloquean
5 intentos con contraseña incorrecta → 6to intento rechazado aunque la contraseña sea correcta,
con mensaje explícito y ventana de espera.
# → PASS

# A3. turno real con tool de lectura, visible en la UI
Escribir "¿qué guías tiene pendientes el cliente 412?" → se ve el estado "pensando" con el hint
a los 15s si aplica → aparece la tarjeta de `components` con los datos reales de trafico-system.
# → PASS. Repite la A1 del Sprint 3 pero ahora frente a ojos humanos, no solo curl.

# A4. los 9 estados de UI se alcanzan (incluidos los 2 de escritura, vía stub)
pensando / respuesta / aclaración / dry-run (stub) / confirmación requerida (stub) / denegado /
sin capacidad / degradado / error (con trace_id) — los 9 de channels.md §2.8.
# → 9/9 PASS. A diferencia del Sprint 4 de v1 (widget), aquí SÍ se prueban los 2 de escritura
#   porque no dependen de una tool L2 real, solo del contrato.

# A5. reportes muestran datos reales y correctos
Comparar el listado de `sessions` de la pantalla de reportes contra una consulta directa a la
tabla `sessions` del mismo periodo → mismos ids, mismos estados.
# → PASS

# A6. aislamiento entre usuarios
Usuario A no puede ver las sesiones de Usuario B salvo que su rol sea `admin`.
# → PASS

# A7. trace_id visible en cualquier error
Forzar un error (parar Omniroute) → la UI muestra el trace_id, y ese mismo trace_id aparece en
el log del agente.
# → PASS
```

#### Criterio de reversión

**Trivial:** `AGENT_UI_ENABLED=false` + restart del contenedor de la UI (si se sirve como proceso
separado) o simplemente no enrutar la ruta en nginx. Nadie fuera del equipo del proyecto tiene esta
URL todavía, así que el reverso no afecta a ningún tercero.

**Riesgo del sprint:** si `web-ui-design.md` aparece a mitad de sprint con un alcance
significativamente mayor (p.ej. dashboards adicionales), **no se amplía el sprint en vuelo**: el
excedente se registra como backlog para un Sprint 4-bis posterior al HITO, para no retrasar la
validación con el usuario.

---

## ███ HITO GO/NO-GO — ver §2 ███

**Ningún sprint de aquí en adelante (S5-S9) empieza sin GO documentado.**

---

### Sprint 5 — Widget embebido en `trafico-system` (un solo sistema)

*(Contenido igual al Sprint 4 de v1, renumerado. Única adición: depende también del HITO.)*

| | |
|---|---|
| **Objetivo** | El canal "widget" funcionando para usuarios reales de trafico-system, con identidad, permisos y estados de UI correctos. |
| **Estimación** | **12 d.p.** |
| **Dependencias** | **HITO GO/NO-GO aprobado** + Sprint 3 |
| **Dueño** | Frontend 0.5 + Agente 1 + TI del dueño de trafico-system |
| **Estado de bloqueo** | BLOQUEADO hasta HITO. Además hereda B-C2 (layout único no verificado) y B-C5 (CSP no verificada) como condiciones a resolver **antes** de empezar, no a mitad. |

#### Entregables

1. **`forsis-ai-widget.js`** (`channels.md` §2.6): JS vanilla, IIFE, sin build step, Shadow DOM,
   `all:initial`, CSS inline. Los 9 estados de UI de §2.8 (ya validados en la UI standalone del
   Sprint 4 — aquí se trata de reproducirlos dentro del Shadow DOM, no de diseñarlos de cero).
2. **`ai_chat_proxy.php`** en `trafico-system`: lee `$_SESSION`, resuelve `company`, firma JWT de
   identidad (HS256, `exp` 60s), evalúa allowlist, reenvía con `Bearer
   ${FORSIS_AGENT_TOKEN_TRAFICO}`. Pass-through puro.
3. **Ruta `POST /api/ai/chat`** en el nginx de trafico-system, `client_max_body_size 64k`.
4. **Inyección** en el layout compartido, con `defer`, solo para sesión válida,
   `data-channel="widget-trafico"`.
5. **Unión de redes**: `trafico-php` se une a `forsis-agent_net`. Solo el proxy.
6. **Resolución de B-C2 y B-C5** antes de integrar.
7. **Inventario de navegadores** de los usuarios de trafico-system (B-C4).
8. **`sessionStorage`** para `session_id` y estado del panel; nada más se persiste en cliente.

#### Criterio de aceptación

Idéntico al Sprint 4 de v1 (A1-A8: aislamiento de estilos, token del agente ausente del navegador,
sesión, empresa desde el servidor, estados de UI, sin CORS, allowlist fail-closed, aislamiento de
empresa). Se referencia en vez de repetir íntegro; ver `sprint-plan.md` §Sprint 4 por el texto
exacto de cada prueba. Dos precisiones de v2:

- **Conteo de estados:** v1 hablaba de "8 estados de UI"; la tabla real de `channels.md` §2.8 tiene
  **9 filas** (pensando, respuesta, aclaración, dry-run, confirmación requerida, denegado, sin
  capacidad, degradado, error). Este plan usa **9** de forma consistente. La discrepancia de v1 se
  deja anotada aquí y **no** se corrige en `sprint-plan.md` (histórico, no se modifica).
- **Alcance alcanzable en este sprint:** 7 de los 9 estados se validan directamente. Los 2 de
  escritura (dry-run y confirmación requerida) ya fueron validados por stub en el Sprint 4 y aquí
  quedan **bloqueados por diseño** hasta que exista la tool L2 real del Sprint 7, igual que en v1.
  Criterio: **7/9 directos + 2/9 con el stub del Sprint 4 reutilizado**; los 9/9 con escritura real
  se cierran en el Sprint 7 (A11).

#### Criterio de reversión

`FORSIS_AI_WIDGET_ENABLED=false` + `docker compose restart php`. Sin redeploy de código. La unión de
red no se desune en el reverso.

**Riesgo:** si B-C2 resulta negativo (no hay layout único), la estimación se duplica a ~20 d.p.

---

### Sprint 6 — Cableado de `forsis-bot` detrás de feature flag (Mattermost)

*(Contenido igual al Sprint 5 de v1, renumerado. Adiciones: depende del HITO y de SEC-1 cerrado.)*

| | |
|---|---|
| **Objetivo** | El canal Mattermost funcionando, reversible en un cambio de variable de entorno. |
| **Estimación** | **9 d.p.** |
| **Dependencias** | **HITO GO/NO-GO aprobado** + Sprints 2 y 3. **SEC-1 (BOT_TOKEN) debe estar cerrada — obligatorio, ver §4.** |
| **Dueño** | Dueño de `forsis-bot` + Agente 1 |
| **Estado de bloqueo** | BLOQUEADO hasta HITO **y** hasta SEC-1 cerrada. Este sprint no puede "empezar en paralelo" a SEC-1 como sí podía S1: cablear un token todavía filtrado a un agente nuevo sería agravar el incidente, no solo mantenerlo. |

#### Entregables

1. **`ejecutar_agente()`** en `actions.py`, sustituyendo `ejecutar_agy()`. `DELEGATE_TO_AGENT=false`
   ⇒ comportamiento legado intacto.
2. **Adaptación de call sites** (`main.py:429`, `main.py:442`) → despacho por `status`, chunking en
   vez de truncado silencioso.
3. **`FORSIS_AGENT_URL`/`FORSIS_AGENT_TOKEN`/`FORSIS_AGENT_TIMEOUT_S=130`** en `.env` del bot — **con
   el token nuevo emitido por SEC-1**, nunca el viejo.
4. **`channel_identity_map` poblada** para la lista blanca de pilotaje, alta manual explícita.
5. **Unión de red**: `forsis-bot` se une a `forsis-agent_net`.
6. **Resolución de B-C6** (ruta HTTP al bot para botones interactivos) o fallback textual.
7. **Manejo de `429`/`Retry-After`**, lectura de `MaxPostSize` real, cola FIFO ≤1 post/s.
8. **Circuit breaker**: 5 fallos consecutivos ⇒ 60s de pausa.
9. **Typing indicator** cada 4s.
10. **Prueba del flag en ambos sentidos.**

#### Criterio de aceptación

Igual al Sprint 5 de v1 (A1-A8: flag en ambos sentidos, `trace_id` compartido, idempotencia ante
reconexión de WebSocket, allowlist fail-closed, identidad no registrada, token nunca en logs,
degradación honesta si el agente cae, chunking de mensajes largos). Se añade:

```bash
# A9 (nuevo en v2). El token en uso es el emitido por SEC-1, no el filtrado
docker exec forsis-bot printenv BOT_TOKEN | head -c 8   # coincide con el runbook de SEC-1,
# NO con el valor documentado como comprometido en el incidente.
```

#### Criterio de reversión

`docker exec forsis-bot env DELEGATE_TO_AGENT=false && docker restart forsis-bot`. Probado en
ambos sentidos antes de cerrar el sprint.

**Nota de secuencia:** igual que en v1, este sprint va antes de las escrituras a propósito.

---

### Sprint 7 — Tools de escritura con gate humano

*(Contenido igual al Sprint 6 de v1, renumerado. Depende también del HITO.)*

| | |
|---|---|
| **Objetivo** | La primera escritura real, con dry-run forzado y aprobación humana. |
| **Estimación** | **12 d.p.** |
| **Dependencias** | **HITO GO/NO-GO aprobado** + Sprint 6. **SEC-1 cerrada** (ya lo estaba desde S6). |
| **Dueño** | Agente 3 (tools) + dueño del sistema destino |
| **Estado de bloqueo** | BLOQUEADO hasta HITO. |

#### Entregables

1. **Primer destino de escritura: `trafico-system`** (no liquidaciones — el Sprint 9 existe
   precisamente porque liquidaciones necesita el módulo `LIQUIDACIONES`, que no existe).
2. **`PlanGuard` completo**, 7 gates activos: gate 6 (dry-run forzado para L2, fail-closed, sin
   excepción), `run_id` correlacionando dry-run y commit, gate 7 (confirmación humana,
   `confirmation_id`, TTL 5 min).
3. **`POST /api/v1/chat/confirm` completo**, con idempotencia, `exp`, verificación de que quien
   confirma es quien originó — **esta es la misma pantalla de confirmaciones del Sprint 4**, ahora
   conectada a una tool real en vez del stub.
4. **Herramienta L2 #1** en trafico-system, `required_permissions` del RBAC real.
5. **Estados de UI restantes en el widget** (dry-run y confirmación, que en el Sprint 5 quedaron
   bloqueados por diseño).
6. **Confirmación en Mattermost**: botones interactivos o fallback textual.
7. **Rol dedicado para creación de solicitudes**, distinto del rol de revisor.
8. **L3 documentada como no implementada**, rechazada en ejecución.

#### Criterio de aceptación

Igual al Sprint 6 de v1 (A1-A10: dry-run no muta nada, gate humano real, confirmación produce
exactamente un efecto, un tercero no puede confirmar, la confirmación expira, el executor rechaza
L2 sin dry-run, actor sin permiso no ejecuta, L3 siempre rechazada, 9/9 estados de widget con
escritura real, la
reversión del Sprint 6 sigue funcionando). Se añade:

```bash
# A11 (nuevo en v2). La pantalla de confirmaciones de la UI standalone (Sprint 4) funciona
#     también contra la tool real, no solo contra el stub.
#     → mismo flujo, mismos criterios A1-A5 del Sprint 4, ahora con una escritura real detrás.
```

#### Criterio de reversión

Tres niveles (igual a v1): kill switch `FORSIS_WRITES_ENABLED=false`, vuelta del canal 2 a `agy`
(`DELEGATE_TO_AGENT=false`), `git revert` del código (sin deshacer datos ya escritos — por eso el
gate humano es obligatorio).

---

### Sprint 8 — Hardening, observabilidad y piloto con usuarios

*(Contenido igual al Sprint 7 de v1, renumerado.)*

| | |
|---|---|
| **Objetivo** | Que el sistema sea operable en producción con usuarios reales, con los tres canales (UI standalone, widget, Mattermost) en calidad consistente. |
| **Estimación** | **9 d.p.** |
| **Dependencias** | Sprints 5, 6, 7 |
| **Dueño** | Todos |
| **Estado de bloqueo** | Ninguno propio. Hereda SEC-3 (Omniroute sin auth) como condición a verificar antes del piloto — ver §4. |

#### Entregables

1. **Métricas y alertas**: p50/p95/p99 por etapa, tasa de error por `error_code`, tasa de
   `llm_salvage`/`llm_failclosed`, turnos por canal (ahora **tres**: UI standalone, widget,
   Mattermost), herramientas por `risk_class`, confirmaciones pendientes por antigüedad.
2. **Alertas con umbrales**: latencia p95>60s, `LLM_UNAVAILABLE`>5 en 5min, circuit breaker
   abierto, BD no conectada, cualquier `audit_log` con un L3 intentado.
3. **Revisión de V-1…V-6** de `llm-provider.md` §3.4 con datos de los tres canales en producción.
4. **Límites de rate**: 20/hora y 5/min por actor, 4 turnos concurrentes.
5. **Runbooks**: caída de Omniroute, caída de BD del agente, respuestas incorrectas, desactivar
   escrituras de urgencia, revertir Mattermost.
6. **Piloto con usuarios reales**: 5-8 de trafico-system (widget), 5-8 de `Forsis PR` (Mattermost),
   más los usuarios ya validados en la UI standalone desde el Sprint 4, 2 semanas. Sin liquidaciones
   (B-C3 sigue abierto salvo que SEC-2 se haya cerrado antes — ver §4).
7. **Backups de la BD del agente** con prueba de restauración.
8. **Documentación de usuario final.**
9. **Decisión sobre el widget en `liquidaciones-system`**, con datos: ¿pasaron A1/A2 de
   `liquidaciones-security-strategy.md` (SEC-2)? Si no, no se despliega.
10. **Verificación de SEC-3** (Omniroute sin auth en `:20130`): reportado al dueño desde el Sprint 1;
    aquí se verifica si se cerró. Si sigue abierto, se documenta como riesgo aceptado con dueño
    nombrado, no bloquea el piloto pero sí se declara explícitamente.

#### Criterio de aceptación

Igual a v1: 5 runbooks ejecutables y probados (al menos un drill real), backup restaurado en limpio,
piloto de 2 semanas con error<5%, ≥3 turnos/usuario/día, cero escrituras no autorizadas, 0 `L3`
ejecutadas y >0 `L3` denegadas registradas, decisión documentada sobre fiabilidad del JSON mode.

#### Criterio de reversión

`FORSIS_AGENT_ENABLED=false` global apaga los tres canales. Se ensaya antes de cerrar el sprint.

---

### Sprint 9 — Módulo `LIQUIDACIONES` del workflow de solicitudes

*(Contenido igual al Sprint 8 de v1, renumerado. Depende también del HITO, heredado transitivamente de S7.)*

| | |
|---|---|
| **Objetivo** | Cerrar el circuito de valor: el agente puede pedir autorización de una liquidación mediante el flujo oficial. |
| **Estimación** | **12 d.p.** |
| **Dependencias** | Sprint 7 (gate humano probado) + **B-C10/B-02 resuelto** (módulo no existe) + **SEC-2 resuelta** (8 endpoints anónimos, Fase A de `liquidaciones-security-strategy.md`) para el widget de liquidaciones. |
| **Dueño** | Dueño de `liquidaciones-system` (0.3 d.p./semana) + Agente 3 |
| **Estado de bloqueo** | **BLOQUEANTE** hasta que el workflow tenga el módulo `LIQUIDACIONES` (tarea B6 de `liquidaciones-security-strategy.md` Fase B) y hasta que SEC-2 (Fase A) esté cerrada para habilitar `liq.solicitud_crear` con algo de confianza en la auditoría. |

#### Entregables

1. **Módulo `LIQUIDACIONES`** en el workflow: plantilla de notificación, cola del revisor,
   transición de estado, registro — siguiendo el patrón de `CAJA_CHICA`/`TARJETA_DEUDOR`/
   `RECEPCION_GUIAS`.
2. **Rol dedicado** para crear solicitudes, distinto del que autoriza (`SUPER USUARIO`).
3. **`liq.solicitud_crear`** (L2) y, opcionalmente, una L2 de solo consulta de estatus.
   **Ninguna L3 se registra en Fase 1** (`autorizar_liquidacion` sería L3).
4. **`status: confirmation_required`** contra el módulo real: agente pide, humano autoriza/rechaza.
5. **Idempotencia hasta el sistema dueño**: clave de idempotencia propia por tool de escritura hacia
   liquidaciones, no solo la del turno.
6. **Verificación de B-C11** (`action=crear` sin `priv`, parte de SEC-2 Fase A/A3): si sigue abierto
   en la fecha del sprint, la tool de creación **no se despliega**.
7. **Widget en `liquidaciones-system`**: solo si SEC-2 (equivalente a B-C3 de v1) se resolvió.

#### Criterio de aceptación

Igual a v1 (A1-A6): flujo completo con humano real en medio, no-autorizado no puede ni pedirlo,
revisor ve la cola sin inundación (≤5 solicitudes/día), rechazo es camino de primera clase,
idempotencia extremo a extremo, SEC-2/B-C11 resueltos o el widget no se despliega.

#### Criterio de reversión

Retirar la tool del catálogo, `FORSIS_WRITES_ENABLED=false`, módulo `LIQUIDACIONES` puesto inactivo
(las solicitudes ya creadas no se deshacen — por diseño, las revisó un humano).

---

## 4. Tareas de seguridad fuera de la ruta crítica (obligatorias, con fecha límite)

Estas tareas **no bloquean el inicio** de ningún sprint salvo el que se indica explícitamente, pero
son obligatorias y deben cerrarse antes de la fecha límite dada. No tener un sprint asignado no las
vuelve opcionales.

| ID | Tarea | Origen | Impacto si no se cierra | Dueño | **Fecha límite (sprint tope)** |
|---|---|---|---|---|---|
| **SEC-1** 🔴 | **Saneo del `BOT_TOKEN` commiteado** (`forsis-bot/docker-compose.yml`, commit `ee300fa`, `system_post_all` sobre 36 canales): rotación, verificación de revocación del viejo, saneo de historial de git (si es viable), reducción de permisos, auditoría de otros secretos literales, runbook de rotación | Sprint 0 de v1 (`sprint-plan.md`), ahora reclasificada por ADR-001 | Mattermost se cablea sobre un incidente de seguridad abierto; cualquiera con el repo sigue pudiendo publicar como `forsisbot` | Dueño de `forsis-bot` | **Antes del inicio del Sprint 6** (cableado de Mattermost). Puede ejecutarse en paralelo a S1-S5, idealmente empieza el día 1. |
| **SEC-2** 🔴 | **Fase A de `liquidaciones-security-strategy.md`**: A1 (gate de auth en 8 endpoints sin ninguno: `liquidaciones.php`, `liquidacion_detalle.php`, `tarjeta_deudor.php`, `nueva_liquidacion_operador.php`, `next_folio.php`, `buscar_operadores.php`, `imprimir_termico_caja.php`, `imprimir_termico_rsp.php`), A2 (match exacto de `priv` en `autorizar_liquidacion.php`), A3 (check de `priv` en `action=crear`) | `liquidaciones-security-strategy.md` §4 Fase A; B-C3/B-C11 de `channels.md` | El widget en liquidaciones heredaría autenticación pública (77/95 usuarios con contraseña vacía); `liq.solicitud_crear` escribiría en una cola sin gate de entrada | Dueño de `liquidaciones-system` | **Antes del Sprint 9** (módulo LIQUIDACIONES y cualquier escritura/widget sobre liquidaciones). Riesgo de rotura ≈ nulo según el propio documento — puede y debe adelantarse, no hay razón técnica para esperar al Sprint 9 para empezarla. |
| **SEC-3** 🟡 | **Auth abierta de Omniroute**: `POST /v1/chat/completions` en `0.0.0.0:20130` responde 200 sin `Authorization` | `llm-provider.md` §1.1 (B-4); B-C13 de `channels.md` | Cualquiera con red al host consume el presupuesto de tokens del combo compartido | Dueño de Omniroute | Reportar en el Sprint 1 (no bloquea su inicio). Verificar si se cerró **antes del Sprint 8** (piloto con usuarios reales) — con un piloto en marcha, el costo de un consumo no autorizado del combo deja de ser hipotético. |

**Regla transversal:** ninguna de estas tres tareas se "resuelve" por omisión al llegar a su fecha
límite. Si en la fecha tope SEC-1 no está cerrada, el Sprint 6 **no empieza** (es dependencia dura,
no solo recomendación). Si SEC-2 no está cerrada en el Sprint 9, el entregable de ese sprint se
reduce a Mattermost + `liq.solicitud_crear` **condicionada** a que B-C11 esté resuelto, sin widget
en liquidaciones, documentado como decisión. Si SEC-3 sigue abierta en el Sprint 8, se documenta
como riesgo aceptado con dueño nombrado (igual que R13 heredado), no bloquea el piloto.

---

## 5. Tabla consolidada de sprints

| Sprint | Objetivo | d.p. | Dependencias | Bloquea a | Estado de bloqueo | Reversión en una línea |
|---|---|---|---|---|---|---|
| **1** | Contenedor Python/FastAPI + BD | 7 | — | S2 | BLOQUEANTE-DOC parcial (`architecture-python.md`) | `down -v` + revert |
| **2** | `OmnirouteProvider` + `POST /api/v1/chat` | 12 | S1 | S3 | Hereda B-2/B-C12 (JSON mode), mitigado no resuelto | redeploy a versión anterior |
| **3** | Vertical slice: 1 tool de lectura | 10 | S2 | S4 | BLOQUEANTE hasta B-05/B-03 verificados | quitar la tool del catálogo |
| **4** 🆕 | UI web standalone (login, chat, reportes, confirmaciones) | 12 | S3 | **HITO** | BLOQUEANTE-DOC (`web-ui-design.md`) | `AGENT_UI_ENABLED=false` |
| **HITO** | GO/NO-GO del usuario | — | S4 | S5-S9 | **Gate obligatorio, no sprint** | N/A — reabre S4 si NO-GO |
| **5** | Widget en `trafico-system` | 12 | HITO + S3 | S8 | BLOQUEADO hasta HITO; B-C2/B-C5 por resolver antes de empezar | `FORSIS_AI_WIDGET_ENABLED=false` |
| **6** | `forsis-bot`/Mattermost tras feature flag | 9 | HITO + S2 + S3 | S7, S8 | BLOQUEADO hasta HITO **y** SEC-1 cerrada | `DELEGATE_TO_AGENT=false` + restart |
| **7** | Tools de escritura con gate humano | 12 | HITO + S6 | S8, S9 | BLOQUEADO hasta HITO | `FORSIS_WRITES_ENABLED=false` |
| **8** | Hardening, observabilidad, piloto | 9 | S5, S6, S7 | S9 | Hereda SEC-3 como verificación previa | `FORSIS_AGENT_ENABLED=false` global |
| **9** | Módulo `LIQUIDACIONES` | 12 | S7 + B-02 resuelto + SEC-2 | — | BLOQUEANTE hasta módulo creado y SEC-2 cerrada | retirar tool + módulo inactivo |
| | **TOTAL** | **95** | | | | |

**Reparto de capacidad:** 41 d.p. de agente/backend (S1,S2,S3,S6,S7), 24 de frontend (S4 UI
standalone + S5 widget), 9 de operación (S8), 12 de integración con el dueño de liquidaciones (S9).
Las tareas SEC-1/SEC-2/SEC-3 no se contabilizan en los 95 d.p. del plan (son responsabilidad de
otros dueños, fuera del presupuesto del agente), igual que en v1 el Sprint 0 tampoco se sumaba al
reparto por rol de la tabla de capacidad del agente — aquí sí suma al total general porque figura
como sprint, lo que es la diferencia operativa clave de ADR-001 respecto a v1: **SEC-1 ya no consume
2 d.p. de la ruta crítica del agente**, los consume el dueño de `forsis-bot` en paralelo.

---

## 6. Riesgos

Se heredan los 18 riesgos de `sprint-plan.md` §3, renumerando el sprint de referencia donde cambió,
y se añaden 2 riesgos nuevos propios de v2 (R19, R20).

| # | Riesgo | Prob. | Impacto | Mitigación | Sprint (v2) | Cambio vs v1 |
|---|---|---|---|---|---|---|
| **R1** 🔴 | `BOT_TOKEN` commiteado sigue válido | Alta (ya ocurrió) | Crítico | Rotar → verificar revocado → rewrite de historial como defensa secundaria → reducir permisos | **SEC-1, tope antes de S6** | **Cambia de posición, no de severidad.** Ya no bloquea el día 1 del plan, pero S6 no empieza sin ella cerrada — el riesgo es idéntico, la ruta crítica es distinta. |
| **R2** 🔴 | JSON mode del combo "Forsis" al 70%/80% | Alta, medida | Crítico desde S7 | 4 capas + métricas desde el día 1 + V-1 antes de avanzar | 2, 7 | Sin cambios. **Se añade**: V-1 es ahora también insumo del HITO — un JSON mode pobre puede producir un NO-GO, lo cual es una red de seguridad adicional que v1 no tenía. |
| **R3** 🔴 | Módulo `LIQUIDACIONES` no existe (B-02) | Alta (verificada) | Alto | Sprint 9 dedicado, decisión del dueño de liquidaciones requerida temprano | 9 | Sin cambios de fondo; el sprint se corrió un número. |
| **R4** 🔴 | 77/95 usuarios de liquidaciones con contraseña vacía | Alta (verificada) | Crítico si se despliega ahí | Widget en trafico-system primero (S5); en liquidaciones, nominal, condicionado a SEC-2 | 5, 9 | Renombrado B-C3→SEC-2 en este documento para unificar con la tabla de §4; sin cambio de severidad. |
| **R5** | `action=crear` no valida `priv` (B-C11) | Media (verificada) | Medio | Condición de entrada del Sprint 9, parte de SEC-2 | 9 | Sin cambios, ahora explícitamente parte de SEC-2. |
| **R6** | Puertos y redes sin red común | Alta (verificada) | Alto | `forsis-agent_net` en S1, bot se une en S6, `trafico-php` en S5 | 1, 5, 6 | Sin cambios de fondo; sprints renumerados. |
| **R7** | Doble despliegue (bot + agente) ahora **triple** (bot + agente + UI standalone) | Alta (aceptada) | Medio | `trace_id` compartido en los tres, `health`/`ready`, circuit breaker, `DELEGATE_TO_AGENT` | 6, 8 | **Empeora ligeramente**: la UI standalone es un tercer proceso/origen a operar, aunque reutiliza el mismo backend. Mitigación sin cambios porque el backend es uno solo. |
| **R8** | La decisión de stack se pospone | Media | Alto | **Resuelto por ADR-001.** Ya no es un riesgo activo | — | **Cerrado.** Se mantiene en la tabla solo para trazabilidad del cambio. |
| **R9** | Omniroute sin auth en `:20130` | Media (verificada) | Medio | Reportar en S1, verificar antes de S8 | **SEC-3, tope antes de S8** | Igual que R1: cambia de posición (ya no "Sprint 1 y 7" sino tarea con tope), no de severidad. |
| **R10** | Turnos largos, usuario repite el mensaje | Alta | Medio | `Idempotency-Key` en los tres canales + hint a los 15s + cancelar honesto | 2, 4, 5, 6 | **Se añade el canal 4** (UI standalone) a la lista de superficies que necesitan esta mitigación — y la obtiene primero, porque se construye en S4. |
| **R11** | Duplicación de acciones por desconexión de WebSocket (MM) | Media | Alto desde S7 | `Idempotency-Key: mm:{post_id}` + dedup del bot + aserción que falla binario | 6, 7 | Sin cambios de fondo; sprints renumerados. |
| **R12** | Inundación del buzón del revisor | Media | Medio | Rol dedicado para crear + idempotencia + dry-run + métrica ≤5/día | 7, 9 | Sin cambios de fondo. |
| **R13** | Permisos del bot demasiado amplios tras "resolver" solo con rotación | Media | Alto | Reducción de permisos como parte de SEC-1 | SEC-1 | Sin cambios de fondo; movido a SEC-1. |
| **R14** | Equipo pequeño y ahora **95** d.p. de trabajo (vs 84 de v1) | Media | Crítico | SEC-1 y el gate de dry-run siguen siendo no negociables; **el HITO es el nuevo punto donde se puede decidir no seguir** sin haber gastado presupuesto de integración | todos | **Se añade el HITO como mecanismo explícito de contención del riesgo**, algo que v1 no tenía: con v1, un agente mediocre se descubría ya integrado en 2 sistemas; con v2, se descubre en una UI aislada. |
| **R15** | Falsa sensación de que el agente "funciona" sin datos reales | Media | Alto | Turno sin tool real = fallo (A1 del S3). **El HITO exige que el usuario lo compruebe en persona**, no un reporte de otro agente | 3, 4, 8 | **Se refuerza.** v1 dependía de que alguien leyera las métricas; v2 obliga a una validación humana explícita en S4/HITO antes de seguir. |
| **R16** | CSP o layout inexistente bloquean el widget | Media | Medio | Resolver antes de empezar S5 | 5 | Sin cambios de fondo; sprint renumerado. |
| **R17** | Botones de confirmación de MM no alcanzables (B-C6) | Media | Bajo | Fallback textual ya diseñado | 6 | Sin cambios de fondo; sprint renumerado. |
| **R18** | Costo de tokens del combo compartido | Media | Medio | Rate limits (S8), caché semántica, SEC-3 reportado | 8 | Sin cambios de fondo. |
| **R19** 🆕 | **El HITO se declara GO sin evidencia documentada** (nadie escribe el acta de §2), y S5 en adelante arranca de facto sin validación real | Media | Alto | Exigir el archivo `hito-go-nogo.md` como entregable obligatorio del HITO, no solo una conversación. Ningún reporte de avance puede declarar "S5 en curso" sin referenciarlo | HITO | **Nuevo en v2** — no existía en v1 porque no había hito formal. |
| **R20** 🆕 | **La UI standalone (S4) se construye con alcance mayor al necesario** (dashboards, analítica, etc.) porque "ya que hay frontend, aprovechamos", retrasando el HITO y con él todo lo demás | Media | Medio | El criterio de reversión y el propio §3/Sprint 4 fijan el alcance mínimo explícitamente (login + chat + reportes + confirmaciones, nada más) y ordenan que cualquier excedente de `web-ui-design.md` vaya a un Sprint 4-bis **posterior** al HITO, nunca antes | 4 | **Nuevo en v2** — riesgo propio de introducir un sprint de UI que antes no existía. |

---

## 7. Lo que este plan NO cubre

- **La corrección completa de `liquidaciones-system`** más allá de SEC-2 (Fase A). Fases B/C de
  `liquidaciones-security-strategy.md` son un proyecto separado.
- **L3 (acciones irreversibles).** Ninguna se registra como invocable.
- **Voz, imágenes, adjuntos, multi-idioma.**
- **Proactividad del agente** (recordatorios, acciones sin que el usuario las pida).
- **Streaming** — decisión argumentada en `channels.md` §1.10.
- **El widget en `liquidaciones-system`** hasta que SEC-2 se resuelva.
- **Diseño detallado de pantallas de la UI standalone** más allá del alcance mínimo de la §3/Sprint 4
  — eso es responsabilidad de `web-ui-design.md` cuando exista.

---

## 8. Definición de "listo" del MVP (v2)

El proyecto está cuando, y solo cuando:

1. `POST /api/v1/chat` cumple el contrato de `channels.md` §1 sobre Python/FastAPI, incluidas las 6
   validaciones fail-closed.
2. Un turno con una tool de lectura real atraviesa el pipeline completo y el resultado coincide con
   la fuente (A2 del Sprint 3).
3. **La UI web standalone existe, el HITO GO/NO-GO fue aprobado por el usuario y está documentado**
   en `hito-go-nogo.md` — condición que v1 no tenía y que es, junto con el stack, el cambio central
   de este documento.
4. El widget funciona en `trafico-system` con Shadow DOM aislado y sin token en el navegador.
5. `forsis-bot` delega al agente tras un flag probado en los dos sentidos, con `trace_id`
   correlacionado, **y SEC-1 está cerrada** (sin esto, este punto no puede declararse cumplido).
6. La primera escritura L2 existe con dry-run forzado, gate humano e idempotencia, probados los tres.
7. Cero escrituras no autorizadas en `audit_log` durante 2 semanas de piloto.
8. El módulo `LIQUIDACIONES` existe, o la decisión de no hacerlo está documentada — **y SEC-2 está
   cerrada** si el widget de liquidaciones forma parte del alcance declarado "listo".
9. Los runbooks existen y al menos dos se ejecutaron en drill.
10. El agente se puede apagar entero con una variable de entorno, y eso se ha probado.
11. SEC-3 tiene una decisión documentada (cerrada, o riesgo aceptado con dueño nombrado) antes de
    declarar el piloto del Sprint 8 como representativo de producción.

---

Generado: 2026-10-05 — Fase 1, revisión v2 por ADR-001. Entregable hermano: `channels.md`.
No modifica `sprint-plan.md` (histórico), ni código de `forsis-bot`, `trafico-system` ni
`liquidaciones-system`: este plan especifica el trabajo, no lo ejecuta.
