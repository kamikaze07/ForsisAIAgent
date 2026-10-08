# Diseño de la Interfaz Web Standalone — Forsis AI Agent (Fase 1)

**Fecha:** 2026-10-05
**Entregable:** `phase1/web-ui-design.md` — cierra el **BLOQUEANTE-DOC** del Sprint 4 de
`sprint-plan-v2.md`.
**Decisión que lo origina:** `ADR-001-stack-y-secuencia.md` (Decisión 2): *"El agente se valida
mediante una interfaz web propia (login propio + UI de chat) ANTES de integrarlo en las UIs de
trafico-system/liquidaciones-system y antes de cablear Mattermost."*
**Fuentes citadas:** `channels.md` §1 (contrato), §1.7 (timeouts), §1.8 (idempotencia), §1.9
(confirmación), §1.10 (no streaming), §2.6 (widget JS vanilla), §2.8 (**9 estados de UI**);
`tools-design.md` §2.3, §2.5 (S10), §7, §12 (42 tools); `permissions.md` §1.1 (identidades), §5
(24 reglas de denegación); `agent-core.md` §4 (flujo y latencias); `db-schema.md` §3.1-§3.5;
`sprint-plan-v2.md` §2 (HITO) y §3 Sprint 4 (alcance, 12 d.p.); código migrado en
`app/main.py`, `docker/nginx/default.conf`, `docker/app/Dockerfile`.

> **Credenciales:** ningún valor real aparece aquí. Todo secreto se referencia como `${VAR}` o
> `[REDACTED]`.
> **No se modifica código** de `trafico-system`, `liquidaciones-system` ni `forsis-bot`. Este
> documento especifica una aplicación **nueva y aislada**, servida por el propio agente.

---

## 0. Resumen de decisiones

| # | Decisión | Valor |
|---|---|---|
| D1 | Naturaleza de la UI | **Superficie de validación**, no producto final. Se diseña para ser desechable/reemplazable sin coste narrativo |
| D2 | Contrato | **El mismo** `POST /api/v1/chat` de `channels.md` §1. La UI es un tercer *Channel Adapter* delgado, `channel: "ui-standalone"` (ver §6.0 — **ADICIÓN al enum**) |
| D3 | Tecnología frontend | **HTML + CSS + JS vanilla ES2020, sin build step, sin npm**, servido estáticamente por FastAPI (`StaticFiles`). Justificación completa en §5 |
| D4 | Compartir código con el widget futuro | **Sí, pero solo un núcleo sin DOM** (`forsis-agent-core.js`): Transport + Store + mapeo de `status`. El render es **separado** (DOM normal aquí, Shadow DOM allá). Justificación en §5.2 |
| D5 | Estados de UI | **9**, exactamente los de `channels.md` §2.8. La discrepancia documental ("8 estados") se anota en §3.5 |
| D6 | Streaming | **No.** `channels.md` §1.10 decidió request/response; esta UI no reabre la decisión y sí implementa su sustituto (hints a 15 s / 60 s) |
| D7 | Autenticación | Login propio contra `agent_ui_users` (`sprint-plan-v2.md` S1 entregable 6). Cookie `HttpOnly; Secure; SameSite=Lax`. **No** se reutiliza ninguna sesión PHP |
| D8 | Confirmación de escrituras | Imposible aprobar sin haber renderizado el dry-run: el botón **Aprobar** se habilita por un `effects_seen_token` emitido por el propio render (§4.4) |
| D9 | Endpoints nuevos | **9 endpoints ADICIONALES** al contrato de `channels.md`, todos bajo `/api/v1/ui/*` y marcados como ADICIÓN (§6) |
| D10 | Idioma y público | Español de México, operadores/auxiliares/facturación/tráfico/gerencia, no técnicos, Windows + navegador de escritorio, red local |

---

## 1. Alcance y objetivo

### 1.1 Qué es

La UI standalone es **la superficie con la que un humano ejercita el agente completo antes de que
exista cualquier integración**. Su propósito único es permitir que el usuario (Cesar) y un puñado de
usuarios piloto respondan en persona, en el **HITO GO/NO-GO** (`sprint-plan-v2.md` §2), a cinco
preguntas:

1. ¿El agente entiende lo que le pido, en español de México, como lo diría un auxiliar de tráfico?
2. ¿Los datos que devuelve son **ciertos**, y puedo ver **de dónde salieron**?
3. ¿Cuando falla, me lo dice de forma honesta y sin vomitar basura técnica?
4. ¿El flujo de aprobación de una escritura me deja ver el efecto **antes** de aprobar?
5. ¿Es lo bastante rápido y predecible para ponerlo frente a 36 personas?

Todo lo que no sirva a esas cinco preguntas **no entra en el Sprint 4**.

### 1.2 Qué NO es

| No es | Por qué |
|---|---|
| Un producto final para los operadores | Los operadores llegarán por el **widget embebido** (Sprint 5) dentro del sistema que ya usan, sin cambiar de pestaña. Esta UI es el banco de pruebas |
| Un reemplazo de las UIs de trafico-system / liquidaciones-system | No replica ninguna pantalla de negocio. Solo conversa y muestra lo que el agente hizo |
| Un dashboard de BI | La "pantalla de reportes" de `sprint-plan-v2.md` S4 entregable 3 es un **listado de la actividad del agente** (sesiones/mensajes/ejecuciones), no un tablero de KPIs de negocio |
| Un panel de administración | No hay CRUD de usuarios, ni de `channel_identity_map`, ni de tools. El alta de cuentas es por seed/SQL (S1 entregable 7) |
| Un cliente multicanal | No muestra conversaciones de Mattermost ni del widget. Solo las sesiones de canal `ui-standalone` (y, para `admin`, también las de otros canales **en modo lectura** desde la pantalla de depuración) |

### 1.3 Alcance del Sprint 4 (12 d.p.) — alineado a `sprint-plan-v2.md`

**ENTRA:**

| # | Entregable | Mapea a |
|---|---|---|
| E1 | Login propio + logout + bloqueo tras 5 intentos | S4 entregable 1 |
| E2 | Pantalla de chat con los **9 estados** de `channels.md` §2.8 | S4 entregable 2 |
| E3 | Historial de conversaciones del propio usuario (y de todos, si `admin`) | S4 entregable 3 |
| E4 | Detalle de ejecución de tool (qué, con qué argumentos, qué devolvió) | S4 entregable 3, ampliado — lectura de `tool_executions` (`db-schema.md` §3.3) |
| E5 | Bandeja de confirmaciones pendientes + flujo aprobar/rechazar | S4 entregable 4 |
| E6 | Vista de depuración del periodo de validación (plan, tools, latencias, reintentos JSON) | Nuevo, justificado en §2.6: sin ella el HITO se evalúa a ciegas |
| E7 | Render de reportes: tabla + totales + exportación CSV/XLSX | Nuevo mínimo viable (§3.3). Es lo que convierte "respondió un párrafo" en "me sirve" |
| E8 | Citación de fuente del dato (`sources[]`, `tools-design.md` §2.5 S10) | Regla S10 es obligatoria: *"sin fuente, no se afirma"* |
| E9 | Stub de dry-run/confirmación para alcanzar los 9 estados sin tools L2 reales | S4 entregable 2 (explícito) |
| E10 | Los 9 endpoints `/api/v1/ui/*` de §6 | Nuevo, especificado aquí |

**NO ENTRA (va a S4-bis, POSTERIOR al HITO):** tema oscuro, responsive móvil real (solo
"no se rompe"), notificaciones push/badge en tiempo real, edición de mensajes, búsqueda
full-text en el historial, PWA/offline, gráficas, adjuntar archivos al chat, multi-idioma,
administración de usuarios desde la UI, i18n, atajos avanzados.

> **Regla de disciplina de alcance** (`sprint-plan-v2.md` S4, "Riesgo del sprint"): si al
> implementar aparece algo deseable que no está en E1-E10, **no se amplía el sprint en vuelo**; se
> registra como backlog de **S4-bis**, que ocurre después del HITO. Este documento ya aplicó esa
> regla a la lista de arriba.

### 1.4 Usuarios y su entorno

| Perfil | Qué hará en esta UI | Consecuencia de diseño |
|---|---|---|
| Gerencia (validador del HITO) | Preguntar, leer reportes, aprobar/rechazar, revisar depuración | Necesita la vista de depuración legible, no logs |
| Tráfico / auxiliares administrativos | Consultas de guías, liberación, pases de descarga | Lenguaje llano, cero jerga de tools en la pantalla principal |
| Facturación | Consultas de liquidaciones y tarjeta deudor, exportar | Export CSV/XLSX es requisito, no adorno |
| Operadores | Consultas puntuales | Teclado simple, un solo campo, Enter envía |
| TI / soporte | Diagnóstico con `trace_id` | `trace_id` copiable en todo error |

Entorno fijo: **Windows, navegador de escritorio evergreen (Chrome/Edge), red local**. No se
diseña para móvil ni para navegadores antiguos (ver BLOQUEANTE **B-U6**).

---

## 2. Inventario de pantallas

Siete pantallas, una ruta cada una. Ninguna requiere más de un nivel de navegación desde el chat.

| # | Pantalla | Ruta | Rol mínimo | Propósito en una línea |
|---|---|---|---|---|
| **P0** | Login | `/ui/login` | — | Entrar con cuenta propia del agente |
| **P1** | Chat | `/ui/chat` *(home)* | `validador` | Conversar: la pantalla donde se pasa el 90% del tiempo |
| **P2** | Historial de conversaciones | `/ui/historial` | `validador` | Volver a una sesión pasada y releerla |
| **P3** | Detalle de ejecución de tool | `/ui/ejecucion/{tool_execution_id}` | `validador` | Qué se ejecutó, con qué argumentos, qué devolvió |
| **P4** | Confirmaciones pendientes | `/ui/confirmaciones` | `validador` | Bandeja del gate humano |
| **P5** | Depuración (solo periodo de validación) | `/ui/depuracion` | `admin` | Plan, tools, latencias, reintentos del JSON mode |
| **P6** | Mi cuenta / cerrar sesión | `/ui/cuenta` | `validador` | Cambiar contraseña, ver rol, cerrar sesión |

Roles: `agent_ui_users.role ∈ {admin, validador}` (`sprint-plan-v2.md` S1 entregable 6). Nada más.
`admin` = `validador` + ver datos de otros usuarios + P5.

### 2.1 P0 — Login propio

**Por qué existe un login propio y no SSO:** `permissions.md` §1.1 define la identidad **I2 —
"Login propio del agente"**, cuyo papel es *vincular* al humano (I1) con las cuentas de servicio
(I3/I4) y **no** ser credencial para los ERP. La UI standalone es precisamente la materialización de
I2. Reutilizar la sesión PHP de liquidaciones sería heredar su postura (MD5 sin salt, 77 usuarios con
contraseña vacía — `permissions.md` §5 D-1, `channels.md` B-C3), y reutilizar la de tráfico
obligaría a que la UI viva dentro de ese sistema, que es justo lo que ADR-001 posterga.

| Elemento | Especificación |
|---|---|
| Campos | `usuario` (texto, autofocus, `autocomplete="username"`), `contraseña` (`autocomplete="current-password"`) |
| Envío | `POST /api/v1/ui/login` (§6.1) |
| Hash | argon2id (preferido) o bcrypt. **Nunca MD5** — `sprint-plan-v2.md` S1 E6 es explícito |
| Cookie | `forsis_agent_ui_session`, `HttpOnly; Secure; SameSite=Lax; Path=/`, TTL **8 h** (jornada), renovada por actividad |
| Sin "recordarme" | `sprint-plan-v2.md` S4 E1 lo excluye en esta fase |
| Antifuerza bruta | 5 intentos fallidos por `(usuario)` **y** por IP ⇒ bloqueo **15 min**, respuesta `429` con mensaje explícito y tiempo restante en minutos |
| Mensaje de error | **Genérico**: *"Usuario o contraseña incorrectos."* Nunca "ese usuario no existe" |
| Fuera de alcance | Recuperación de contraseña por correo, 2FA, OAuth. Un `admin` resetea por SQL |
| Empresa | **No se elige en el login.** Se elige por conversación (§2.2) porque `company` no tiene default (`channels.md` §1.3 regla 3) |

### 2.2 P1 — Chat principal

Es la pantalla hogar. Estructura de tres zonas (wireframe en §8.2):

| Zona | Contenido |
|---|---|
| Barra superior | Logo/nombre · **selector de empresa `FORSIS | GERO`** (obligatorio, sin default) · usuario · enlaces a P2/P4/P5 · badge con nº de confirmaciones pendientes |
| Hilo | Lista de turnos (usuario / agente), con los 9 estados de §3.5, tarjetas de `components`, bloques de reporte, citación de fuente |
| Compositor | Textarea + botón Enviar + indicador de estado + botón Cancelar durante `pensando` |

**Selector de empresa — regla dura.** Al entrar, el selector arranca **sin valor** y el botón
Enviar está deshabilitado con el hint *"Elige empresa (FORSIS o GERO) para empezar."* Esto
implementa en la UI la lección de `channels.md` §1.3 regla 3 y `permissions.md` §5 D-7: *el default
silencioso a `forsis` es la fuente de error más peligrosa*. Cambiar de empresa **cierra la sesión
conversacional y abre una nueva** (`session_id` incluye `company`, `channels.md` §3.5): la UI avisa
*"Empiezo una conversación nueva: cambiaste de empresa."*

### 2.3 P2 — Historial de conversaciones

Lee `agent_sessions` + `agent_messages` (`db-schema.md` §3.1, §3.2) vía `GET /api/v1/ui/sessions`
y `GET /api/v1/ui/sessions/{id}` (§6.3, §6.4).

| Elemento | Especificación |
|---|---|
| Lista | Una fila por sesión: fecha/hora, empresa, primeras ~60 chars del primer mensaje del usuario, nº de turnos, `state` de la sesión, nº de tools ejecutadas, indicador si tuvo errores |
| Filtros | Rango de fechas (por defecto últimos 7 días), empresa, `status` del último turno, "solo con errores", "solo con escrituras" |
| Orden | `updated_at DESC` (índice `ix_sessions_updated` ya existe) |
| Paginación | 25 por página, `?limit&offset`. Sin scroll infinito (peor para auditar) |
| Aislamiento | `validador` ve **solo sus** sesiones; `admin` ve todas y la columna "usuario" aparece. Criterio A6 del Sprint 4 |
| Detalle | Abrir una sesión la renderiza **en modo lectura** con el mismo render del chat (misma función, `readOnly: true`), para que lo que el usuario releyó sea literalmente lo que vio |
| Reanudar | Botón *"Continuar esta conversación"* solo si la sesión tiene < 24 h (TTL de sesión, `agent-core.md` §3.2). Si expiró: *"Esta conversación ya expiró; puedo empezar una nueva con el mismo tema."* |

### 2.4 P3 — Detalle de ejecución de tool

La pantalla que convierte al agente de caja negra en sistema auditable. Lee `tool_executions`
(`db-schema.md` §3.3) vía `GET /api/v1/ui/executions/{id}` (§6.5).

| Bloque | Campos mostrados | Origen |
|---|---|---|
| Identidad | `tool_name` (+ nombre legible), `category`, clase de riesgo **L0/L1/L2** (`tools-design.md` §12), `id` copiable | `tool_executions` |
| Estado | `status` (`proposed`/`approved`/`rejected`/`running`/`success`/`failed`) con color, `requires_approval` | `tool_executions.status` |
| Argumentos | `parameters_in` renderizado como tabla clave/valor, **enmascarado** según `tools-design.md` §8.3 / `permissions.md` §6.3 | `parameters_in` |
| Resultado | `result_out`: si es tabular ⇒ tabla; si no ⇒ JSON con plegado. Nº de filas devueltas | `result_out` |
| Error | `error_message` **traducido** (§7.3) + bloque técnico plegado para `admin` | `error_message` |
| Tiempos | `execution_time_ms`, `created_at`, `completed_at` | `tool_executions` |
| Contexto | Empresa, `session_id` (enlace a P2), `trace_id`, mensaje del usuario que lo originó (enlace al turno) | join con `agent_sessions`/`agent_messages` |
| Si fue L2 | Bloque "Dry-run" con `plan.effects[]`, `preconditions[]`, `blast_radius`, `reversibility` (`tools-design.md` §2.3) + quién aprobó y cuándo (`approval_requests`) | `approval_requests` §3.4 |

**Regla de contenido:** esta pantalla **no interpreta**. Muestra lo que la BD guardó. Si
`parameters_in` tiene un campo que el diseñador no previó, se renderiza igual como clave/valor; no
se oculta.

**Regla de enmascarado:** la UI **no enmascara**; consume lo ya enmascarado por el agente antes de
persistir (`tools-design.md` §8.3). Si un valor llega en claro y debía ir enmascarado, es un bug del
agente, no de la UI — y la UI lo delata al mostrarlo.

### 2.5 P4 — Bandeja de confirmaciones pendientes (gate humano)

Lee `approval_requests` (`db-schema.md` §3.4) vía `GET /api/v1/ui/approvals` (§6.6).
Flujo completo en §4.

| Elemento | Especificación |
|---|---|
| Lista | Una tarjeta por aprobación `pending`: `summary`, `action_code`, `risk_level`, empresa, quién la originó, **cuenta atrás** hasta `expires_at` |
| Orden | Las que expiran antes, primero |
| Alcance | Solo las propias. `channels.md` §1.9: *"quién puede confirmar = el mismo `actor.subject` que originó la petición"*. Ni un `admin` aprueba por otro |
| Expiradas | Se muestran 1 h más, en gris, con sello **VENCIDA** y el motivo. No desaparecen en silencio |
| Abrir | Lleva al **panel de aprobación** (§4.3), que es la única superficie donde se puede aprobar |
| Badge | El contador de la barra superior de P1 se refresca al cargar la página y tras cada turno. **Sin polling continuo** (sería inventar tiempo real en una UI de validación) |
| Vacía | Estado vacío honesto: *"No tienes confirmaciones pendientes."* |

### 2.6 P5 — Vista de depuración (solo durante la validación)

**Por qué existe.** Dos hechos la hacen obligatoria, no un lujo:

1. `agent-core.md` §0 y `ADR-001` §"No decidido aquí": el **JSON mode del combo "Forsis" es fiable
   solo al 70% crudo / 80% con salvage**. Habrá reintentos y fallos. Sin una vista que los muestre,
   el usuario en el HITO no puede distinguir *"el agente no sabe hacer eso"* de *"el modelo devolvió
   basura y se reintentó"*. Son diagnósticos opuestos con acciones opuestas.
2. `llm-provider.md` (vía `channels.md` §1.5.3) declara `llm_model_real` **obligatorio** porque el
   combo enruta cada llamada a un proveedor distinto: *"sin eso, un fallo intermitente de formato es
   imposible de diagnosticar"*.

| Bloque | Contenido | Origen |
|---|---|---|
| Turno | Mensaje del usuario, `status` final, `trace_id`, `plan_id` | `trace` del `ChatResponse` + `agent_messages` |
| Plan generado | `tasks[]` con tool, argumentos y dependencias, en tabla. Máx 2 tasks (`agent-core.md` §4.2 D-5) | `plans` / `agent_messages.tool_calls` |
| Tools invocadas | Lista con enlace a P3 cada una, con su `status` y `execution_time_ms` | `tool_executions` |
| Latencias | Desglose `llm` / `tools` / `total` en ms, contra el presupuesto de `agent-core.md` §4.3 (p50 8 s, p95 25 s, techo 120 s), con barra visual y marca del techo | `trace.latency_ms` |
| Reintentos del JSON mode | `llm_attempts`, y por capa: `json_ok` / `salvage` / `failclosed` | `trace.llm_attempts` + métricas (§6.9) |
| Modelo real | `llm_model_real` por llamada | `trace.llm_model_real` |
| Agregados del periodo | Tasa de `status` por tipo, tasa de salvage, p50/p95 de latencia, top de tools, nº de denegaciones por `error_code` de `permissions.md` §5 | `GET /api/v1/ui/metrics` (§6.9) |

| Regla | Valor |
|---|---|
| Acceso | Rol `admin` **y** flag `AGENT_UI_DEBUG_ENABLED=true`. Ambas condiciones |
| Temporalidad | Pensada para el periodo de validación. Al pasar el HITO, se apaga con el flag; el código no se borra (es la herramienta de diagnóstico de los sprints 5-9) |
| Relación con `debug` del contrato | `channels.md` §1.5.3: el objeto `debug` (plan serializado, SQL, prompts) **requiere rol de soporte**. La UI envía `debug: true` **solo** si el usuario es `admin` y el flag está activo; en cualquier otro caso envía `debug: false` |
| Datos de negocio | `trace` no contiene datos de negocio (`channels.md` §1.5.3). El bloque "Tools invocadas" sí, vía P3 — y por eso P3 respeta el aislamiento por usuario |

### 2.7 P6 — Mi cuenta

Mínima: usuario, `display_name`, rol, `last_login_at`, cambio de contraseña
(`POST /api/v1/ui/password`, §6.8) y **Cerrar sesión**. Cambiar la contraseña invalida las demás
sesiones del usuario.

---

## 3. Diseño del chat

### 3.1 Composición del mensaje

| Aspecto | Decisión | Razón |
|---|---|---|
| Control | `<textarea>` autoexpansible, 1→6 filas, `maxlength="4000"` | `channels.md` §1.3 regla 2: > 4000 ⇒ `413`. Se impide en el cliente **y** se valida en el servidor |
| Contador | Aparece a partir de 3500 chars: *"3 512 / 4 000"* | No distraer en el caso normal |
| Enviar | **Enter** envía · **Shift+Enter** salto de línea | Convención universal de chat; los usuarios no técnicos ya la conocen de WhatsApp |
| Deshabilitado cuando | (a) empresa sin elegir, (b) turno en vuelo, (c) **hay una confirmación pendiente en el hilo** | (c) es regla explícita de `channels.md` §2.8: *"El input de texto se **deshabilita** mientras hay confirmación pendiente"* |
| Sugerencias iniciales | 4 chips de ejemplo en la sesión vacía, redactados en el español de los usuarios: *"¿Qué guías pendientes tiene el cliente 412?"*, *"Saldo de tarjeta deudor del operador …"*, *"Guías liberadas de esta semana"*, *"¿Qué puedes hacer?"* | Un campo de texto vacío frente a un no técnico produce parálisis. Los chips enseñan el dominio sin manual |
| Adjuntos | **No** (S4-bis) | El contrato no acepta adjuntos (`channels.md` §1.3) |
| Autocompletado de folios | **No** en S4 | Requeriría endpoints de búsqueda incremental: alcance de S4-bis |
| ULID de cliente | Cada envío genera un ULID y lo usa en `Idempotency-Key: ui:{session_id}:{client_msg_ulid}` | Análogo a la clave del widget (`channels.md` §1.8); estable entre reintentos de red. Ver §6.0 |

**Borrador local.** El texto no enviado se guarda en `sessionStorage` por `session_id`. Si el
navegador se recarga a mitad de redacción, no se pierde. No se guarda en `localStorage` (sería
persistir contenido de negocio en el equipo del usuario sin necesidad).

### 3.2 Render de respuestas (incluidas las largas)

**Qué se renderiza, en este orden, por turno del agente:**

1. **Burbuja de `answer`** — markdown **mínimo**: `**negrita**`, `` `código` ``, listas `-`/`1.`,
   saltos de línea. **Nada más.** Todo se escapa primero y luego se aplican las sustituciones; no
   hay `innerHTML` con contenido del modelo. Regla idéntica a `channels.md` §2.8 (*"sin HTML crudo,
   todo escapado"*).
2. **Tarjetas de `components[]`** — `type: "guide-card"` y los que vayan apareciendo. El render es
   **genérico y a prueba de tipos desconocidos**: `title` + tabla de `fields[{label,value}]` +
   `actions[]`. Un `type` que la UI no conoce se dibuja con el render genérico, nunca se oculta
   (ocultar datos que el agente sí devolvió es el peor fallo posible en una UI de validación).
3. **Bloque de reporte** si aplica (§3.3).
4. **Pie de fuente** (§3.4).
5. **Pie técnico discreto**: `trace_id` (siempre copiable, en todo turno, no solo en errores — es
   más barato que explicarle al usuario cómo encontrarlo) y, si `admin`, enlace *"Ver detalle"* a P5.

**Respuestas largas.** El usuario puede pedir *"dame el detalle de las 40 guías"*.

| Regla | Valor |
|---|---|
| Colapsado por altura | Una burbuja de `answer` > **420 px** se colapsa a 420 px con degradado inferior y botón **"Mostrar todo"** / **"Mostrar menos"**. Nunca se trunca el texto en el DOM: se limita la altura visible. Ctrl+F del navegador debe poder encontrar todo |
| Scroll | El hilo hace autoscroll al final **solo si** el usuario ya estaba al final (umbral 80 px). Si estaba leyendo arriba, aparece el botón flotante **"↓ Nuevo mensaje"**. Robar el scroll a alguien que está leyendo es la queja #1 de las UIs de chat |
| Copiar | Botón **Copiar** por turno del agente (copia `answer` en texto plano) |
| Bloques tabulares | Siempre van al bloque de reporte (§3.3), nunca a markdown dentro de la burbuja: una tabla de 40 filas en markdown es ilegible y no se puede exportar |
| Límite de turnos en el DOM | Se renderizan los últimos **50** turnos; los anteriores se cargan con **"Cargar mensajes anteriores"**. Evita que una sesión larga arrastre el render |

### 3.3 Render de REPORTES

Es el entregable que convierte *"el agente contestó"* en *"el agente me sirve"*, y el que
facturación y gerencia van a juzgar en el HITO.

**Cuándo se activa.** Cuando un `tool_executions.result_out` del turno es **tabular**: un
`{columns: [...], rows: [[...]]}` o un array de objetos homogéneos de ≥ 2 filas. La UI lo detecta
estructuralmente; **no** interpreta el texto del modelo. Si el agente devuelve tabla, hay tabla; si
no, no se fabrica.

**Anatomía del bloque de reporte:**

```
┌─ REPORTE ───────────────────────────────────────────────────────────┐
│ Guías liberadas · FORSIS · 01–05 oct 2026            48 filas       │
│ Fuente: traf.guias_liberadas_reporte (L0) · 00:00.42 · ver detalle  │
├─────────────────────────────────────────────────────────────────────┤
│ Guía ▲   │ Cliente        │ Estatus      │ Fecha      │  Importe    │
│ 90822    │ CLIENTE 412    │ Liberada     │ 03/10/2026 │   4,210.00  │
│ …        │                │              │            │             │
├─────────────────────────────────────────────────────────────────────┤
│ TOTALES  │ 48 guías       │              │            │ 198,430.50  │
├─────────────────────────────────────────────────────────────────────┤
│ [Exportar CSV]  [Exportar XLSX]            Mostrando 25 de 48  ▸    │
└─────────────────────────────────────────────────────────────────────┘
```

| Aspecto | Especificación |
|---|---|
| Encabezado | Título (del `answer` o del `summary` de la tool), empresa, rango si aplica, **nº total de filas** |
| Línea de fuente | `tool_name` + clase de riesgo + `execution_time_ms` + enlace a **P3** (detalle de ejecución). Materializa §3.4 |
| Orden | Click en cabecera ordena **en el cliente** (asc/desc). No se re-consulta al servidor: el dataset ya está completo en memoria |
| Paginación | 25 filas visibles, "Mostrar 25 más". Sin paginación de servidor en S4 |
| Formato de números | `toLocaleString('es-MX')`. Importes con 2 decimales y separador de miles. Nunca notación científica |
| Formato de fechas | `dd/mm/aaaa` (y `dd/mm/aaaa HH:mm` si hay hora). Zona **America/Mexico_City** siempre; nunca UTC a la vista del usuario |
| **Totales** | Fila `TOTALES` fijada al pie. Se suman **solo** las columnas que el agente declaró numéricas en el esquema del resultado. **La UI no decide qué es sumable por heurística de contenido** — ver regla dura abajo |
| Celdas vacías | `—` (guion em), no `null`, no `undefined`, no cadena vacía ambigua |
| Texto largo en celda | Truncado visual con `title` completo en tooltip; el valor íntegro va al export |
| Estados legacy | Se muestran **tal cual los devuelve el sistema** (`<Por Pagar>`, `Cancelado 2`…). `tools-design.md` §2.5 S4: los estados son texto libre heredado. La UI **no normaliza ni embellece** estados |
| Acentos y latin1 | El agente transcodifica `sicrePR` latin1→UTF-8 (`tools-design.md` §2.5 S5). La UI solo exige `charset=utf-8`. Si aparece `Ã³` en pantalla, es un bug del agente que esta UI deliberadamente **no** parchea (ocultarlo sería perder la señal) |

> **Regla dura de totales (anti–"dato plausible pero falso").** La UI **suma en el cliente solo si**
> el resultado trae la columna marcada como numérica en su esquema. Si no hay esquema, **no se
> muestra fila de totales**; en su lugar: *"No puedo sumar esta columna automáticamente."* Esto es la
> traducción a UI de `tools-design.md` §2.5 S3 (importes conviven como `varchar`/`double`/`*Letra`):
> un `parseFloat` optimista sobre `"$1,234.00 PESOS"` produce `1` y nadie lo nota. **Registrado como
> BLOQUEANTE B-U2** porque requiere que el agente declare tipos de columna, y hoy
> `tool_executions.result_out` es un JSONB sin esquema.

**Exportación.** `POST /api/v1/ui/export` (§6.7), que **re-lee el `tool_execution_id` del
servidor** y genera el archivo ahí.

| Decisión | Razón |
|---|---|
| El export se genera **en el servidor**, no en el navegador | (a) XLSX en JS vanilla sin build step exigiría embarcar una librería grande; en Python es `openpyxl`. (b) El servidor exporta **el dataset completo**, no las 25 filas pintadas. (c) Queda rastro auditable del export en `audit_records` |
| CSV | UTF-8 **con BOM** (`\xEF\xBB\xBF`) y separador `,`. El BOM es obligatorio: sin él, Excel en Windows en español destroza los acentos — y todos los usuarios son Windows + Excel |
| XLSX | `openpyxl`, una hoja, fila de encabezado congelada, formato de número en columnas de importe, fila de totales con `SUM()` **real** (fórmula, no valor) |
| Nombre de archivo | `forsis_{tool}_{EMPRESA}_{aaaammdd_hhmm}.{csv,xlsx}` |
| Alcance | Solo `tool_execution_id` que pertenezcan a una sesión del propio usuario (o cualquiera si `admin`). Mismo aislamiento que P2/P3 |
| Tamaño | Tope **20 000 filas**. Por encima: *"El reporte es muy grande para exportar aquí; acótalo por fechas."* Honesto y acotado |

### 3.4 Citación de la fuente del dato

**Es un requisito, no una cortesía.** `tools-design.md` §2.5 **S10**: *"Toda respuesta del agente que
cite cifras debe adjuntar `sources[]`; sin fuente, no se afirma."*

| Nivel | Qué se muestra | Dónde |
|---|---|---|
| L1 — Pie de turno | *"Fuente: `traf.guias_liberadas_reporte` · tráfico · FORSIS · hace 2 min"* con nombre legible: *"Reporte de guías liberadas (trafico-system)"* | Debajo de cada respuesta del agente que contenga datos |
| L2 — Por bloque | La línea de fuente del encabezado del reporte (§3.3) | Dentro del bloque |
| L3 — Detalle | Enlace **"ver detalle"** → **P3**: argumentos exactos, resultado crudo, latencia, momento | Nueva página |
| L4 — Varias fuentes | Si el turno ejecutó 2 tools, el pie lista las dos, numeradas, y los bloques referencian `[1]` / `[2]` | Pie de turno |

**Y el caso más importante: cuando NO hay fuente.** Si el turno respondió **sin ejecutar ninguna
tool** (smalltalk, `no_capability`, o el `IntentRouter` determinista de `agent-core.md` §4.1 paso 3)
la UI muestra una marca explícita y visualmente distinta:

```
ⓘ Respuesta sin consulta a los sistemas — no contiene datos de Forsis.
```

Esto es lo que impide que una alucinación con pinta de dato pase por consulta real. Es **el control
de UI más valioso de todo el documento**: un número sin esa marca viene de una tool; un número con
esa marca es, por definición, sospechoso y se trata como tal.

> **BLOQUEANTE B-U1.** `ChatResponse` (`channels.md` §1.5) **no tiene campo `sources[]`**.
> Hoy solo trae `trace.tools_executed[]` (nombres de tool, sin `tool_execution_id`, sin tiempos por
> tool, sin mapeo a qué parte del `answer` sustenta cada una). La UI puede implementar L1 y L2 de
> forma degradada con `trace.tools_executed[]`, pero **L3 (enlace a P3) es imposible** sin el `id`.
> Resolución propuesta: añadir al contrato
> `trace.tool_executions: [{id, tool, class, rows, ms}]`. Es una **adición retrocompatible**
> (campo nuevo dentro de `trace`, que ya es obligatorio) y se especifica en §6.0 como ADICIÓN.

### 3.5 Los 9 estados de UI

Correspondencia **1:1** con `channels.md` §2.8, sin reinterpretar nada. 7 vienen del `status` del
contrato (`channels.md` §1.5.2) + `dry-run` (derivado del contenido de `confirmation`) + `pensando`
(local).

| # | Estado UI | Origen | Render en la UI standalone | Interacción |
|---|---|---|---|---|
| **1** | **pensando** | **local**, del envío a la respuesta | Burbuja con tres puntos animados + `aria-live="polite"`: *"El asistente está pensando."* A los **15 s**: *"Sigo trabajando en esto…"*. A los **60 s**: *"Está tardando más de lo normal."* | Botón **Cancelar** → `AbortController.abort()`. Aviso honesto: *"Dejé de esperar. Si la acción ya se había enviado, puede completarse."* La UI **no finge** cancelar el turno del servidor |
| **2** | **respuesta** (`ok`) | `status: ok` | Burbuja con `answer` (markdown mínimo, todo escapado) + tarjetas de `components` + bloque de reporte + pie de fuente | Copiar · Exportar (si hay reporte) · ver detalle |
| **3** | **aclaración** (`clarification_needed`) | `clarification` | Burbuja con `question` + **chips** de `options` como `<button>` reales. Si `options` viene vacío, se habilita el textarea con el placeholder puesto en `missing[0]` | Click en chip ⇒ nuevo `POST` con `inputs` poblado. El chip evita que el usuario teclee "FORSIS" mal (misma razón que el widget) |
| **4** | **dry-run** | `confirmation.dry_run_result` dentro de `confirmation_required` | Bloque de fondo neutro, encabezado **"Simulación — no se ha hecho ningún cambio"**, tabla de campos del `dry_run_result`, `warnings[]` en ámbar. Detalle completo en §4.2 | **Solo lectura.** Debe *leerse* como informativo, no como acción |
| **5** | **confirmación requerida** (`confirmation_required`) | `confirmation` | Panel con borde de acento, `summary` en negrita, badge `risk_class` (`L2`), **cuenta atrás** a `expires_at`, botones **Confirmar** (primario) / **Cancelar** (secundario). **El textarea se deshabilita** mientras esté pendiente | Confirmar ⇒ `POST /api/v1/chat/confirm` con `decision:"approve"` e `Idempotency-Key` fijada **al montar el panel**, no al hacer clic ⇒ doble clic = una sola solicitud. Al expirar: botones deshabilitados + *"La confirmación venció. Vuelve a pedirlo."* |
| **6** | **denegado** (`denied`, HTTP 403) | 403 | Burbuja con icono de candado y `answer` **tal cual** | **Sin reintento.** No se sugiere "pide permisos a TI" salvo que el propio `answer` lo diga. La UI **no traduce** el `error.code` de `permissions.md` §5 a prosa propia: el `answer` ya explica causa y vía humana |
| **7** | **sin capacidad** (`no_capability`) | `status: no_capability` | Burbuja neutra con `answer` | Botón **"Ver qué puedo hacer"** ⇒ lista las capabilities visibles para ese actor (`GET /api/v1/ui/capabilities`, §6.10) |
| **8** | **degradado** (`degraded`) | `status: degraded` | Respuesta **normal** (datos correctos) + nota al pie discreta: *"Respuesta con formato simplificado."* | Ninguna. `agent-core.md` §4.2 D-4: los **datos son correctos**, solo la redacción es pobre. No se alarma al usuario con rojo |
| **9** | **error** (`error`) | 4xx/5xx o fallo de red | Burbuja con borde rojo + `answer` + **`trace_id`** en texto pequeño seleccionable + botón **Copiar trace_id** | **Reintentar** solo si `error.retryable == true`. Con `LLM_UNAVAILABLE` (502) **no** se ofrece reintentar — `channels.md` §1.6.1: *"ofrecer un botón que se sabe inútil es peor que no ofrecerlo"* |

**Nota sobre la discrepancia documental.** `channels.md` §2.8 define la tabla con **9 filas** y
`sprint-plan-v2.md` S4 entregable 2 también enumera **9** (pensando, respuesta, aclaración, dry-run,
confirmación requerida, denegado, sin capacidad, degradado, error), con criterio de aceptación
**A4: 9/9 PASS**. Otros pasajes de la documentación de fase 1 se refieren informalmente a *"8
estados"* (contando los 7 valores del enum `status` + `pensando`, y fundiendo **dry-run** dentro de
**confirmación requerida**, ya que ambos nacen del mismo `status: confirmation_required`).
**Esta UI implementa 9**, y los trata como dos estados visuales distintos a propósito: el bloque de
simulación debe poder leerse **sin** que haya nada que aprobar (p. ej. una expiración, o un dry-run
cuyo `valid: false` nunca llega a ofrecer botones). Fundirlos haría imposible la garantía de §4.4.

**Dos reglas transversales, heredadas literalmente de `channels.md` §2.8:**

1. **La UI nunca inventa texto de estado.** Todo lo que el usuario lee *sobre el resultado* viene de
   `answer`. Lo único que la UI redacta son los estados **locales**: pensando, cancelado, sin red,
   borrador guardado, sesión expirada.
2. **`trace_id` siempre visible en errores.** Es lo que convierte *"el agente falló"* en un ticket
   diagnosticable, dado que el modelo que respondió varía por llamada (`channels.md` §1.5.3).

### 3.6 Estados locales adicionales (no son estados del contrato)

No amplían los 9; son condiciones del navegador y se renderizan como avisos de barra, no como
turnos del agente:

| Condición | Render |
|---|---|
| `navigator.onLine === false` | Barra ámbar fija: *"Sin conexión. Tu mensaje se enviará cuando vuelva la red."* El envío queda en cola (1 mensaje máx) |
| Fallo de red (`TypeError` de `fetch`) | Estado **9 error** con `answer` local: *"No pude comunicarme con el agente. Revisa tu conexión y vuelve a intentar."* + Reintentar (es un fallo de transporte, sí reintentable) |
| `401` por cookie expirada | Redirección a P0 conservando el borrador: *"Tu sesión expiró. Vuelve a entrar."* |
| `409 IDEMPOTENCY_IN_FLIGHT` | *"Ya estoy procesando ese mensaje."* Reintento automático **una vez** tras `Retry-After` (`channels.md` §1.8) |
| `429 RATE_LIMITED` | *"Demasiadas peticiones. Intenta en N segundos."* Botón deshabilitado con cuenta atrás de `Retry-After` |

---

## 4. Flujo de confirmación de escrituras

> En el Sprint 4 **no hay tools L2 reales** (`sprint-plan-v2.md` S4 E2: llegan en el Sprint 7). Este
> flujo se construye completo y se ejercita contra un **stub** (`AGENT_UI_L2_STUB=true`, §4.6). El
> objetivo es validar la UX de aprobación **antes** de que exista una escritura real — cuando el
> coste de equivocarse ya no es cero.

### 4.1 Principio rector

**Es imposible aprobar sin haber visto el efecto.** No como recomendación de diseño, sino como
invariante técnico verificable (§4.4). El razonamiento está en `tools-design.md` §7.2 **D7**: *"El
plan presentado al humano se renderiza desde `effects[]` estructurado, **no** desde prosa del LLM. El
LLM no puede mentir sobre lo que la tool hará."*

Consecuencias directas sobre esta UI:

| # | Regla |
|---|---|
| R1 | El panel de aprobación se renderiza **exclusivamente** desde `confirmation.dry_run_result` / `plan.effects[]`. **Cero texto del LLM** en la zona de decisión |
| R2 | Si `effects[]` viene vacío o ausente ⇒ **no se muestran botones**. Mensaje: *"No puedo mostrarte qué cambiaría; no voy a ejecutar esto."* Fail-closed en la UI, no solo en el servidor |
| R3 | Si falta `blast_radius` ⇒ idem R2. `tools-design.md` §7.2 **D8**: *"`blast_radius` es obligatorio y cuantitativo … Si el agente no puede acotarlo, no ejecuta"* |
| R4 | Los botones viven **solo** en el panel de aprobación. No hay "aprobar" desde la lista de P4, ni desde el pie de un turno, ni atajo de teclado global |
| R5 | "sí", "ok", "dale" escritos en el textarea **nunca** aprueban. Ni los lee la UI como aprobación. `tools-design.md` §7.1 paso 3: *"botón/comando explícito, no 'sí' en lenguaje natural ambiguo"* |
| R6 | La aprobación la da el **mismo** usuario que originó la petición. `channels.md` §1.9. El servidor lo valida; la UI ni muestra el panel a otro |

### 4.2 Cómo se muestra el dry-run (estado 4)

Renderizado desde la estructura de `tools-design.md` §2.3, con el lenguaje de la plantilla de §7.3
traducido a la UI (wireframe en §8.5):

| Sección | Campo origen | Render |
|---|---|---|
| Cabecera | — | **"Simulación — no se ha hecho ningún cambio"**, fondo neutro, icono de lupa. Deliberadamente **no** parece un botón ni una alerta |
| Qué hará | `plan.summary` + `plan.effects[]` | Lista con viñetas, **una línea por efecto**, en lenguaje humano derivado de los campos: `{system, target, op, rows}` ⇒ *"Crear 1 solicitud de liberación en trafico-system"*, *"Registrar 3 entradas de auditoría"*. El mapeo `op`→verbo es una tabla fija en el cliente (`INSERT`→Crear, `UPDATE`→Modificar, `POST`→Enviar), **no** prosa del modelo |
| Alcance | `plan.blast_radius` | *"3 guías: 12345, 12346, 12347"* · importe en MXN si `importe_mxn != null`. **Cuantitativo siempre** |
| Precondiciones | `plan.preconditions[]` | Lista con ✅/❌ por `result` + `detail`. Una sola ❌ ⇒ **no hay botón Confirmar** (sería ofrecer algo que el servidor rechazará por `permissions.md` §5 D-11/D-17) |
| Reversibilidad | `plan.reversibility` | Línea destacada: *"Reversible: puede rechazarse en ATLAS antes de aprobarse"* o *"**No reversible.**"* en negrita |
| Avisos | `dry_run_result.warnings[]` | Bloque ámbar, uno por línea |
| Payload | `plan.payload_preview` | Plegado, **cerrado por defecto**, rótulo *"Ver datos exactos que se enviarán"*. Abierto = JSON formateado |
| Motivo | `requested_payload.motivo` | **Mostrado íntegro y textual.** Ver §4.5 |
| Procedencia | `trace` + sesión | *"Solicitado por {usuario} · {empresa} · {tool_name} · clase L2 · trace `{id}`"* |

### 4.3 Panel de aprobación (estado 5)

Aparece **inmediatamente debajo** del bloque de dry-run, visualmente ligado a él (borde de acento
continuo). No es un modal: un modal invita a cerrarlo sin leer, y además taparía el dry-run que es
justo lo que hay que leer.

| Elemento | Especificación |
|---|---|
| `summary` | En negrita, tamaño mayor. Viene de `confirmation.summary` |
| Badge de riesgo | `risk_class` (`L2`) + `action_code` de `approval_requests` |
| Cuenta atrás | `mm:ss` hasta `expires_at`, **TTL 5 min** (`channels.md` §1.9). Últimos 60 s en rojo. Al llegar a 0: botones `disabled` + *"La confirmación venció. Vuelve a pedirlo."* — **sin auto-reintento** |
| Botón **Confirmar** | Primario. `disabled` hasta que se cumplan las **4 condiciones** de §4.4 |
| Botón **Cancelar / No ejecutar** | Secundario, **siempre habilitado**. Envía `decision:"reject"`, que deja rastro (`channels.md` §1.9: *"deja rastro en el audit log de que se ofreció y se declinó"*) |
| `Idempotency-Key` | Generada **al montar el panel**, no al hacer clic. Doble clic ⇒ una sola solicitud (`channels.md` §2.8) |
| Tras el clic | Botones `disabled` + spinner *"Ejecutando…"*. No se permite un segundo envío ni con doble clic ni con Enter |
| `Esc` | **No** cancela. Un gesto accidental no debe decidir sobre una escritura. Solo el botón |
| Enter | **No** confirma. El foco inicial va al **cuerpo del dry-run**, no al botón |

### 4.4 La garantía: imposible aprobar sin haber visto el efecto

Cuatro candados simultáneos. **Confirmar** se habilita solo si **todos** se cumplen:

| # | Candado | Implementación | Qué fallo previene |
|---|---|---|---|
| **C1** | **Render completo** | El panel emite `effects_seen_token = sha256(confirmation_id + JSON canónico de effects[] + blast_radius)` **al terminar de pintar** el dry-run. Si el render falla o faltan `effects[]`/`blast_radius`, no hay token y el botón no existe | Que un bug de render muestre un panel vacío con botón activo |
| **C2** | **Visibilidad real** | `IntersectionObserver` sobre el bloque de dry-run: debe haber estado **≥ 2 s** con **≥ 60 %** visible en el viewport. No basta con que esté en el DOM | Aprobar desde un hilo con scroll arriba, o con el panel fuera de pantalla |
| **C3** | **Despliegue de "no reversible"** | Si `reversibility` indica no reversible, hay que abrir el plegado *"Ver datos exactos"* **y** marcar una casilla: *"Entiendo que esta acción no se puede deshacer."* | Aprobar a ciegas lo irreversible |
| **C4** | **Validación en servidor** | `POST /api/v1/chat/confirm` **exige** `effects_seen_token` y lo recalcula del lado del servidor sobre el dry-run persistido. No coincide ⇒ `422 EFFECTS_NOT_ACKNOWLEDGED`. Nada se ejecuta | Un cliente modificado, un script, o un `curl` que salte la UI |

> **C4 es el candado que importa.** C1-C3 son UX y un atacante los esquiva con DevTools. C4 vive en
> el servidor y hace de la garantía algo **estructural**: aprobar requiere poseer el hash del
> `effects[]` exacto que el servidor persistió. Esto convierte "el usuario vio el efecto" en una
> precondición criptográfica, igual que `confirmation_token` está ligado a `hash(tool, args, empresa,
> actor)` en `tools-design.md` §7.2 **D3**. Se especifica como **ADICIÓN** al contrato en §6.2.

### 4.5 El campo `motivo`

`permissions.md` §5 **D-15**: *"`motivo` ausente, < 15 caracteres, o detectado como **autogenerado
por el LLM** ⇒ `VALIDATION / MOTIVO_INVALIDO`"*. La UI lo trata en consecuencia:

| Regla | Valor |
|---|---|
| Quién lo escribe | **El humano**, en un textarea del panel, **antes** de poder confirmar. Nunca se precarga con texto del LLM |
| Si el agente propuso un motivo | Se muestra **como cita gris no editable** rotulada *"El agente propuso:"* y el campo del humano arranca **vacío**. Copiarlo exige un clic explícito en *"Usar este texto"*, lo que lo convierte en confirmado por el humano |
| Validación en cliente | Mínimo **15 caracteres** (mismo umbral que D-15), contador visible, trim |
| Mensaje de error | *"Explica brevemente el motivo (mínimo 15 caracteres). Queda registrado con tu nombre."* |
| Atribución | Nota permanente bajo el campo: *"Este motivo y tu nombre quedan en la auditoría de {sistema}."* `permissions.md` §1.1: la atribución al humano vive en `solicitante`/`motivo` del sistema destino |

### 4.6 Cómo se refleja el resultado

| Caso | Render |
|---|---|
| **Éxito** | Un **nuevo turno** del agente con `answer` (p. ej. *"Solicitud SC-00412 creada; la revisará un SUPER USUARIO."*). El panel de aprobación se **reemplaza** por un recibo compacto: ✅ **Ejecutado** · hora · quién · enlace a **P3**. **El dry-run original permanece visible** en el hilo: el registro de lo que se aprobó no se borra |
| **Rechazo** | Recibo: ⊘ **No ejecutado** · *"Cancelaste esta acción"* · hora. El dry-run permanece |
| **Expirado** | Recibo: ⏱ **Venció** · *"Pasaron más de 5 minutos"* + botón **"Volver a pedirlo"** que reenvía el mensaje original como turno nuevo (nuevo dry-run, nuevo token) |
| **`STATE_CONFLICT`** (D-17/D-11) | Turno de error con `answer` del servidor + explicación en lenguaje llano: *"Algo cambió mientras decidías: una de las guías ya no es elegible. Vuelve a pedirlo para ver la situación actual."* Es el caso de `tools-design.md` §7.1 paso 4 (re-evaluación obligatoria) y la UI **no** lo presenta como bug |
| **`effects_drift`** (D9) | Banda ámbar sobre el recibo: *"La acción se ejecutó, pero el efecto no fue idéntico al simulado. Revisa el detalle."* + enlace a P3. **Nunca se oculta**: es la señal de que el sistema cambió bajo los pies |
| **Fallo de ejecución** | Estado **9 error** con `trace_id`. El recibo dice ❌ **Falló** y el dry-run permanece |

**Stub de L2 para el Sprint 4.** Con `AGENT_UI_L2_STUB=true` se registra una tool
`stub.escritura_demo` (clase L2, **sin canal upstream**: no toca ningún sistema) cuyo dry-run
devuelve un `plan.effects[]` realista. Permite alcanzar los estados 4 y 5 y ejercitar C1-C4 de punta
a punta sin escribir una sola fila en trafico-system ni liquidaciones-system. **El stub no se
despliega con el flag en `true` fuera del entorno de validación**, y su `tool_name` hace evidente en
`tool_executions` que fue un simulacro.

---

## 5. Arquitectura frontend

### 5.1 Decisión: HTML + CSS + JS vanilla, sin build step

| Opción evaluada | Veredicto |
|---|---|
| **A. HTML/CSS/JS vanilla sin build** | ✅ **ELEGIDA** |
| B. React/Vue + Vite | ❌ Rechazada |
| C. HTMX + Jinja2 (SSR) | ❌ Rechazada, con matices |
| D. Alpine.js vía CDN | ❌ Rechazada |

**Por qué A:**

| # | Argumento |
|---|---|
| 1 | **El widget del Sprint 5 es, por decisión ya tomada, JS vanilla en un archivo sin build step** (`channels.md` §2.6: *"un archivo, ~700-900 líneas, IIFE, sin dependencias"*). Si la UI standalone usa React, el equipo mantiene **dos modelos mentales y dos stacks** para la misma lógica de cliente, y nada de lo aprendido en S4 se traslada a S5 |
| 2 | **No hay Node en el despliegue.** `docker/app/Dockerfile` es `python:3.12-slim`; `docker-compose` tiene `app` (uvicorn), `nginx`, `postgres`. Meter React obliga a un stage de build con Node, o a commitear `dist/` — un artefacto compilado versionado en un repo cuyo único lenguaje es Python. Coste operativo permanente para una UI que el §1.1 declara **desechable** |
| 3 | **El presupuesto es 12 d.p. compartidos** entre "Frontend 0.5 + Agente 1" para 10 entregables. Un día de andamiaje de tooling es ~8% del sprint, gastado en infraestructura que no responde ninguna de las 5 preguntas del HITO |
| 4 | **La complejidad real es baja.** 7 pantallas, un POST que domina el flujo, sin streaming (D6), sin tiempo real, sin colaboración. El estado es `{session_id, turns[], uiState, pendingConfirmation}` — el mismo `Store` del widget. Eso no necesita un reconciliador de DOM virtual |
| 5 | **`escape`-por-defecto es más fácil de auditar sin framework.** Toda la salida del modelo pasa por **una** función `esc()` y se asigna con `textContent`. En React la tentación es `dangerouslySetInnerHTML` para el markdown; aquí no existe el atajo |
| 6 | **Depurable en el equipo del usuario.** Si en el HITO algo falla en el Windows de Cesar, se abre DevTools y se lee el fuente **real**, sin sourcemaps ni minificación |

**Por qué no C (HTMX/SSR)**, que es la alternativa más seria: encaja perfecto con FastAPI y eliminaría
JS de cliente en P0/P2/P3/P4. Pero el **chat** necesita cliente de verdad —`AbortController` para el
Cancelar del estado 1, temporizadores de 15 s/60 s, cuenta atrás de la confirmación,
`IntersectionObserver` de C2, borrador local, ULID de idempotencia. Terminaría siendo **HTMX para 5
pantallas + JS vanilla para el chat**: dos paradigmas por el precio de uno. Y la pantalla que decide
el HITO es el chat. **Nota:** las plantillas **sí** se renderizan con Jinja2 en el servidor (layout,
nav, datos iniciales de P2/P3/P4); lo que se rechaza es HTMX como mecanismo de interacción.

**Por qué no D:** Alpine por CDN añade una dependencia externa en red local (si no hay salida a
internet, la UI no arranca) y hay que vendorizarla igual — con lo que se pierde la ventaja y se
queda el framework.

### 5.2 Compartir código con el widget futuro: SÍ, pero solo el núcleo sin DOM

**El dato clave de la tarea:** el widget del Sprint 5 será JS vanilla sin build step embebido en apps
PHP legacy, con **Shadow DOM** y CSS inline (`channels.md` §2.6). Pregunta: ¿un solo código base o
dos?

| Opción | Evaluación |
|---|---|
| **Compartir TODO** (un bundle que detecta si está embebido) | ❌ El widget tiene requisitos que la UI standalone no tiene y que la encarecen: `attachShadow`, `all:initial`, `z-index: 2147483000`, CSS en string JS, FAB, foco atrapado, `Esc` cierra, convivir con DataTables/Bootstrap. Y la UI standalone tiene lo que el widget no: 7 rutas, login, tablas ordenables, export, P5. Un archivo que haga ambas cosas tiene un `if (embedded)` en cada función de render y **se depura el doble de mal en los dos sitios**. Además el widget declara presupuesto de 700-900 líneas: compartir el render lo revienta |
| **Separar TODO** (copiar y divergir) | ❌ Reimplementa el mapeo de los 9 estados, la cadena de errores de §1.6, la lógica de `Idempotency-Key`, el TTL de confirmación y los hints de 15/60 s. Esas reglas son **del contrato**, no de la presentación: dos copias divergen, y divergir en el estado 6 (`denied`) o en "no reintentar `LLM_UNAVAILABLE`" produce comportamientos de seguridad distintos según por dónde entre el usuario |
| **Compartir solo el núcleo sin DOM** | ✅ **ELEGIDA** |

**Lo que se comparte — `forsis-agent-core.js` (ESM, cero referencias a `document`/`window.document`):**

```
static/shared/forsis-agent-core.js          ~250-300 líneas, sin DOM, testeable en Node sin jsdom
  ├── Transport        fetch + AbortController + timeout 135 s (channels.md §1.7 fila 9)
  │                    + headers (X-Forsis-Channel, Idempotency-Key, X-Forsis-Trace-Id)
  ├── mapStatus()      ChatResponse → uno de los 9 estados (channels.md §2.8). Pura.
  ├── mapError()       HTTP + error_code → { retryable, mensaje_es_MX }  (§1.6, §7.3)
  ├── Store            { session_id, turns[], uiState, pendingConfirmation } + suscriptores
  ├── Idempotency      ULID + composición de la clave de scope
  ├── Confirmation     TTL/cuenta atrás, effects_seen_token (C1), reglas R2/R3 (§4.1)
  └── fmt              números/fechas es-MX + America/Mexico_City
```

**Lo que NO se comparte:** todo lo que toca el DOM.

| | UI standalone | Widget (S5) |
|---|---|---|
| Montaje | Documento normal, CSS en `.css` externo | Shadow DOM, CSS en string |
| Render | Módulos por pantalla, tablas, export, P5 | Un `Render` compacto, sin tablas ni export |
| Rutas | 7 rutas servidas por FastAPI | Ninguna (panel único) |
| Chrome | Nav, barra superior, badges | FAB + panel, `all:initial` |

**Justificación en una línea:** se comparte **lo que el contrato dicta** (y cuya divergencia es un
riesgo de corrección y de seguridad) y se separa **lo que el entorno de montaje dicta** (y cuya
unificación solo produce ramas condicionales). La frontera es exactamente "¿toca el DOM?", que es
una pregunta objetiva y verificable en CI.

**Verificación en CI (barata y efectiva):** un test falla si `forsis-agent-core.js` contiene
`document`, `window.`, `innerHTML` o `addEventListener`. Un `grep` en el pipeline mantiene la
frontera honesta sin disciplina humana.

**Riesgo asumido y mitigación:** `forsis-agent-core.js` nace en el Sprint 4 sirviendo a un solo
consumidor, con el riesgo de abstraer prematuramente *para* un consumidor que todavía no existe.
Mitigación: en S4 se escribe como el núcleo de **esta** UI, sin un solo parámetro puesto "para el
widget". El Sprint 5 lo adoptará **o lo rechazará** con evidencia; si lo rechaza, S4 no pagó nada
porque el núcleo es el que esta UI necesitaba de todos modos.

### 5.3 Estructura de archivos

```
app/
├── main.py                       # existente — monta routers + StaticFiles
├── api/v1/
│   ├── chat.py                   # POST /api/v1/chat, /chat/confirm   (contrato, Sprints 2-3)
│   └── ui.py                     # ADICIONES de §6 — router /api/v1/ui/*
├── web/
│   ├── routes.py                 # GET /ui/* → HTMLResponse (Jinja2), 7 rutas
│   ├── auth.py                   # cookie de sesión, dependencia require_ui_user()
│   ├── export.py                 # CSV (csv + BOM) y XLSX (openpyxl)
│   └── templates/
│       ├── _layout.html          # <head>, nav, CSP, flag de debug
│       ├── login.html  chat.html  historial.html  ejecucion.html
│       └── confirmaciones.html   depuracion.html  cuenta.html
└── static/
    ├── shared/forsis-agent-core.js   # §5.2 — sin DOM, ESM
    ├── js/
    │   ├── chat.js        # P1: compositor, hilo, 9 estados, reportes
    │   ├── approval.js    # P4 + panel: candados C1-C3, cuenta atrás
    │   ├── tables.js      # orden/paginación en cliente, formato es-MX
    │   └── common.js      # esc(), toasts, fetchJSON, barra de red
    └── css/
        ├── base.css       # reset, tokens, tipografía
        └── app.css        # layout, chat, tablas, panel de aprobación
```

Sin `node_modules`, sin `package.json`, sin bundler. Los `.js` se sirven como ESM
(`<script type="module">`); los navegadores objetivo (Chrome/Edge evergreen en Windows) soportan
módulos nativos.

### 5.4 Servido estático desde FastAPI

```python
# app/main.py  (adición al archivo existente)
from fastapi.staticfiles import StaticFiles
from app.api.v1 import ui as ui_router
from app.web import routes as web_routes

app.include_router(ui_router.router, prefix="/api/v1/ui", tags=["UI"])
app.include_router(web_routes.router, prefix="/ui",        tags=["UI-Pages"])
app.mount("/static", StaticFiles(directory="app/static"), name="static")
```

| Aspecto | Decisión |
|---|---|
| Quién sirve los estáticos | **FastAPI** (`StaticFiles`) en S4: un solo artefacto, un solo despliegue, cero cambios en nginx. Si el perfilado muestra coste real, nginx los sirve con un `location /static/` — **optimización de S4-bis, no de S4** |
| Nginx | `docker/nginx/default.conf` ya hace `proxy_pass` de `/` a `fastapi_backend` con `proxy_read_timeout 120s`. **Se sube a 130 s** para cumplir `channels.md` §1.7 fila 6 (*"nunca debe cortar antes que la app"*): con 120 s en nginx y 120 s de techo de turno, el `504 TURN_TIMEOUT` tipado del agente se perdería y el usuario vería un 504 genérico de nginx. **Cambio de una línea, obligatorio** |
| Caché | `Cache-Control: public, max-age=31536000, immutable` con `?v={APP_VERSION}` en las URLs. HTML siempre `no-store` |
| Origen | La UI vive en el **mismo origen** que la API ⇒ cero CORS, cookies `SameSite=Lax` suficientes |
| Puerto público `8099` | `sprint-plan-v2.md` ("Lo que NO cambió") mantiene la decisión de **no exponer 8099**. La UI se alcanza por el listener interno/`:8080` desde la red local. **BLOQUEANTE B-U5**: hay que confirmar por dónde entra el navegador del usuario — y si fuera por `8099`, `channels.md` **B-C1** aplica tal cual |
| `/docs` y `/redoc` | Existen hoy en `main.py`. Deben quedar **detrás de autenticación o desactivados** en el entorno de validación: exponen el esquema completo del agente a cualquiera con acceso de red. **BLOQUEANTE B-U4** |

### 5.5 Rutas, sesión y estado

**Rutas (7 páginas + 1 redirección):** navegación clásica de servidor, una página por pantalla. **Sin
SPA router**: el historial del navegador, el botón Atrás, abrir en pestaña nueva y copiar URL
funcionan gratis — y en una UI de auditoría, "copiar el enlace de esta ejecución y pegarlo en un
mensaje" es una necesidad real.

| Ruta | Plantilla | Protección |
|---|---|---|
| `/ui/` | redirige a `/ui/chat` o `/ui/login` | — |
| `/ui/login` | `login.html` | pública; si ya hay sesión redirige a `/ui/chat` |
| `/ui/chat` | `chat.html` | `require_ui_user()` |
| `/ui/historial` | `historial.html` | `require_ui_user()` |
| `/ui/ejecucion/{id}` | `ejecucion.html` | `require_ui_user()` + pertenencia (o `admin`) |
| `/ui/confirmaciones` | `confirmaciones.html` | `require_ui_user()` |
| `/ui/depuracion` | `depuracion.html` | `require_ui_user(role="admin")` + `AGENT_UI_DEBUG_ENABLED` |
| `/ui/cuenta` | `cuenta.html` | `require_ui_user()` |

**Sesión de la UI (distinta de la sesión conversacional — no confundirlas):**

| | Sesión de la UI | Sesión conversacional |
|---|---|---|
| Qué es | Login del usuario en esta app | Hilo de conversación con el agente |
| Dónde vive | Cookie `forsis_agent_ui_session` + tabla `agent_ui_sessions` | `agent_sessions` (`db-schema.md` §3.1) |
| TTL | **8 h**, renovada por actividad | **24 h** (`agent-core.md` §3.2) |
| Clave | `session_token` opaco (32 bytes aleatorios, hash en BD) | `(channel_type, channel_session_id, user_id)` incl. `company` |
| Al expirar | Redirección a P0 conservando el borrador | *"Esta conversación expiró; empiezo una nueva."* |

Cookie: `HttpOnly`, `Secure`, `SameSite=Lax`, `Path=/`, sin `Domain` explícito (host-only). Token
opaco en BD, no JWT: así `admin` puede revocar sesiones por SQL y el cambio de contraseña invalida
el resto. **Sin almacenamiento de credenciales ni de tokens en `localStorage`**: un XSS en una app
legacy no debe poder leer nada de esta UI (y por eso tampoco se usa `localStorage` para la sesión).

**Estado en el cliente:**

| Dato | Dónde | Por qué |
|---|---|---|
| `session_id` conversacional | `sessionStorage` (por pestaña) | Dos pestañas = dos hilos; igual que el widget (`channels.md` §2.6 `Persist`) |
| `company` elegida | `sessionStorage` | **Nunca** `localStorage`: una empresa "recordada" de la semana pasada es exactamente el default silencioso que D-7 prohíbe |
| `turns[]` del hilo | Memoria (`Store`) | Se repuebla del servidor al recargar (`GET /api/v1/ui/sessions/{id}`) |
| Borrador | `sessionStorage` | §3.1 |
| Datos de reportes | Memoria | Se reconsultan; no se cachean datos de negocio en el equipo |
| Confirmación pendiente | Memoria + `Store` | Al recargar se repuebla de `GET /api/v1/ui/approvals` (la verdad vive en el servidor) |

**Seguridad de cliente:**

| Control | Valor |
|---|---|
| CSP | `default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; object-src 'none'` — sin `unsafe-inline`, posible precisamente porque no hay framework que lo exija |
| `X-Frame-Options` | `DENY` para `/ui/*`. Nginx hoy pone `SAMEORIGIN` global; para la UI se endurece. **Esta UI no se embebe en ningún sitio** (eso es el widget, y el widget no es un iframe) |
| CSRF | Todos los `POST` de `/api/v1/ui/*` exigen `X-Forsis-CSRF` = token de doble envío (cookie no-HttpOnly `forsis_csrf` + header). `SameSite=Lax` no basta para `POST` de formulario. Ver §6.0 |
| Escapado | Única función `esc()`; `textContent` por defecto. `innerHTML` prohibido fuera de un helper auditado y verificado por `grep` en CI |
| Enmascarado | La UI **no** enmascara: consume lo ya enmascarado (`tools-design.md` §8.3). Si ve un secreto, lo muestra — y así delata el bug del agente (§2.4) |

---

## 6. Endpoints ADICIONALES que la UI necesita

> **ADICIÓN AL CONTRATO.** `channels.md` §1 define exactamente dos operaciones: `POST /api/v1/chat`
> y `POST /api/v1/chat/confirm`. La UI standalone necesita nueve más, que `channels.md` **no
> define**. Todos se declaran aquí, marcados como adición, bajo el prefijo **`/api/v1/ui/`** para que
> nunca se confundan con el contrato estable. **Reglas de diseño transversales**, tomadas del mismo
> contrato:
>
> | Regla | Valor | Origen |
> |---|---|---|
> | A-1 Autenticación | Cookie de sesión `forsis_agent_ui_session` (`HttpOnly`, `Secure`, `SameSite=Lax`). **Nunca** el bearer estático por canal: ese token autentica al *adaptador*, no al usuario (`channels.md` §1.4 decisión 2) | `channels.md` §1.4 |
> | A-2 CSRF | `X-Forsis-CSRF` obligatorio en todo método mutante, con doble envío de cookie | §5.5 |
> | A-3 Validación | `extra="forbid"` en todos los modelos Pydantic. Campo desconocido ⇒ `422 VALIDATION_ERROR`. Fail-closed, igual que `ChatRequest` | `channels.md` §1.3 regla 1 |
> | A-4 Errores | Mismo shape que el contrato: `{answer, session_id, status:"error", error:{code,message,retryable,details}, trace}` — **`answer` siempre presente, nunca `null`** | `channels.md` §1.6 |
> | A-5 `answer` en español de México, en segunda persona, sin jerga y sin nombres de máquina en el mensaje principal | `channels.md` §1.5.1, `tools-design.md` §5.2 |
> | A-6 Aislamiento | Todo recurso devolvido debe pertenecer al usuario de la sesión. Si no ⇒ `404 NOT_FOUND` (**no** `403`: no se confirma la existencia del recurso ajeno) | §2.3 de este documento |
> | A-7 Trazabilidad | Toda respuesta lleva `X-Forsis-Trace-Id`; los endpoints de escritura también `X-Forsis-Trace-Id` en la auditoría | `channels.md` §1.2 |
> | A-8 Idempotencia | Los `POST` mutantes aceptan `Idempotency-Key` con la misma semántica de `channels.md` §1.8 (TTL 24 h, scope `(channel, actor.subject, key)`) | `channels.md` §1.8 |
> | A-9 Paginación | `limit` (1..200, defecto 25) + `offset`. El límite máximo es explícito: estos endpoints devuelven datos de negocio a un navegador | — |
> | A-10 Rate limit | Los mismos límites que `channels.md` §3.7, aplicados por usuario | `channels.md` §1.6 |

### 6.0 Ajustes ADICIONALES al contrato de `channels.md` (retrocompatibles)

Tres ajustes mínimos e inevitables. Se listan aquí, no se inventan endpoints nuevos por separado.

| # | Ajuste | Tipo | Justificación |
|---|---|---|---|
| **ADJ-1** | `ChatResponse.trace` gana `tool_executions: [{id, tool, class, rows, ms}]` | **Campo nuevo dentro de un objeto obligatorio** — retrocompatible | Sin el `id`, la citación de fuente (§3.4 L3) y el enlace a P3 son imposibles. `trace` ya es obligatorio y no contiene datos de negocio (`channels.md` §1.5.3), así que el `id` es opaco y no filtra nada. **Sin este campo, BLOQUEANTE B-U1** |
| **ADJ-2** | `ChatRequest.channel` acepta `"ui-standalone"` | **Valor nuevo de un enum existente** — requiere actualizar el `Literal` del lado agente | `channel` es obligatorio y no tiene default (`channels.md` §1.3). La UI **debe** declarar su canal; sería un error de contrato mandarlo como `"widget-trafico"`, porque el token por canal está ligado a `X-Forsis-Channel` y `403 CHANNEL_MISMATCH` es la respuesta correcta a esa mentira. Requiere un token propio: `${FORSIS_AGENT_TOKEN_UI_STANDALONE}` |
| **ADJ-3** | `POST /api/v1/chat/confirm` acepta `effects_seen_token` (string, opcional) y devuelve `422 EFFECTS_NOT_ACKNOWLEDGED` si está presente y no coincide | **Campo opcional con fail-closed si se envía** — retrocompatible | Candado C4 de §4.4. Sin él, "imposible aprobar sin ver el efecto" es una promesa de UI que un `curl` rompe; con él es una precondición que el servidor verifica |

### 6.1 `POST /api/v1/ui/login`

| | |
|---|---|
| **Auth** | Ninguna (es el endpoint de login) |
| **CSRF** | Sí (token de sesión anónimo previo) |
| **Request** | `{"username": "cvazquez", "password": "••••••••"}` — ambos 1..128 |
| **Response 200** | `{"redirect": "/ui/chat", "user": {"username":"…","display_name":"…","role":"validador"}}` |
| **Errores** | `401 INVALID_CREDENTIALS` (mensaje genérico, A-5) · `429 LOCKED_OUT` + `Retry-After` + `{"locked_until","attempts_remaining":0}` (A2 del sprint: 5 intentos ⇒ bloqueo 15 min) · `422 VALIDATION_ERROR` |
| **Notas** | argon2id/bcrypt (`AGENT_UI_HASH_ALGO`, def. argon2id) · comparación en tiempo constante · el login **no** consume cuota de `POST /chat` · sesión anterior destruida al hacer login nuevo |

### 6.2 `POST /api/v1/ui/logout`

| | |
|---|---|
| **Auth** | Cookie de sesión |
| **Request** | `{}` (sin cuerpo) |
| **Response 200** | `{"redirect": "/ui/login"}` |
| **Errores** | Ninguno: idempotente. Logout sin sesión ⇒ 200 |
| **Notas** | Destruye la fila de `agent_ui_sessions` **y** borra la cookie. No cierra la sesión conversacional del agente: `agent_sessions` es del agente, no de la UI. Si el usuario cierra sesión y vuelve a entrar, recupera sus hilos (mismo `user_id`) |

### 6.3 `GET /api/v1/ui/sessions`

Listado del historial (§2.3).

| | |
|---|---|
| **Auth** | Cookie de sesión |
| **Query** | `from` (ISO date, defecto 7 días atrás) · `to` (ISO date, defecto hoy) · `company` (FORSIS\|GERO, opcional) · `status` (último `status`, opcional) · `only_errors` (bool) · `only_writes` (bool) · `limit` (1..200, def. 25) · `offset` (def. 0) · `scope` (`mine`\|`all`; `all` **solo si `role=admin`**, si no ⇒ `403 FORBIDDEN`) |
| **Response 200** | `{"items":[{"session_id":"uuid","company":"FORSIS","title":"¿qué guías tiene…","first_message_at":"…","updated_at":"…","turns":7,"tool_executions":3,"last_status":"ok","has_errors":false,"has_writes":false,"state":"active"}],"total":142,"limit":25,"offset":0}` |
| **Errores** | `401` · `403 FORBIDDEN` (`scope=all` sin admin) · `422` (fechas invertidas, enums inválidos) |
| **Notas** | Orden `updated_at DESC` (`ix_sessions_updated` ya existe). `title` = primeros 60 chars del **primer mensaje del usuario**, no del agente: es lo que el usuario reconoce como "su" conversación. `total` habilita la paginación sin estimar |

### 6.4 `GET /api/v1/ui/sessions/{session_id}`

Detalle de una sesión, para el modo lectura de P2 y para recargar el chat.

| | |
|---|---|
| **Auth** | Cookie de sesión + pertenencia (o `admin`) |
| **Path** | `session_id` (UUID) |
| **Response 200** | `{"session":{…igual que un ítem de §6.3…},"turns":[{"message_id":"…","role":"user","content":"…","created_at":"…"},{"role":"assistant","status":"ok","content":"…","components":[…],"confirmation":null,"clarification":null,"trace":{…},"created_at":"…"}],"tool_executions":[{"id":"uuid","tool":"traf.guias_liberadas_reporte","status":"success","execution_time_ms":420,"requires_approval":false,"class":"L0"}],"approvals":[{"confirmation_id":"cnf_…","status":"approved","expires_at":"…"}]}` |
| **Errores** | `401` · `404 NOT_FOUND` (no existe **o** es de otro usuario — A-6) · `403 SESSION_MISMATCH` si la sesión existe pero pertenece a otra empresa distinta a la actual sin haber cambiado de empresa |
| **Notas** | Los turnos se reconstruyen con la **misma función de render** que el chat en vivo, en `readOnly:true`, para que lo releído sea literalmente lo que se vio. `status` por turno requiere que `agent_messages` lo persista: **no está en el esquema actual** (`db-schema.md` §3.2 solo tiene `role`, `content`, `tool_calls`, `tool_call_id`, `token_count`) ⇒ **BLOQUEANTE B-U3** |

### 6.5 `GET /api/v1/ui/executions/{execution_id}`

Detalle de ejecución de tool (P3).

| | |
|---|---|
| **Auth** | Cookie de sesión + pertenencia de la sesión padre (o `admin`) |
| **Response 200** | `{"execution":{"id":"uuid","tool_name":"liq.solicitud_crear","tool_display_name":"Crear solicitud de liquidación","category":"escritura","risk_class":"L2","status":"success","requires_approval":true,"parameters_in":{…},"result_out":{…},"result_shape":"table","error_message":null,"execution_time_ms":812,"created_at":"…","completed_at":"…","session_id":"uuid","trace_id":"…","message_id":"…"},"dry_run":{"plan":{"summary":"…","effects":[…],"preconditions":[…],"reversibility":"…","blast_radius":{…}},"payload_preview":{…}},"approval":{"approver_user_id":"cvazquez","approval_channel":"ui-standalone","responded_at":"…","rejection_reason":null}}` |
| **Errores** | `401` · `404 NOT_FOUND` (A-6) |
| **Notas** | `parameters_in` llega **ya enmascarado** por el agente (`tools-design.md` §8.3); la UI no re-enmascara. `result_shape ∈ {table, json, scalar, empty}` lo declara el servidor y determina el render de §3.3 — **es la pieza que resuelve el BLOQUEANTE B-U2**: sin `result_shape` con el esquema de columnas, la UI no puede saber qué columnas son numéricas y **no muestra fila de totales** |

### 6.6 `GET /api/v1/ui/approvals`

Bandeja de confirmaciones pendientes (P4).

| | |
|---|---|
| **Auth** | Cookie de sesión |
| **Query** | `status` (`pending`\|`approved`\|`rejected`\|`expired`\|`all`, def. `pending`) · `limit` · `offset` |
| **Response 200** | `{"items":[{"confirmation_id":"cnf_…","approval_id":"uuid","tool_execution_id":"uuid","action_code":"LIQ_SOLICITUD_CREAR","summary":"Crear solicitud de cancelación del vale PR-00123","risk_level":"medium","risk_class":"L2","company":"FORSIS","requested_by":"cvazquez","requested_at":"…","expires_at":"…","seconds_remaining":212,"can_respond":true,"status":"pending"}],"total":1,"limit":25,"offset":0}` |
| **Errores** | `401` |
| **Notas** | **Solo las del propio usuario** (`channels.md` §1.9: *"el mismo `actor.subject` que originó la petición"*). Ni un `admin` ve las de otro — es una restricción de privacidad *y* de integridad: nadie aprueba por ti. Orden: `expires_at ASC` (lo que expira antes, primero). `expired` se calcula **en el servidor** a partir de `expires_at` + `status='pending'`, no en el cliente: un reloj del navegador manipulado no debe volver pendiente lo vencido. Las expiradas se conservan 1 h visibles con sello **VENCIDA** |

### 6.7 `POST /api/v1/ui/export`

Genera la descarga de un reporte (usado por §3.3).

| | |
|---|---|
| **Auth** | Cookie de sesión + pertenencia (o `admin`) |
| **CSRF** | Sí |
| **Idempotency** | Acepta `Idempotency-Key` (A-8) |
| **Request** | `{"tool_execution_id":"uuid","format":"csv"\|"xlsx","columns":[…opcional, para acotar…]}` |
| **Response 200** | Archivo: `Content-Type: text/csv; charset=utf-8` o `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` · `Content-Disposition: attachment; filename="forsis_liq_reporte_operador_FORSIS_20261005_1430.csv"` · BOM UTF-8 en CSV |
| **Errores** | `401` · `403 EXPORT_NOT_ALLOWED` (tool sin capability de export) · `404 NOT_FOUND` (A-6) · `413 REPORT_TOO_LARGE` (> 20 000 filas: *"El reporte es muy grande para exportar aquí; acótalo por fechas."*) · `422 VALIDATION_ERROR` · `422 UNSUPPORTED_FORMAT` · `415 UNSUPPORTED_MEDIA_TYPE` (formato no soportado) |
| **Notas** | Se exporta **el `result_out` completo persistido**, no el dataset del cliente: así el archivo no depende de lo que se pintó ni de cuántas filas se paginaron. Genera entrada en `audit_records` (`event_type='ui_export'`, `actor_id`, `target_id=tool_execution_id`) — un export de datos de negocio **debe** ser auditable (`permissions.md` §6). CSV con `csv.writer` y BOM explícito; XLSX con `openpyxl`, encabezado congelado, fila de totales con fórmula `SUM()` |

### 6.8 `POST /api/v1/ui/password`

| | |
|---|---|
| **Auth** | Cookie de sesión |
| **CSRF** | Sí |
| **Request** | `{"current_password":"…","new_password":"…"}` — nueva ≥ 12 chars, distinta de la actual |
| **Response 200** | `{"ok":true,"sessions_invalidated":2}` |
| **Errores** | `401` · `422 WEAK_PASSWORD` (*"La contraseña nueva debe tener al menos 12 caracteres."*) · `422 CURRENT_PASSWORD_INVALID` · `429 RATE_LIMITED` (5 por hora) |
| **Notas** | Revalida **todas** las otras sesiones del usuario, incluida la actual si se pide. Tras el cambio, el usuario **sigue conectado** en la pestaña actual (evita que un usuario no técnico se quede fuera del sistema por un error tipográfico) |

### 6.9 `GET /api/v1/ui/metrics`

Agregados del periodo de validación, para P5.

| | |
|---|---|
| **Auth** | Cookie de sesión **y** `role=admin` **y** `AGENT_UI_DEBUG_ENABLED=true`. Si falta el flag ⇒ `404 NOT_FOUND` (no se anuncia la existencia de la pantalla) |
| **Query** | `from`, `to` (def. desde el inicio de la fase de validación) |
| **Response 200** | `{"period":{"from":"…","to":"…"},"totals":{"turnos":812,"ok":701,"clarification_needed":41,"confirmation_required":18,"denied":22,"no_capability":14,"degraded":9,"error":7},"latency_ms":{"llm":{"p50":3600,"p95":10500},"tools":{"p50":300,"p95":2000},"total":{"p50":8120,"p95":25000,"techo":120000},"over_techo":1},"json_mode":{"llm_attempts_total":968,"attempts_por_turno":{"p50":1,"p95":2,"max":3},"salvaged":87,"failed_closed":6,"ok_rate_pct":87.6},"tools_top":[{"tool":"traf.guias_liberadas_reporte","calls":212,"avg_ms":430}],"denials":[{"error_code":"PRIV_VACIO","count":9},{"error_code":"TOOL_NO_AUTORIZADA","count":7}],"models":[{"model":"claude-sonnet-4.5","calls":512},{"model":"…","calls":456}]}` |
| **Errores** | `401` · `403 FORBIDDEN` (no admin, flag sí) · `404 NOT_FOUND` (flag off) · `422` (fechas) |
| **Notas** | `llm_model_real` por llamada es **obligatorio** en el contrato (`channels.md` §1.5.3) precisamente porque *"sin eso, un fallo intermitente de formato es imposible de diagnosticar"*; este endpoint lo agrega. `json_mode` implementa la pregunta de `agent-core.md` §0 (JSON mode fiable al 70/80%): `salvaged` = respuestas reparadas por la capa 2, `failed_closed` = rechazadas por la capa 4. El desglose por capa (llm / tools) es lo que permite ver *dónde* se fue el tiempo, no solo cuánto |

### 6.10 `GET /api/v1/ui/capabilities`

Lista qué puede pedir el actor (alimenta el botón *"Ver qué puedo hacer"* del estado 7).

| | |
|---|---|
| **Auth** | Cookie de sesión |
| **Response 200** | `{"company":"FORSIS","items":[{"group":"Consultas de guías","tools":[{"name":"traf.guias_buscar","display":"Buscar guías","class":"L0","example":"¿qué guías tiene el cliente 412?"}]},{"group":"…","tools":[…]}],"hidden_count":24}` |
| **Errores** | `401` · `422` (empresa no seleccionada) |
| **Notas** | Devuelve **solo** el catálogo filtrado por permisos — el mismo `Registry.list_definitions(actor)` que el Planner ve (`agent-core.md` §4.2 D-1: *"Si el usuario no puede ejecutar algo, el Planner no debe ni verlo"*). No se enumeran tools denegadas. `hidden_count` es informativo y **no** se acompaña de la lista: `'FORBIDDEN / PRIV_VACIO' + "te faltan 24 herramientas"` es información de``.

### 6.11 `GET /api/v1/ui/health` *(auxiliar)*

| | |
|---|---|
| **Auth** | Ninguna |
| **Response 200** | `{"agent":"ok","database":"ok","widget_stub":true,"l2_stub":true,"version":"…"}` |
| **Notas** | Para el usuario, permite determinar si el problema es "el agente está caído" o "mi navegador". Distinto de `/health` de `app/main.py` (que es un eco para Docker). **Sin datos de negocio, sin rutas internas.** *Es el único endpoint `/api/v1/ui/*` sin cookie, y por eso solo devuelve salud agregada* |

---

## 7. Accesibilidad y pragmática

### 7.1 Español de México, no español de translating machine

| Regla | Ejemplo del mal | Ejemplo del bien |
|---|---|---|
| **Tuteo consistente, nunca "usted"** | *"¿Desea confirmar la operación?"* | *"¿Confirmas la operación?"* |
| **Sin anglicismos innecesarios** | *"Timeout", "retry", "payload", "streaming", "widget"* | *"Se tardó demasiado"*, *"vuelve a intentar"*, *"datos que se envían"* |
| **Los nombres de máquina solo en el detalle técnico** | El error 502 muestra *"upstream 502 from Omniroute"* | *"No pude consultar al modelo que redacta las respuestas. Intenta en un momento."* — el texto técnico va **debajo**, en un plegado, para `admin` |
| **Voseo: nunca** | — | México no usa voseo. Nunca |
| **Fechas y números nativos** | `2026-10-05T18:42:00Z` | `05/10/2026, 18:42` · `4,210.00` |
| **Sin flexión de género forzada** | — | *"Hola, {nombre}"* · *"¿Cuántas guías…?"*. El plural correcto lo pone la tool |
| **Sin emojis como única señal** | ✅❌ sin texto | ✅/❌ **siempre** con texto al lado. Un usuario con daltonismo (≈8% de hombres) no puede distinguir un emoji verde de uno rojo |
| **"Guías", no "Guias"** | — | Todos los términos con acento correcto: guías, liquidaciones, Operación, días. Es la diferencia entre "habla español" y "habla español" |

**Vocabulario de la UI, fijo:** *enviar* (no "submit"), *turno*→ nunca se dice; se dice **"pregunta"** o
**"mensaje"**; *sesión* solo para el login; *herramienta* → **"consulta"** en la pantalla principal y
`nombre_de_tool` solo en P3/P5. **La palabra "tool" no aparece nunca en la pantalla principal.**

### 7.2 Teclado

| Requisito | Implementación |
|---|---|
| Recorrido de tabulación | Orden lógico: nav → hilo (contenedor `role="log"`) → chips de aclaración → textarea → Enviar → panel de aprobación. Sin trampas de foco |
| `Enter` envía / `Shift+Enter` salta | En el textarea del chat. **En el campo de `motivo` (§4.5), `Enter` NO envía**: un motivo truncado a media palabra es un bug de auditoría |
| Foco | Al enviar, el foco **se queda** en el textarea (para escribir la siguiente). Al cambiar de estado, el foco **no se mueve solo**: los cambios de estado se anuncian por `aria-live`, no roban el foco |
| Foco en el panel de aprobación | Al aparecer, el foco va al **inicio del bloque de dry-run**, nunca al botón Confirmar (R5: `Enter` no confirma) |
| Foco atrapado | Solo en login y en modales (export). **No** en el hilo |
| `Esc` | Cierra modales. **No** cancela una confirmación (§4.3). **No** cancela el turno en vuelo mientras el estado sea 1 (el botón Cancelar sí lo hace, explícitamente) |
| Atajos globales | **Ninguno** en S4. Un atajo de "aprobar todo" sería un agujero de seguridad esperando ocurrir. Los atajos van a S4-bis |
| Foco visible | `:focus-visible` con anillo de 2 px. **Nunca** `outline:none` sin reemplazo |
| Saltar al contenido | Enlace **"Saltar al chat"** como primer elemento enfocable de la nav |

### 7.3 Errores en lenguaje humano

**Principio:** el usuario lee **un** mensaje. El técnico lee el resto, debajo, si tiene permisos.

| Código (`channels.md` §1.6 / `permissions.md` §5) | HTTP | Mensaje para el usuario | ¿Botón de reintentar? |
|---|---|---|---|
| `UNAUTHENTICATED` | 401 | *"Tu sesión expiró. Vuelve a entrar."* | → login |
| `FORBIDDEN` (`PRIV_VACIO`, `ROL_NO_MAPEADO`, `TOOL_NO_AUTORIZADA`, `MODULO_NO_AUTORIZADO`) | 403 | Se muestra **`answer` del servidor tal cual**. La UI **no traduce** el código: `permissions.md` §5 garantiza que el `answer` explica causa y vía humana. Traducirlo sería una segunda fuente de verdad que puede contradecir al servidor | **No** |
| `FORBIDDEN / PRIV_SUBSTRING_MATCH` | 403 | `answer` tal cual. Es un caso que un usuario **nunca debe ver**; si aparece, es un hallazgo: la UI lo marca para `admin` en P5 | No |
| `BLOCKED_L3` | 403 | *"Esa acción no está disponible para ningún usuario por el agente."* Solo si `answer` no lo dice | No |
| `CHANNEL_MISMATCH` | 403 | *"La configuración del agente está mal (canal). Avisa a soporte."* + `trace_id` | No |
| `SESSION_MISMATCH` | 403 | *"Esa conversación no es tuya o es de otra empresa. Empecemos una nueva."* + botón "Nueva conversación" | No |
| `SERVICE_DISABLED` (kill-switch) | 503 | *"El agente está detenido por mantenimiento. Intenta más tarde."* | No |
| `AUDIT_UNAVAILABLE` (D-20) | 403 | *"El agente no puede guardar el registro de auditoría, así que no va a ejecutar la acción."* — **honestidad sobre por qué no** | No |
| `RATE_LIMITED` | 429 | *"Has hecho muchas consultas seguidas. Espera N segundos."* + cuenta atrás | Sí, tras `Retry-After` |
| `VALIDATION_ERROR` (empresa ausente) | 422 | *"Antes de empezar, elige si es FORSIS o GERO."* + el selector resaltado | — |
| `MESSAGE_TOO_LONG` | 413 | *"Tu mensaje es muy largo (máximo 4 000 caracteres)."* | No |
| `LLM_UNAVAILABLE` | 502 | *"No pude consultar al modelo que redacta las respuestas. Intenta en un momento."* | **No** (`retryable:false`, §1.6.1) |
| `DEPENDENCY_UNAVAILABLE` | 503 | *"Un sistema de Forsis no está disponible ahorita."* | Sí, con backoff |
| `TURN_TIMEOUT` | 504 | *"Esto está tardando demasiado y lo cancelé. Ya lo intenté N veces. Prueba con una pregunta más concreta."* | No — reformular |
| `CONFIRMATION_EXPIRED` | 410 | *"La confirmación venció. Vuelve a pedirlo."* + botón "Volver a pedirlo" | No |
| `IDEMPOTENCY_IN_FLIGHT` | 409 | *"Ya estoy procesando ese mensaje."* | Auto-1 reintento tras `Retry-After: 5` |
| Fallo de red | — | *"No pude comunicarme con el agente. Revisa tu conexión."* | Sí |
| Error de JS | — | **NO** se muestra `undefined is not a function`. Un error de render degrada **solo** ese turno a una burbuja: *"No pude mostrar esta respuesta correctamente. Copia el identificador y avisa a soporte."* + `trace_id`. El resto del chat sigue usable | — |

> **Nota sobre `AUDIT_UNAVAILABLE`:** el mensaje explica un mecanismo interno (el registro de
> auditoría) al usuario final. Se acepta: es preferible a un rechazo mudo, y la alternativa —"no
> pude completar la operación"— es el mismo `FORBIDDEN` que D-20 impide diferenciar. El texto técnico
> va debajo para `admin`.

### 7.4 Conexiones lentas

| Situación | Tratamiento |
|---|---|
| Red lenta, todo normal | Estado **1 pensando** con hint a los 15 s. Nada más. El usuario no necesita saber que hay latencia de red |
| Carga de P2/P3 con dataset grande | Skeleton en la tabla + texto *"Cargando…"*. **Umbral de 400 ms**: por debajo no se muestra skeleton (evita parpadeo) |
| Export de 10 000 filas | El `POST` de export puede tardar. Botón *"Preparando archivo…"* + `aria-live`. Con `Retry-After` lo trata el estado 429. Tope de 20 000 filas con mensaje honesto |
| Recarga durante un turno en vuelo | El turno **sigue vivo en el servidor**. Al recargar, la UI consulta `GET /api/v1/ui/sessions/{id}` y si el último mensaje del usuario no tiene respuesta, muestra: *"La respuesta a tu última pregunta todavía no está lista. Espera un momento o vuelve a preguntar."* **No se pierde trabajo silenciosamente** |
| Doble clic en Enviar | Bloqueado por `uiState.inFlight` + `Idempotency-Key` estable (§3.1). Un clic = un turno, siempre |
| Pulsación repetida de Enter | Idem anterior. Además se deshabilita el botón al enviar |
| `429` global por tráfico | Barra superior global: *"El agente está muy solicitado; las respuestas pueden tardar unos segundos."* No es culpa del usuario y no debe parecer un error suyo |

### 7.5 Qué pasa si el turno excede 120 s

Cadena completa, de fuera hacia dentro (`channels.md` §1.7):

| t | Capa | Qué ve el usuario |
|---|---|---|
| 0 s | Envío | Estado 1, burbuja con tres puntos, *"El asistente está pensando."* |
| **15 s** | Hint de UI (canal 10 de la tabla) | *"Sigo trabajando en esto…"* |
| 60 s | Hint de UI | *"Está tardando más de lo normal."* |
| 60 s | Techo de llamada LLM, dentro del agente | El `ThreadPoolExecutor` corta (`llm-provider.md` §2.2). El turno cae a `LLM_UNAVAILABLE` o `TURN_TIMEOUT` |
| 100 s | Hint adicional de UI (decisión propia, `< 120`) | *"Último aviso: sigo esperando. Si no respondo en 20 segundos, cancelo y te lo explico."* |
| **120 s** | **Techo de turno en `AgentService`** | `504 TURN_TIMEOUT` |
| 125 s | Límite de FPM (n/a aquí: uvicorn) | — |
| **130 s** | `proxy_read_timeout` de nginx (tras el ajuste de §5.4) | — |
| **135 s** | `AbortController` del `fetch()` | Si todo lo anterior falló |

**Lo que el usuario ve en el peor caso (120 s):** estado **9 error**:

```
╔══════════════════════════════════════════════════════════════╗
║  Esto está tardando demasiado y lo cancelé.                  ║
║                                                              ║
║  Ya lo intenté varias veces por dentro. Prueba con una       ║
║  pregunta más concreta, por ejemplo indicando el número de   ║
║  guía o el cliente.                                          ║
║                                                              ║
║  trace_id: 7f1c8a2e-…  [Copiar]                               ║
╚══════════════════════════════════════════════════════════════╝
```

| Decisión | Razón |
|---|---|
| **Nunca** spinner infinito | El techo de turno es 120 s (`agent-core.md` §4.3). Un spinner más allá de eso es mentir sobre el estado |
| **Nunca** reintentar automáticamente | Un `504` significa que el interno **ya se agotó** (`channels.md` §1.6.1) |
| Botón Cancelar activo todo el tiempo en estado 1 | `AbortController.abort()`. Aborta la **espera**, no el turno del servidor. Aviso explícito: *"Dejé de esperar. Si la acción ya se había enviado, puede completarse."* Honestidad, no ficción de cancelación |
| El turno tardío **no se pierde** | Aunque el usuario cancele la espera, la respuesta se guarda en `agent_messages` y aparece al recargar o al volver al historial |
| Si fue una escritura (estado 5) | Un dry-run que expira no ejecuta **nada**. El mensaje de expiración (§4.6) es explícito: nada se hizo |

---

## 8. Wireframes

### 8.1 P0 — Login

```
                    ┌──────────────────────────────────────────────┐
                    │            Forsis · Agente                    │
                    │         Pregunta, consulta y reporta          │
                    └──────────────────────────────────────────────┘

                    ┌──────────────────────────────────────────────┐
                    │                                              │
                    │   Usuario                                   │
                    │  ┌────────────────────────────────────────┐  │
                    │  │ cvazquez                           ▌   │  │
                    │  └────────────────────────────────────────┘  │
                    │                                              │
                    │   Contraseña                                 │
                    │  ┌────────────────────────────────────────┐  │
                    │  │ ••••••••••••                    👁       │  │
                    │  └────────────────────────────────────────┘  │
                    │                                              │
                    │   ⚠ Entre 5 intentos fallidos se bloquea     │
                    │     esta cuenta 15 minutos.                  │
                    │                                              │
                    │  ┌────────────────────────────────────────┐  │
                    │  │           Entrar                        │  │
                    │  └────────────────────────────────────────┘  │
                    │                                              │
                    │   Usuario o contraseña incorrectos.          │
                    │                                              │
                    └──────────────────────────────────────────────┘
```

### 8.2 P1 — Chat

```
┌────────────────────────────────────────────────────────────────────────────────────┐
│ Forsis Agente │ Empresa: [ FORSIS ▾ ]        (2) Confirmaciones │ Historial │ ⚙  │
│                                                                        Depuración  │
│                                                       ⚠ Elige empresa para empezar   │
├────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                    │
│  ┌──────────────────────────────────────────────────────────────────────────────┐ │
│  │ ⓘ TIPS DE EJEMPLO                                                            │ │
│  │  ¿Qué guías pendientes tiene el cliente 412?   ← chip                       │ │
│  │  Saldo de tarjeta deudor del operador …        ← chip                       │ │
│  │  Guías liberadas de esta semana                ← chip                       │ │
│  │  ¿Qué puedes hacer?                            ← chip                       │ │
│  └──────────────────────────────────────────────────────────────────────────────┘ │
│                                                                                    │
│                                              ┌───────────────────────────────────┐ │
│                                              │ ¿qué guías tiene el cliente 412?  │ │
│                                              └───────────────────────────────────┘ │
│                                                                                    │
│  ┌──────────────────────────────────────────────────────────────────────────────┐ │
│  │ El cliente 412 tiene 7 guías pendientes.                                     │ │
│  │                                                                              │ │
│  │ ┌─ GUÍA 90822 ─────────────────────────────────────────────────────────────┐ │ │
│  │ │ Estatus      Por Pagar                    │ Destino    Tuxpan, Ver.       │ │ │
│  │ │ Cliente      CLIENTE 412                  │ Ruta       3 días            │ │ │
│  │ │ [Abrir detalle]  [Ver carta porte]                                       │ │ │
│  │ └───────────────────────────────────────────────────────────────────────────┘ │ │
│  │  … (burbuja colapsada a 420 px, botón "Mostrar todo")                        │ │
│  │                                                                              │ │
│  │ ⓘ Fuente: Consultas de guías liberadas · trafico-system · FORSIS             │ │
│  │   trace 7f1c8a2e…  [Copiar]          [Copiar]  ·  Ver detalle ▸             │ │
│  └──────────────────────────────────────────────────────────────────────────────┘ │
│                                                            ↓ Nuevo mensaje (3)     │
├────────────────────────────────────────────────────────────────────────────────────┤
│  ┌──────────────────────────────────────────────────────────────────┐  ┌────────┐ │
│  │ Escribe tu pregunta…                                             │  │ Enviar │ │
│  │                                                                  │  └────────┘ │
│  └──────────────────────────────────────────────────────────────────┘               │
│  Enter envía · Shift+Enter salto de línea              0 / 4 000                    │
└────────────────────────────────────────────────────────────────────────────────────┘
```

### 8.3 P1 — con estado 5 (confirmación requerida) y 4 (dry-run)

```
│  ┌──────────────────────────────────────────────────────────────────────────────┐   │
│  │ ▓▓ SIMULACIÓN — no se ha hecho ningún cambio ▓▓                            │   │
│  │                                                                              │   │
│  │  Solicitar liberación de 3 guías en FORSIS                                   │   │
│  │                                                                              │   │
│  │  Qué hará                                                                  │   │
│  │   • Crear 1 solicitud de liberación en trafico-system                       │   │
│  │   • Registrar 3 entradas de auditoría                                       │   │
│  │   • Enviar la solicitud a ATLAS (resultado asíncrono)                       │   │
│  │                                                                              │   │
│  │  Alcance       3 guías: 12345, 12346, 12347                                 │   │
│  │  Reversible    Sí — puede rechazarse en ATLAS antes de aprobarse            │   │
│  │                                                                              │   │
│  │  Precondiciones  ✅ 3/3 guías elegibles   ✅ motivo válido   ✅ sin duplicada │   │
│  │                                                                              │   │
│  │  ⚠ Aviso: ATLAS responde asíncrono; la liberación puede tardar 2 min.       │   │
│  │                                                                              │   │
│  │  ▸ Ver datos exactos que se enviarán                                        │   │
│  ├──────────────────────────────────────────────────────────────────────────────┤   │
│  │ ⚠ ESTA ACCIÓN ES DE ESCRITURA — requiere tu confirmación                   │   │
│  │   Solicitar liberación de 3 guías         [L2]  trafico-system · FORSIS      │   │
│  │   Solicitado por: cvazquez · trafico.liberacion_solicitar · trace 7f1c8a2e  │   │
│  │                                                                              │   │
│  │   Motivo (lo escribes tú, queda en la auditoría)                            │   │
│  │   ┌──────────────────────────────────────────────────────────────────────┐   │   │
│  │   │ ________________________________________________________________  │   │   │
│  │   └──────────────────────────────────────────────────────────────────────┘   │   │
│  │   El agente propuso: "Corrección de datos del cliente…"  [Usar este texto]   │   │
│  │   (23 caracteres, mínimo 15)                                               │   │
│  │                                                                              │   │
│  │        ┌───────────────────┐   ┌──────────────────┐      ⏱ 4:52              │   │
│  │        │  Confirmar        │   │  No ejecutar     │                         │   │
│  │        └───────────────────┘   └──────────────────┘                         │   │
│  │   (deshabilitado hasta leer el dry-run 2 s con ≥60% visible)                 │   │
│  └──────────────────────────────────────────────────────────────────────────────┘   │
│  El campo de mensaje está deshabilitado mientras haya una confirmación pendiente. │
```

### 8.4 P2 — Historial

```
┌────────────────────────────────────────────────────────────────────────────────────┐
│ Historial de conversaciones                     [Filtros ▾]  ● solo mías  ○ todas   │
├────────────────────────────────────────────────────────────────────────────────────┤
│ Desde [01/10/2026] Hasta [05/10/2026]  Empresa [Todas ▾]  Estado [Todos ▾]          │
│ ☐ Solo con errores   ☐ Solo con escrituras        [Aplicar]  [Limpiar]              │
├────────────────────────────────────────────────────────────────────────────────────┤
│ #  │ Fecha/hora        │ Empresa │ Resumen                  │ Turnos │ Tools │ Estado │
│────┼───────────────────┼─────────┼──────────────────────────┼────────┼───────┼────────│
│ 12 │ 05/10 14:32       │ FORSIS  │ ¿qué guías tiene pendie… │   7    │   3   │ ok     │
│ 11 │ 05/10 14:18       │ GERO    │ saldo tarjeta deudor …   │   3    │   2   │ ⚠ den  │
│ 10 │ 05/10 11:02       │ FORSIS  │ libera las guías 12345…  │   9    │   5   │ ✍ conf │
│  9 │ 04/10 17:45       │ FORSIS  │ ¿qué puedes hacer?        │   1    │   0   │ ok     │
│  8 │ 04/10 16:20       │ FORSIS  |error · no encuentro la …  │   2    │   1   │ ✖ err  │
├────────────────────────────────────────────────────────────────────────────────────┤
│ Mostrando 4 de 12        ◀ 1 2 3 ▶         [Continuar] (abrir en el chat)         │
└────────────────────────────────────────────────────────────────────────────────────┘
```

### 8.5 P4 — Bandeja de confirmaciones + panel

```
┌────────────────────────────────────────────────────────────────────────────────────┐
│ Confirmaciones pendientes (1)                                                     │
├────────────────────────────────────────────────────────────────────────────────────┤
│ ┌──────────────────────────────────────────────────────────────────────────────┐  │
│ │ ⚠ CREAR SOLICITUD DE CANCELACIÓN DE VALE            [L2]  Acciona en 4:52   │  │
│ │   PR-00123                                                                  │  │
│ │   liq.solicitud_crear · FORSIS · lo pidió cvazquez · 05/10 14:28            │  │
│ │                                                                              │  │
│ │   ┌────────────────────────────────────────────────────────────────────────┐ │  │
│ │   │ Alcance: 1 vale (PR-00123), importe $12,480.00                        │ │  │
│ │   │ Precondiciones ✅ ✅ ✅   Reversible: Sí — puede rechazarse en ATLAS  │ │  │
│ │   └────────────────────────────────────────────────────────────────────────┘ │  │
│ │                                                              [Abrir y decidir]│  │
│ └──────────────────────────────────────────────────────────────────────────────┘  │
├────────────────────────────────────────────────────────────────────────────────────┤
│ VENCIDAS (se conservan 1 h)                                                       │
│ ┌──────────────────────────────────────────────────────────────────────────────┐  │
│ │ ⏱ VENCIDA — Crear solicitud de retimbrado de guía 90822     venció 14:31   │  │
│ │   Nada se ejecutó. [Volver a pedirlo]                                        │  │
│ └──────────────────────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────────────────────┘
```

### 8.6 P3 — Detalle de ejecución de tool

```
┌────────────────────────────────────────────────────────────────────────────────────┐
│ ← Volver al chat                                                                  │
├────────────────────────────────────────────────────────────────────────────────────┤
│ Crear solicitud de liberación                        [L2]  ✅ success             │
│ traf.liberacion_solicitar · guid 3f2a91c4-…                 [Copiar id]          │
│ Sesión 7c1b… · Turno #5 · trafico-system · FORSIS · trace 7f1c8a2e…               │
├────────────────────────────────────────────────────────────────────────────────────┤
│ ARGUMENTOS DE ENTRADA                                          completado 05/10 14:29│
│ ┌──────────────────────────────────────────────────────────────────────────────┐ │
│ │ empresa          FORSIS                                                        │ │
│ │ num_guias        ["12345","12346","12347"]                                     │ │
│ │ motivo           "Corrección de datos del cliente receptor en destino Tuxpan" │ │
│ │ contrasena       [REDACTED]                                                    │ │
│ └──────────────────────────────────────────────────────────────────────────────┘ │
├────────────────────────────────────────────────────────────────────────────────────┤
│ RESULTADO                                                                           │
│ ┌──────────────────────────────────────────────────────────────────────────────┐ │
│ │ { "solicitud_id": "SC-00412", "estado": "EN_TRANSITO", "guias": 3 }           │ │
│ └──────────────────────────────────────────────────────────────────────────────┘ │
├────────────────────────────────────────────────────────────────────────────────────┤
│ DRY-RUN (lo que se aprobó antes de ejecutar)                                      │
│   ▸ Ver effects[], blast_radius, precondiciones y payload_preview                │
├────────────────────────────────────────────────────────────────────────────────────┤
│ APROBACIÓN                                                                        │
│   Aprobada por cvazquez · canal ui-standalone · 05/10 14:29 · 812 ms             │
├────────────────────────────────────────────────────────────────────────────────────┤
│ TIEMPO  ████████░░░░░░░░░░░░  812 ms  (el presupuesto por turno es 120 000 ms)  │
└────────────────────────────────────────────────────────────────────────────────────┘
```

### 8.7 P5 — Depuración (admin, periodo de validación)

```
┌────────────────────────────────────────────────────────────────────────────────────┐
│ Depuración · periodo de validación        Del 01/10 al 05/10    [Actualizar]     │
├────────────────────────────────────────────────────────────────────────────────────┤
│ ESTADOS DE LOS 812 TURNOS                                                          │
│  ok ██████████████████████████████ 701 (86.5%)                                    │
│  clarificación ██ 41 (5.1%)   confirmación req ▌ 18 (2.2%)                       │
│  denegado █▌ 22 (2.7%)       sin capacidad ▎ 14 (1.7%)                           │
│  degradado ▏ 9 (1.1%)        error ▏ 7 (0.9%)                                   │
├────────────────────────────────────────────────────────────────────────────────────┤
│ LATENCIA (ms)                          presupuesto (agent-core §4.3)             │
│  llm     p50 3 600   p95 10 500     ████████░░░░░░░░░░░░░░░░░░░░░                │
│  tools   p50   300   p95  2 000     █░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░              │
│  TOTAL   p50 8 120   p95 25 000     ████████░░░░░░░░░░░░░░░░░░░░░░                │
│                                     techo 120 000   ▏ 1 turno lo superó        │
├────────────────────────────────────────────────────────────────────────────────────┤
│ MODO JSON DEL MODELO  ← la pregunta de "70-80% fiable"                            │
│  968 llamadas LLM · 1.19 intentos por turno (p95 2, máx 3)                       │
│  ✅ válidos 875 (90.4%)   🔧 reparados con salvage 87 (9.0%)   ⛔ fail-closed 6   │
│  modelo real: claude-sonnet-4.5 512 · …  456                                    │
├────────────────────────────────────────────────────────────────────────────────────┤
│ TURNOS RECIENTES                                                                   │
│ 14:32  ok        8.1s   ¿qué guías tiene pendientes el cliente 412?   ▸           │
│ 14:31  🔧salvage 11.4s  libera las guías 12345, 12346              ▸           │
│ 14:29  confirm   9.8s  crear solicitud de liberación (L2)            ▸           │
│ 14:28  ⛔timeout 120s  reporte de liquidaciones de octubre           ▸           │
├────────────────────────────────────────────────────────────────────────────────────┤
│ DENEGACIONES (permissions.md §5)                                                   │
│  PRIV_VACIO 9 · TOOL_NO_AUTORIZADA 7 · ROL_NO_MAPEADO 3 · NO_ALLOWLIST 3          │
│ TOP TOOLS: trafico.guias_liberadas_reporte 212 · liq.reporte_operador 98          │
└────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 9. Criterios de aceptación verificables

Lo que el usuario (Cesar) probará en persona en el **HITO GO/NO-GO**. Cada criterio es
ejecutable y tiene un veredicto binario. **A1-A6 son los del Sprint 4** de `sprint-plan-v2.md`,
reproducidos y precisados; **A7-A16 los añade este documento** para cubrir lo que el plan dejaba
como "alcance mínimo derivado".

```
# A1. El login es propio e independiente de los otros sistemas
Entrar con la cuenta sembrada en el Sprint 1. Después, cerrar sesión en trafico-system
(si estuviera abierta) y recargar la UI del agente.
→ PASS si la sesión del agente sigue viva, si son cookies de host/ruta distintos y si no
  comparten almacenamiento. Verificación: DevTools → Application → Cookies (dos hosts, dos
  cookies, ninguna compartida).

# A2. Los intentos fallidos se bloquean
5 intentos con contraseña incorrecta → el 6º intento se rechaza AUNQUE la contraseña sea
correcta, con mensaje explícito y ventana de espera en minutos.
→ PASS. Y el mensaje de credenciales inválidas es genérico (nunca "ese usuario no existe").

# A3. Turno real con tool de lectura, visible en la UI
Escribir "¿qué guías tiene pendientes el cliente 412?"
→ PASS si: se ve el estado "pensando"; a los 15 s aparece el hint (si el turno tarda tanto);
  aparece la tarjeta de `components` con datos REALES de trafico-system; y el pie cita la
  fuente. Es la A1 del Sprint 3 pero frente a ojos humanos, no frente a curl.

# A4. Los 9 estados de UI se alcanzan — 9/9
pensando · respuesta · aclaración · dry-run (stub) · confirmación requerida (stub) ·
denegado · sin capacidad · degradado · error (con trace_id).
→ PASS si se alcanzan los 9 y cada uno se ve DISTINTO del otro.
  Guion para provocarlos:
    1 pensando         cualquier pregunta
    2 respuesta        "¿qué guías tiene el cliente 412?"
    3 aclaración       "dame el saldo del operador"  (sin decir cuál → clarification)
    4 dry-run          stub.escritura_demo (AGENT_UI_L2_STUB=true)
    5 confirmación     el mismo, panel con cuenta atrás
    6 denegado         entrar con una cuenta de prueba cuyo rol no autorice la tool
    7 sin capacidad    "mándale un correo al cliente"  (fuera del catálogo de 42 tools)
    8 degradado        tumbar el composer LLM (AGENT_LLM_COMPOSER_FORCE_FAIL=true)
    9 error            apagar el contenedor de Postgres → 503, o forzar 502 LLM_UNAVAILABLE
→ 9/9 PASS. Para el 9: el trace_id es visible, seleccionable y copiable con un clic.

# A5. Los reportes/historial muestran datos reales y correctos
Comparar el listado de P2 (historial) contra una consulta directa:
  SELECT id, channel_type, user_id, updated_at FROM agent_sessions
   WHERE user_id = '<usuario>' ORDER BY updated_at DESC LIMIT 25;
→ PASS si coinciden fila por fila, en el mismo orden, y las fechas se muestran en
  America/Mexico_City (no en UTC).

# A6. Aislamiento por usuario
Con una segunda cuenta de rol `validador`, intentar abrir la URL de una sesión y de una
ejecución de la primera cuenta.
→ PASS si devuelve 404 (no 403 — no se confirma la existencia del recurso ajeno) y la UI
  dice algo honesto y no técnico. Con rol `admin`: sí se ve, y aparece la columna "usuario".

# A7. Imposible aprobar sin haber visto el efecto  ← el criterio más importante
(a) Provocar el estado 5 y, SIN hacer scroll hasta el dry-run, intentar hacer clic en
    Confirmar.
    → PASS si el botón está deshabilitado (candado C2).
(b) Con DevTools, quitar el atributo `disabled` del botón y hacer clic.
    → PASS si el servidor responde 422 EFFECTS_NOT_ACKNOWLEDGED y NADA se ejecuta (C4).
(c) Reproducir (b) con curl, enviando `decision:"approve"` sin `effects_seen_token`.
    → PASS si responde 422 y nada se ejecuta.
(d) Escribir "sí, dale, confirmo" en el campo de mensaje mientras hay una confirmación
    pendiente.
    → PASS si el campo está DESHABILITADO y nada se aprueba (R5).
→ 4/4 PASS. Si (b) o (c) fallan, es NO-GO: la garantía es de servidor, no de UI.

# A8. El motivo lo escribe el humano
Provocar el estado 5 y observar el campo `motivo`.
→ PASS si: arranca VACÍO; el motivo propuesto por el agente aparece como cita gris no
  editable; usarlo exige un clic explícito; con menos de 15 caracteres el botón Confirmar
  sigue deshabilitado y hay mensaje explicativo.

# A9. Lo irreversible exige un acto extra
Provocar un dry-run del stub con `reversibility` = no reversible.
→ PASS si Confirmar exige además abrir "Ver datos exactos" Y marcar la casilla
  "Entiendo que esta acción no se puede deshacer" (candado C3).

# A10. La confirmación vence y el vencimiento es honesto
Provocar el estado 5 y esperar 5 minutos sin actuar.
→ PASS si: la cuenta atrás llega a 0; los botones se deshabilitan; aparece "La confirmación
  venció. Vuelve a pedirlo."; el dry-run PERMANECE visible en el hilo; y la bandeja P4 la
  muestra con sello VENCIDA diciendo que nada se ejecutó.

# A11. Doble clic = una sola acción
Provocar el estado 5 y hacer doble clic rápido en Confirmar.
→ PASS si se crea UNA sola ejecución. Verificación:
  SELECT count(*) FROM tool_executions WHERE session_id = '<uuid>' AND tool_name LIKE 'stub%';
  → exactamente 1. (Idempotency-Key fijada al montar el panel, no al hacer clic.)

# A12. La empresa nunca se asume
(a) Entrar y, sin elegir empresa, intentar enviar un mensaje.
    → PASS si el botón Enviar está deshabilitado con el hint "Elige empresa…".
(b) Con curl, mandar un ChatRequest sin `company`.
    → PASS si responde 422 VALIDATION_ERROR (channels.md §1.3 regla 3).
(c) Cambiar de FORSIS a GERO a mitad de conversación.
    → PASS si la UI avisa que empieza una conversación nueva y el `session_id` cambia.
(d) Cerrar el navegador, volver a entrar.
    → PASS si la empresa NO viene preseleccionada (no se persiste en localStorage).

# A13. Citación de fuente, y la marca cuando no hay fuente
(a) Una respuesta con datos.
    → PASS si el pie cita la tool (nombre legible) y "ver detalle" abre P3 con los
      argumentos y el resultado reales de esa ejecución.
(b) Escribir "hola".
    → PASS si aparece la marca "Respuesta sin consulta a los sistemas — no contiene datos
      de Forsis." Es la verificación de que una alucinación no puede pasar por consulta real.

# A14. Export correcto en Excel de Windows en español
Pedir un reporte con acentos y con importes, exportar CSV y XLSX, abrir ambos con el Excel
real del equipo del usuario (no con LibreOffice ni con Google Sheets).
→ PASS si: los acentos se ven bien (BOM UTF-8 en el CSV); los importes son NÚMEROS (no
  texto); la fila de totales del XLSX es una fórmula SUM() y cuadra con la de la pantalla;
  el archivo contiene TODAS las filas del reporte, no las 25 paginadas.
→ Y: pedir un reporte de más de 20 000 filas da el mensaje honesto de acotar por fechas.

# A15. El turno que excede 120 s se explica, no se cuelga
Forzar un turno largo (AGENT_FORCE_SLOW_TURN_S=130 en el entorno de validación).
→ PASS si: a los 15 s y a los 60 s aparecen los hints; a los 120 s aparece el estado 9 error
  con el mensaje de "lo cancelé" + trace_id; NUNCA queda un spinner infinito; y NO se ofrece
  reintentar automáticamente.
→ Y: pulsar Cancelar a los 30 s da el aviso honesto ("Si la acción ya se había enviado,
  puede completarse"), no una ficción de cancelación.

# A16. La UI no se rompe sola, y un error de render no tumba el chat
(a) Recargar la página a mitad de un turno en vuelo.
    → PASS si al recargar la UI dice que la respuesta aún no está lista y, al llegar,
      aparece (nada se pierde en silencio).
(b) Inyectar un `components[]` con un `type` desconocido.
    → PASS si se renderiza con el render genérico (NUNCA se oculta un dato que el agente
      devolvió).
(c) Inyectar un `answer` con `<script>alert(1)</script>` y con `<b>negrita</b>`.
    → PASS si se ve el texto literal, sin ejecutar nada y sin aplicar el HTML
      (todo escapado, channels.md §2.8).
(d) Provocar un error de JS en un turno.
    → PASS si solo ese turno degrada a "No pude mostrar esta respuesta correctamente" +
      trace_id, y el resto del chat sigue usable.

# A17. Teclado y accesibilidad mínima
Recorrer toda la UI SOLO con teclado (Tab / Shift+Tab / Enter / Espacio).
→ PASS si: se llega a todos los controles; el foco es siempre visible; Enter envía y
  Shift+Enter salta línea en el chat; en el campo `motivo` Enter NO envía; el panel de
  aprobación recibe el foco en el CUERPO del dry-run y no en el botón Confirmar; y Esc no
  cancela ni confirma nada relevante.
→ Y: todo ✅/❌ tiene texto al lado (no solo color/emoji).

# A18. Depuración responde la pregunta del JSON mode
Abrir P5 como `admin` tras un día de uso.
→ PASS si se puede leer, sin consultar la BD a mano: cuántos turnos hubo por estado; p50/p95
  de latencia contra el techo de 120 s; cuántas llamadas al LLM necesitaron reintento;
  cuántas se repararon con salvage y cuántas murieron fail-closed; qué modelo real respondió.
→ Y: con rol `validador` o con AGENT_UI_DEBUG_ENABLED=false, la ruta devuelve 404.
```

**Umbral de GO.** `A1-A7` y `A12` son **bloqueantes de GO**: si cualquiera falla, es NO-GO sin
discusión (son identidad, los 9 estados, la garantía de aprobación y el guardarraíl de empresa).
`A8-A11` y `A13-A18` son **requeridos**, pero un fallo puntual puede resolverse como corrección
puntual dentro del mismo sprint si no afecta a los anteriores. **A7 (b) y (c) son el corazón del
hito**: si la garantía "imposible aprobar sin ver el efecto" solo vive en el navegador, la UI no
está lista para preceder a ninguna escritura real.

---

## 10. BLOQUEANTES

Nada de lo siguiente se asume resuelto. Cada punto es verificable, tiene dueño y una **resolución
propuesta** concreta; ninguno se "estima" ni se da por hecho.

| # | Bloqueante | Impacto si no se resuelve | Resolución propuesta | Dueño | ¿Bloquea S4? |
|---|---|---|---|---|---|
| **B-U1** | **`ChatResponse` no tiene `sources[]` ni `tool_execution_id`.** Hoy `trace.tools_executed[]` solo trae **nombres** de tool (`channels.md` §1.5). Pero `tools-design.md` §2.5 **S10** exige: *"Toda respuesta que cite cifras debe adjuntar `sources[]`; sin fuente, no se afirma"* | **La citación de fuente nivel L3 es imposible**: no hay cómo enlazar del pie de una respuesta a P3. Y S10 queda sin implementar en la UI, que es donde el usuario la verifica | **ADJ-1** de §6.0: añadir `trace.tool_executions: [{id, tool, class, rows, ms}]`. Adición retrocompatible dentro de un objeto ya obligatorio que por contrato no lleva datos de negocio | Agente 2 (`agent-core`) + Agente 3 (`channels`) | **Sí** para E8. E1-E7 pueden avanzar; L1/L2 de §3.4 se degradan a mostrar solo nombres de tool |
| **B-U2** | **`tool_executions.result_out` es un JSONB sin esquema** (`db-schema.md` §3.3). No hay forma de saber qué columnas son numéricas | **No se pueden calcular totales con seguridad.** `tools-design.md` §2.5 **S3** advierte que los importes conviven como `varchar`/`double`/`*Letra`: un `parseFloat` sobre `"$1,234.00"` da `1` y **nadie lo nota**. Un total falso en un reporte de facturación es exactamente el fallo que este proyecto no puede permitirse | Que cada tool declare `result_shape` + esquema de columnas (`{name, type: string|number|money|date|status}`), expuesto en §6.5. **Mientras no exista: la UI NO muestra fila de totales** y dice *"No puedo sumar esta columna automáticamente."* Degradación segura, nunca un número inventado | Agente 2 (tools) | **Parcial**: los totales (E7) quedan fuera hasta que exista. La tabla y el export sí funcionan |
| **B-U3** | **`agent_messages` no persiste el `status` del turno** ni `trace_id`. El esquema solo tiene `role, content, tool_calls, tool_call_id, token_count` (`db-schema.md` §3.2) | **El historial (P2) no puede mostrar el estado de cada turno** ni filtrar por `status`/`only_errors`, que es entregable explícito del Sprint 4 (E3) y criterio **A5**. Tampoco se puede reconstruir un hilo pasado con los mismos 9 estados que el usuario vio en vivo | Migración: `ALTER TABLE agent_messages ADD COLUMN status VARCHAR(32) NULL, ADD COLUMN trace_id VARCHAR(64) NULL, ADD COLUMN plan_id VARCHAR(64) NULL;` + índice parcial para `only_errors`. Es aditivo, sin reescritura de filas | Agente 1 (`db-schema`) | **Sí** para E3/E6 y para A5 |
| **B-U4** | **`/docs` y `/redoc` están abiertos** en `app/main.py` (`docs_url="/docs"`, `redoc_url="/redoc"`) | Cualquiera con acceso de red al host obtiene **el esquema completo** de la API del agente, incluidos los endpoints de §6 y los nombres de las 42 tools. Es reconocimiento gratis sobre un sistema que escribe en dos ERP de producción | Condicionar por entorno: `docs_url=None if not settings.debug else "/docs"`, o dejarlos detrás de `require_ui_user(role="admin")`. Cambio de una línea | Agente 1 | **No** bloquea el desarrollo, pero **sí** el despliegue del entorno de validación |
| **B-U5** | **No está verificado por dónde entra el navegador del usuario.** `sprint-plan-v2.md` mantiene la decisión de **no exponer el puerto `8099`**, pero `docker/nginx/default.conf` publica `443` (vía `8099:443`) con certificados de `forsispr1.ddns.net`, y la UI necesita ser alcanzable desde los equipos Windows en red local | Si se decide servirla por `8099`, **`channels.md` B-C1 aplica tal cual**: un bearer estático (y ahora una cookie de sesión) sobre un puerto público es superficie innecesaria. Si solo se sirve interna, hay que confirmar que los equipos de los usuarios alcanzan ese host/puerto y con qué nombre DNS y qué certificado | Decidir explícitamente: (a) solo red local por el listener interno `:8080` detrás de un nombre interno, o (b) `8099` **con** las mitigaciones de B-C1. Documentar la elección en un ADR | Infraestructura + usuario | **Sí** para el despliegue del entorno de validación (no para el desarrollo) |
| **B-U6** | **No se verificó qué navegadores usan los usuarios.** Es el mismo **B-C4** de `channels.md`, heredado: *"no se verificó qué navegadores usan los 36 usuarios"* | Esta UI usa ESM nativo, `IntersectionObserver` (candado C2), `AbortController`, `fetch`, `toLocaleString('es-MX')`. En un IE11 o en un kiosco antiguo **no carga nada** — y a diferencia del widget (cuyo fallo aceptable es "no aparecer"), aquí el fallo es "la pantalla está en blanco" | Inventario de navegadores de los equipos piloto antes del Sprint 4. Si todos son Chrome/Edge evergreen (lo esperable en Windows actual), **cerrado sin trabajo**. Si no, la UI muestra una pantalla de "navegador no soportado" en vez de fallar en blanco | TI Forsis | **No** para el desarrollo; **sí** para el HITO (el usuario debe poder abrirla en SU equipo) |
| **B-U7** | **`agent_ui_users` no existe todavía.** Es entregable del **Sprint 1** (`sprint-plan-v2.md` E6/E7), y este documento asume su forma: `username`, `password_hash`, `role ∈ {admin, validador}`, `display_name`, `is_active`, `failed_attempts`, `locked_until`, `last_login_at` | Sin esa tabla no hay login (E1) ni aislamiento por usuario (A6), y por tanto **nada más del Sprint 4 se puede probar** | Confirmar que el Sprint 1 la crea con esos campos **y además** la tabla `agent_ui_sessions(token_hash, user_id, created_at, last_seen_at, expires_at, ip, user_agent)` que §5.5 necesita para sesiones revocables. Esa segunda tabla **no está declarada en ningún documento de fase 1**: es una adición que hay que aprobar | Agente 1 (`db-schema`) | **Sí**, es dependencia dura |
| **B-U8** | **El mapeo `agent_ui_users` → actor del contrato no está definido.** El `ChatRequest.actor` exige `{subject, subject_type, roles[], authorized}` (`channels.md` §1.3) y `permissions.md` §5 **D-2** deniega a todo `human_id` sin fila activa en `agent_identities` con al menos uno de `traf_username` / `liq_nombre_usu` | Un usuario de la UI standalone **que no esté mapeado a una identidad de tráfico o de liquidaciones recibirá `FORBIDDEN / ROL_NO_MAPEADO` en todas sus consultas**, y la UI se verá "rota" aunque funcione perfectamente. Es el modo de fallo más probable del día 1 del HITO | Decidir y documentar: ¿`agent_ui_users.username` **es** el `human_id` de `agent_identities`, o hay una columna de enlace? Y ¿qué `subject_type` se envía para el canal `ui-standalone`? Sembrar las cuentas piloto **ya mapeadas** y con `write_allowlisted` coherente con **D-10** | Agente 1 + Agente 3 | **Sí**. Sin esto, A3 falla por diseño |
| **B-U9** | **El enum `channel` no incluye `ui-standalone`** (`channels.md` §1.3) y el modelo de token es **uno por canal** (§1.4), con `403 CHANNEL_MISMATCH` si no coinciden | La UI **no puede mandar un `channel` válido** sin mentir (usar `widget-trafico`, que además está ligado a otro token). Mentir el canal rompe la trazabilidad por canal y la revocación independiente de tokens | **ADJ-2** de §6.0: añadir `"ui-standalone"` al enum y crear `${FORSIS_AGENT_TOKEN_UI_STANDALONE}`. Nota: la UI es **del mismo proceso** que el agente, así que puede llamar al servicio en proceso en vez de por HTTP — pero hacerlo **saltaría la validación del contrato**, que es justo lo que el Sprint 4 debe demostrar. **Decisión recomendada: la UI llama por HTTP a su propio endpoint**, con su propio token, para que el contrato se ejercite de verdad | Agente 3 | **Sí** |
| **B-U10** | **`effects_seen_token` (candado C4) no está en el contrato** de `POST /api/v1/chat/confirm` | La garantía *"imposible aprobar sin haber visto el efecto"* queda **solo en el navegador**, y un `curl` la rompe. Eso convierte el criterio **A7(b)/(c)** —el corazón del hito— en NO-GO | **ADJ-3** de §6.0: campo opcional con fail-closed si se envía; el servidor recalcula el hash sobre el dry-run persistido y devuelve `422 EFFECTS_NOT_ACKNOWLEDGED` si no coincide. Mismo patrón que `confirmation_token` ligado a `hash(tool, args, empresa, actor)` en `tools-design.md` §7.2 **D3** | Agente 2 + Agente 3 | **Sí** para A7 |
| **B-U11** | **El stub L2 no está especificado en ningún documento.** `sprint-plan-v2.md` S4 E2/E4 dice "contra el stub" sin definir qué es | Sin un stub bien definido, los estados **4** y **5** y los candados **C1-C4** no se pueden probar en S4 (las tools L2 reales llegan en el Sprint 7) y el criterio **A4** cae a 7/9 | Registrar `stub.escritura_demo` (clase L2, **sin canal upstream**) cuyo dry-run devuelva un `plan` con la forma exacta de `tools-design.md` §2.3, incluidos `effects[]`, `preconditions[]`, `blast_radius` y un caso con `reversibility` no reversible (para A9). Activado solo por `AGENT_UI_L2_STUB=true` y con nombre que lo delate en `tool_executions` | Agente 2 | **Sí** para E9, A4, A7-A11 |
| **B-U12** | **`proxy_read_timeout` de nginx está en 120 s**, igual que el techo de turno. `channels.md` §1.7 fila 6 exige **130 s** (*"nunca debe cortar antes que la app"*) | Con ambos en 120 s hay una condición de carrera: nginx puede cortar **antes** de que el agente serialice su `504 TURN_TIMEOUT` tipado, y el usuario vería un 504 genérico de nginx — sin `answer` legible, sin `trace_id`. Rompe **A15** y la regla `channels.md` §1.5.1 (*`answer` nunca es null*) | Cambiar a `proxy_read_timeout 130s;` en `docker/nginx/default.conf` (ambos server blocks). Una línea | Infraestructura | **Sí** para A15 |
| **B-U13** | **No hay esquema declarado para `components[]`.** `channels.md` §1.5 muestra `guide-card` como ejemplo, sin catálogo cerrado de `type` ni de `actions[]` | La UI implementa un render genérico (`title` + `fields[]` + `actions[]`) que **no se rompe** con tipos desconocidos (A16b), pero **no puede dar afordancias específicas** ni validar que un `action` sea seguro de ofrecer. Un `actions[]` que dispare una escritura sin pasar por el gate del §4 sería un agujero | Catalogar los `type` del MVP y declarar que **ningún `action` de `components[]` puede ejecutar una escritura**: toda escritura pasa por el flujo del §4, sin excepción. Hasta entonces, la UI renderiza los `actions[]` **solo** como enlaces de navegación/lectura, nunca como botones de ejecución | Agente 3 | **No** (el render genérico cubre S4), pero sí antes de habilitar `actions[]` ejecutables |
| **B-U14** | **No está decidido quién usa la UI en el HITO ni con qué datos.** Los usuarios son operadores, auxiliares, facturación, tráfico y gerencia (5 perfiles con 5 niveles de permiso distintos), pero no hay lista de cuentas piloto | El HITO se evaluaría con **una sola cuenta** (`admin`), que es precisamente la que **no** ejercita el estado **6 denegado**, ni el aislamiento (**A6**), ni **D-1/D-3** de `permissions.md`. Se validaría el camino feliz de un superusuario y se descubrirían los permisos en producción | Definir **al menos 3 cuentas piloto**: un `admin`, un `validador` con rol de tráfico, y un `validador` con rol de liquidaciones — cada una mapeada a identidades reales distintas (B-U8), con una de ellas **deliberadamente sin** permiso para alguna tool, para poder provocar el estado 6 de forma reproducible | Usuario (Cesar) + Agente 1 | **Sí** para A4 (estado 6) y A6 |
| **B-U15** | **El periodo de retención y el borrado de datos no están definidos para la UI.** `agent_messages` guarda texto de negocio y `tool_executions.result_out` guarda **resultados completos** de consultas (saldos, importes, listados de guías) | La UI **expone** esos datos por HTTP a un navegador (P2/P3/export). Sin política de retención, el agente acumula indefinidamente copias de datos de los dos ERP, en una BD nueva, y el export los replica a archivos en equipos Windows. Es una ampliación real de la superficie de datos de Forsis que nadie ha aprobado | Definir retención de `agent_messages` / `tool_executions.result_out` (propuesta: **90 días** para `result_out`, que es lo voluminoso y lo sensible; `audit_records` **se conserva**, es append-only por diseño) y registrar que el export queda auditado (`event_type='ui_export'`, §6.7) | Agente 1 + usuario | **No** para S4; **sí** antes del piloto del Sprint 8 |

### 10.1 Resumen de bloqueantes por severidad

| Bloquean el **arranque** del Sprint 4 | Bloquean **criterios del HITO** | Bloquean el **despliegue** del entorno de validación | Posteriores al HITO |
|---|---|---|---|
| **B-U7** (tablas `agent_ui_users` / `agent_ui_sessions`) · **B-U8** (mapeo a `agent_identities`) · **B-U9** (`channel: ui-standalone` + token) | **B-U1** (A13) · **B-U3** (A5) · **B-U10** (A7) · **B-U11** (A4, A7-A11) · **B-U12** (A15) · **B-U14** (A4 estado 6, A6) | **B-U4** (`/docs` abierto) · **B-U5** (puerto/origen de acceso) · **B-U6** (navegadores) | **B-U2** (totales — degradación segura mientras tanto) · **B-U13** (`components[]` con acciones) · **B-U15** (retención de datos) |

### 10.2 Lo que este documento NO pudo verificar

Se declara explícitamente en vez de asumirse:

| # | No verificado | Por qué importa |
|---|---|---|
| 1 | Que el `POST /api/v1/chat` real devuelva lo que `channels.md` especifica. Hoy `app/main.py` lo tiene como **stub** que responde `{"error":"not_implemented"}` | Toda la UI se diseñó contra el **documento**, no contra una implementación. Los Sprints 2-3 son dependencia dura del Sprint 4 (y el plan ya lo dice) |
| 2 | Que exista una tool de lectura real contra `trafico-system` al empezar S4 | **A3** la necesita. `sprint-plan-v2.md` ya declara la dependencia: *"sin una tool real, la UI solo muestra texto"* |
| 3 | El aspecto real del `result_out` de las tools de reporte | El render de reportes (§3.3) se diseñó desde la forma **declarada** de `tools-design.md`. B-U2 es la consecuencia explícita |
| 4 | Que los equipos de los usuarios alcancen el host del agente, con qué nombre y con qué certificado | B-U5 / B-U6 |
| 5 | El rendimiento del render con un reporte de 20 000 filas en los equipos reales | Se acotó por diseño (25 filas visibles, export en servidor), pero no se midió |
| 6 | Si `openpyxl` está en las dependencias del proyecto | El export XLSX (E7) lo requiere. Hay que confirmarlo o añadirlo en `requirements.txt` antes de S4 |

---

## Apéndice A — Variables de entorno de la UI

Ningún valor real. Todos los secretos se inyectan por entorno y **nunca** se escriben en el
repositorio (lección directa de `BOT_TOKEN` commiteado — `channels.md` §3.1, `sprint-plan-v2.md`
SEC-1).

```ini
# --- Identidad y sesión de la UI ---
AGENT_UI_ENABLED=true
AGENT_UI_SESSION_COOKIE=forsis_agent_ui_session
AGENT_UI_SESSION_TTL_H=8
AGENT_UI_SECRET_KEY=${AGENT_UI_SECRET_KEY}          # [REDACTED] — 32+ bytes aleatorios
AGENT_UI_HASH_ALGO=argon2id                          # nunca md5
AGENT_UI_MAX_LOGIN_ATTEMPTS=5
AGENT_UI_LOCKOUT_MINUTES=15

# --- Token del canal (ADJ-2 de §6.0) ---
FORSIS_AGENT_TOKEN_UI_STANDALONE=${FORSIS_AGENT_TOKEN_UI_STANDALONE}   # [REDACTED]

# --- Flags del periodo de validación ---
AGENT_UI_DEBUG_ENABLED=true        # habilita P5 y /api/v1/ui/metrics (solo rol admin)
AGENT_UI_L2_STUB=true              # registra stub.escritura_demo (B-U11). NUNCA en producción
AGENT_UI_EXPORT_MAX_ROWS=20000

# --- Límites y tiempos (derivados de channels.md §1.7) ---
AGENT_UI_FETCH_TIMEOUT_S=135       # AbortController del cliente
AGENT_UI_HINT_1_S=15
AGENT_UI_HINT_2_S=60
AGENT_UI_HINT_3_S=100

# --- Sólo para provocar criterios de aceptación; prohibidos fuera de validación ---
AGENT_LLM_COMPOSER_FORCE_FAIL=false   # A4 estado 8 (degradado)
AGENT_FORCE_SLOW_TURN_S=0             # A15 (turno > 120 s)
```

| Variable | Riesgo si queda activa fuera del entorno de validación |
|---|---|
| `AGENT_UI_L2_STUB=true` | Una tool L2 de simulacro registrada en producción. Debe fallar el arranque si `ENV=production` |
| `AGENT_UI_DEBUG_ENABLED=true` | P5 y `/api/v1/ui/metrics` accesibles (aunque siguen exigiendo rol `admin`) |
| `AGENT_LLM_COMPOSER_FORCE_FAIL` / `AGENT_FORCE_SLOW_TURN_S` | Degradación o timeouts inducidos. Deben fallar el arranque si `ENV=production` |

---

## Apéndice B — Trazabilidad del documento

| Requisito de la tarea | Sección |
|---|---|
| 1. Alcance y objetivo, alineado al Sprint 4 | §1 (con §1.3 entra/no entra y la regla de S4-bis) |
| 2. Inventario de pantallas (7) | §2 (P0-P6) |
| 3. Diseño del chat, reportes, citación, 9 estados | §3 (§3.3 reportes, §3.4 citación, §3.5 los 9 estados) |
| 4. Flujo de confirmación de escrituras | §4 (§4.4 = la garantía con 4 candados) |
| 5. Arquitectura frontend + ¿compartir con el widget? | §5 (§5.1 decisión, §5.2 compartir solo el núcleo sin DOM) |
| 6. Endpoints adicionales con rigor de `channels.md` | §6 (§6.0 ADJ-1/2/3 + 11 endpoints `/api/v1/ui/*`) |
| 7. Accesibilidad y pragmática, 120 s | §7 (§7.3 errores, §7.5 el techo de 120 s) |
| 8. Wireframes ASCII | §8 (7 wireframes) |
| 9. Criterios de aceptación verificables | §9 (A1-A18, con umbral de GO) |
| 10. Bloqueantes | §10 (B-U1…B-U15 + §10.2 lo no verificable) |

**Documentos relacionados:** `ADR-001-stack-y-secuencia.md` · `channels.md` · `tools-design.md` ·
`permissions.md` · `agent-core.md` · `db-schema.md` · `sprint-plan-v2.md` — todos en
`knowledge/phase1/`.

**Código al que afecta (no modificado por este documento):** `app/main.py` (montaje de routers y
`StaticFiles`, §5.4), `docker/nginx/default.conf` (`proxy_read_timeout` 120→130 s, **B-U12**),
`requirements.txt` (`openpyxl`, §10.2 punto 6). **No se toca** `trafico-system`,
`liquidaciones-system` ni `forsis-bot`.
