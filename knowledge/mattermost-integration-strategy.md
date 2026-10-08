# Estrategia de Integración Mattermost — Forsis AI Agent

**Fecha:** 2026-10-03
**Pregunta:** ¿Extender `forsis-bot` actual (Opción A/C) o construir integración nueva en el agente (Opción B)?
**Veredicto:** **Opción C (Híbrido)** — `forsis-bot` queda como gateway Mattermost y el Forsis AI Agent entra por detrás vía API REST interna. Se documenta por qué A y B se descartan como estrategia principal.

---

## 1. Resumen ejecutivo

`forsis-bot` funciona y no debe tocarse en su núcleo. Pero delegar la intelligence por `subprocess` a un CLI (`agy`) es la pieza frágil que hay que reemplazar. La recomendación no es "elegir A o B" sino **separar el transporte del razonamiento**:

```
Mattermost  ⇄  forsis-bot (gateway)  ──HTTP──▶  Forsis AI Agent (FastAPI)
              WebSocket, mentions,          Planner/Executor/Capabilities,
              confirmación, allowlist        acceso a trafico/liquidaciones
```

- **forsis-bot** conserva: WebSocket, mención, hilos, confirmación humana, allowlist, memoria pgvector, posting.
- **forsis-bot pierde:** el `subprocess.run(["agy", ...])`. Lo sustituye por una llamada HTTP a `POST /api/v1/chat` (el endpoint **ya existe** en el prototipo, ver §3.2).
- **El agente gana:** una interfaz (Mattermost) más, sin reescribir el transporte que ya funciona.

Riesgo principal de esta vía: **dos procesos que desplegar** en lugar de uno. Se mitiga con el hecho de que el cambio en `forsis-bot` es de ~30 líneas en un solo archivo (`actions.py`) y es reversible con un `git revert` (§7).

---

## 2. Estado verificado en el servidor (2026-10-03)

Evidencia recogida del host, no de documentación previa.

### 2.1 `forsis-bot`

| Aspecto | Valor |
|---|---|
| Path | `/home/servidor/forsis-bot` |
| Tamaño | 12 módulos Python, **2 702 LOC** |
| Repositorio | git, 2 commits (`3f8994a`, `ee300fa`), sin historial de cambios funcionales |
| Contenedor | `forsis-bot` — Up 23 hours, imagen `forsis-bot-forsis-bot` |
| Red | `ai-network` (172.26.0.2) — **única red** |
| Memoria | `forsis-memory` (pgvector pg16, 172.26.0.3) en `ai-network` |
| LLM | `OPENAI_API_BASE=http://litellm:4000/v1`, `MODEL=ollama_chat/llama3.5` (compose) vs `llama3.1:8b` (`.env`) — **divergencia sin resolver** |
| Token MM | `BOT_TOKEN` en el compose, prefijo `ho9ncs…` (el doc previo registra `ns5nmg…` → **el token fue rotado**) |
| Autorización | `AGY_USUARIOS_AUTORIZADOS=""` → **fail-closed, nadie puede ejecutar acciones** |

Funciones clave en `app/main.py` (1 077 líneas):

| Línea | Función | Rol en la estrategia |
|---|---|---|
| 352 | `procesar_post()` | Punto de entrada único por post. Aquí se decide a quién enrutar. |
| 314 | `bot_mencionado()` | Detección de mención / DM |
| 126 | `obtener_historial_canal()` | Reconstrucción de contexto conversacional |
| 153 | `registrar_actividad_operativa()` | Log de actividad → alimenta pgvector |
| 880 | rama `ejecutar_tarea_servidor` | **Punto exacto a sustituir** (subprocess) |
| 1048 | `Thread(target=procesar_post)` | Despacho asíncrono por post |
| 1020 | `while True: ws.recv()` | Bucle WebSocket con auto-reconexión |

### 2.2 La delegación actual es `subprocess`, no API

`app/actions.py:225-267`:

```python
def ejecutar_agy(instruccion, timeout_seg=180):
    resultado = subprocess.run(
        ["agy", "--print", instruccion, "--sandbox",
         "--dangerously-skip-permissions",
         "--print-timeout", f"{timeout_seg}s"],
        capture_output=True, text=True, timeout=timeout_seg + 15,
    )
```

Cuatro problemas concretos de este diseño:

1. **`--dangerously-skip-permissions`** dentro de un contenedor que corre como root y tiene montadas las credenciales de Google del usuario del host (`/home/servidor/.gemini:ro`). La confirmación humana ocurre *en Mattermost antes*, pero entre el "sí" y el `subprocess` no hay ninguna barrera adicional.
2. **La credencial es personal, no de servicio.** El compose lo admite: `antigravity-oauth-token` es la credencial de Google del usuario del host. Si el host se compromete, el agente hereda esa sesión.
3. **El resultado es texto plano.** `stdout` se pega al post con `respuesta_agy[:900]` (`main.py:442`). No hay structured output, ni `session_id`, ni componentes UI, ni código de error tipado — todo se colapsa a un string.
4. **El transporte es `stdout`**, no un contrato. Cualquier cambio en la salida de `agy` rompe silenciosamente la experiencia en Mattermost.

### 2.3 Aislamiento de red — el hallazgo que más condiciona la decisión

```
forsis-bot  → ai-network                 (172.26.0.2)
trafico-php → forsis-comunicaciones, trafico-system_default
liquidaciones-php → liquidaciones-system_default
atlas-php   → forsis-comunicaciones, tablero-guias_default
```

**`forsis-bot` no comparte red con ningún sistema de negocio.** Hoy no importa porque `agy` corre dentro del contenedor vía subprocess (hereda el filesystem, no la red). En cuanto el agente se vuelva un servicio HTTP:

- **Opción C** requiere que Forsis AI Agent se una a `trafico-system_default` y `liquidaciones-system_default` **y** que `forsis-bot` se una a `ai-network` + la red del agente. Es un cambio de compose de 2-3 líneas.
- **Opción B** requiere lo mismo, más re-implementar WebSocket y reconexión.

Punto de atención de seguridad: `ai-network` es una red externa compartida con `onlyoffice`. Cualquier servicio que se una a ella gana alcance de red sobre los demás miembros. Recomendación: **crear una red dedicada `forsis-agent_net`** y unir solo el agente + forsis-bot, en vez de reutilizar `ai-network`.

### 2.4 El prototipo ya tiene la otra mitad

De `knowledge/prototype-review.md`:

- `POST /api/v1/chat` — existe, con `ChatRequest{message, session_id, inputs, debug}` y `ChatResponse{answer, session_id, components[], clarification, debug}`.
- `src/interfaces/mattermost/__init__.py` — **vacío** (placeholder, Sprint 4 "Pendiente").
- `src/integration/providers/MattermostProvider.py` — esqueleto, no funcional.
- FastAPI + uvicorn, sin docker-compose.

Es decir: el endpoint que forsis-bot necesita ya está diseñado. La integración es cablear, no inventar.

---

## 3. Evaluación de las tres opciones

### Opción A — Extender `forsis-bot` (proxy puro)

**Veredicto: insuficiente por sí sola.** Corrija sobre el transporte, pero no resuelve el problema real, que es el aislamiento entre "gateway" y "ejecución con permisos". El agente seguiría siendo invocado por subprocess o por un `requests.post` acoplado al `stdout`.

Lo que sí aporta: un cambio mínimo en `forsis-bot` es naturalmente un cambio en Opción C también. **A no es una alternativa a C, es la primera mitad de C.**

### Opción B — Cliente Mattermost nuevo en el agente

**Veredicto: rejectada.** El cálculo no cierra:

| Esfuerzo a reimplementar | Evidencia de que ya existe y funciona |
|---|---|
| WebSocket + reconexión | `main.py:1020-1077` — bucle con backoff, probándose en producción 23 h |
| Detección de menciones | `bot_mencionado()` (`main.py:314`) |
| Reconstrucción de contexto | `obtener_historial_canal()` + `construir_historial()` |
| Confirmación humana con TTL | `acciones_pendientes` + `CONFIRMACION_TTL` (`main.py:897`) |
| Allowlist fail-closed | `usuarios_autorizados_agy()` (`actions.py:213`) |
| Cola de learning | `posts_procesados` (1 048 cap) |
| Respuestas con threading | `Thread(target=procesar_post, daemon=True)` |
| Cuenta de bot + permisos | `EnableBotAccountCreation=false` → requiere token admin para crear otro |

Tres argumentos que decisión el asunto:

1. **Duplicar la allowlist es un riesgo de seguridad, no solo de esfuerzo.** Habría dos listas de autorización que mantener sincronizadas. El patrón actual —"un 'soy de TI' en el chat no debe bastar"— (`actions.py:208-210`) está bien pensado; duplicarlo lo degrada.
2. **Dos clientes WebSocket sobre el mismo token.** El prototipo usaría el mismo `BOT_TOKEN`. Dos conexiones con el mismo usuario compiten por los mismos eventos `posted`, con reglas de desempate que no están documentadas en Mattermost. Fuente clásica de mensajes perdidos o duplicados.
3. **`system_post_all` + WebSocket es un superficie de broadcast amplia.** Duplicarla duplica el riesgo.

A favor de B, honestamente: **cohesión** — un solo proceso, un solo deploy, un solo log. Es un argumento real, y es exactamente lo que la Opción C sacrifica.

### Opción C — Híbrido (recomendado)

**Veredicto: adoptada.** Ver §4 para el diseño.

---

## 4. Diseño recomendado (Opción C)

### 4.1 Reparto de responsabilidades

| Capa | Componente | Responsabilidad |
|---|---|---|
| Transporte | `forsis-bot` | WebSocket, mención/DM, hilos, dedup, allowlist, confirmación, memoria pgvector, posting |
| Razonamiento | **Forsis AI Agent** | Planner, Executor, Capabilities, acceso a trafico/liquidaciones, composer de respuesta |
| Contrato | REST interno | `POST /api/v1/chat` + endpoint de salud |

### 4.2 El cambio en `forsis-bot` (superficie exacta)

Un solo archivo, una sola función. `actions.py`, reemplazar `ejecutar_agy()` por:

```python
AGENT_URL = os.getenv("FORSIS_AGENT_URL", "http://forsis-ai-agent:8000")
AGENT_TOKEN = os.getenv("FORSIS_AGENT_TOKEN")          # fail-closed si falta
AGENT_TIMEOUT_S = int(os.getenv("FORSIS_AGENT_TIMEOUT_S", "180"))

def ejecutar_agy(instruccion, timeout_seg=None, session_id=None):
    """Delega al Forsis AI Agent. Sustituye al subprocess a `agy`."""
    timeout = (timeout_seg or AGENT_TIMEOUT_S) / 1000 if timeout_seg else AGENT_TIMEOUT_S
    try:
        r = requests.post(
            f"{AGENT_URL}/api/v1/chat",
            json={"message": instruccion, "session_id": session_id, "debug": False},
            headers={"Authorization": f"Bearer {AGENT_TOKEN}"},
            timeout=AGENT_TIMEOUT_S,
        )
        r.raise_for_status()
        data = r.json()
        return data.get("answer"), data.get("session_id"), data.get("components")
    except requests.Timeout:
        return None, session_id, None
    except Exception as e:
        print("ERROR agent:", e)
        return None, session_id, None
```

Y en `main.py`, los dos call sites (`main.py:429` y `main.py:442`) se adaptan al nuevo shape de retorno.

**El nombre `ejecutar_agy` debe cambiar a `ejecutar_agente`.** Mantener el nombre viejo es una deuda que cobra intereses en tres meses.

### 4.3 Lo que gana cada capa

**Forsis-bot:**
- ✅ Sale `subprocess` → sale `--dangerously-skip-permissions`, sale la credencial personal de Google montada en el contenedor.
- ✅ Timeout, retry y circuit breaker en HTTP en vez de en `subprocess.run`.
- ✅ Respuesta estructurada: `components` habilita tarjetas en Mattermost sin lógica nueva en el bot.
- ✅ `session_id` permite continuidad conversacional real (hoy cada tarea es un `agy --print` aislado y sin memoria).
- ✅ Diff de ~30 líneas, reversible.

**Forsis AI Agent:**
- ✅ Un `POST /api/v1/chat` es trivial de testear con `requests` o `pytest`; un WebSocket no lo es.
- ✅ El agente puede atender Mattermost y HTTP/web desde el mismo proceso, sin una línea de código de transporte duplicado.
- ✅ Provisiona una sola vez: el compose del agente, con sus redes hacia trafico y liquidaciones.

### 4.4 Lo que C cuesta (con honestidad)

- **Un servicio más que desplegar.** Mitigación: el agente ya necesita desplegarse de todos modos para la vía web; Mattermost entra como un consumidor más de la misma API.
- **Hop de red.** ~5-20 ms intra-host. Irrelevante frente a los 3-15 s del planner LLM.
- **Dos fuentes de logs.** Mitigación: `trace_id` compartido en el request y en el log del bot.
- **Posible punto de fallo único.** Si el agente cae, `forsis-bot` sigue sirviendo memoria, contexto y respuestas no-agente (el clima, la web, el learning). Hay que asegurar el graceful degrade: si el agente devuelve 5xx, el bot responde con un mensaje honesto, no con silencio.

### 4.5 Migración de memoria (pgvector)

`forsis-memory` es memoria conversacional del bot; el prototipo tiene su propio PostgreSQL para memoria del agente. **No intentar fusionarlos en esta fase.** Son esquemas distintos y el valor de unirlos es marginal frente al riesgo. Evaluarlo post-MVP.

Documentar la frontera: pgvector = memoria conversacional de Mattermost. PostgreSQL del agente = memoria de sesión de `ChatRequest`. Si más adelante se quisieran respuestas semánticas sobre el historial del chat, ahí sí tiene sentido un `Provider` de lectura contra `forsis-memory` (el patrón `MattermostProvider` ya existe como esqueleto en el prototipo).

---

## 5. Seguridad

Hallazgos, en orden de urgencia:

| # | Hallazgo | Ubicación | Acción |
|---|---|---|---|
| S1 | **`BOT_TOKEN` commiteado en git** | `forsis-bot/docker-compose.yml:12` (commit `ee300fa`, confirmado con `git show HEAD:docker-compose.yml`) | **Rotar el token ahora**, sacarlo a `.env`/secrets, y revisar el historial. Es la prioridad #1: el token da `system_post_all`. |
| S2 | `DATABASE_URL` con password en claro en el compose | `forsis-bot/docker-compose.yml` | Mover a `.env`, rotar la password de `forsis` |
| S3 | `POSTGRES_PASSWORD: forsis123` | `forsis-bot/docker-compose.yml` | Idem |
| S4 | `/home/servidor/.gemini` (credencial personal de Google) montada en un contenedor | `forsis-bot/docker-compose.yml` | **Desaparece con la Opción C.** No requiere acción si se migra. |
| S5 | `MM_LOCALMODETOKEN` activo (`EnableLocalMode=true`) | Mattermost | Riesgo preexistente, fuera del alcance de esta decisión. Bypass total de auth si el contenedor se compromete. |
| S6 | `AllowCorsFrom=*` | Mattermost | Revisar; innecesario si solo hay clientes same-origin |
| S7 | El nuevo endpoint del agente necesita su propia auth | — | `FORSIS_AGENT_TOKEN` + red dedicada. Sin esto, Opción C **empeora** la postura respecto a hoy: hoy el agente vive detrás del token del bot. |

**Nota sobre S1:** el token en el repo (`ho9ncs…`) es el mismo que corre en producción. Cualquiera con acceso de lectura al repo tiene capacidad de publicar como `forsisbot` en los 36 canales del equipo Forsis PR. Rotar y limpiar el historial del repo antes de avanzar con la migración.

**Sobre la allowlist:** hoy `AGY_USUARIOS_AUTORIZADOS=""` — nadie está autorizado. Con la Opción C, la lista vacía debe seguir significando lo mismo: fail-closed. El agente nuevo **no** debe traer su propia allowlist permisiva que compense la del bot. La autorización se evalúa **una sola vez**, en `forsis-bot`, antes de que exista una petición HTTP.

---

## 6. Plan de implementación

| Fase | Trabajo | Esfuerzo | Reversible |
|---|---|---|---|
| **0. Sanitizar** | Rotar `BOT_TOKEN`, sacarlo del compose y del historial. Mover passwords a `.env`. | ~1 h | No (pero hay que hacerlo igual) |
| **1. Agente en red** | `docker-compose.yml` del agente: FastAPI, `forsis-agent_net`, uniones a `trafico-system_default` y `liquidaciones-system_default`, auth por token | ~4 h | Sí |
| **2. Contrato** | Fijar el shape de `ChatRequest`/`ChatResponse`. Añadir tests de contrato. Sin esto, la fase 3 es adivinar | ~3 h | Sí |
| **3. Cablear forsis-bot** | Sustituir `ejecutar_agy` por `ejecutar_agente`, adaptar los 2 call sites, feature flag | ~3 h | **Sí — `git revert` de un commit** |
| **4. Verificar E2E** | Un post en Mattermost → el agente responde. Comparar contra el comportamiento de `agy` | ~3 h | Sí |
| **5. Cortar** | Quitar los binds de `.gemini`/`agy` del compose. Retirar `subprocess` | ~1 h | Revertir fase 3 |
| **6. Decidir memoria** | Mantener pgvector separado o integrar. **Fuera de alcance del MVP** | — | — |

Feature flag para la fase 3:

```yaml
DELEGATE_TO_AGENT: "false"   # true = HTTP, false = subprocess legacy
```

Con el flag en `false`, `forsis-bot` se comporta exactamente como hoy. Eso convierte la migración en un cambio desplegable sin riesgo de downtime.

**Total estimado:** ~2 días-persona hasta producción, dominado por la fase 0 (limpieza de secretos) y la 2 (definir el contrato antes de cablear).

---

## 7. Criterios de decisión para revisar esta recomendación

Esta recomendación es correcta **si**:

- `forsis-bot` sigue siendo funcional y sin dueño activo que lo modifique a diario.
- El equipo quiere conservar la semántica de confirmación humana y la allowlist como están.
- No hay una razón estratégica fuerte por consolidation de procesos.

Debería revisarse a Opción B **si**:

- `forsis-bot` dejara de mantenerse (dueñoHW en el repo, < 2 meses sin cambios).
- La duplicación de la allowlist se vuelve un problema real de incidentes.
- Los 2 segundos de reconexión del WebSocket se vuelven un SLA incumplido.
- La carga de mantenimiento de dos compose se percibe como significativa (> 1 h/mes).

Señales de que C está funcionando:

- `subprocess` y los binds de `.gemini` desaparecieron del compose.
- Un `trace_id` cruza los logs de ambos procesos.
- El bot responde honestamente cuando el agente está caído.
- El agente se testea sin necesidad de levantar Mattermost.

---

## 8. Conclusión

**Opción C (Híbrido).** Se conserva lo que funciona y se reemplaza lo que no:

- Se mantiene `forsis-bot` como gateway Mattermost (2 702 LOC probadas, un solo cambio en `actions.py`).
- Se elimina la delegación por `subprocess` a un CLI con `--dangerously-skip-permissions` y credencial personal de Google montada.
- El agente entra por el endpoint que **ya tiene diseñado**: `POST /api/v1/chat`.

Opción B tiene un coste — reescribir transporte que funciona en producción para ganar cohesión de proceso — y arrastra un riesgo de seguridad concreto: dos allowlists y dos conexiones WebSocket compitiendo con el mismo token.

Antes de la fase 1, la fase 0 no es opcional: **el `BOT_TOKEN` está commiteado en el repo de `forsis-bot`.**

---

## 9. Referencias

**Documentos internos:**
- `knowledge/forsis-bot-status.md` — decisión original "REUSE the existing bot"
- `knowledge/mattermost-analysis.md` — estado de la instancia MM v11.6.0, config, permisos
- `knowledge/mattermost-bot-integration.md` — opciones de integración MM (REST v4, webhooks, local mode)
- `knowledge/trafico-system-analysis.md` §9 — "no hay integración directa" entre forsis-bot y trafico
- `knowledge/prototype-review.md` — arquitectura del prototipo, `POST /api/v1/chat`, Sprint 4 pendiente

**Código inspeccionado en el servidor:**
- `/home/servidor/forsis-bot/app/actions.py` (267 líneas) — `ejecutar_agy()`, `usuarios_autorizados_agy()`
- `/home/servidor/forsis-bot/app/main.py` (1 077 líneas) — `procesar_post()`, bucle WebSocket
- `/home/servidor/forsis-bot/docker-compose.yml` — secretos, redes, binds
- `docker ps` / `docker network inspect` — estado de contenedores y redes

**Verificaciones ejecutadas:**
- `git show HEAD:docker-compose.yml | grep -c ho9ncs…` → 1 (token confirmado en historial)
- `docker exec forsis-bot printenv BOT_TOKEN` → prefijo `ho9ncs…` (token en uso = el commiteado)
- `docker inspect` redes de `trafico-php`, `liquidaciones-php`, `atlas-php` → sin solape con `ai-network`