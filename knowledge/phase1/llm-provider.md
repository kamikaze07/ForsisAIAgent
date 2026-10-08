# OmnirouteProvider — Diseño del LLM Provider (Fase 1, Agente 2)

**Fecha:** 2026-10-05
**Entregable:** `llm-provider.md` (de 2) — ver también `agent-core.md`
**Fuentes de Fase 0:** `prototype-reusability-analysis.md` §0 y §1.2, `omniroute-config.md`, `prototype-review.md` §12.1
**Código leído:** `src/infrastructure/llm_gateway/{base.py,ollama_provider.py}` del prototipo; `/home/servidor/omniroute/` (fuente y `.env`)
**Verificación empírica:** ejecutada en esta sesión contra el Omniroute real en este host (ver §2)

---

## 1. Resuelto: el puerto real (corrige a Fase 0 y a `omniroute-config.md`)

`omniroute-config.md` dejó esto abierto y su corrección del 2026-10-03 apuntaba a 20129 como "la API real". **Las dos versiones estaban parcialmente equivocadas.** Verificación de esta sesión:

```
docker ps  →  omniroute   0.0.0.0:20129-20130->20129-20130/tcp, 20128/tcp, 0.0.0.0:20132->20132/tcp
ss -ltn    →  0.0.0.0:20129   0.0.0.0:20130   0.0.0.0:20132   127.0.0.1:20128
```

Pruebas HTTP reales (desde el host y desde dentro del contenedor):

| Puerto | `GET /v1/models` (host) | `POST /v1/chat/completions` (host) | Desde dentro del contenedor | Veredicto |
|---|---|---|---|---|
| 20128 | — | — | `ECONNREFUSED` | No usar (bind loopback del host, no del contenedor) |
| **20129** | sin respuesta desde el host | sin respuesta desde el host | **401** | Publicado por Docker pero **no alcanzable desde el host**; responde solo dentro del contenedor |
| **20130** | **401** (requiere auth) | **200 — FUNCIONA** | 401 | ✅ **Este es el puerto a usar** |
| 20131 | sin respuesta | sin respuesta | **426 Upgrade Required** | Es un **WebSocket** (`EMBED_WS_PROXY_PORT=20131` en `.env`), **no** el "PROD_API_PORT" |

**Conclusión — corrección doble:**

1. **El puerto correcto es 20130**, el mismo que `deployment-strategy.md` ya usaba. La "corrección obligatoria" listada en `PHASE-1-BRIEF.md` §Correcciones (*"deployment-strategy.md usa puerto 20130 (dashboard) — debe corregirse"*) **se anula: no hay que corregir nada ahí.** El 20130 sirve el dashboard *y* la API `/v1/*` en el mismo puerto (Next.js: las rutas `/v1/...` son route handlers de la misma app, ver `src/app/api/v1/`).
2. **20131 NO es el puerto de API de producción.** `prototype-reusability-analysis.md` lo infirió del comentario `# PROD_API_PORT=20131` en el `.env`, pero esa línea **está comentada** y el 20131 real sirve un WebSocket. Usarlo fallaría.

Evidencia de que el combo existe y resuelve:

```
POST :20130/v1/chat/completions  {"model":"ComboQueNoExisteXYZ", ...}
  → 400 "Unable to determine provider for model ... or ensure the model is added as a combo entry"
POST :20130/v1/chat/completions  {"model":"Forsis", ...}
  → 200  (resuelve a modelos reales: ver §2.4)
```

El combo `Forsis` está configurado y el campo `model` acepta su nombre directamente, como documentaba `omniroute-config.md`.

### 1.1 BLOQUEANTE de seguridad (B-4, nuevo)

`POST /v1/chat/completions` en 20130 **responde 200 sin cabecera `Authorization`, y también con un Bearer inválido**:

```
POST chat sin auth            → 200
POST chat con "Bearer invalido123" → 200
GET  /v1/models sin auth      → 401
```

Es decir: `/v1/models` exige autenticación pero **el endpoint de inferencia no la valida**. Y el puerto está en `0.0.0.0` (no en loopback), por lo que es alcanzable desde la red del host.

**Implicaciones:**
- El agente *puede* funcionar sin API key, pero **no debe diseñarse así**: el provider debe enviar `Authorization: Bearer ${OMNIROUTE_API_KEY}` siempre, para que el día que Omniroute cierre ese hueco (o se actualice) el agente no se rompa.
- **Es un hallazgo que debe reportarse al dueño de Omniroute**, con independencia de este proyecto: cualquiera con acceso de red al host puede consumir el presupuesto de tokens del combo. Fuera del alcance del Agente 2, pero no se puede dejar sin registrar.

---

## 2. Medición empírica (reemplaza el benchmark de Ollama)

`prototype-reusability-analysis.md` §1.2 declaró inválido el benchmark de Ollama (2.96 s warm / 14.27 s cold) y pidió re-medir. Hecho.

**Método:** 20 llamadas reales a `POST :20130/v1/chat/completions` con `model:"Forsis"`, `temperature:0`, `response_format:{"type":"json_object"}`, system prompt de Planner realista (catálogo de 3 capabilities + instrucciones de formato) y preguntas variadas con identificadores distintos en cada una (para no medir aciertos de caché).

### 2.1 Latencias observadas

| Métrica | Valor |
|---|---|
| mínimo | 0.03 s (**caché**, ver §2.2) |
| p50 | **3.6 s** |
| p95 | **10.5 s** |
| máximo observado | **34.6 s** |

### 2.2 Timeout propuesto: 60 s (techo duro)

Derivación, no corazonada:
- El máximo observado en 20 llamadas fue **34.6 s**, con el mismo prompt que en otra llamada tardó 0.03 s. La varianza es enorme porque el combo enruta a proveedores distintos (§2.4), algunos con cola.
- `34.6 s × 1.7` ≈ 59 s → **`OMNIROUTE_TIMEOUT_S = 60`** como techo duro por llamada.
- **Comparación:** el prototipo usaba 45 s contra Ollama local. 60 s es más alto porque hay red + cola de Omniroute + cola del proveedor upstream, exactamente el riesgo que anticipaba `prototype-reusability-analysis.md`.
- Con reintentos de formato (máx 3 intentos) el peor caso teórico es 180 s, por eso el presupuesto de turno completo de `agent-core.md` §4.3 corta en **120 s** a nivel de `AgentService`: el techo del turno manda sobre la suma de los techos por llamada.

**El `ThreadPoolExecutor` + `future.result(timeout=...)` del prototipo se conserva al 100%.** El motivo original (una petición colgada >50 min sin que `httpx.ReadTimeout` se disparara) es **más** probable contra una API remota, no menos. El timeout del cliente HTTP por sí solo no es suficiente.

Las latencias de 0.03-0.07 s son **caché semántica de Omniroute** (`src/lib/semanticCache.ts`). Es un regalo: preguntas repetidas salen gratis. Pero significa que **no se puede medir la latencia real con prompts repetidos** — cualquier benchmark futuro debe variar el input.

### 2.3 Hallazgo: el combo inyecta un prompt propio enorme

Primera prueba, con un solo mensaje de usuario (`"ping"`) y **sin** system prompt:

```json
"usage": {"prompt_tokens": 4126, "completion_tokens": 14, "total_tokens": 4140}
```

**4 126 tokens de prompt para un "ping" de 1 token.** El combo "Forsis" está configurado con un system prompt / herramientas propias de ~4 000 tokens que se inyectan en toda llamada. En llamadas posteriores con system prompt propio, `prompt_tokens` osciló entre 135 y 276, lo que sugiere que la inyección es condicional (o que la caché de prompt la absorbe).

**Consecuencias de diseño:**
- **Coste.** Cada turno del agente puede arrastrar miles de tokens que el agente no controla.
- **Interferencia.** Un system prompt ajeno de 4 000 tokens compite con las instrucciones del Planner, y **es la explicación más probable** de los fallos del §3 (el modelo intenta narrar o usar herramientas propias en vez de obedecer el formato pedido).
- **Acción para Fase 2 (B-3):** revisar la configuración del combo "Forsis" en el dashboard de Omniroute y, si es posible, **crear un combo dedicado al agente, sin prompt de sistema inyectado y con modelos de JSON fiable**. Es la mitigación de mayor impacto y menor costo de todo este documento.
- La ventana de contexto conservadora de `agent-core.md` §3.2 (6 turnos / 2 000 tokens) sale de aquí.

### 2.4 Hallazgo: el modelo que responde es impredecible y no se puede fijar

El campo `model` de la respuesta reveló que **cada llamada al combo puede caer en un proveedor distinto**. En 20 llamadas respondieron:

`claude-opus-5`, `claude-sonnet-4.5`, `gemini-3.8-flash-tiered`, `deepseek-ai/deepseek-v4-pro-0813`, `deepseek-ai/deepseek-v4-flash-0731`, `space-bunny-free`

Esto es el failover del combo funcionando como está diseñado — y es la ventaja que `prototype-reusability-analysis.md` §1.2 anticipaba (el agente ya no necesita lógica propia de "si falla el modelo A, probar B"). **Pero tiene tres consecuencias que el análisis de Fase 0 no previó:**

1. **El comportamiento de formato no es estable** entre llamadas idénticas (causa raíz del §3).
2. **Un reintento puede caer en otro modelo.** Eso es bueno (el reintento tiene probabilidad real de arreglar el problema, no solo repetirlo) y justifica mantener los reintentos del prototipo.
3. **No se puede fijar un modelo como mitigación.** Se intentó pasar `model:"claude-opus-5"` directamente para forzar un modelo con JSON mode fiable:
   ```
   4 de 5 llamadas → HTTP 402 Payment Required
   1 de 5          → 200 (servida desde caché)
   ```
   Fijar modelo **no es una opción disponible** con las credenciales actuales. Solo el combo tiene presupuesto. Esto es parte del bloqueante B-3.

**Obligación derivada:** registrar `response.model` en el audit log de cada turno (`agent-core.md` §3.3). Sin eso, un fallo intermitente de formato es imposible de diagnosticar.

---

## 3. BLOQUEANTE B-2: JSON mode no es confiable (70%)

Esta era la pregunta que `prototype-reusability-analysis.md` §1.2 marcó como *"Verificar, no asumir — Bloqueante de Fase 1: probar con una llamada real"*. **Probado. El resultado es negativo.**

### 3.1 Resultado

20 llamadas con `response_format: {"type": "json_object"}` y un system prompt que pide JSON explícitamente:

| Métrica | Resultado |
|---|---|
| Contenido parseable con `json.loads()` directo | **70 %** (14/20) |
| Contenido parseable tras *salvage* (strip de fences + recorte `{`…`}`) | **80 %** (16/20) |
| Irrecuperable (texto en prosa, sin JSON) | **20 %** |

### 3.2 Modos de falla observados (textuales)

| Modo | Modelo | Contenido real devuelto | Recuperable |
|---|---|---|---|
| **Fence de markdown** | `claude-sonnet-4.5` | ` ```json\n{\n  "capability": "buscar_guia",... ` | ✅ sí (strip de fence) |
| **Tool-calling narrado** | `deepseek-v4-pro-0813` | `Voy a buscar la guía 90822 para ti search_guide(guide_id="90822")` | ❌ no |
| **Negativa de rol** | `deepseek-v4-flash-0731` | `No tengo acceso a herramientas para buscar información de logística...` | ❌ no |
| **Pregunta de aclaración** | `deepseek-v4-flash-0731` | `No tengo información sobre qué es "guía 12345"... ¿Podrías especificar...?` | ❌ no |

Los dos modos irrecuperables vienen **ambos** de la familia `deepseek` del combo, y los dos consisten en que el modelo **ignora el rol de Planner** y actúa como asistente conversacional. Esto encaja con el hallazgo §2.3: hay un system prompt del combo compitiendo con el del agente.

Nota: `response_format` **no está en el esquema de validación de entrada de Omniroute** para chat completions — `src/shared/validation/schemas/apiV1.ts` lo declara solo para imágenes (`z.enum(["url","b64_json"])`), y el schema de chat usa `.catchall(z.unknown())`, que lo **acepta y lo pasa al proveedor sin validar**. Por eso el soporte real depende por completo del modelo que atienda la llamada: Omniroute no lo garantiza ni lo emula.

### 3.3 Decisión sobre JSON mode

> **DECISIÓN: enviar `response_format: {"type":"json_object"}` siempre, pero NO confiar en él. El provider trata el JSON válido como un resultado a validar, no como una garantía del transporte.**

Es la misma postura que ya tenía `OllamaProvider` (que reintentaba con feedback) — solo que lo que allí era defensa en profundidad, aquí es **el mecanismo principal de corrección**. Defensa en 4 capas:

1. **Capa 1 — Pedirlo.** `response_format: {"type":"json_object"}` + prompt explícito. Cuesta cero y funciona el 70 % de las veces.
2. **Capa 2 — Salvage determinista (NUEVO respecto al prototipo).** Antes de declarar fallo, extraer JSON del texto: strip de ```` ```json ````/```` ``` ````, luego recorte del primer `{` al último `}`. **Medido: sube 70 % → 80 %.** Es ~10 líneas de código y recupera el modo de falla más frecuente. `OllamaProvider` no lo tenía porque el `format:"json"` nativo de Ollama sí era fiable.
3. **Capa 3 — Reintento con feedback (reutilizado del prototipo, 100 %).** Reinyectar el modo de falla concreto + el formato. Vale más aquí que en Ollama, porque el reintento puede caer en otro modelo (§2.4). **Máx 2 reintentos (3 intentos).**
4. **Capa 4 — Fail-closed.** Agotados los intentos → `ProviderError` → el `AgentService` responde *"no pude entender la solicitud, reformúlala"*. **Jamás** se ejecuta un plan parcialmente parseado.

**Probabilidad compuesta estimada:** con 80 % de éxito por intento e intentos cuasi-independientes (modelos distintos), 3 intentos ⇒ **~99 %** de planes obtenidos. El 1 % restante cae en la capa 4, que es un error honesto al usuario, no una acción equivocada.

### 3.4 Plan de verificación (requisito explícito del encargo)

Lo anterior se basó en 20 llamadas. Antes de cerrar Fase 2 hace falta confirmación estadística:

| # | Prueba | Criterio de aceptación | Cuándo |
|---|---|---|---|
| V-1 | 200 llamadas con prompt de Planner real y catálogo completo (de Agente 3), inputs todos distintos | ≥95 % de planes válidos **tras las 4 capas** | Inicio Sprint 1 |
| V-2 | Medir tasa cruda por modelo (agrupar por `response.model`) | Identificar qué modelos del combo son irrecuperables | Junto con V-1 |
| V-3 | Con el resultado de V-2, pedir al dueño de Omniroute un **combo dedicado** sin prompt inyectado y sin los modelos que fallan | Combo creado, o justificación de por qué no | Sprint 1 |
| V-4 | Re-medir latencias tras V-3 (inputs variados, sin caché) | Confirmar o ajustar el timeout de 60 s | Sprint 1 |
| V-5 | Probar `response_format: {"type":"json_schema"}` (más estricto; existe en el código de Omniroute) con el esquema de `ExecutionPlan` | Si funciona, sustituye a `json_object` y puede hacer sobrar la capa 2 | Sprint 1, oportunista |
| V-6 | Prueba de caos: Omniroute apagado, y Omniroute colgado sin responder | El agente responde error en ≤120 s en ambos casos, nunca se cuelga | Sprint 2 |

**Si V-1 queda por debajo de 95 %**, la mitigación escalada es: (a) exigir el combo dedicado de V-3 como bloqueante duro, (b) considerar un modelo propio dedicado al Planner (vuelve a entrar Ollama local *solo* para planificación, aprovechando que `LLMProvider` permite dos providers distintos para Planner y Composer sin tocar el núcleo).

---

## 4. Contrato de `OmnirouteProvider`

### 4.1 Interfaz: sin cambios

`LLMProvider` (ABC del prototipo, 38 líneas) **no cambia ni una línea** — confirma el veredicto de `prototype-reusability-analysis.md` §1.1:

```python
class LLMProvider(ABC):
    @abstractmethod
    def generate_plan(self, system_prompt: str, user_prompt: str,
                      context: dict | None = None,
                      capabilities: list | None = None,
                      workflows: list | None = None,
                      options: dict | None = None) -> ExecutionPlan: ...

    @abstractmethod
    def generate_text(self, system_prompt: str, user_prompt: str,
                      options: dict | None = None) -> str: ...
```

### 4.2 Construcción y configuración

```python
OmnirouteProvider(
    base_url: str,          # http://host.docker.internal:20130   ← 20130, §1
    model: str,             # "Forsis"  (nombre del combo, va directo en `model`)
    api_key: str,           # ${OMNIROUTE_API_KEY}  — SIEMPRE enviar, §1.1
    timeout_s: float = 60.0,    # techo duro, derivado en §2.2
    max_retries: int = 2,       # → 3 intentos
    temperature: float = 0.0,   # determinismo para el Planner
)
```

| Variable de entorno | Valor | Nota |
|---|---|---|
| `OMNIROUTE_BASE_URL` | `http://host.docker.internal:20130` | §1 — **no** 20129 ni 20131 |
| `OMNIROUTE_MODEL` | `Forsis` | combo; sustituir por el combo dedicado si sale de V-3 |
| `OMNIROUTE_API_KEY` | `[REDACTED]` — secreto de entorno | nunca en git (lección de `BOT_TOKEN`, brief §Correcciones) |
| `OMNIROUTE_TIMEOUT_S` | `60` | §2.2 |
| `OMNIROUTE_MAX_RETRIES` | `2` | §3.3 |

### 4.3 Request HTTP exacto

```http
POST {base_url}/v1/chat/completions
Authorization: Bearer {api_key}
Content-Type: application/json

{
  "model": "Forsis",
  "stream": false,
  "temperature": 0.0,
  "response_format": {"type": "json_object"},     // solo en generate_plan
  "messages": [
    {"role": "system", "content": "<PromptBuilder.build_system_prompt(...)>"},
    {"role": "user",   "content": "<texto del usuario>"}
    // en reintentos se añade un 3er mensaje role:"user" con el feedback del error
  ]
}
```

### 4.4 Parseo de la respuesta

```python
body["choices"][0]["message"]["content"]   # el texto a parsear
body["model"]                              # modelo REAL que respondió → audit (§2.4)
body["usage"]                              # tokens → control de coste (§2.3)
```

Validar defensivamente: `choices` puede venir vacío. `choices == []` ⇒ se trata como fallo de formato (reintento), no como excepción de sistema.

### 4.5 Comportamiento de `generate_plan` (pseudocódigo)

```
valid_names ← {cap.name for cap in capabilities}
messages    ← [system, user]
last_error  ← None

repetir hasta max_retries+1 veces:
    si last_error:
        messages += [user: RETRY_INSTRUCTIONS(last_error)]     # §5.2 de agent-core

    try:
        raw, model_real, usage ← _call(messages, json_mode=True)   # techo duro 60 s
    catch HTTPError | TimeoutError:
        raise ProviderError                 # NO se reintenta un fallo de transporte:
                                            # el combo ya hace failover de modelo
    audit(model_real, usage)

    content ← _salvage_json(raw)            # CAPA 2 — strip de fence + recorte {..}
    try: decision ← json.loads(content)
    except: last_error ← "no es JSON válido (...)"; continuar

    si no es dict:          last_error ← "debe ser un objeto JSON"; continuar

    si "plan" en decision:                           # formato multi-task
        try: tasks ← _parse_multi_step_plan(decision["plan"], valid_names)
        except _PlanParseError as e: last_error ← str(e); continuar
        retornar ExecutionPlan(new_plan_id(), tasks)

    cap ← decision.get("capability")
    si cap es None:        retornar ExecutionPlan(new_plan_id(), tasks=[])   # "no sé"
    si cap ∉ valid_names:  last_error ← f"'{cap}' no está en el catálogo"; continuar
    si no es dict(params): last_error ← "'parameters' debe ser objeto"; continuar

    retornar ExecutionPlan(new_plan_id(), [Task(...)])

raise ProviderError(f"sin plan válido tras N intentos: {last_error}")   # CAPA 4
```

**Dos decisiones explícitas en este pseudocódigo:**

- **Un fallo de transporte NO se reintenta** (se propaga como `ProviderError`). Es un cambio de criterio respecto a la intuición: Omniroute ya hace failover entre 19 estrategias del lado del servidor, así que si *él* devuelve un error HTTP, reintentar desde el agente solo suma latencia a un fallo ya definitivo. Los reintentos del agente son **exclusivamente por formato de respuesta inválido** — exactamente lo que concluyó `prototype-reusability-analysis.md` §1.2.
- **`capability: null` es un éxito, no un fallo.** Devuelve un plan vacío y el `AgentService` responde "no puedo responder eso". Conservado del prototipo; es lo que evita que el agente alucine capabilities.

### 4.6 `_salvage_json` (capa 2, nuevo)

```python
_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.S)

def _salvage_json(raw: str) -> str:
    m = _FENCE.search(raw)
    if m:
        raw = m.group(1)                  # recupera el fallo de claude-sonnet-4.5
    i, j = raw.find("{"), raw.rfind("}")
    if i >= 0 and j > i:
        raw = raw[i:j+1]                  # recorta prosa antes/después del objeto
    return raw.strip()
```

Medido: **70 % → 80 %** de planes parseables. Nunca "arregla" un JSON malformado — solo descarta envoltorio; si el contenido sigue sin ser JSON, falla igual y pasa a la capa 3.

### 4.7 `generate_text` (para el ResponseComposer)

Idéntico, pero **sin** `response_format`, sin validación de esquema, sin reintentos de formato (es prosa libre) y con `temperature` configurable (0.3 propuesto, para que la redacción no suene robótica). Un fallo aquí **nunca** es fatal: el `AgentService` degrada a `TemplateComposer` (`agent-core.md` §4.2, D-4).

---

## 5. Comparación `OmnirouteProvider` vs `OllamaProvider`

| Aspecto | `OllamaProvider` (prototipo, 276 líneas) | `OmnirouteProvider` (nuevo) | ¿Se reutiliza? |
|---|---|---|---|
| Endpoint | `POST {base}/api/chat` | `POST {base}/v1/chat/completions` | **No** (1 línea) |
| Payload | `{model, messages, stream, options{temperature}}`, `format:"json"` | `{model, messages, stream, temperature, response_format}` | **No** — estándar OpenAI, más simple |
| Autenticación | ninguna | `Authorization: Bearer` | **Nuevo** |
| Parseo | `body["message"]["content"]` | `body["choices"][0]["message"]["content"]` | **No** (1 línea) |
| Semántica de `model` | modelo concreto (`qwen2.5:7b`) | **nombre del combo** (`Forsis`) — el modelo real varía por llamada | **Cambia de semántica** |
| JSON mode | `format:"json"` nativo, **fiable** | `response_format` **no garantizado (70 %)** | **Degrada** → motiva la capa 2 |
| Salvage de JSON | no existe (no hacía falta) | `_salvage_json()` | **Nuevo** (§4.6) |
| Reintento con feedback al modelo | sí | sí, con feedback **más específico** | **Sí, 100 %** |
| Techo duro `ThreadPoolExecutor` | sí (45 s), motivado por un cuelgue real de >50 min | sí (**60 s**) | **Sí, 100 %** — más necesario aún |
| Failover entre modelos | no lo tenía (y le hacía falta) | **lo resuelve Omniroute** (19 estrategias) | **Se elimina del agente** |
| `_parse_multi_step_plan()` + validación de catálogo cerrado | sí (78 líneas, la pieza más valiosa) | idéntico | **Sí, 100 %** |
| Validación de `TaskDependencyField` | sí | idéntico | **Sí, 100 %** |
| `order_tasks()` como validación previa | sí | idéntico | **Sí, 100 %** |
| Registro del modelo real / tokens | no aplicaba | **obligatorio** (§2.4, §2.3) | **Nuevo** |
| Coste por llamada | 0 (local) | tokens del combo + ~4 000 de prompt inyectado (§2.3) | **Nuevo riesgo** |

**Reutilización efectiva de la lógica: ~70 %**, confirmando la estimación de `prototype-reusability-analysis.md` §1.2. Lo que se bota es protocolo (~30 líneas); lo que se conserva es validación y defensa (~150 líneas), que es la parte difícil.

**Corrección a Fase 0:** el análisis predijo que `OmnirouteProvider` sería *"~100-150 líneas, más corto que `OllamaProvider`"*. Será **del mismo tamaño o un poco mayor**: el protocolo es más simple, pero el salvage de JSON y la telemetría obligatoria (modelo real, tokens) añaden más de lo que se quita. La predicción de que Omniroute absorbe el failover **sí se cumplió**; la de que el provider sería más corto, no.

---

## 6. Resumen de bloqueantes y resoluciones

| # | Tema | Estado | Detalle |
|---|---|---|---|
| **Puerto de Omniroute** | ✅ **RESUELTO** | **20130** (no 20129, no 20131). Anula la "corrección obligatoria" del brief sobre `deployment-strategy.md` | §1 |
| **Combo "Forsis" existe** | ✅ **RESUELTO** | Confirmado; `model:"Forsis"` resuelve y responde 200 | §1 |
| **B-2 JSON mode** | ⚠️ **BLOQUEANTE MITIGADO** | 70 % crudo / 80 % con salvage. No confiable, pero manejable con 4 capas. Requiere V-1…V-5 | §3 |
| **B-3 Prompt inyectado + modelo no fijable** | ⚠️ **BLOQUEANTE ABIERTO** | ~4 000 tokens de prompt ajeno por llamada; `model` fijo → 402 Payment Required. Requiere combo dedicado (V-3) | §2.3, §2.4 |
| **B-4 Inferencia sin autenticación** | 🔴 **BLOQUEANTE DE SEGURIDAD (nuevo)** | `POST /v1/chat/completions` responde 200 sin `Authorization` y con Bearer inválido, en `0.0.0.0:20130`. Reportar al dueño de Omniroute | §1.1 |
| **Timeout** | ✅ **PROPUESTO CON DATOS** | **60 s** por llamada (máx observado 34.6 s × 1.7); 120 s por turno | §2.2 |
| **B-1 Stack Python vs PHP** | 🔴 **BLOQUEANTE ABIERTO** | Fuera del alcance de este documento | `agent-core.md` §0 |

---
Generado: 2026-10-05 — Fase 1, Agente 2
Mediciones reproducibles: `/tmp/bench.py`, `/tmp/bench2.py`, `/tmp/bench_results.json`
