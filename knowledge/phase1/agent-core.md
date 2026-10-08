# Núcleo del Agente IA — Diseño (Fase 1, Agente 2)

**Fecha:** 2026-10-05
**Entregable:** `agent-core.md` (de 2) — ver también `llm-provider.md`
**Fuentes de Fase 0:** `prototype-review.md`, `prototype-reusability-analysis.md`, `omniroute-config.md`, `phase1/PHASE-1-BRIEF.md`
**Código leído:** `/home/servidor/forsis-agent/src/agent/{contracts,planner,executor,prompts,memory}/`, `src/infrastructure/llm_gateway/`, `docs/DECISIONS.md`

---

## 0. BLOQUEANTE #1 — Contradicción de stack: Python (prototipo) vs PHP/Laravel (brief)

Antes que cualquier diseño, hay que resolver esto porque cambia la respuesta a "¿qué se reutiliza?".

| Fuente | Dice |
|---|---|
| `phase1/PHASE-1-BRIEF.md` §Decisiones ya tomadas, punto 2 | **"Stack: PHP/Laravel 11 + PHP 8.3 (consistencia con trafico-system / liquidaciones-system)"** |
| `prototype-review.md` §Resumen, `prototype-reusability-analysis.md` §1.1 | El prototipo reutilizable es **Python** (~202 archivos .py, Pydantic, FastAPI, httpx) y el veredicto "85-90% reutilizable" está calculado sobre código Python |
| `PHASE-1-BRIEF.md` §Decisiones, punto 5 | "provider propio **reutilizando lógica del prototipo**" |

**Las dos afirmaciones son incompatibles tal cual:** no se puede a la vez escribir Laravel 11 y reutilizar 85-90% de código Python. Lo que sí se reutiliza en ambos escenarios es el **patrón** (Planner/Executor/Registry/Capability) y los **contratos** (forma de los datos), no las clases.

**Interpretación que adopta este documento (y que debe confirmarse):**
Este diseño se escribe **agnóstico al lenguaje**: define el patrón, los contratos (como esquemas, no como clases Pydantic) y el flujo. Se marcan explícitamente las piezas donde el lenguaje importa.

Las dos lecturas posibles y su costo:

- **Opción A — Python (FastAPI), reutilizando el prototipo.** El agente es un servicio aparte; `trafico-system`/`liquidaciones-system` lo consumen por HTTP. Se reutiliza el código real (contratos, Planner, Executor, Registry, plan_ordering, prompts, memoria). Costo: un stack más que mantener en la casa.
- **Opción B — PHP/Laravel 11, reimplementando el patrón.** Consistencia operativa con el resto de los sistemas. Costo: se tiran ~2 000 líneas de core probado (40+ tests en verde según `prototype-review.md`) y se rehace el Executor multi-task con dependencias tipadas y fan-out, que es la pieza **más delicada y mejor testeada** del prototipo. Es la parte que no conviene reescribir sin tests equivalentes.

**Recomendación de este agente: Opción A (Python/FastAPI) para el núcleo del agente**, exponiendo `POST /api/v1/chat` como la frontera. Razones:
1. El brief ya define la frontera como HTTP (`forsis-bot` → `POST /api/v1/chat`, punto 3) — el lenguaje detrás de esa frontera es un detalle de implementación para todos los consumidores.
2. La consistencia PHP aplica a los sistemas **de negocio** (trafico/liquidaciones), que no cambian. El agente no es un módulo de ellos.
3. El riesgo de reescribir el Executor en PHP sin su suite de tests es la clase de riesgo que los principios de Fase 1 ("fail-closed", "no asumir") piden evitar.

**Si se confirma la Opción B**, este documento sigue siendo válido como especificación del patrón y de los contratos, pero el presupuesto de Fase 2 debe incluir reescritura + re-testeo del Executor (estimar sobre las 189 líneas de `executor.py` + `plan_ordering.py` + `dependency_resolver.py`, no sobre las 189 solas).

> **Decisión requerida del orquestador antes de Fase 2.** Todo lo que sigue es válido en ambos escenarios salvo donde se indique.

---

## 1. Componentes del núcleo

Cinco piezas, con una sola responsabilidad cada una. La frontera clave es la del principio de `DECISIONS.md` #4 y #7: **el LLM elige, el código ejecuta**.

```
┌────────────────────────────────────────────────────────────────┐
│  Channel Adapter  (forsis-bot / widget)   ← no es del núcleo   │
└───────────────────────────┬────────────────────────────────────┘
                            │ UserRequest
┌───────────────────────────▼────────────────────────────────────┐
│  AgentService (orquestador del turno — stateful por sesión)    │
│   · carga AgentContext        · persiste turno + audit         │
└───┬──────────┬─────────────┬─────────────┬─────────────────────┘
    │          │             │             │
    │     ┌────▼─────┐  ┌────▼─────┐  ┌────▼──────────────┐
    │     │ Planner  │  │ Executor │  │ ResponseComposer  │
    │     │(stateless│  │(determin-│  │(template | LLM)   │
    │     │  + LLM)  │  │  ista)   │  └───────────────────┘
    │     └────┬─────┘  └────┬─────┘
    │          │ lee         │ resuelve
    │     ┌────▼─────────────▼─────┐
    │     │  CapabilityRegistry    │
    │     │  defs (→Planner)  /    │
    │     │  impls (→Executor)     │
    │     └────────────────────────┘
    │
┌───▼────────────────────────┐   ┌──────────────────────────────┐
│ SessionStore (Postgres)    │   │ LLMProvider (OmnirouteProv.) │
│ memoria conversacional     │   │ ver llm-provider.md          │
└────────────────────────────┘   └──────────────────────────────┘
```

### 1.1 Qué se reutiliza y qué cambia

| Componente del prototipo | Veredicto | Cambio requerido |
|---|---|---|
| `contracts/` (UserRequest, AgentContext, ExecutionPlan, Task, TaskDependency, CapabilityCall, ExecutionResult, CapabilityDefinition, ErrorResponse) | **Reutilizar** | `extra="forbid"` (ver §2.1); añadir `tenant/company` y `actor` (ver §2.2) |
| `planner/planner.py` | **Reutilizar** | Inyectar contexto conversacional resuelto (hoy pasa `history` crudo) |
| `executor/executor.py` | **Reutilizar** | Corregir `__init__` duplicado (ver §1.2); añadir gate dry-run para escrituras |
| `executor/registry.py` | **Reutilizar** | Añadir filtrado por permisos (ver §4.2) |
| `executor/plan_ordering.py`, `dependency_resolver.py` | **Reutilizar sin cambios** | — |
| `prompts/builder.py` + `system.py` | **Reutilizar, endurecer** | Ver §5 (crítico por el hallazgo de JSON mode) |
| `memory/conversation_memory.py` + `conversation_resolver.py` | **Reutilizar patrón** | Store en Postgres, no en memoria de proceso (ver §3) |
| `infrastructure/llm_gateway/ollama_provider.py` | **NO reutilizar** | Reemplazar por `OmnirouteProvider` — ver `llm-provider.md` |
| `infrastructure/llm_gateway/base.py` (`LLMProvider` ABC) | **Reutilizar sin cambios** | Es el punto de extensión que anticipaba este cambio |

### 1.2 Bug encontrado en el prototipo (no propagar)

`src/agent/executor/executor.py` define `__init__` **dos veces** (líneas 37-39 y 164-167). En Python gana la segunda, así que el `runtime=None` sí funciona — pero es código muerto confuso y un lector razonable asume lo contrario. **En el nuevo proyecto debe quedar un solo constructor.** No es un bug funcional hoy; es una trampa de mantenimiento.

---

## 2. Contratos

### 2.1 Forma de los contratos (válida en Python o PHP)

Los contratos del prototipo son correctos y se adoptan tal cual en su **forma**. Esquema canónico:

```
UserRequest       { request_id, user_id, text, context{}, company, channel }
AgentContext      { session_id, history[], state{}, resolved_entities{} }
CapabilityCall    { capability_name, parameters{} }
TaskDependency    { source_task_id, source_field: enum, target_parameter }
Task              { task_id, description, status: enum, capability_call?,
                    dependencies[], depends_on[TaskDependency] }
ExecutionPlan     { plan_id, tasks[Task] }
ErrorResponse     { error_code, message, details? }
ExecutionResult   { success, data?, error?, warnings[], metadata{},
                    execution_time_ms?, started_at?, finished_at?,
                    capability_id?, correlation_id?, task_id? }
CapabilityDefinition { id, name, description, version, category, tags[],
                    required_permissions[], input_schema{}, output_schema{},
                    timeout, retry_policy{}, async_supported, experimental }
```

**Cambio obligatorio: validación estricta.** El prototipo permite campos extra (`prototype-review.md` §3.1 ya lo señala). El nuevo proyecto debe **rechazar** campos no declarados (`extra="forbid"` en Pydantic, o validación equivalente). Motivo alineado con fail-closed: un plan del LLM con un campo inventado debe fallar de inmediato y reintentarse, no colarse silenciosamente hasta el Executor.

**`TaskDependencyField` se mantiene como catálogo CERRADO** (`top_label`, `top_value`, `each_row_label`, `each_row_value`). Es una decisión de seguridad, no de conveniencia: impide que el LLM exprese "acceso arbitrario a objetos" vía una ruta tipo `$result[0].foo.bar`. No ampliarlo sin una necesidad de negocio demostrada.

### 2.2 Campos nuevos requeridos por Fase 1

Tres adiciones que el prototipo no tenía y el nuevo alcance exige:

1. **`company` en `UserRequest`** (y propagado a `AgentContext`). El prototipo ya tenía multiempresa en la capa de datos (`readonly_url_for(company)`, `prototype-review.md` §2.1) pero **no en el contrato del agente** — la empresa se decidía por default global. Con Forsis y Gero en juego, el aislamiento multiempresa tiene que viajar en el contrato, no en configuración.
2. **`actor` / identidad y permisos en `AgentContext`**. Necesario para el filtrado del catálogo (§4.2) y para el gate humano de liquidaciones (brief, punto 4). El Registry no puede filtrar por permisos si no sabe quién pregunta.
3. **`mode: "dry_run" | "commit"` en `CapabilityCall`** para capabilities de escritura. El brief exige "dry-run obligatorio en acciones de escritura": eso debe ser un campo tipado del contrato, no una convención de nombres de capability.

---

## 3. Gestión de sesiones

### 3.1 Qué tenía el prototipo y por qué no basta

`conversation_memory.py` resuelve correctamente el problema **conceptual** (referencias tipo "esa guía", "él") con un diseño limpio: `EntityMention` tipada, `ConversationMemoryStore` como puerto abstracto, e `InMemoryConversationMemoryStore` como implementación.

Su propia docstring admite la limitación: *"Persistencia: en memoria de proceso... se pierde en un reinicio"*. Para un MVP desplegado en contenedor eso significa que **cada redeploy borra el contexto de todas las conversaciones activas**. No es aceptable en producción, y menos con múltiples réplicas (cada una tendría su propia memoria y el usuario recibiría respuestas incoherentes según qué réplica atienda).

### 3.2 Diseño de sesiones para el nuevo agente

El puerto `ConversationMemoryStore` **ya existe y es el punto de extensión correcto** — solo hay que implementarlo contra Postgres. Cero cambios en `ConversationResolver` ni en la capa de chat.

```
PostgresConversationMemoryStore implements ConversationMemoryStore
    get(session_id)  → carga los últimos N turnos
    save(memory)     → upsert del turno nuevo
```

**Reglas de sesión:**

| Regla | Valor propuesto | Motivo |
|---|---|---|
| Identidad de sesión | `session_id` = (canal, conversación, usuario) | Una sesión por hilo de Mattermost / pestaña del widget; nunca global por usuario |
| Ventana de contexto | **últimos 6 turnos** o 2 000 tokens, el que se alcance primero | El combo "Forsis" ya inyecta mucho prompt propio (ver `llm-provider.md` §2.3: 4 126 tokens de prompt para un "ping"). La ventana debe ser conservadora. |
| TTL | 24 h de inactividad → sesión cerrada | Evita que "esa guía" resuelva a algo de la semana pasada |
| Qué se persiste | turno (texto usuario, capability elegida, entidades), **no** el plan completo ni los datos de negocio devueltos | Minimiza PII en reposo; los datos de negocio se reconsultan |
| Aislamiento | `company` forma parte de la clave de sesión | Una sesión nunca puede mezclar datos de Forsis y Gero |
| Concurrencia | lock optimista por `session_id` (versión de fila) | Reemplaza el `threading.Lock` del store en memoria, que no sirve entre réplicas |

El esquema concreto de las tablas es del **Agente 1** (`db-schema.md`). Este documento especifica *qué* hay que guardar; no define DDL para no colisionar.

### 3.3 Auditoría (requisito transversal)

Cada turno debe quedar auditado con: `request_id`, `session_id`, `user_id`, `company`, texto del usuario, `plan_id` + plan serializado, capabilities ejecutadas, éxito/error, latencia del LLM, latencia total, modelo real que respondió (ver `llm-provider.md` §2.4 — el combo no garantiza qué modelo contesta, así que registrarlo es obligatorio para poder diagnosticar).

---

## 4. Flujo de un request

### 4.1 Diagrama de flujo (request → plan → execution → response)

```
 (1) UserRequest
      │  {request_id, user_id, text, company, channel}
      ▼
 (2) AgentService.handle()
      ├─ valida contrato (extra=forbid) ────────── falla → ErrorResponse(VALIDATION)
      ├─ resuelve actor + permisos
      └─ SessionStore.get(session_id) → AgentContext
      ▼
 (3) ¿Smalltalk / intent trivial?  (IntentRouter, patrones deterministas)
      │ sí → ResponseComposer(template) ──────────────────────────► (9)
      │ no
      ▼
 (4) ConversationResolver
      └─ inyecta entidades previas ("esa guía" → {folio: 12345})
      ▼
 (5) Planner.plan(request, context)            [STATELESS]
      ├─ Registry.list_definitions(actor) → catálogo FILTRADO por permisos
      ├─ PromptBuilder.build_system_prompt(catálogo)
      └─ LLMProvider.generate_plan(...)   ◄── OmnirouteProvider
             │  reintentos por FORMATO inválido (máx 3 intentos)
             │  validación contra catálogo CERRADO
             ▼
          ExecutionPlan {plan_id, tasks[0..2]}
      │
      ├─ tasks == []  → "no puedo responder eso" (determinista) ──► (9)
      └─ ProviderError → ErrorResponse(LLM_UNAVAILABLE) ─────────► (9)
      ▼
 (6) PlanGuard  [NUEVO respecto al prototipo]
      ├─ ¿alguna task es de ESCRITURA?
      │     sí → fuerza mode=dry_run; si requiere gate humano →
      │          crea solicitud y responde "pendiente de aprobación" ─► (9)
      └─ ¿actor tiene required_permissions de TODAS las tasks?
            no → ErrorResponse(FORBIDDEN), fail-closed ───────────► (9)
      ▼
 (7) Executor.execute_plan(plan)               [DETERMINISTA, SIN LLM]
      ├─ order_tasks()  → valida + orden topológico
      │     inválido → PlanValidationError, NADA se ejecuta
      └─ por cada task en orden:
            ├─ _check_dependencies_ready()
            │     no usable → ExecutionResult(DEPENDENCY_UNRESOLVED), skip
            ├─ fan-out? → una ejecución POR FILA del resultado fuente
            └─ Registry.resolve_implementation() → Capability.execute(params)
                  └─ Tool → API REST (escritura) | Query Object → DB RO (lectura)
      ▼
 (8) ExecutionResult {success, data{task_results}, warnings[]}
      ▼
 (9) ResponseComposer
      ├─ TemplateComposer (determinista)  ← default y fallback
      └─ LLMComposer (redacta, NUNCA decide)   ◄── OmnirouteProvider
            └─ si falla o excede timeout → cae a TemplateComposer
      ▼
(10) RichResponse {texto, componentes UI[], trace{plan_id, model, latencias}}
      └─ SessionStore.save(turno) + AuditLog.write()
      ▼
    Channel Adapter → usuario
```

### 4.2 Decisiones de flujo que difieren del prototipo

| # | Decisión | Por qué |
|---|---|---|
| D-1 | **Catálogo filtrado por permisos en el paso (5), no solo validado en (6)** | Si el usuario no puede ejecutar algo, el Planner no debe ni verlo. Evita que el LLM proponga un plan que luego se rechaza (mala UX) y reduce el prompt. El `Registry.list_definitions()` actual no recibe actor — hay que extenderlo. |
| D-2 | **`PlanGuard` como paso explícito entre Planner y Executor** | El prototipo iba de plan a ejecución directo (solo lectura, riesgo bajo). Con escrituras a `liquidaciones-system` hace falta un punto único donde se aplique dry-run y el gate humano. Un paso nombrado es auditable; un `if` dentro del Executor no. |
| D-3 | **IntentRouter determinista antes del LLM** | El prototipo ya lo tiene (`agent/router/`). Mantenerlo es más valioso ahora: cada llamada al combo cuesta dinero y latencia (p50 ~3.6 s, ver `llm-provider.md` §2.2). Un "hola" no debe costar una llamada al LLM. |
| D-4 | **Fallback a TemplateComposer siempre disponible** | Si el LLM se cae, el agente sigue respondiendo datos correctos con formato pobre, en vez de no responder. Degradación elegante. |
| D-5 | **Máximo 2 tasks por plan (se mantiene el límite del prototipo)** | `MULTI_STEP_INSTRUCTIONS` lo impone hoy. Con el hallazgo de JSON mode (70% de cumplimiento, `llm-provider.md` §3), subir el límite multiplica la superficie de error de formato. Ampliar solo con evidencia de que el formato es estable. |

### 4.3 Presupuesto de latencia del turno

Con los números reales medidos contra Omniroute (no los del benchmark de Ollama, que `prototype-reusability-analysis.md` §1.2 declara inválidos):

| Etapa | p50 | p95 | Techo duro |
|---|---|---|---|
| Planner (1 llamada LLM) | 3.6 s | 10.5 s | **60 s** |
| Planner con 1 reintento de formato | 7 s | 21 s | 60 s (compartido) |
| Executor (lecturas DB RO) | 0.3 s | 2 s | 30 s/capability (ya en `CapabilityDefinition.timeout`) |
| Composer LLM | 3.6 s | 10.5 s | **60 s** |
| **Turno completo** | **~8 s** | **~25 s** | **120 s** |

Derivación del techo en `llm-provider.md` §2.2. Si el turno completo supera 120 s se corta y se responde con error — nunca se deja al usuario esperando indefinidamente.

---

## 5. Prompts

### 5.1 Qué se conserva del prototipo

`PromptBuilder` + `system.py` están bien diseñados y se reutilizan en su estructura:
- Catálogo **dinámico** desde el Registry, nunca hardcodeado.
- El LLM ve solo `nombre(params): descripción` — jamás SQL, nombres de tabla ni infraestructura (cumple `DECISIONS.md` #7).
- Un solo ejemplo concreto en `MULTI_STEP_INSTRUCTIONS`, para que el modelo generalice la *estructura* en vez de memorizar casos. Es la decisión correcta.

### 5.2 Cambios obligatorios (motivados por el hallazgo de JSON mode)

El hallazgo de `llm-provider.md` §3 — **el combo "Forsis" solo devuelve JSON parseable en 70% de los intentos, incluso con `response_format: json_object`** — traslada peso del protocolo al prompt. Cambios:

1. **Prohibición explícita de markdown.** El modo de falla más frecuente observado fue `claude-sonnet-4.5` envolviendo JSON correcto en ```` ```json ````. El prompt debe decir literalmente: *"No uses bloques de código, no uses ``` , no expliques nada. El primer carácter de tu respuesta debe ser `{` y el último `}`."*
2. **Prohibición explícita de tool-calling narrado.** `deepseek-v4-pro` respondió `Voy a buscar la guía 90822 para ti search_guide(guide_id="90822")` — inventó una sintaxis de herramienta ajena al catálogo. El prompt debe decir: *"No describas lo que vas a hacer. No uses sintaxis de llamada a función. Solo el objeto JSON."*
3. **Anti-"no tengo acceso".** `deepseek-v4-flash` respondió *"No tengo acceso a herramientas para buscar información de logística"*. El prompt debe afirmar: *"Tú no ejecutas nada y no necesitas acceso a ningún sistema. Tu única tarea es ELEGIR un nombre de la lista y extraer sus parámetros. Otro componente ejecuta."* Es un reencuadre de rol, y es el fallo más caro porque el modelo se niega a cooperar.
4. **Prompt de reintento más fuerte que el genérico actual.** Hoy dice *"Tu respuesta anterior no fue válida: {error}"*. Debe incluir el formato esperado otra vez **y** el modo de falla concreto detectado (fence de markdown / texto narrado / negativa), porque el reintento puede caer en un modelo distinto del que falló (§2.4 de `llm-provider.md`).
5. **Idioma fijado.** El catálogo y las preguntas son en español; algunos modelos del combo respondieron en inglés. Fijar: *"Los valores de `parameters` se copian literalmente de la pregunta del usuario; no traduzcas identificadores."*

### 5.3 Prompts del núcleo (inventario)

| Prompt | Uso | Criticidad | Nota |
|---|---|---|---|
| `SYSTEM_PLANNER_PROMPT` | rol del Planner | **Crítica** | Añadir el reencuadre del punto 3 |
| `catalog` (generado) | capabilities disponibles | **Crítica** | Ya dinámico; filtrar por permisos (D-1) |
| `RESPONSE_FORMAT_INSTRUCTIONS` | forma de la respuesta | **Crítica** | Añadir puntos 1 y 2 |
| `NO_CAPABILITY_MATCH_INSTRUCTIONS` | salida de escape | Alta | Se conserva; es lo que evita alucinar capabilities |
| `MULTI_STEP_INSTRUCTIONS` | planes de 2 tasks | Media | Se conserva, con el límite de 2 |
| `RETRY_INSTRUCTIONS` | corrección de formato | **Crítica (nuevo)** | Punto 4 |
| Prompts del `LLMComposer` | redacción de la respuesta | Baja | Formato libre; un fallo aquí degrada a template, no rompe nada |

**Regla de oro que no cambia:** un fallo de prompt del Planner debe producir *ninguna acción*, nunca *una acción equivocada*. Por eso la validación contra catálogo cerrado (`capability_name not in valid_names` → reintento) se conserva íntegra: es la red que hace que un prompt imperfecto sea un problema de disponibilidad, no de corrección.

---

## 6. Criterios de verificación para Fase 2

El núcleo se considera correctamente implementado cuando:

1. Un plan con un `capability_name` inexistente **nunca** llega al Executor (test con provider mock).
2. Un plan con dependencia circular falla en `order_tasks()` y **no ejecuta ninguna** task.
3. Una capability de escritura sin `mode=commit` aprobado **no** produce efectos (test contra API en sandbox).
4. Un usuario sin permiso no ve la capability en el prompt **ni** puede ejecutarla si la nombra explícitamente (doble defensa, D-1 + D-2).
5. Reinicio del contenedor a mitad de conversación: "esa guía" sigue resolviendo (sesiones en Postgres, §3.2).
6. Dos sesiones de empresas distintas nunca comparten entidades resueltas.
7. Con el LLM caído, una pregunta de smalltalk sigue respondiendo (D-3) y una pregunta de datos responde con error claro, no con un timeout de 50 minutos (`llm-provider.md` §2.2).

---

## 7. Dependencias con otros agentes de Fase 1

| Necesito de | Qué |
|---|---|
| Agente 1 (`db-schema.md`) | Tablas de sesión, turnos, audit log y solicitudes de aprobación |
| Agente 1 (`architecture.md`) | Puerto/URL de Omniroute en el contenedor (**debe ser 20130, no 20129** — ver `llm-provider.md` §1) |
| Agente 3 (`tools-design.md`) | `CapabilityDefinition` concreta de cada tool; cuáles son de escritura |
| Agente 3 (`permissions.md`) | Modelo de permisos que consume `Registry.list_definitions(actor)` |
| Agente 4 (`channels.md`) | Cómo se construye `session_id` por canal |

---

## 8. Resumen de bloqueantes

| # | Bloqueante | Dónde | Dueño |
|---|---|---|---|
| **B-1** | Stack Python vs PHP/Laravel sin resolver — cambia qué significa "reutilizar el prototipo" | §0 | Orquestador |
| **B-2** | JSON mode de Omniroute no es confiable (70%) | `llm-provider.md` §3 | Mitigado por diseño; requiere validación en Fase 2 |
| **B-3** | El combo no permite fijar modelo (402 Payment Required) y el prompt propio del combo es enorme | `llm-provider.md` §2.3, §2.4 | Requiere decisión de configuración de Omniroute |

---
Generado: 2026-10-05 — Fase 1, Agente 2
