# Canales de Acceso — Forsis AI Agent (Fase 1, Agente 4)

**Fecha:** 2026-10-05
**Entregable:** `channels.md` (1 de 2) — ver también `sprint-plan.md`
**Fuentes citadas:** `prototype-review.md` §6.1 y §6.3, `mattermost-integration-strategy.md` §2–§5,
`mattermost-analysis.md`, `mattermost-bot-integration.md`, `mattermost-api-inventory.md`,
`phase1/architecture.md` §2–§3, `phase1/db-schema.md`, `phase1/agent-core.md` §2–§4,
`phase1/llm-provider.md` §2.2, `phase1/tools-design.md` §1–§2,
`liquidaciones-security-strategy.md` §2 y §4, `trafico-system-analysis.md` §2–§5,
`liquidaciones-system-analysis.md` §2.

> **Credenciales:** ningún valor real aparece en este documento. Todo secreto se referencia como
> `${VAR}` o `[REDACTED]`.

---

## 0. Alcance y definición de "canal"

Un **canal** es una vía de acceso técnico por la que un usuario humano conversa con el agente.
Hay exactamente **dos** en el MVP, y ambos consumen el **mismo** `POST /api/v1/chat`:

| # | Canal | Transporte | Dónde vive el código | Estado hoy |
|---|---|---|---|---|
| **C1** | **Widget de chat embebido** | HTTPS, same-origin vía proxy PHP del sistema anfitrión | Nuevo: JS vanilla servido por el agente, inyectado en `trafico-system` y `liquidaciones-system` | No existe |
| **C2** | **Mattermost** | WebSocket MM → `forsis-bot` → HTTP al agente | `forsis-bot` ya existe (2 702 LOC, `ai-network`), cambio de ~30 líneas en `actions.py` | Funciona, pero delega por `subprocess.run(["agy", …])` |

**Principio rector de este diseño:** el agente **no tiene lógica de canal**. Todo lo específico del
canal vive en un *Channel Adapter* delgado (el widget, o `forsis-bot`), y el núcleo recibe siempre el
mismo `UserRequest` (`agent-core.md` §1, "Channel Adapter … no es del núcleo"). Esto es lo que permite
que el segundo canal cueste días y no semanas.

**No se modifica código existente en esta fase.** Los cambios en `forsis-bot`, `trafico-system` y
`liquidaciones-system` se *especifican* aquí como diffs propuestos; su ejecución es trabajo de Fase 2
(ver `sprint-plan.md`).

---

## 1. Contrato de `POST /api/v1/chat`

### 1.1 Base, versionado y endpoints

| Aspecto | Valor |
|---|---|
| Base URL externa (widget, vía proxy del anfitrión) | `https://forsispr1.ddns.net:8099/api/v1` (`architecture.md` §3.1) |
| Base URL interna (forsis-bot, red Docker) | `http://forsis-ai-agent-nginx:8080/api/v1` — listener HTTP plano interno, sin coste TLS (`architecture.md` §3.1) |
| Endpoint de conversación | `POST /api/v1/chat` |
| Endpoint de salud | `GET /api/v1/health` (sin auth, sin tocar BD ni LLM; `200 {"status":"ok"}`) |
| Endpoint de readiness | `GET /api/v1/ready` (verifica BD propia + Omniroute; usado por el circuit breaker del bot) |
| Confirmación de acción | `POST /api/v1/chat/confirm` (§1.9) |
| Versionado | En la ruta (`/v1`). Un cambio incompatible crea `/v2`; `/v1` se mantiene mientras haya un consumidor vivo. |

El shape base **es el del prototipo** (`prototype-review.md` §6.1) — no se inventa un contrato nuevo;
se extiende con los campos que `agent-core.md` §2.2 declaró obligatorios (`company`, `actor`, `mode`).

### 1.2 Headers de request

| Header | Obligatorio | Valor | Notas |
|---|---|---|---|
| `Content-Type` | sí | `application/json; charset=utf-8` | Rechazo `415` si no |
| `Authorization` | sí | `Bearer ${FORSIS_AGENT_TOKEN}` | Token **por canal**, no global (§1.4) |
| `X-Forsis-Channel` | sí | `widget-trafico` \| `widget-liquidaciones` \| `mattermost` | Debe coincidir con el canal ligado al token; si no → `403` |
| `X-Forsis-Trace-Id` | recomendado | UUIDv4 generado por el adaptador | Si falta, el agente lo genera y lo devuelve. Es lo que une los logs de los dos procesos (`mattermost-integration-strategy.md` §4.4) |
| `Idempotency-Key` | sí en `mode=commit`; recomendado siempre | string ≤ 128 chars | §1.8 |
| `X-Forsis-Identity` | sí en canal widget | JWT corto firmado por el sistema anfitrión | §2.4. **No** se usa en Mattermost (ahí la identidad va en el body, §3.5) |
| `Accept-Language` | no | `es-MX` por defecto | El catálogo y los prompts son en español (`agent-core.md` §5.2 punto 5) |

### 1.3 `ChatRequest` — schema JSON

```jsonc
{
  "message":        "¿cuántas guías pendientes tiene el cliente 412?",  // string, 1..4000, requerido
  "session_id":     "mm:9f3a…:zgu6…",       // string|null. null ⇒ el agente crea una y la devuelve
  "channel":        "mattermost",            // enum: widget-trafico|widget-liquidaciones|mattermost
  "company":        "FORSIS",                // enum: FORSIS|GERO. REQUERIDO, sin default (§1.6)
  "actor": {                                  // requerido — identidad resuelta por el adaptador
    "subject":      "martin01",              // id estable del usuario EN SU SISTEMA DE ORIGEN
    "subject_type": "mattermost_user",       // enum: trafico_user|liquidaciones_user|mattermost_user
    "display_name": "Martín R.",
    "roles":        ["TRAFICO_OPERACION"],   // roles tal como los reporta el sistema de origen
    "authorized":   true                      // el adaptador YA evaluó su allowlist (§1.5)
  },
  "inputs":         { "folio": "90822" },    // object|null — slots pre-rellenados por el adaptador
  "mode":           "chat",                   // enum: chat|confirm  (ver §1.9)
  "thread": {                                 // object|null — metadatos de hilo, solo informativos
    "root_id":      "p7k2…",
    "reply_count":  3
  },
  "client": {                                 // object|null — telemetría, nunca lógica
    "adapter":      "forsis-bot/1.4.0",
    "locale":       "es-MX"
  },
  "debug":          false                     // bool. Si true, se requiere rol de soporte (§1.7)
}
```

**Reglas de validación (fail-closed, `extra="forbid"` — `agent-core.md` §2.1):**

1. Cualquier campo no declarado ⇒ `422 VALIDATION_ERROR`. No se ignora silenciosamente.
2. `message` vacío o solo whitespace ⇒ `422`. `message` > 4000 chars ⇒ `413` (§3.7).
3. `company` **no tiene default**. Es la lección directa de `liquidaciones-system-analysis.md` §1 punto 4
   ("el mismo endpoint lee FORSIS o GERO según el estado de sesión… la fuente de error más peligrosa
   para un agente automatizado") y de `liquidaciones-security-strategy.md` §4 ("fijar empresa
   explícitamente; el default silencioso es `forsis`"). Si falta ⇒ `422`, nunca se asume.
4. `actor.authorized == false` ⇒ `403 FORBIDDEN` inmediato, sin planificar, sin consumir LLM.
5. `session_id` que no pertenece a `(channel, company, actor.subject)` ⇒ `403 SESSION_MISMATCH`.
   Previene el secuestro de sesión entre canales y entre empresas (`agent-core.md` §3.2, "`company`
   forma parte de la clave de sesión").

### 1.4 Autenticación

**Modelo: token de servicio por canal, bearer estático, red privada.**

| Consumidor | Token | Transporte | Red |
|---|---|---|---|
| `forsis-bot` | `${FORSIS_AGENT_TOKEN_MATTERMOST}` | HTTP plano `:8080` | red Docker dedicada `forsis-agent_net` (§3.8) |
| Proxy PHP de `trafico-system` | `${FORSIS_AGENT_TOKEN_TRAFICO}` | HTTP plano `:8080` | `forsis-comunicaciones` (`architecture.md` §2.1) |
| Proxy PHP de `liquidaciones-system` | `${FORSIS_AGENT_TOKEN_LIQUIDACIONES}` | HTTP plano `:8080` | `liquidaciones-system_default` (`liquidaciones-security-strategy.md` §4) |

Cinco decisiones explícitas:

1. **Tokens distintos por canal.** Un token filtrado se revoca sin tirar los otros dos canales, y el
   log dice de inmediato qué adaptador se comprometió. Es la mitigación directa de la lección de
   `BOT_TOKEN` (`mattermost-integration-strategy.md` §5, S1).
2. **El token autentica al *adaptador*, no al *usuario*.** La identidad del humano viaja en
   `actor` (Mattermost) o en `X-Forsis-Identity` (widget). Confundir las dos cosas es exactamente el
   error que `mattermost-integration-strategy.md` §5 S7 anticipa ("el nuevo endpoint del agente
   necesita su propia auth. Sin esto, Opción C **empeora** la postura respecto a hoy").
3. **La autorización se evalúa UNA sola vez, en el adaptador**, y el agente la respeta sin
   re-expandirla. `mattermost-integration-strategy.md` §5 es explícito: *"El agente nuevo **no** debe
   traer su propia allowlist permisiva que compense la del bot."* El agente puede ser **más**
   restrictivo (el `PlanGuard` de `agent-core.md` §4.1 paso 6 filtra por `required_permissions`),
   nunca más permisivo.
4. **Sin token ⇒ fail-closed.** `FORSIS_AGENT_TOKEN` ausente en el adaptador: el adaptador no arranca.
   Token ausente o inválido en el request: `401`, sin pistas sobre el motivo.
5. **Comparación en tiempo constante** (`hash_equals` / `secrets.compare_digest`) y token mínimo de
   32 bytes aleatorios. Rotación trimestral; soporte de **dos** tokens válidos simultáneos por canal
   (`…_TOKEN` y `…_TOKEN_NEXT`) para rotar sin ventana de caída.

**BLOQUEANTE B-C1:** el agente expone `8099:443` al host (`architecture.md` §3.1) con el mismo
`POST /api/v1/chat` que el listener interno. Un bearer estático sobre un puerto público es una
superficie innecesaria: cualquiera con acceso de red al host puede intentar fuerza bruta. Ver §5.

### 1.5 `ChatResponse` — schema JSON

```jsonc
{
  "answer":      "El cliente 412 tiene 7 guías pendientes…",  // string, SIEMPRE presente (§1.5.1)
  "session_id":  "mm:9f3a…:zgu6…",                             // string, SIEMPRE presente
  "status":      "ok",                                          // enum, §1.5.2
  "components":  [                                              // array, puede ir vacío
    { "type": "guide-card", "title": "Guía 90822",
      "fields": [ {"label":"Estatus","value":"<Por Pagar>"} ],
      "actions": [] }
  ],
  "clarification": {                                            // object|null
    "question": "¿Te refieres al cliente 412 de FORSIS o de GERO?",
    "missing":  ["company"],
    "options":  [ {"label":"FORSIS","value":"FORSIS"},
                  {"label":"GERO","value":"GERO"} ]
  },
  "confirmation": {                                             // object|null — §1.9
    "confirmation_id": "cnf_01JB…",
    "summary":         "Crear solicitud de cancelación del vale PR-00123",
    "tool":            "liq.solicitud_crear",
    "risk_class":      "L2",
    "dry_run_result":  { "valid": true, "warnings": [] },
    "expires_at":      "2026-10-05T18:42:00-06:00"
  },
  "context_updated": true,
  "updated_context": { "folio": "90822" },
  "trace": {                                                    // SIEMPRE presente (§1.5.3)
    "trace_id":        "7f1c…",
    "plan_id":         "pln_01JB…",
    "llm_model_real":  "claude-sonnet-4.5",
    "llm_attempts":    2,
    "latency_ms":      { "llm": 7310, "tools": 420, "total": 8120 },
    "tools_executed":  ["traf.guias_listar"]
  },
  "debug": null                                                  // object|null, solo si se pidió y se permite
}
```

#### 1.5.1 `answer` nunca es null

Incluso en fallo. Si el LLM está caído, `answer` trae el mensaje honesto del `TemplateComposer`
(`agent-core.md` §4.2 D-4) y `status` lo refleja. Esta es la propiedad que permite al adaptador ser
trivial: **imprime `answer`, siempre**. La alternativa (adaptador que decide qué decir ante cada
error) replica lógica de producto en dos lugares.

#### 1.5.2 Enum de `status`

| `status` | HTTP | Significado | Qué hace el adaptador |
|---|---|---|---|
| `ok` | 200 | Respuesta completa | Publica `answer` + `components` |
| `clarification_needed` | 200 | Faltan datos; `clarification` poblado | Publica la pregunta; widget muestra chips/select |
| `confirmation_required` | 200 | Dry-run OK, espera un humano (`tools-design.md` §1, L2) | Publica resumen + botones Confirmar/Cancelar |
| `no_capability` | 200 | El agente no sabe hacer eso (plan vacío — `agent-core.md` §4.1) | Publica `answer` tal cual |
| `denied` | 403 | Permisos insuficientes o L3 prohibida (`tools-design.md` §1) | Publica `answer` |
| `degraded` | 200 | Se respondió con datos reales pero formato pobre (composer LLM caído) | Publica `answer`; registra métrica |
| `error` | 4xx/5xx | Fallo; `answer` explica en lenguaje humano | Publica `answer`; **nunca** silencio |

**Decisión:** `confirmation_required` y `clarification_needed` son **200, no 4xx**. No son errores del
cliente: son estados normales de una conversación. Devolverlos como 4xx obligaría al adaptador a
tratar un flujo feliz como excepción, y `forsis-bot` ya hace `raise_for_status()`
(`mattermost-integration-strategy.md` §4.2) — un 4xx ahí se convertiría en "no hay respuesta".

#### 1.5.3 `trace` es obligatorio en la respuesta

`llm_model_real` no es telemetría opcional: `llm-provider.md` §2.4 lo declara **obligatorio** porque
el combo "Forsis" enruta cada llamada a un proveedor distinto y *"sin eso, un fallo intermitente de
formato es imposible de diagnosticar"*. Al devolverlo en el contrato (no solo en el log del agente),
el adaptador puede adjuntarlo en modo debug sin consultar al equipo del agente.

`debug` sigue siendo el objeto detallado del prototipo (plan serializado, SQL, prompts) y requiere
rol de soporte; `trace` es siempre público al adaptador y **no contiene datos de negocio**.

### 1.6 Códigos HTTP

| Código | `error_code` | Causa | ¿Reintentable por el cliente? |
|---|---|---|---|
| 200 | — | `ok`, `clarification_needed`, `confirmation_required`, `no_capability`, `degraded` | — |
| 400 | `MALFORMED_JSON` | Body no es JSON | No |
| 401 | `UNAUTHENTICATED` | Bearer ausente/inválido | No |
| 403 | `FORBIDDEN` | `actor.authorized=false`, permisos insuficientes, L3 | No |
| 403 | `CHANNEL_MISMATCH` | `X-Forsis-Channel` no corresponde al token | No |
| 403 | `SESSION_MISMATCH` | `session_id` de otro actor/empresa/canal | No |
| 409 | `IDEMPOTENCY_IN_FLIGHT` | Misma `Idempotency-Key` aún ejecutándose | Sí, con backoff (§1.8) |
| 410 | `CONFIRMATION_EXPIRED` | TTL de confirmación vencido | No — hay que repetir la petición original |
| 413 | `MESSAGE_TOO_LONG` | `message` > 4000 chars | No |
| 415 | `UNSUPPORTED_MEDIA_TYPE` | Content-Type incorrecto | No |
| 422 | `VALIDATION_ERROR` | Campo extra, `company` ausente, enum inválido | No |
| 429 | `RATE_LIMITED` | Cuota por actor o por canal excedida (§3.7) | Sí, respetar `Retry-After` |
| 500 | `INTERNAL_ERROR` | Bug del agente | Sí, una vez |
| 502 | `LLM_UNAVAILABLE` | Omniroute inalcanzable o error HTTP | **No** (§1.6.1) |
| 503 | `DEPENDENCY_UNAVAILABLE` | BD propia o sistema de negocio caído | Sí, con backoff |
| 504 | `TURN_TIMEOUT` | Turno excedió 120 s (§1.7) | No — reformular |

**Body de error** (mismo shape siempre, y **con `answer` legible**, §1.5.1):

```jsonc
{
  "answer":     "No pude consultar el modelo de lenguaje. Intenta de nuevo en un momento.",
  "session_id": "mm:9f3a…:zgu6…",
  "status":     "error",
  "error": { "code": "LLM_UNAVAILABLE",
             "message": "upstream 502 from Omniroute",
             "retryable": false,
             "details": {} },
  "trace":      { "trace_id": "7f1c…" }
}
```

#### 1.6.1 Por qué `502 LLM_UNAVAILABLE` no es reintentable

`llm-provider.md` §4.5 fija el criterio: *"Un fallo de transporte NO se reintenta … Omniroute ya hace
failover entre 19 estrategias del lado del servidor, así que si *él* devuelve un error HTTP,
reintentar desde el agente solo suma latencia a un fallo ya definitivo."* El contrato propaga ese
criterio al cliente con `retryable: false`, para que el adaptador no vuelva a intentar lo que ya se
agotó. Los reintentos internos del agente son **exclusivamente por formato de respuesta inválido**.

### 1.7 Timeouts — alineados a 60 s/llamada y 120 s/turno

Cadena completa, de dentro hacia fuera. Cada capa es estrictamente mayor que la que envuelve, con
margen explícito, para que **el timeout se dispare siempre en la capa más profunda que lo entiende**:

| # | Capa | Valor | Fuente / derivación |
|---|---|---|---|
| 1 | Capability individual (tool) | **30 s** | `CapabilityDefinition.timeout` (`agent-core.md` §4.3) |
| 2 | Llamada LLM a Omniroute (techo duro) | **60 s** | `llm-provider.md` §2.2 (máx observado 34.6 s × 1.7) |
| 3 | Techo duro de pared por llamada LLM | **60 s** vía `ThreadPoolExecutor` + `future.result()` | `llm-provider.md` §2.2: *"El timeout del cliente HTTP por sí solo no es suficiente"* — hubo un cuelgue real de >50 min |
| 4 | **Turno completo en `AgentService`** | **120 s** | `agent-core.md` §4.3. *El techo del turno manda sobre la suma de los techos por llamada.* Al vencer ⇒ `504 TURN_TIMEOUT` |
| 5 | `fastcgi_read_timeout` / FPM `request_terminate_timeout` | **125 s** | 120 s + 5 s para serializar la respuesta de error |
| 6 | `proxy_read_timeout` en nginx del agente | **130 s** | nunca debe cortar antes que la app |
| 7 | Cliente HTTP de `forsis-bot` (`requests.post(timeout=…)`) | **(5 s connect, 130 s read)** | ligeramente por encima de nginx: así el bot recibe el `504` tipado del agente en vez de un `requests.Timeout` opaco |
| 8 | Cliente HTTP del proxy PHP del anfitrión (cURL) | `CONNECTTIMEOUT=5`, `TIMEOUT=130` | idem |
| 9 | `fetch()` del widget (`AbortController`) | **135 s** | último en rendirse |
| 10 | Hint de UI del widget ("esto está tardando…") | a los **15 s** | p95 del turno es ~25 s (`agent-core.md` §4.3); avisar a los 15 s cubre la cola sin alarmar en el caso normal |

**Regla de oro:** `FORSIS_AGENT_TIMEOUT_S` en `forsis-bot` debe ser **130**, no 180.
`mattermost-integration-strategy.md` §4.2 propone `180` heredado del `subprocess` de `agy`; con el
techo de turno en 120 s ese valor solo añade 60 s de espera inútil ante un cuelgue del transporte.

### 1.8 Idempotencia

**El problema real:** el p95 del turno es ~25 s y el techo 120 s. Un usuario impaciente que repite su
mensaje, o un `forsis-bot` que se reconecta por WebSocket y reprocesa un post, puede duplicar un
turno. Si el turno solo *lee*, duplicar cuesta tokens. Si *escribe* (crear una solicitud en el
workflow de liquidaciones, `tools-design.md` §1.1), duplicar crea dos solicitudes para el revisor
humano — exactamente el "inundación del buzón del revisor" que
`liquidaciones-security-strategy.md` §0 identifica como hallazgo #5.

**Diseño:**

| Aspecto | Decisión |
|---|---|
| Header | `Idempotency-Key`, **obligatorio** cuando `mode=confirm` o la respuesta anterior fue `confirmation_required`; recomendado siempre |
| Clave del adaptador Mattermost | `mm:{post_id}` — el `post_id` de Mattermost es inmutable y único; es la clave natural y **elimina por diseño** la duplicación por reconexión del WebSocket |
| Clave del adaptador widget | `wdg:{session_id}:{client_msg_ulid}` — ULID generado en el navegador antes del envío, estable entre reintentos de red |
| Alcance de unicidad | `(channel, actor.subject, Idempotency-Key)` |
| Almacenamiento | Tabla `idempotency_keys(key, scope, request_hash, state, response_body, created_at)` en la BD propia del agente (`db-schema.md`) |
| TTL | **24 h** (misma ventana que el TTL de sesión, `agent-core.md` §3.2) |
| Reenvío con misma clave y **mismo** `request_hash`, turno terminado | **200 con la respuesta guardada, byte a byte.** No se re-ejecuta nada |
| Reenvío con misma clave, turno **en vuelo** | `409 IDEMPOTENCY_IN_FLIGHT` + `Retry-After: 5`. No se encola un segundo turno |
| Reenvío con misma clave y **distinto** `request_hash` | `422 IDEMPOTENCY_KEY_REUSED`. Señal de bug en el adaptador, no de intención del usuario |
| Sin header en un turno de solo lectura | Permitido. Se ejecuta normalmente |

`request_hash` = SHA-256 de `(message, company, actor.subject, session_id, mode, inputs)`
canonicalizados. Guardarlo es lo que distingue "reintento de red" de "clave reutilizada por error".

**Nota de honestidad:** la idempotencia del agente protege el *turno*, no la *acción de negocio
aguas abajo*. `liquidaciones-security-strategy.md` §8 ya advierte que `autorizar_liquidacion` no tiene
idempotencia más allá del check `estatus = '<Por Autorizar>'`. Como el MVP **no ejecuta L3**
(`tools-design.md` §1), el riesgo queda acotado a solicitudes duplicadas (reversibles por rechazo),
no a pagos duplicados. Cuando se amplíe a L2 con efecto directo, cada tool deberá llevar su propia
clave de idempotencia en el payload hacia el sistema dueño.

### 1.9 Flujo de confirmación (dry-run → humano → commit)

`tools-design.md` §0 regla 3: *"toda tool de clase ≥ L2 acepta `dry_run` y el planner la invoca
primero con `dry_run=true` **siempre**. El Executor rechaza (fail-closed) cualquier invocación L2/L3
que no venga precedida de un dry-run válido en la misma traza."* El contrato materializa esto en **dos
requests**, no en uno con un flag:

```
① POST /api/v1/chat          { message: "cancela el vale PR-00123", mode: "chat" }
   → 200 { status: "confirmation_required",
           confirmation: { confirmation_id: "cnf_…", summary: "…",
                           risk_class: "L2", dry_run_result: {…},
                           expires_at: "+5 min" } }
   [el agente YA ejecutó el dry-run; NO ha mutado nada]

② POST /api/v1/chat/confirm  { session_id, confirmation_id: "cnf_…", decision: "approve" }
   Headers: Idempotency-Key: mm:{post_id_del_click}
   → 200 { status: "ok", answer: "Solicitud SC-00412 creada; la revisará un SUPER USUARIO." }
```

| Regla | Valor | Por qué |
|---|---|---|
| TTL de la confirmación | **5 min** | Ventana corta: el estado del sistema de negocio cambia. `forsis-bot` ya tiene `CONFIRMACION_TTL` (`mattermost-integration-strategy.md` §2.1) — se **reutiliza su semántica**, y el TTL autoritativo es el del agente |
| Quién puede confirmar | **el mismo `actor.subject`** que originó la petición | Un tercero no aprueba por ti en un hilo público de Mattermost |
| `decision: "reject"` | cierra la confirmación, `status: ok`, sin efecto | Deja rastro en el audit log de que se ofreció y se declinó |
| Confirmación vencida | `410 CONFIRMATION_EXPIRED` | Nunca se ejecuta un commit sobre un dry-run viejo |
| Un solo `approve` por `confirmation_id` | garantizado por la fila de estado + `Idempotency-Key` | Doble clic en el widget no crea dos solicitudes |
| L3 | **nunca llega aquí** | `tools-design.md` §1: L3 no se registra como invocable; se degrada a la L2 equivalente |

### 1.10 Streaming: **NO** en el MVP

**Decisión: `POST /api/v1/chat` es request/response, sin SSE ni WebSocket.** Cinco razones, en orden
de peso:

1. **El canal Mattermost no puede consumirlo.** `forsis-bot` publica un post con la API REST v4 de
   Mattermost; un post es un objeto completo, no un flujo. Para "streamear" habría que editar el post
   N veces (`PUT /posts/{id}`), lo que multiplica las llamadas a la API de MM por token de respuesta y
   choca con los rate limits (§3.7). El resultado visible sería peor que un indicador de "escribiendo".
2. **El valor del streaming se lo come el planner.** El turno es Planner (p50 3.6 s) → Executor →
   Composer (p50 3.6 s) (`agent-core.md` §4.3). Los primeros ~4-11 s **no producen un solo token
   mostrable**: el output del Planner es un JSON interno que el usuario nunca debe ver. Streamear solo
   ahorraría latencia percibida en el último tramo, que es ya el más corto.
3. **El JSON mode al 70 % lo hace activamente peligroso.** `llm-provider.md` §3 documenta que el
   combo devuelve markdown fences, tool-calling narrado y negativas de rol. La capa 2
   (`_salvage_json`) y la capa 3 (reintento) **requieren el texto completo** para decidir. Con
   streaming habría que mostrar tokens antes de saber si la respuesta es válida — y un reintento
   obligaría a borrar lo ya mostrado al usuario. El fail-closed de la capa 4 es incompatible con
   emitir parcialmente.
4. **La caché semántica de Omniroute devuelve en 0.03 s** (`llm-provider.md` §2.2). Una fracción real
   de respuestas no tiene nada que streamear.
5. **El anfitrión es PHP-FPM detrás de nginx** (`architecture.md` §3). SSE a través de FPM exige
   desactivar buffering, ocupar un worker durante todo el turno y re-tunear timeouts en dos capas; con
   `pm` limitado a 1 GB de RAM (`architecture.md` §3.2) un puñado de conexiones SSE abiertas agota el
   pool.

**Qué se hace en su lugar** (cubre el 90 % del beneficio al 5 % del coste):

| Canal | Feedback de progreso |
|---|---|
| Mattermost | `POST /users/me/typing` (vía `mattermostdriver`) cada ~4 s mientras el HTTP está en vuelo. Es el indicador nativo del cliente MM; no cuesta posts ni ediciones |
| Widget | Estado `pensando` local (§2.6) + hint textual a los 15 s. No requiere nada del servidor |

**Cuándo reabrir la decisión:** si (a) el combo pasa a tener JSON mode fiable (≥ 95 %, V-1 de
`llm-provider.md` §3.4) **y** (b) el p95 del Composer sube por encima de ~20 s, entonces streamear
*solo la fase del Composer* vía SSE empieza a tener sentido — y solo para el widget, nunca para
Mattermost. Se añadiría como `POST /api/v1/chat?stream=true` **sin** romper `/v1`.

---

## 2. Canal C1 — Widget de chat embebido

### 2.1 Restricciones duras del entorno

| Restricción | Evidencia | Consecuencia de diseño |
|---|---|---|
| Dos apps PHP legacy, server-rendered, **sin build step** | `liquidaciones-system-analysis.md` §2: *"PHP server-rendered + DataTables (server-side) — sin SPA, sin build step"*; `trafico-system-analysis.md` §3: monolito PHP 8 sin framework | **JS vanilla, un solo `.js`, sin bundler, sin npm.** El Vue 3 + Vite del prototipo (`prototype-review.md` §6.2, 85 MB de `node_modules`) **no se reutiliza**: introduciría un build step en dos sistemas que no lo tienen |
| CSS global impredecible (DataTables, Bootstrap, estilos propios acumulados) | ambos análisis | **Shadow DOM** para aislamiento, no convenciones de prefijos |
| Autenticación **solo por cookie de sesión PHP**, sin API de tokens | `liquidaciones-system-analysis.md` §1 punto 3: *"No existe API de tokens. Cualquier integración del agente debe mantener cookie de sesión"* | La identidad se obtiene **del servidor anfitrión**, no del navegador (§2.4) |
| nginx de ambos sistemas **no publica su puerto al host** (trafico `:8091`, liquidaciones listener interno `:8081`) | `trafico-system-analysis.md` §5.4, `liquidaciones-system-analysis.md` §2 | El browser del usuario llega por la URL pública TLS; el **servidor** del anfitrión llega al agente por la red Docker |
| Multiempresa en sesión, default silencioso peligroso | `liquidaciones-security-strategy.md` §4 | `company` se lee del servidor y se **inyecta**; el widget nunca la deja elegir libremente |

### 2.2 Topología: proxy same-origin (la decisión central)

El widget **nunca llama al agente directamente**. Habla con un endpoint nuevo en su propio sistema,
que reenvía al agente por la red Docker:

```
Navegador  ──POST /api/ai/chat──▶  nginx del anfitrión  ──FPM──▶  ai_chat_proxy.php
 (widget)      same-origin,                                          │ lee $_SESSION
               cookie de sesión                                      │ firma identidad
                                                                     │ añade Bearer
                                                                     ▼
                                              forsis-ai-agent-nginx:8080/api/v1/chat
```

Qué compra esta decisión, frente a que el widget llame a `:8099` por CORS:

| Problema | Con proxy same-origin | Con llamada directa + CORS |
|---|---|---|
| CORS | **No existe.** Mismo origen | Requiere `Access-Control-Allow-Origin` + credentials + preflight en el agente |
| CSP | `connect-src 'self'` basta | Hay que añadir `https://forsispr1.ddns.net:8099` a la CSP de dos apps |
| Identidad del usuario | `$_SESSION` está disponible **en el servidor**, donde ya es confiable | Habría que exponer un token al JS del navegador (extraíble por cualquier XSS del sistema anfitrión) |
| Token del agente | Vive **solo** en el `.env` del anfitrión, nunca en el navegador | Imposible: un bearer en JS es un bearer público |
| Puerto público del agente | Se puede cerrar `8099` por completo (mitiga B-C1) | Obligatorio tenerlo abierto |
| Coste | ~60 líneas de PHP por sistema | 0 líneas de PHP, pero 4 problemas arriba |

**El proxy es la pieza que hace que un widget sea seguro en una app legacy sin API de tokens.**

### 2.3 Inyección en las páginas

Una línea por sistema, en el pie del layout compartido, **detrás de un flag**:

```php
<?php // propuesta — NO aplicada en Fase 1
if (getenv('FORSIS_AI_WIDGET_ENABLED') === 'true' && !empty($_SESSION['trafico_usuario'])): ?>
  <script src="/assets/forsis-ai-widget.js" defer
          data-endpoint="/api/ai/chat"
          data-channel="widget-trafico"></script>
<?php endif; ?>
```

| Sistema | Punto de inyección propuesto | Clave de sesión que condiciona el render | Estado |
|---|---|---|---|
| `trafico-system` | pie del layout de `app/views/` (`trafico-system-analysis.md` §3 lista `views/`) | `$_SESSION['trafico_usuario']` (`trafico-system-analysis.md` §: claves `trafico_usuario`, `trafico_login_en`) | **BLOQUEANTE B-C2**: no verifiqué que exista un único layout/footer compartido por todos los módulos |
| `liquidaciones-system` | pie común de las vistas PHP server-rendered | `$_SESSION['usuario']` (patrón del gate inline de `set_empresa.php`, `liquidaciones-security-strategy.md` §1) | **BLOQUEANTE B-C2** (idem) |

Reglas de inyección:

1. **Nunca se renderiza para una sesión anónima.** Es la misma lección que
   `liquidaciones-security-strategy.md` §1: hay 8 endpoints sin gate alguno; el widget no debe sumarse
   a esa lista.
2. **`defer` siempre.** Cero impacto en el render inicial de páginas con DataTables pesados.
3. **Un solo archivo**, servido por el anfitrión desde `/assets/` (copiado en el deploy del agente),
   no desde el dominio del agente: así `script-src 'self'` sigue bastando.
4. **El flag es de entorno, no de código.** Permite activar en `liquidaciones-system` y no en
   `trafico-system` (o por host), y apagar sin redeploy (criterio de reversión, `sprint-plan.md`).
5. **Carga en orden tolerante:** si el `.js` no carga, la página funciona exactamente como hoy. El
   widget es puramente aditivo.

### 2.4 Identidad del usuario ya logueado

**Problema:** `liquidaciones-system` usa MD5 sin salt y no tiene API de tokens
(`liquidaciones-system-analysis.md` §1 punto 3); `trafico-system` tiene RBAC propio con `roles` /
`permisos` / `roles_permisos` (`trafico-system-analysis.md` §4.2). El agente no puede ni debe
autenticar al usuario: solo puede **confiar en una afirmación firmada por el sistema anfitrión**.

**Diseño: identity assertion JWT de vida corta, emitida server-side, nunca vista por el navegador.**

`ai_chat_proxy.php` (nuevo, en el anfitrión) hace exactamente esto:

```
1. if (!isset($_SESSION[<clave del sistema>])) → 401, fin.          ← fail-closed
2. empresa  ← $_SESSION['empresa']  (liquidaciones) | CompanyContext (trafico)
   if (empresa vacía) → 409 "fija la empresa antes de usar el asistente"   ← §1.3 regla 3
3. roles    ← RBAC del sistema (trafico: roles_permisos; liquidaciones: priv con match EXACTO)
4. assertion ← JWT HS256, firmado con ${FORSIS_AGENT_IDENTITY_SECRET}, exp = now + 60s
      { iss: "trafico-system", sub: <id de usuario>, name, roles[], company,
        chan: "widget-trafico", jti: <ulid>, iat, exp }
5. authorized ← evaluación de la ALLOWLIST del anfitrión (§2.5)
6. POST interno al agente:
      Authorization:      Bearer ${FORSIS_AGENT_TOKEN_TRAFICO}
      X-Forsis-Identity:  <assertion>
      X-Forsis-Channel:   widget-trafico
      body: ChatRequest con actor{} y company poblados desde los pasos 2-5
7. devuelve el JSON del agente tal cual al navegador (pass-through, sin reinterpretar)
```

| Decisión | Valor | Motivo |
|---|---|---|
| Algoritmo | HS256, secreto compartido de 32+ bytes | Dos partes, mismo host, sin PKI que mantener. RS256 si algún día hay más emisores |
| `exp` | **60 s** | La assertion solo tiene que sobrevivir un hop intra-Docker |
| `jti` | ULID, registrado por el agente con TTL 120 s | Impide replay dentro de la ventana de validez |
| `iss` + `chan` | validados contra el token bearer | Un proxy de liquidaciones no puede emitir identidades de tráfico |
| Visibilidad en el navegador | **nunca** | El JWT se crea y se consume server-side; un XSS en el anfitrión no lo obtiene |
| Doble verificación | El agente valida firma **y** `actor.subject == jwt.sub` | Un body manipulado por el proxy (o un bug) no cambia la identidad |

**Por qué no reusar la cookie de sesión del anfitrión hacia el agente:** obligaría al agente a
entender dos esquemas de sesión PHP distintos, a tocar `$_SESSION` de otro sistema y, con MD5 sin salt
del lado de liquidaciones, a heredar su postura de seguridad. La assertion firmada **traduce** la
sesión a un contrato propio y deja la responsabilidad de autenticar donde ya está.

**Multiempresa:** `company` viaja en la assertion y en el body; el agente verifica que coincidan. Es la
defensa contra el hallazgo de `liquidaciones-system-analysis.md` §1 punto 4.

### 2.5 Allowlist del widget

`mattermost-integration-strategy.md` §5 es terminante: *"La autorización se evalúa una sola vez, en
`forsis-bot`, antes de que exista una petición HTTP."* El widget necesita el equivalente propio.

| Nivel de acción | Quién decide | Dónde |
|---|---|---|
| ¿Puede usar el agente en absoluto? | `FORSIS_AI_WIDGET_ALLOWLIST` (lista explícita de usuarios o roles) en el `.env` del anfitrión | `ai_chat_proxy.php` paso 5 |
| ¿Puede ver una capability concreta? | `Registry.list_definitions(actor)` filtrado por permisos | agente (`agent-core.md` §4.2 D-1) |
| ¿Puede ejecutarla? | `PlanGuard` | agente (`agent-core.md` §4.1 paso 6) |

Lista vacía ⇒ **nadie autorizado**, igual que `AGY_USUARIOS_AUTORIZADOS=""` en forsis-bot hoy
(`mattermost-integration-strategy.md` §2.1). Fail-closed, sin excepción, también en el canal nuevo.

> **Advertencia explícita para `liquidaciones-system`:** 77 de 95 usuarios tienen contraseña vacía y
> `priv` vacío (`liquidaciones-security-strategy.md` §0.1), lo que significa que **cualquiera puede
> obtener una sesión válida con cualquier string**. Hasta que A1+A2 de la Fase A de ese documento estén
> hechos, la allowlist del widget de liquidaciones debe ser una **lista nominal de usuarios con `priv`
> no vacío**, jamás "cualquier sesión autenticada". Ver BLOQUEANTE B-C3.

### 2.6 Componente JS: estructura y aislamiento

```
assets/forsis-ai-widget.js     ← un archivo, ~700-900 líneas, IIFE, sin dependencias
  ├── boot()                   lee data-* del <script>, crea el host, engancha el FAB
  ├── ShadowRoot               mode:'open'; TODO el CSS vive aquí, en un <style> inline
  ├── Transport                fetch() + AbortController + mapeo de status/error (§1.5.2)
  ├── Store                    { session_id, turns[], uiState, pendingConfirmation }
  ├── Render                   lista de turnos, burbujas, chips de clarificación,
  │                            tarjetas de `components`, panel de confirmación
  └── Persist                  sessionStorage: solo { session_id, ui.open }
```

**Aislamiento CSS — Shadow DOM, no prefijos:**

```js
const host = document.createElement('div');
host.id = 'forsis-ai-widget-host';
host.style.cssText = 'all:initial;position:fixed;z-index:2147483000;bottom:0;right:0;';
const root = host.attachShadow({ mode: 'open' });
root.innerHTML = `<style>${CSS}</style><div class="fab">…</div><div class="panel" hidden>…</div>`;
document.body.appendChild(host);
```

| Técnica | Qué resuelve |
|---|---|
| `attachShadow` | El CSS global de DataTables/Bootstrap **no entra**; el del widget **no sale**. Es la única garantía real en una app legacy |
| `all:initial` en el host | Neutraliza herencia de `font`, `color`, `line-height`, `box-sizing` del anfitrión |
| `z-index: 2147483000` | Por debajo del máximo, por encima de modales típicos de Bootstrap/DataTables |
| CSS **inline** en el `<style>` del shadow root | Un solo archivo, cero requests extra, cero dependencia de `style-src` externo |
| Sin web fonts | `font-family: system-ui, -apple-system, sans-serif`. Evita tocar `font-src` en la CSS |
| `prefers-reduced-motion` respetado | Accesibilidad básica, coste cero |

**Compatibilidad:** Shadow DOM v1 y `fetch` están disponibles en todo navegador evergreen.
**BLOQUEANTE B-C4:** no se verificó qué navegadores usan los 36 usuarios (si hay IE11 o un kiosco
antiguo, el widget no carga — degradaría a no mostrarse, que es el fallo aceptable, pero hay que
saberlo).

**Accesibilidad mínima:** `role="dialog"` + `aria-live="polite"` en la lista de mensajes (los estados
"pensando"/"listo" se anuncian), foco atrapado en el panel abierto, `Esc` cierra, el FAB es un
`<button>` real con `aria-label`.

### 2.7 CORS y CSP

**CORS: no aplica.** El widget hace `fetch('/api/ai/chat')` — mismo origen, cookie enviada por
defecto. No hay preflight, no hay `Access-Control-*`. Si en algún momento se abandona el proxy, habría
que: `Access-Control-Allow-Origin` con lista explícita (**nunca `*`** — es precisamente el hallazgo S6
de `mattermost-integration-strategy.md` §5 sobre `AllowCorsFrom=*` en Mattermost),
`Allow-Credentials: true`, y `Vary: Origin`. Se evita por completo.

**CSP del anfitrión** — el widget está diseñado para no exigir relajaciones:

| Directiva | Requisito del widget | Nota |
|---|---|---|
| `script-src` | `'self'` | El `.js` se sirve desde `/assets/` del anfitrión. **Sin `unsafe-inline`, sin `unsafe-eval`** |
| `connect-src` | `'self'` | Solo `/api/ai/chat` |
| `style-src` | `'self'` | El `<style>` vive **dentro** del Shadow DOM, que no está gobernado por `style-src` de la página. Si alguna implementación lo exigiera, se usa un nonce, no `unsafe-inline` |
| `img-src` | `'self' data:` | Iconos como SVG inline/`data:`. Sin CDN |
| `font-src` | sin cambios | Sin web fonts |
| `frame-src` | sin cambios | **El widget no es un iframe** (ver abajo) |

**Por qué no un iframe:** un iframe aislaría el CSS igual de bien, pero (a) necesitaría
`frame-src`/`frame-ancestors` en dos CSP, (b) rompería el z-index y el redimensionado fluido,
(c) obligaría a `postMessage` para cualquier interacción con la página, y (d) no aporta nada frente al
Shadow DOM, porque el JS ya es nuestro y el token nunca está en el navegador.

**Cabeceras de respuesta del proxy:** `Cache-Control: no-store`, `X-Content-Type-Options: nosniff`.
**BLOQUEANTE B-C5:** no se verificó si `trafico-system` o `liquidaciones-system` envían hoy alguna
cabecera CSP. Si no envían ninguna, el widget funciona igual; si envían una restrictiva, hay que
auditarla antes del Sprint 5.

### 2.8 Representación de estados en la UI

El widget tiene **exactamente** un estado visual por `status` del contrato (§1.5.2), más dos estados
puramente locales. Esta correspondencia 1:1 es deliberada: evita que el widget "interprete"
respuestas.

| Estado UI | Origen | Representación | Interacción |
|---|---|---|---|
| **pensando** | local, desde el envío hasta la respuesta | Burbuja del agente con tres puntos animados + `aria-live` "El asistente está pensando". A los **15 s** el texto cambia a *"Sigo trabajando en esto…"*; a los **60 s**, *"Está tardando más de lo normal."* | Botón **Cancelar** → `AbortController.abort()`. Cancelar aborta la *espera*, no el turno del servidor; se avisa: *"Dejé de esperar. Si la acción ya se había enviado, puede completarse."* Honestidad, no ficción de cancelación |
| **respuesta** (`ok`) | `status: ok` | Burbuja con `answer` (markdown mínimo: `**`, `` ` ``, listas, saltos — **sin HTML crudo**, todo escapado) + tarjetas de `components` | Copiar al portapapeles |
| **aclaración** (`clarification_needed`) | `clarification` | Pregunta + chips de `options` (botones). Si `options` está vacío, campo de texto normal | Click en chip ⇒ nuevo `POST` con `inputs` poblado. El chip evita que el usuario teclee "FORSIS" mal |
| **dry-run** | `confirmation.dry_run_result` dentro de `confirmation_required` | Bloque con fondo neutro, encabezado **"Simulación — no se ha hecho ningún cambio"**, tabla de campos del `dry_run_result`, `warnings[]` en ámbar | Solo lectura. Es informativo y debe *leerse* como informativo |
| **confirmación requerida** (`confirmation_required`) | `confirmation` | Panel con borde de acento, `summary` en negrita, badge de `risk_class` (`L2`), cuenta atrás visible hasta `expires_at`, botones **Confirmar** (primario) y **Cancelar** (secundario). El input de texto se **deshabilita** mientras hay confirmación pendiente | Confirmar ⇒ `POST /chat/confirm` con `decision:"approve"` e `Idempotency-Key` fijada **al montar el panel** (no al hacer clic): doble clic = una sola solicitud. Al expirar, los botones se deshabilitan y aparece *"La confirmación venció. Vuelve a pedirlo."* |
| **denegado** (`denied`) | 403 | Burbuja con icono de candado y `answer` | Sin reintento. No se sugiere "pide permisos a TI" salvo que el `answer` lo diga |
| **sin capacidad** (`no_capability`) | `status: no_capability` | Burbuja neutra con `answer` | Ofrece *"ver qué puedo hacer"* → lista las capabilities visibles para ese actor |
| **degradado** (`degraded`) | `status: degraded` | Respuesta normal + nota al pie discreta: *"Respuesta con formato simplificado."* | Ninguna. Los **datos son correctos**; solo la redacción es pobre (`agent-core.md` §4.2 D-4) |
| **error** (`error`) | 4xx/5xx o fallo de red | Burbuja con borde rojo + `answer` + `trace_id` en texto pequeño seleccionable | **Reintentar** solo si `error.retryable == true`. Con `LLM_UNAVAILABLE` (§1.6.1) **no** se ofrece reintentar: ofrecer un botón que se sabe inútil es peor que no ofrecerlo |

Dos reglas transversales:

- **El widget nunca inventa texto de estado.** Todo lo que el usuario lee sobre el resultado viene de
  `answer`. Lo único que el widget redacta son los estados *locales* (pensando, cancelado, sin red).
- **`trace_id` siempre visible en errores.** Es lo que convierte "el bot falló" en un ticket
  diagnosticable, dado que el modelo que respondió varía por llamada (`llm-provider.md` §2.4).

---

## 3. Canal C2 — Mattermost vía `forsis-bot`

### 3.1 Punto de partida verificado

De `mattermost-integration-strategy.md` §2 y `mattermost-analysis.md` (evidencia de servidor, no de
documentación):

| Aspecto | Valor |
|---|---|
| Instancia | Mattermost **Team Edition v11.6.0**, contenedor `forsis-chat`, `https://chatforsis.ddns.net`, host `:25080` → 8065 |
| BD | PostgreSQL 15, contenedor `forsis-chat-db` |
| Equipos | 5; principal **Forsis PR** (`pc64qx8…`, **36 miembros**, 14 canales) |
| Bot | `forsisbot` (usuario `zgu6x8p5mjdaxdj5qdbynqak4w`), `system_user + system_post_all` |
| Gateway | `forsis-bot`, 12 módulos Python, 2 702 LOC, `mattermostdriver`, WebSocket con auto-reconexión (`main.py:1020-1077`) |
| Red | `ai-network` (172.26.0.2) — **única red**; no comparte red con ningún sistema de negocio |
| Delegación actual | `subprocess.run(["agy","--print",…,"--dangerously-skip-permissions",…])` en `actions.py:225-267` |
| Allowlist | `AGY_USUARIOS_AUTORIZADOS=""` ⇒ **nadie autorizado** (fail-closed) |
| `EnableBotAccountCreation` | **false** ⇒ crear otro bot exige token de admin |
| `EnableUserAccessTokens` | **false** ⇒ no hay tokens de usuario; el bot token es la única credencial |
| 🔴 Seguridad | **`BOT_TOKEN` commiteado** en `forsis-bot/docker-compose.yml` (commit `ee300fa`), con `system_post_all` sobre los 36 canales. **Prioridad #1** |

Las dos restricciones de Mattermost (`EnableBotAccountCreation=false`,
`EnableUserAccessTokens=false`) **confirman** la Opción C: no se puede crear un segundo bot sin
intervención de admin, así que reutilizar `forsisbot` como único gateway no es solo preferible, es lo
practicable.

### 3.2 Flujo de un mensaje entrante

```
① Usuario escribe en #Trafico-Operación: "@forsisbot ¿qué guías pendientes tiene el cliente 412?"
         │
② Mattermost → evento WebSocket `posted` → forsis-bot (main.py:1020, while True: ws.recv())
         │
③ dedup: post_id ∈ posts_procesados (cap 1048)?  → sí: descartar        [ya existe]
④ bot_mencionado() (main.py:314): ¿mención o DM? → no: salir            [ya existe]
⑤ Thread(target=procesar_post) (main.py:1048)                           [ya existe]
         │
⑥ procesar_post() (main.py:352):
     ├─ usuarios_autorizados_agy() (actions.py:213) → NO: responder "no autorizado", FIN
     │        ← ÚNICO punto de autorización. Fail-closed. No se duplica en el agente
     ├─ obtener_historial_canal() (main.py:126) → contexto conversacional   [ya existe]
     └─ resolver identidad y empresa (§3.5) → actor{}, company
         │
⑦ ejecutar_agente()  ← REEMPLAZA ejecutar_agy()   [EL ÚNICO CAMBIO REAL, §3.4]
     ├─ POST http://forsis-ai-agent-nginx:8080/api/v1/chat
     │     Authorization: Bearer ${FORSIS_AGENT_TOKEN_MATTERMOST}
     │     X-Forsis-Channel: mattermost
     │     X-Forsis-Trace-Id: <uuid4>
     │     Idempotency-Key: mm:{post_id}          ← §1.8, mata la duplicación por reconexión
     │     body: ChatRequest{ message, session_id, company, actor, thread, mode:"chat" }
     ├─ mientras está en vuelo: POST /users/me/typing cada 4 s  (§1.10)
     └─ timeout (5, 130)  → §1.7
         │
⑧ El agente: AgentService → Planner → PlanGuard → Executor → Composer
   (agent-core.md §4.1; el bot no sabe nada de esto, y eso es el objetivo)
         │
⑨ ChatResponse → el bot despacha por `status`:
     ok / degraded / no_capability → post con `answer` (+ attachments de `components`)
     clarification_needed          → post con la pregunta; `session_id` guardado para el siguiente turno
     confirmation_required         → post con `summary` + **acciones interactivas** (§3.6)
     denied                        → post con `answer`
     error / timeout / excepción   → post honesto: "No pude procesar eso (ref 7f1c…)". NUNCA silencio
         │
⑩ create_post(channel_id, message, root_id=<hilo>) → chunking si procede (§3.7)
⑪ registrar_actividad_operativa() (main.py:153) → pgvector                [ya existe]
```

Lo esencial del diagrama: **de los 11 pasos, 9 ya existen y funcionan**. Solo ⑦ cambia, y ⑨ se
enriquece. Eso es lo que `mattermost-integration-strategy.md` §4.2 quiere decir con "~30 líneas".

### 3.3 Reparto de responsabilidades

| Responsabilidad | `forsis-bot` | Agente |
|---|---|---|
| WebSocket, reconexión, dedup de posts | ✅ | ❌ |
| Detección de mención / DM | ✅ | ❌ |
| **Autorización del usuario (allowlist)** | ✅ **única fuente** | ❌ (solo restringe más, §1.4 punto 3) |
| Mapeo usuario MM → `actor` + `company` | ✅ | ❌ |
| Construcción de `session_id` | ✅ (fórmula de §3.5) | valida que corresponda al actor |
| Hilos, chunking, typing, rate limits | ✅ | ❌ |
| Memoria conversacional de chat (pgvector) | ✅ | ❌ (frontera explícita, `mattermost-integration-strategy.md` §4.5) |
| Planner / Executor / tools / dry-run / audit | ❌ | ✅ |
| Memoria de sesión del agente (Postgres) | ❌ | ✅ |
| Redacción de la respuesta | ❌ | ✅ |

### 3.4 Qué cambia en `actions.py` (propuesta — no aplicada)

**Un archivo, una función.** Partiendo del esqueleto de `mattermost-integration-strategy.md` §4.2, con
las correcciones que exige el contrato de §1:

```python
# forsis-bot/app/actions.py  —  PROPUESTA, no aplicada en Fase 1
AGENT_URL        = os.getenv("FORSIS_AGENT_URL", "http://forsis-ai-agent-nginx:8080")
AGENT_TOKEN      = os.getenv("FORSIS_AGENT_TOKEN")             # fail-closed si falta
AGENT_TIMEOUT_S  = int(os.getenv("FORSIS_AGENT_TIMEOUT_S", "130"))   # §1.7, NO 180
DELEGATE         = os.getenv("DELEGATE_TO_AGENT", "false").lower() == "true"  # feature flag

class AgentReply(NamedTuple):
    ok: bool; answer: str; session_id: str | None
    status: str; components: list; confirmation: dict | None; trace_id: str | None

def ejecutar_agente(mensaje, *, actor, company, session_id=None,
                    post_id=None, root_id=None, mode="chat") -> AgentReply:
    """Delega al Forsis AI Agent. Sustituye el subprocess a `agy`."""
    if not AGENT_TOKEN:
        return AgentReply(False, "El asistente no está configurado.", session_id,
                          "error", [], None, None)
    trace_id = str(uuid.uuid4())
    try:
        r = requests.post(
            f"{AGENT_URL}/api/v1/chat",
            json={"message": mensaje, "session_id": session_id, "channel": "mattermost",
                  "company": company, "actor": actor, "mode": mode,
                  "thread": {"root_id": root_id}, "debug": False},
            headers={"Authorization": f"Bearer {AGENT_TOKEN}",
                     "X-Forsis-Channel": "mattermost",
                     "X-Forsis-Trace-Id": trace_id,
                     "Idempotency-Key": f"mm:{post_id}" if post_id else None},
            timeout=(5, AGENT_TIMEOUT_S),
        )
        data = r.json()                      # el agente SIEMPRE devuelve JSON con `answer` (§1.5.1)
        return AgentReply(r.status_code < 400, data.get("answer", ""),
                          data.get("session_id"), data.get("status", "error"),
                          data.get("components", []), data.get("confirmation"),
                          (data.get("trace") or {}).get("trace_id", trace_id))
    except requests.Timeout:
        return AgentReply(False, "El asistente tardó demasiado. Intenta de nuevo.",
                          session_id, "error", [], None, trace_id)
    except Exception as e:
        log.error("agent error trace=%s: %s", trace_id, e)
        return AgentReply(False, f"No pude procesar eso (ref {trace_id[:8]}).",
                          session_id, "error", [], None, trace_id)
```

Correcciones deliberadas respecto al esbozo de Fase 0:

| # | Esbozo de `mattermost-integration-strategy.md` §4.2 | Aquí | Por qué |
|---|---|---|---|
| 1 | `timeout_seg / 1000 if timeout_seg else …` | eliminado | Ese cálculo es un bug: mezcla ms y s. El techo viene del contrato (§1.7) |
| 2 | `timeout=180` | `(5, 130)` | 130 = techo de turno 120 s + margen (§1.7). 180 solo añade espera inútil |
| 3 | `r.raise_for_status()` | eliminado | Mata el body del error, que **sí** trae un `answer` legible (§1.5.1 y §1.6). Perder eso convierte un error honesto en silencio |
| 4 | `return None, …` en el `except` | `AgentReply` con `answer` humano | `mattermost-integration-strategy.md` §4.4: *"si el agente devuelve 5xx, el bot responde con un mensaje honesto, no con silencio"* |
| 5 | tupla de 3 | `NamedTuple` de 7 | Añade `status`, `confirmation`, `trace_id`, sin los cuales ⑨ no puede despachar |
| 6 | sin `company` / `actor` | obligatorios | `agent-core.md` §2.2; `company` sin default (§1.3 regla 3) |
| 7 | sin idempotencia | `Idempotency-Key: mm:{post_id}` | §1.8: anula la duplicación por reconexión del WebSocket |
| 8 | sin feature flag | `DELEGATE_TO_AGENT` | `mattermost-integration-strategy.md` §6: con `false` el bot se comporta **exactamente** como hoy |
| 9 | nombre `ejecutar_agy` conservado | `ejecutar_agente` | §4.2 del mismo documento: *"Mantener el nombre viejo es una deuda que cobra intereses en tres meses"* |

Call sites a adaptar: `main.py:429` y `main.py:442` (hoy `respuesta_agy[:900]`), que pasan a despachar
por `status` y a usar el chunking de §3.7 en vez del truncado a 900 chars.

**Circuit breaker (añadido):** tras 5 fallos consecutivos de transporte, el bot deja de llamar al
agente durante 60 s y responde *"El asistente está temporalmente fuera de servicio."* Evita que una
caída del agente convierta cada mención en 130 s de espera. Es la mitigación del "punto de fallo
único" de `mattermost-integration-strategy.md` §4.4.

### 3.5 Mapeo usuario Mattermost → identidad del agente

**El problema:** `martin01` en Mattermost y `martin01` en `trafico-system` **no son la misma cuenta por
construcción**, aunque se parezcan. `mattermost-analysis.md` lista usuarios MM con nombres como
`qegzf8n3hpbd9g84bco7gwzdph` (IDs, no personas), `Vigilancia` (un puesto, no un individuo) y usuarios
de tres empresas distintas. Deducir la identidad de negocio del username de MM sería **adivinar**.

**Diseño: tabla de mapeo explícita, administrada, fail-closed.**

```
channel_identity_map
  channel            'mattermost'
  external_id        <mattermost user_id, p.ej. 'zgu6x8p5mjdaxdj5qdbynqak4w'>   ← ID, NO username
  subject            <id de usuario en el sistema de negocio>
  subject_type       'trafico_user' | 'liquidaciones_user'
  company            'FORSIS' | 'GERO'
  roles              [..]      (snapshot informativo; la verdad vive en el sistema dueño)
  enabled            bool
  created_by, created_at, revoked_at
  UNIQUE (channel, external_id)
```

| Regla | Valor | Motivo |
|---|---|---|
| Clave externa | **`user_id` de Mattermost**, no `username` | Los usernames se renombran; los IDs no. Un rename no debe transferir identidad de negocio a otra persona |
| Sin fila ⇒ | **denegado**, con mensaje accionable: *"No tengo tu identidad registrada. Pide a TI que te dé de alta en el asistente."* | Fail-closed. Es la misma semántica que `AGY_USUARIOS_AUTORIZADOS=""` |
| Varias empresas por persona | fila por empresa + `company` **explícita en cada turno**; si hay ambigüedad, el agente responde `clarification_needed` pidiendo empresa | `liquidaciones-security-strategy.md` §4: fijar empresa explícitamente, nunca default silencioso |
| Cuentas no-humanas (`Vigilancia`, bots, IDs crudos) | **nunca** se mapean | Una caseta compartida no es un actor auditable |
| Alta/baja | manual por TI (tabla en la BD del agente) | 36 usuarios: el coste de un alta manual es trivial frente al riesgo de un mapeo automático equivocado |
| Relación con la allowlist | **ortogonal**: `AGY_USUARIOS_AUTORIZADOS` dice *quién puede hablarle al bot*; el mapeo dice *como quién actúa*. Hay que pasar **ambos** | Dos preguntas distintas; colapsarlas es como confundir autenticación con autorización |
| Permisos efectivos | los del `subject` en su sistema dueño, no los de MM | Mattermost no sabe nada de RBAC de tráfico. Ser admin de MM no da permisos de negocio |

**`session_id` (cierra la dependencia que `agent-core.md` §7 pide a este documento):**

| Canal | Fórmula | Granularidad resultante |
|---|---|---|
| Mattermost, en hilo | `mm:{root_id}:{mm_user_id}:{company}` | Una sesión por hilo y por persona |
| Mattermost, canal sin hilo | `mm:{channel_id}:{mm_user_id}:{company}` | Una sesión por canal y por persona |
| Mattermost, DM | `mm:{channel_id}:{mm_user_id}:{company}` | El DM ya es privado |
| Widget | `wdg:{sistema}:{subject}:{company}:{tab_ulid}` | Una sesión por pestaña |

Cumple `agent-core.md` §3.2: *"Una sesión por hilo de Mattermost / pestaña del widget; nunca global
por usuario"*, y `company` forma parte de la clave, así que **una sesión jamás mezcla FORSIS y GERO**.
Incluir `mm_user_id` evita que dos personas en el mismo hilo público compartan contexto resuelto
("esa guía" de A no se le aplica a B).

### 3.6 Hilos, respuestas y acciones interactivas

| Caso | Comportamiento |
|---|---|
| Mención en un canal | Responder **en hilo** (`root_id = post.id`). No contamina el canal; 36 miembros lo agradecen |
| Mención dentro de un hilo | Responder en el mismo hilo (`root_id = post.root_id`) |
| DM | Responder en el DM, sin hilo |
| Continuidad | `session_id` derivado de `root_id` (§3.5) ⇒ el hilo **es** la conversación. Es la ganancia concreta sobre hoy, donde *"cada tarea es un `agy --print` aislado y sin memoria"* (`mattermost-integration-strategy.md` §4.3) |
| Hilo inactivo > 24 h | Sesión expirada (`agent-core.md` §3.2). El bot avisa: *"Empiezo de nuevo; el hilo estaba inactivo."* en vez de resolver "esa guía" a algo de la semana pasada |

**Confirmaciones (`status: confirmation_required`):** el post lleva un *message attachment* con
`actions` (botones nativos de MM). La `integration.url` apunta a un endpoint del **bot** (no del
agente), que al recibir el click:

1. verifica que `user_id` del click == `actor.external_id` que originó la petición (§1.9),
2. llama a `POST /api/v1/chat/confirm` con `Idempotency-Key: mm:{action_post_id}`,
3. **edita** el post original (`PUT /posts/{id}`) para quitar los botones y mostrar el resultado.

Editar en vez de postear evita que un botón quede clickable después de resuelto. `forsis-bot` ya tiene
la maquinaria de confirmación con TTL (`acciones_pendientes` + `CONFIRMACION_TTL`,
`main.py:897`); se **reutiliza su semántica** y el TTL autoritativo pasa a ser el del agente (5 min).

**BLOQUEANTE B-C6:** los *interactive message buttons* requieren que el bot exponga un endpoint HTTP
alcanzable por el servidor de Mattermost. `forsis-bot` vive en `ai-network` y hoy **no expone ningún
puerto**; `forsis-chat` está en otra red. No verifiqué si hay ruta de red entre ambos. Si no la hay, el
fallback del MVP es **confirmación textual** (*"responde `sí` para confirmar"*), que la maquinaria
existente del bot ya soporta y que no requiere red nueva. Decidir en Sprint 6.

### 3.7 Mensajes largos y rate limits

**Mensajes largos.** Hoy el bot hace `respuesta_agy[:900]` (`main.py:442`) — truncado silencioso, que
es la peor opción: el usuario no sabe que falta información.

| Regla | Valor | Motivo |
|---|---|---|
| Límite de post en MM | 16 383 caracteres (default de `MaxPostSize`) | **BLOQUEANTE B-C7**: no verifiqué el valor real en esta instancia; el diseño debe leerlo de `GET /api/v4/config/client` al arrancar, no hardcodearlo |
| Umbral de chunking del bot | **3 500 chars** por post | Muy por debajo del límite; legible en móvil; deja margen para attachments |
| Partición | por párrafos/líneas (nunca a mitad de palabra ni dentro de un bloque ``` ```), máximo **4 posts** en el mismo hilo, numerados `(1/3)` | Legible y acotado |
| Si excede 4 posts | primer post con resumen + **archivo adjunto** `.md`/`.csv` vía `POST /api/v4/files` | Un listado de 200 guías es un archivo, no un chat |
| Tablas | `components` → *message attachment* con `fields`, no ASCII art | Se ve bien en móvil; el ASCII se rompe |
| Truncado | **prohibido sin aviso.** Si se recorta, el post lo dice y ofrece el adjunto | El usuario debe poder confiar en que lo que ve está completo |

**Rate limits.**

| Límite | Dónde | Valor propuesto |
|---|---|---|
| API de Mattermost | servidor MM (`RateLimitSettings`) | **BLOQUEANTE B-C8**: no verificado si está habilitado ni con qué cuota. El bot debe manejar `429` con `Retry-After` + backoff exponencial, y **jamás** reintentar en bucle cerrado |
| Posts del bot por canal | bot | ≤ 1 post/s por canal; cola FIFO por canal. `system_post_all` sobre 36 canales es mucha superficie de broadcast (`mattermost-integration-strategy.md` §5 S1) — autolimitarse es prudencia, no cortesía |
| Turnos del agente por actor | agente | 20/hora, 5/min ⇒ `429 RATE_LIMITED` + `Retry-After`. Protege el presupuesto de tokens del combo, que es real y compartido (`llm-provider.md` §2.3: ~4 000 tokens inyectados por llamada) |
| Turnos concurrentes por actor | agente | **1**. Un segundo mensaje mientras el primero está en vuelo ⇒ `409 IDEMPOTENCY_IN_FLIGHT` si es el mismo post, o se encola si es nuevo |
| Concurrencia global del agente | agente | ≤ 4 turnos simultáneos (límite de `php: cpus 1.5 / 1 GB`, `architecture.md` §3.2). Excedente ⇒ `429` |
| `typing` | bot | 1 cada 4 s, cancelado al responder |

### 3.8 La red Docker que falta unir

Estado verificado (`mattermost-integration-strategy.md` §2.3):

```
forsis-bot         → ai-network (172.26.0.2)                                   ← única red
forsis-memory      → ai-network (172.26.0.3)
forsis-chat        → chat_forsis-chat-net
trafico-php        → forsis-comunicaciones, trafico-system_default
liquidaciones-php  → liquidaciones-system_default
atlas-php          → forsis-comunicaciones, tablero-guias_default
```

**`forsis-bot` no comparte red con el agente ni con ningún sistema de negocio.** Hoy no importa porque
`agy` corre dentro del contenedor del bot (hereda el filesystem, no la red). En cuanto el agente sea
un servicio HTTP, **sin red común no hay integración posible**.

**Propuesta: red dedicada `forsis-agent_net`, con exactamente dos miembros.**

```yaml
# docker-compose.yml del AGENTE (nuevo)
networks:
  forsis-agent_net:          # nueva, dedicada
    name: forsis-agent_net
  ai-network:        { external: true }   # solo para forsis-memory (pgvector)
  forsis-comunicaciones: { external: true }   # trafico-system
  liquidaciones-system_default: { external: true }   # liquidaciones-system

services:
  nginx:
    networks: [default, forsis-agent_net]        # :8080 interno visible al bot
  php:
    networks: [default, ai-network, forsis-comunicaciones, liquidaciones-system_default]
  db:
    networks: [default]                          # ← aislada, sin `ports:` (architecture.md §3.3)

# docker-compose.yml de FORSIS-BOT (cambio propuesto: 2 líneas)
networks:
  ai-network:        { external: true }
  forsis-agent_net:  { external: true }          # ← AÑADIR
services:
  forsis-bot:
    networks: [ai-network, forsis-agent_net]     # ← AÑADIR
```

| Decisión | Motivo |
|---|---|
| Red **nueva dedicada**, no reutilizar `ai-network` | `mattermost-integration-strategy.md` §2.3: *"`ai-network` es una red externa compartida con `onlyoffice`. Cualquier servicio que se una a ella gana alcance de red sobre los demás miembros. Recomendación: crear una red dedicada `forsis-agent_net`"* |
| El bot se une **solo** a `forsis-agent_net`, no a las redes de negocio | El bot no debe poder hablar con `trafico-php` ni con `liquidaciones-php`. Toda escritura pasa por el agente, donde está el `PlanGuard` |
| El bot ve **`nginx:8080`**, no `php:9000` | El agente se consume solo por HTTP; FastCGI no se expone |
| `forsis-ai-agent-db` sigue solo en `default` | `architecture.md` §3.3: cero exposición externa. Unir el bot a `forsis-agent_net` **no** le da acceso a la BD del agente |
| El agente **no** se une a `chat_forsis-chat-net` | El agente nunca habla con Mattermost directamente. Toda la superficie de MM queda en el bot — que es el punto de la Opción C |

**Lo que NO se hace y conviene decir en voz alta:** no se unen `forsis-bot` y `forsis-chat` por red
Docker. El bot ya alcanza Mattermost por su URL pública (`https://chatforsis.ddns.net`) y eso funciona
desde 23 h+ en producción. Cambiarlo no aporta nada y rompería la reconexión probada.

---

## 4. Diagrama de flujo de ambos canales

```
╔══════════════════════════════════════════════════════════════════════════════════════╗
║  CANAL 1 — WIDGET EMBEBIDO                     CANAL 2 — MATTERMOST                  ║
╚══════════════════════════════════════════════════════════════════════════════════════╝

  Navegador del usuario                           Cliente Mattermost (web/móvil)
  (ya logueado en trafico/liquidaciones)          (usuario del equipo Forsis PR, 36 miem.)
          │                                                 │
          │ clic en el FAB, escribe                         │ "@forsisbot ¿…?"  (canal o DM)
          ▼                                                 ▼
  ┌───────────────────────────────┐              ┌──────────────────────────────────────┐
  │ forsis-ai-widget.js           │              │ forsis-chat (MM TE v11.6.0)          │
  │  · IIFE, sin build step       │              │  chatforsis.ddns.net · host :25080   │
  │  · Shadow DOM (CSS aislado)   │              └──────────────┬───────────────────────┘
  │  · fetch same-origin          │                             │ WebSocket  evento `posted`
  │  · estados: pensando/dry-run/ │                             ▼
  │    confirmación/error         │              ┌──────────────────────────────────────┐
  └──────────────┬────────────────┘              │ forsis-bot  (Python, mattermostdriver)│
                 │ POST /api/ai/chat             │  red: ai-network + forsis-agent_net ★ │
                 │ (cookie de sesión PHP)        │  ③ dedup post_id    [existe]          │
                 ▼                               │  ④ bot_mencionado() [existe]          │
  ┌───────────────────────────────┐              │  ⑥ ALLOWLIST ← único punto de autoriz.│
  │ nginx del anfitrión  :443     │              │     fail-closed, NO se duplica        │
  │ (trafico :8091 / liq :8081,   │              │  ⑥ mapeo MM user_id → actor + company │
  │  no publicados al host)       │              │  ⑦ ejecutar_agente()  ← ÚNICO CAMBIO  │
  └──────────────┬────────────────┘              │     (sustituye subprocess a `agy`)    │
                 │ FastCGI :9000                 │     + typing cada 4 s                 │
                 ▼                               │     + Idempotency-Key: mm:{post_id}   │
  ┌───────────────────────────────┐              │     + circuit breaker 5 fallos/60 s   │
  │ ai_chat_proxy.php  (NUEVO)    │              └──────────────┬───────────────────────┘
  │  1. $_SESSION  → 401 si no    │                             │
  │  2. company    → 409 si vacía │                             │
  │  3. roles del RBAC            │                             │
  │  4. JWT identity, exp 60 s    │                             │
  │  5. ALLOWLIST del anfitrión   │                             │
  │  6. + Bearer del canal        │                             │
  └──────────────┬────────────────┘                             │
                 │                                              │
   HTTP interno  │  Authorization: Bearer ${…_TRAFICO}           │  Authorization: Bearer ${…_MATTERMOST}
   red Docker    │  X-Forsis-Identity: <JWT>                     │  X-Forsis-Channel: mattermost
                 │  X-Forsis-Channel: widget-trafico             │  Idempotency-Key: mm:{post_id}
                 │  X-Forsis-Trace-Id: <uuid>                    │  X-Forsis-Trace-Id: <uuid>
                 │                                              │
                 └──────────────────┬───────────────────────────┘
                                    ▼
            ╔═══════════════════════════════════════════════════════════╗
            ║         POST /api/v1/chat        (contrato único)          ║
            ║  forsis-ai-agent-nginx  :8080 interno / :8099 TLS host     ║
            ╚═══════════════════════════┬═══════════════════════════════╝
                                        ▼
            ┌───────────────────────────────────────────────────────────┐
            │ forsis-ai-agent-php   (agent-core.md §4.1)                │
            │  valida contrato (extra=forbid, company obligatoria)      │
            │  SessionStore.get(session_id)  → Postgres propio          │
            │  IntentRouter determinista (smalltalk sin LLM)            │
            │  Planner ──► OmnirouteProvider :20130  combo "Forsis"     │
            │              60 s/llamada · 3 intentos · salvage JSON     │
            │  PlanGuard   permisos + dry-run forzado + gate humano     │
            │  Executor    lecturas → DB read-only                      │
            │              escrituras → API REST del sistema dueño      │
            │  Composer    LLM, con fallback a plantilla determinista   │
            │  AuditLog + SessionStore.save   (techo de turno: 120 s)   │
            └───────────────────────────────┬───────────────────────────┘
                                            ▼
                      ChatResponse { answer, session_id, status,
                                     components[], clarification?,
                                     confirmation?, trace{} }
                                            │
            ┌───────────────────────────────┴───────────────────────────┐
            ▼                                                           ▼
  Widget: render por `status`                        Bot: despacho por `status`
   ok/degraded   → burbuja + tarjetas                 ok/degraded → create_post (en hilo)
   clarification → chips de opciones                  clarification → post pregunta
   confirmation  → panel + cuenta atrás               confirmation → attachment con botones
                   + Confirmar/Cancelar                              (o "responde sí" si B-C6)
   denied        → candado                            denied → post con answer
   error         → rojo + trace_id + reintento        error  → post honesto + ref trace_id
                   solo si retryable                         NUNCA silencio
            │                                                           │
            └───────────► POST /api/v1/chat/confirm ◄───────────────────┘
                          { confirmation_id, decision }
                          Idempotency-Key obligatoria · TTL 5 min
                          mismo actor que originó · un solo approve

  ★ = red Docker que falta crear y unir (§3.8). Sin ella, el canal 2 no funciona.
```

---

## 5. BLOQUEANTES

Ordenados por urgencia. Los marcados 🔴 deben resolverse **antes** del sprint que los consume.

| # | Bloqueante | Evidencia | Impacto si no se resuelve | Dueño | Sprint que lo consume |
|---|---|---|---|---|---|
| **B-C0** 🔴 | **`BOT_TOKEN` commiteado en `forsis-bot/docker-compose.yml`** (commit `ee300fa`), con `system_post_all` sobre 36 canales. El token en el repo es el que corre en producción | `mattermost-integration-strategy.md` §5 S1, verificado con `git show HEAD:docker-compose.yml` y `docker exec forsis-bot printenv BOT_TOKEN` | Cualquiera con lectura del repo publica como `forsisbot` en los 36 canales. **Integrar el canal 2 sin sanear esto amplía la superficie de un token ya comprometido** | Dueño de forsis-bot | **Sprint 0 — bloquea todo el canal 2** |
| **B-C1** 🔴 | El agente publica `8099:443` al host con `POST /api/v1/chat` y bearer estático. Con el diseño de proxy same-origin (§2.2) **ningún consumidor del MVP lo necesita** | `architecture.md` §3.1 vs §2.2 de este doc | Superficie pública innecesaria para fuerza bruta del bearer | Agente 1 + este diseño | Sprint 1. **Recomendación: no publicar 8099 en el MVP**, o restringirlo por `allow`/`deny` de nginx a IPs internas |
| **B-C2** 🟠 | No verifiqué que `trafico-system` y `liquidaciones-system` tengan **un único layout/footer compartido** por todos los módulos. Sin él, inyectar el widget son N ediciones, no 1 | `trafico-system-analysis.md` §3 (lista `views/`, sin detalle de layout); `liquidaciones-system-analysis.md` §2 ("sin SPA") | La estimación del Sprint 5 (widget en un sistema) puede duplicarse | Fase 2, antes de Sprint 5 | Sprint 5 |
| **B-C3** 🔴 | **77 de 95 usuarios de `liquidaciones-system` tienen contraseña vacía y `priv` vacío** ⇒ cualquiera obtiene sesión válida con cualquier string. El widget hereda esa autenticación | `liquidaciones-security-strategy.md` §0.1, verificado en producción | Un widget sobre ese sistema es un agente accesible por 77 credenciales públicas | Dueño de liquidaciones (Fase A: A1+A2) | **Bloquea el widget en liquidaciones.** Mitigación interina: allowlist **nominal** (§2.5). Por eso el Sprint 5 despliega el widget en **trafico-system primero** |
| **B-C4** 🟡 | Navegadores reales de los usuarios no inventariados (Shadow DOM + `fetch` requieren evergreen) | — | El widget no carga en un navegador antiguo (falla cerrado: no se muestra) | TI | Sprint 5 |
| **B-C5** 🟡 | No verifiqué si los dos sistemas envían cabeceras CSP hoy, ni cuáles | — | Una CSP restrictiva podría bloquear `/assets/forsis-ai-widget.js` | Fase 2 | Sprint 5 |
| **B-C6** 🟠 | Los *interactive buttons* de MM exigen que el servidor Mattermost alcance un endpoint HTTP del bot. `forsis-bot` no expone puertos y está en otra red que `forsis-chat` | `mattermost-integration-strategy.md` §2.3; no verificado | Sin ruta, las confirmaciones con botón no funcionan | Fase 2 | Sprint 6. **Fallback definido:** confirmación textual con la maquinaria `acciones_pendientes` ya existente |
| **B-C7** 🟡 | `MaxPostSize` real de esta instancia no verificado (asumido el default 16 383) | `mattermost-analysis.md` no lo lista | Un post largo podría rechazarse | Fase 2 | Sprint 6. Mitigación: leerlo de `GET /api/v4/config/client` al arrancar |
| **B-C8** 🟡 | `RateLimitSettings` de Mattermost no verificado (¿habilitado? ¿cuota?) | `mattermost-analysis.md` no lo lista | El bot podría comerse `429` sin manejarlos | Fase 2 | Sprint 6. Mitigación: manejar `429` + `Retry-After` desde el día 1 |
| **B-C9** 🔴 | **Stack del agente sin resolver: Python/FastAPI vs PHP/Laravel 11.** `PHASE-1-BRIEF.md` dice Laravel; `architecture.md` describe php-fpm + Laravel; `agent-core.md` §0 recomienda Python por el core reutilizable | `agent-core.md` §0 (B-1), `PHASE-1-BRIEF.md` §Decisiones punto 2 | **Este documento es agnóstico** (el contrato HTTP y el widget no cambian), pero el Sprint 2 no puede empezar sin la decisión, y el presupuesto cambia (reescribir el Executor en PHP ≠ reutilizarlo) | Orquestador | **Sprint 1 — decisión, no investigación** |
| **B-C10** 🟠 | **Módulo `LIQUIDACIONES` no existe** en el workflow `solicitudes_cancelacion`; sus módulos son `CAJA_CHICA`, `TARJETA_DEUDOR`, `RECEPCION_GUIAS` | `liquidaciones-security-strategy.md` §2, verificado en `solicitud_cancelacion.php:390` | `status: confirmation_required` para autorizar liquidaciones no tiene destino: el agente **no puede ni pedir aprobación** para la acción más valiosa | Dueño de liquidaciones (B6) | Sprint 8 (es el último sprint del plan precisamente por esto) |
| **B-C11** 🟡 | `solicitud_cancelacion?action=crear` **no valida `priv`** ⇒ cualquier sesión inyecta solicitudes al buzón del revisor | `liquidaciones-security-strategy.md` §0 hallazgo #5 | El agente, aun con dry-run e idempotencia, escribe en una cola sin gate de entrada | Dueño de liquidaciones (A3) | Sprint 7 |
| **B-C12** 🟡 | **JSON mode del combo "Forsis" al 70 % / 80 % con salvage.** Afecta a los canales porque el 1 % residual se ve como `status: error` | `llm-provider.md` §3 | Fiabilidad percibida del agente en ambos canales | Mitigado por diseño (4 capas); requiere V-1…V-5 | Sprint 2 (V-1 al inicio) |
| **B-C13** 🟡 | `POST /v1/chat/completions` de Omniroute responde **200 sin `Authorization`**, en `0.0.0.0:20130` | `llm-provider.md` §1.1 (B-4) | Cualquiera con red al host consume el presupuesto de tokens del combo | Dueño de Omniroute | Reportar en Sprint 1; no bloquea los canales |

### 5.1 Lo que NO es un bloqueante, y conviene decirlo

- **Dos procesos que desplegar** (bot + agente) — coste aceptado y documentado
  (`mattermost-integration-strategy.md` §4.4); se mitiga con `trace_id` compartido y feature flag.
- **El hop de red extra** (~5-20 ms intra-host) — irrelevante frente a los 3.6 s de p50 del planner.
- **Ausencia de streaming** — decisión argumentada (§1.10), no una carencia pendiente.
- **Memoria pgvector del bot separada de la memoria del agente** — frontera deliberada
  (`mattermost-integration-strategy.md` §4.5), fuera del MVP.

---
Generado: 2026-10-05 — Fase 1, Agente 4. Entregable hermano: `sprint-plan.md`.
Ningún código de `forsis-bot`, `trafico-system` ni `liquidaciones-system` fue modificado: todos los
diffs de este documento son **propuestas** para Fase 2.
