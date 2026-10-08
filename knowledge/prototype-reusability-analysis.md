# Análisis de Reutilización del Prototipo ante Omniroute (API remota)

**Fecha:** 2026-10-03
**Contexto:** `prototype-review.md` (33 KB) ya evaluó el prototipo `forsis-agent`
asumiendo que seguiría usando Ollama local. Este documento responde la
pregunta que queda abierta: **¿qué cambia si el nuevo agente usa Omniroute
(API remota, `http://forsispr1.ddns.net:20130/`, combo `Forsis`) en vez de
Ollama local?**

**Verificación empírica realizada en esta sesión** (no solo lectura de docs):
- Probado el endpoint real de Omniroute puerto a puerto (20128/20129/20130).
- Leído el código fuente de Omniroute en `/home/servidor/omniroute/` (es
  open-source, está instalado localmente — no es una caja negra).
- Confirmado el contrato real de API contra `examples/quickstart/` y
  `src/shared/validation/schemas/apiV1.ts`.

---

## 0. Hallazgo que reencuadra toda la pregunta

**Omniroute es OpenAI-API-compatible**, no un protocolo propio:

```
POST http://<host>:<puerto-API>/v1/chat/completions
Authorization: Bearer <api-key>
Content-Type: application/json

{
  "model": "Forsis",        <- nombre del combo, funciona como alias de modelo
  "stream": false,
  "messages": [{"role": "user", "content": "..."}]
}
```

Confirmado en `omniroute/examples/quickstart/{python_requests.py,curl_terminal.sh,nodejs_axios.js,php_curl.php}`
y en `src/lib/modelAliasResolver.ts` (`getComboByName(model)` — el combo se
referencia por su `name` directamente en el campo `model`, sin prefijo
especial).

**Corrección a `omniroute-config.md`:** el puerto **20130 es el dashboard**
(`307 → /dashboard`, sirve una SPA Next.js, `/docs` es la UI web, no Swagger).
El puerto **20129 es la API real** (`API_PORT=20129` en el `.env` de
Omniroute) pero no respondió en las pruebas de red externas — típico de un
bind a `127.0.0.1` dentro del host. Desde el propio host:

| Ruta | Puerto 20130 (dashboard) | Puerto 20129 (API) |
|---|---|---|
| `/` | 307 → `/dashboard` | sin respuesta desde fuera del host (bind loopback) |
| `/v1/models` | 401 (requiere auth) | — |
| `/v1/chat/completions` | 405 (existe, método incorrecto en prueba GET) | — |

**Acción para Fase 1:** probar `/v1/chat/completions` contra **20129** (no
20130) desde dentro del host, con `Authorization: Bearer <API_KEY>` real. El
`docker-compose` propuesto en `deployment-strategy.md` ya apunta a
`host.docker.internal:20130` — **hay que corregirlo a 20129** o confirmar que
Omniroute expone el combo también en el dashboard-port (no verificado).

Esto es lo más importante del análisis: **el prototipo no necesita un
protocolo nuevo**, necesita el protocolo *más estándar que existe* (OpenAI
chat completions), que es más simple que el protocolo nativo de Ollama
(`/api/chat` con forma de respuesta propia) que ya implementa.

---

## 1. Respuesta directa a las 5 preguntas del encargo

### 1.1 ¿Qué componentes son agnósticos al tipo de LLM (local vs. remoto)?

**Totalmente agnósticos — cero cambios:**

| Componente | Por qué |
|---|---|
| `src/agent/contracts/*.py` | Pydantic puro, no habla con ningún LLM |
| `src/agent/planner/planner.py` | Solo invoca `LLMProvider.generate_plan(...)` — depende de la interfaz, no de la implementación |
| `src/agent/executor/*.py` (Executor, Registry, Factory, plan_ordering) | Orquestación determinista, nunca llama al LLM directamente |
| `src/agent/response/composer.py` (interfaz + `TemplateResponseComposer`) | El fallback determinista no toca al LLM |
| `src/agent/prompts/builder.py` | Construye strings de prompt; el *consumidor* del string (Ollama vs Omniroute) es indiferente |
| `src/infrastructure/llm_gateway/base.py` (`LLMProvider` ABC) | Es exactamente el punto de extensión diseñado para este cambio |

Esto confirma el veredicto de `prototype-review.md` §11.1: el core
Planner/Executor/Registry fue diseñado correctamente como agnóstico al LLM.
**El cambio de Ollama local → Omniroute remoto no invalida ninguna decisión
de diseño de esta capa — es precisamente el caso de uso que la abstracción
`LLMProvider` anticipaba.**

### 1.2 ¿`OllamaProvider` es adaptable a Omniroute o hay que reescribirlo?

**Ni lo uno ni lo otro: se reemplaza por un provider nuevo y más simple,
reutilizando ~70% de la lógica de `OllamaProvider` (la que no es protocolo).**

Comparación concreta línea por línea de `ollama_provider.py` (276 líneas):

| Pieza de `OllamaProvider` | ¿Se reutiliza para `OmnirouteProvider`? | Nota |
|---|---|---|
| `_call()` → `POST {base_url}/api/chat`, payload `{model, messages, stream, options}` | **No** — cambia a `POST {base_url}/v1/chat/completions`, payload OpenAI estándar | Omniroute usa el formato de facto-estándar; de hecho es *más simple* de generar que el de Ollama |
| Parseo de respuesta: `body["message"]["content"]` | **No** — cambia a `body["choices"][0]["message"]["content"]` | Una línea |
| `format: "json"` para forzar JSON mode | **Verificar, no asumir** | Omniroute traduce entre proveedores (`src/lib/providers/*/translators/openai-chat.ts`); `response_format` existe en el código (`json_object`/`json_schema`, 32 referencias) pero su soporte final depende de qué modelo real hay detrás del combo "Forsis" — si es un modelo sin JSON mode nativo, Omniroute podría ignorarlo o emularlo. Bloqueante de Fase 1: probar con una llamada real |
| Reintentos con feedback al modelo si el JSON es inválido (`last_error` → reinyectar mensaje) | **Sí, 100% reutilizable** | Es lógica de aplicación, no de protocolo — más necesaria aún si no se puede garantizar JSON mode |
| `ThreadPoolExecutor` + timeout duro de pared | **Sí, 100% reutilizable** | El hallazgo empírico que lo motivó (colgarse sin excepción) es un riesgo igual o mayor en una API remota sobre red (latencia de red + cola de Omniroute + proveedor upstream) |
| `_parse_multi_step_plan()`, validación contra catálogo cerrado | **Sí, 100% reutilizable** | Agnóstico al transporte |
| `Authorization: Bearer <api_key>` | **Nuevo** | Ollama local no tenía auth; Omniroute sí la requiere (confirmado: `/v1/models` → 401 sin header) |
| Selección de modelo (`self.model = "qwen2.5:7b"`) | **Cambia de semántica** | En Omniroute el "modelo" es el nombre del combo (`"Forsis"`), que internamente hace fallback/failover entre varios modelos reales — el agente ya no necesita saber qué modelo concreto responde |

**Conclusión:** crear `OmnirouteProvider(LLMProvider)` nuevo (~100-150 líneas,
más corto que `OllamaProvider` porque Omniroute ya resuelve fallback/retry de
*modelo* del lado del servidor — el agente solo reintenta por *formato de
respuesta inválido*, no por modelo caído). El contrato `LLMProvider` (base.py)
no cambia ni una línea.

**Ventaja no anticipada en `prototype-review.md`:** Omniroute absorbe
responsabilidades que `OllamaProvider` tenía que resolver él mismo:
- Failover entre modelos (el combo ya hace fallback con 19 estrategias) →
  ya no hace falta lógica propia de "si falla el modelo A, probar B".
- El benchmark de latencias de Ollama local (2.96s warm / 14.27s cold,
  documentado en `prototype-review.md` §12.1) **deja de ser válido** — las
  latencias de Omniroute dependen del proveedor real detrás del combo
  (puede ser un modelo cloud con latencia de red adicional, o un modelo
  gratuito con colas). **Hay que re-medir en Fase 1**, no asumir que el
  budget de timeout (`OLLAMA_TIMEOUT_S`) sigue siendo correcto.

### 1.3 ¿Los Query Objects / Domain Services son reutilizables o están acoplados al prototipo?

**Sin cambios respecto al veredicto de `prototype-review.md` §11.3 — esta
pregunta es ortogonal al tipo de LLM.** Los Query Objects hablan con MariaDB
(`sicrePR`/`sicreGero`), nunca con el LLM. Cambiar Ollama→Omniroute no mueve
esta aguja:

- **No reutilizables (sin cambio de veredicto):** los Query Objects
  validados (Trips, Operators, Fleet, Customers, Billing, Analytics) siguen
  acoplados al esquema real de Forsis/Gero, no al proveedor de LLM.
- **Patrón reutilizable (sin cambio de veredicto):** Query Object pattern,
  Domain Service pattern, Capability pattern — independientes del LLM.

La única razón por la que esta pregunta aparece en el encargo es para
confirmar que **no hay acoplamiento oculto** entre capa de datos y capa de
LLM en el prototipo. Revisado: no lo hay. `Capability.execute(params)` recibe
parámetros ya extraídos por el Planner; nunca ve al LLM directamente.

### 1.4 ¿El patrón Planner/Executor aporta al nuevo agente o era workaround para limitaciones de modelo local?

**Aporta — no es un workaround de modelo local, es más necesario aún con
un modelo remoto.** Razones:

1. **El problema que resuelve (LLM no determinista decidiendo, código
   determinista ejecutando) no depende de dónde corre el modelo.** Un modelo
   cloud grande (GPT-4, Claude) es *menos* propenso a alucinar SQL, pero
   sigue siendo no determinista — el patrón de "el LLM elige una capability
   de un catálogo cerrado, nunca genera SQL libre" es una decisión de
   seguridad/corrección, no una muleta para qwen2.5:7b.
2. **Con Omniroute, el riesgo de latencia/fallo de red aumenta** (host remoto
   vs. `127.0.0.1:11434`), lo que hace *más* valioso tener:
   - `ExecutionResult` con `success`/`error` tipado (nunca una excepción
     cruda llega al usuario).
   - El patrón de reintento con feedback al modelo (`last_error`).
   - El fallback a `TemplateResponseComposer` si el LLM de redacción falla
     o tarda — con latencia de red real este fallback se activará con más
     frecuencia, no menos.
3. **Lo que sí era específico de modelos locales pequeños** (y por tanto
   puede *simplificarse*, no eliminarse):
   - El benchmark multi-modelo (`qwen2.5:7b` para planning, `mistral:7b`
     para respuesta, por limitaciones de RAM/latencia en CPU) — con
     Omniroute el combo "Forsis" puede apuntar a un solo modelo más capaz
     que haga ambos roles razonablemente bien, simplificando
     `ResponseComposer` (quizás ya no se necesite variar de modelo entre
     planning y redacción).
   - El `ThreadPoolExecutor` con timeout de pared por cuelgues de Ollama en
     CPU — sigue siendo necesario pero por otra razón (latencia de red /
     proveedor upstream caído), no por saturación de CPU local.

**Conclusión:** Planner/Executor/Registry se mantienen integros. Lo que
cambia es la configuración operativa alrededor (qué modelo(s) usar para qué
rol, qué timeouts calibrar), no el patrón arquitectónico.

### 1.5 Recomendación de stack: Python/FastAPI vs. PHP/Laravel

**Esta es la decisión con mayor impacto práctico del análisis y donde este
documento diverge más del archivo `deployment-strategy.md` ya escrito.**

`deployment-strategy.md` (generado en la misma sesión que este documento,
por otro agente) **ya asume PHP/Laravel** — el compose propuesto usa
`php:8.3-fpm-alpine`, `Laravel storage`, convención de trafico/liquidaciones.
Este análisis evalúa si esa asunción es correcta dado lo que se descubre
aquí.

**Factores a favor de PHP/Laravel (consistencia con el host):**
- trafico-system, liquidaciones-system y ATLAS son PHP. Un cuarto stack en
  Python rompe la convención operativa (deploy, logs, monitoreo, personal
  que mantiene el código).
- `deployment-strategy.md` ya resolvió topología de red, puertos, volúmenes,
  recursos asumiendo PHP-FPM. Cambiar de stack invalida ese documento de 452
  líneas.
- Integración con Omniroute es **trivial en cualquier lenguaje** porque es
  HTTP + JSON estándar (`php_curl.php` existe literalmente en
  `omniroute/examples/quickstart/` junto al de Python) — este factor, que
  antes podía inclinar la balanza hacia Python por el ecosistema de clientes
  Ollama, **desaparece** con Omniroute. Antes había más tooling Python para
  Ollama (librería oficial, LangChain, etc.); con una API OpenAI-compatible
  pura, PHP tiene exactamente las mismas capacidades (un cliente HTTP y
  `json_decode`).

**Factores a favor de Python/FastAPI (reutilizar prototipo):**
- ~2,500-3,500 líneas de código *probado* (40+ tests) se reutilizan
  directamente (contracts, Planner, Executor, Registry, LLMProvider+base).
  Reescribir esto en PHP/Laravel desde cero cuesta más que adaptar
  `OllamaProvider`→`OmnirouteProvider`.
- Pydantic (contratos) no tiene equivalente directo igual de maduro en PHP;
  reescribir `ExecutionPlan`/`Task`/`TaskDependency` con validación
  estructural fuerte en PHP (Laravel Data / Spatie Data) es factible pero no
  es un port de 1 día.
- El patrón fan-out (`each_row_*`), el ordenamiento topológico de tasks
  (`order_tasks`), y el Executor multi-task con dependencias tipadas son
  ~189 líneas de lógica no trivial ya depurada — reescribirlas introduce
  riesgo de regresión silenciosa.

**Lo que el cambio Ollama→Omniroute cambia en esta decisión (el punto real
del encargo):**

El argumento histórico más fuerte para Python era "el ecosistema de LLM
locales (Ollama, llama.cpp, transformers) es Python-first". **Ese argumento
desaparece con Omniroute** — ya no hay SDK de Ollama que reutilizar, solo
HTTP+JSON, que PHP maneja igual de bien. Esto **debilita** el caso para
Python y **fortalece** el caso para PHP/Laravel por consistencia operativa.

**Recomendación:**

- **Si el criterio dominante es velocidad a MVP + reutilizar las ~40
  horas-persona ya invertidas en el core probado:** mantener Python/FastAPI,
  solo cambiar `OllamaProvider`→`OmnirouteProvider`. Aceptar el costo de
  operar un quinto lenguaje/runtime en el servidor (ya documentado como
  friction en `deployment-strategy.md`: colisión de puerto 8000, volumen
  huérfano `forsis_postgres_data`).
- **Si el criterio dominante es consistencia operativa a largo plazo**
  (mantenimiento, onboarding de otros desarrolladores del equipo que ya
  conocen Laravel, alineación con `deployment-strategy.md` ya aprobado): ir
  con PHP/Laravel, usando el prototipo Python **solo como especificación de
  diseño** (contratos, flujo, patrón Query Object/Capability), no como
  código a portar línea por línea.
- **Posición de este análisis:** dado que `deployment-strategy.md` ya
  invirtió en una topología Docker completa asumiendo PHP-FPM (redes,
  puertos 8099, volúmenes Laravel-style `storage/`), y que el cambio a
  Omniroute **elimina** la única ventaja fuerte de Python (SDK/tooling de
  LLM local), **la recomendación es PHP/Laravel**, usando este documento y
  `prototype-review.md` como el blueprint de diseño a replicar (no el código
  a copiar). Si se ignora esta recomendación y se opta por Python de todos
  modos, `deployment-strategy.md` requiere una revisión antes de Fase 1
  (imagen base, convención de volúmenes, puerto 8000 ya colisiona con un
  `uvicorn` suelto del prototipo abandonado).

---

## 2. Componentes a copiar (si se decide mantener/portar el core Python)

Lista acotada respecto a `prototype-review.md` §12.2, con el cambio de
provider ya resuelto:

```
src/agent/contracts/             # sin cambios
src/agent/planner/planner.py     # sin cambios
src/agent/executor/               # sin cambios (executor, registry, factory, plan_ordering)
src/agent/prompts/builder.py     # sin cambios
src/agent/response/composer.py   # sin cambios (interfaz + TemplateResponseComposer)
src/infrastructure/llm_gateway/base.py   # sin cambios (LLMProvider ABC)
src/infrastructure/llm_gateway/ollama_provider.py  # BASE para escribir omniroute_provider.py:
                                                    #   - copiar _parse_multi_step_plan, reintentos, ThreadPoolExecutor+timeout
                                                    #   - reescribir _call(): endpoint /v1/chat/completions, auth Bearer,
                                                    #     parseo choices[0].message.content
src/infrastructure/database/readonly_session.py    # sin cambios (si se mantiene DB-direct)
```

**Nuevo archivo a crear:** `src/infrastructure/llm_gateway/omniroute_provider.py`
— no es un port, es un provider nuevo que reutiliza la lógica de aplicación
de `OllamaProvider` sobre un transporte distinto.

---

## 3. Bloqueantes de Fase 1 derivados de este análisis

1. **Corregir el puerto objetivo:** usar 20129 (API), no 20130 (dashboard),
   para las llamadas `/v1/chat/completions` — actualizar
   `omniroute-config.md` y el `docker-compose.yml` propuesto en
   `deployment-strategy.md` (`OMNIROUTE_BASE_URL`).
2. **Obtener API key real** del combo "Forsis" y probar una llamada
   `/v1/chat/completions` end-to-end con `format: json` equivalente
   (`response_format: {type: "json_object"}`) para confirmar si el modelo
   real detrás del combo soporta JSON mode fiable, o si hay que depender
   más del bucle de reintento con feedback.
3. **Re-medir latencias** con el combo real — el benchmark de
   `prototype-review.md` (2.96s/14.27s) es de Ollama local y no aplica.
4. **Decisión de stack (Python vs. PHP)** — bloqueante antes de escribir
   cualquier código, igual que la decisión API-only vs. DB-direct ya
   señalada en `prototype-review.md` §12.1.

---

## 4. Resumen ejecutivo

| Pregunta | Respuesta corta |
|---|---|
| ¿Componentes agnósticos al LLM? | Contracts, Planner, Executor, Registry, Factory, PromptBuilder, TemplateResponseComposer, interfaz `LLMProvider` — el core completo (~2,500 líneas) |
| ¿OllamaProvider adaptable? | No se adapta, se reemplaza por `OmnirouteProvider` nuevo que reutiliza ~70% de su lógica (reintentos, parseo multi-step, timeout de pared); el transporte cambia de protocolo propio de Ollama a OpenAI-compatible estándar (más simple) |
| ¿Query Objects/Domain Services reutilizables? | Sin cambio respecto al análisis previo — son ortogonales al LLM; siguen acoplados al esquema Forsis/Gero, no al proveedor |
| ¿Planner/Executor es workaround o aporta? | Aporta — el problema que resuelve (determinismo sobre LLM no determinista) es independiente de dónde corre el modelo, y se vuelve más valioso con latencia/fallos de red remota |
| Stack recomendado | **PHP/Laravel**, dado que Omniroute (HTTP+JSON estándar) elimina la ventaja de ecosistema Python que existía con Ollama local, y `deployment-strategy.md` ya invirtió en topología PHP-FPM. Si se prioriza reutilizar código probado, Python/FastAPI con `OmnirouteProvider` nuevo es la alternativa viable. |

**Documento generado:** 2026-10-03
**Fuentes verificadas en esta sesión:** código fuente de `/home/servidor/omniroute/`
(examples/quickstart, src/shared/validation/schemas/apiV1.ts,
src/lib/modelAliasResolver.ts), pruebas HTTP reales contra puertos
20128/20129/20130, código de `/home/servidor/forsis-agent/src/infrastructure/llm_gateway/`.
