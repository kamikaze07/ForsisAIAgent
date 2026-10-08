# Sprint 3 — Acta de ejecución

**Fecha:** 2026-10-05
**Objetivo:** primera capability real de lectura sobre datos productivos, con sandbox SQL
de solo lectura y PlanGuard aplicando la clasificación de riesgo.
**Resultado:** ✅ **40 PASS / 0 FAIL** (`./verify-sprint3.sh`)
**Catálogo:** `CATALOG_VERSION = 2026.10.05-sprint3`

---

## 1. Qué se construyó

| Componente | Archivo | Función |
|---|---|---|
| Clases de riesgo | `app/core/risk.py` | `RiskClass` L0–L3 y `SPRINT3_ALLOWED` (solo L0/L1) |
| Parser allowlist SQL | `app/infrastructure/db/sql_guard.py` | R-3: rechaza todo lo que no sea `SELECT`/`SHOW`/`DESCRIBE`/`WITH` |
| Pool de solo lectura | `app/infrastructure/db/readonly_pool.py` | R-1..R-5: usuario `forsis_agent_ro`, transacción read-only, `LIMIT` forzado, `MAX_EXECUTION_TIME` |
| Capability L0 | `app/capabilities/trafico/guias_listar.py` | `traf.guias_listar`: lista/filtra guías de SICRET |
| Escrituras denegadas | `app/capabilities/trafico/escrituras_denegadas.py` | `traf.guia_liberar` (L2) y `traf.factura_cancelar` (L3): registradas, `execute()` siempre deniega |
| Catálogo explícito | `app/capabilities/catalog.py` | Declaración única de qué existe; sin reflexión |
| PlanGuard | `app/core/plan_guard.py` | 7 gates; **gate 5 (permisos + riesgo) operativo**, 1–4/6–7 stubs ruidosos |
| ToolRunner | `app/core/executor/tool_runner.py` | Guard → JSON Schema → ejecución con techo 30 s → `degraded` ante fallo → métricas |
| Composición determinista | `app/core/response/template_composer.py` | `compose_tool_outcome()`: los datos los renderiza el código, no el LLM |
| Cableado del turno | `app/core/agent_service.py` | Planner con catálogo → ToolRunner → plantilla → auditoría |

---

## 2. Decisiones de diseño (y por qué)

1. **El LLM no escribe SQL ni nombres de columna.** La consulta es un esqueleto fijo con
   parámetros vinculados y un mapa **cerrado** de columnas ordenables. Un parámetro
   inesperado es un 422 del JSON Schema, no una cadena concatenada.
   Evidencia: `order_by: "; DROP TABLE guias"` → `TOOL_PARAMS_INVALID`.
2. **El LLM no redacta cifras de negocio.** Elige la herramienta; el código presenta el
   resultado con plantillas. Ninguna cifra es alucinable.
3. **Defensa en profundidad para SQL.** La barrera **fuerte** es el `GRANT SELECT` del
   servidor (error 1792 verificado en ambos destinos); el parser R-3 es la barrera
   **temprana**, que falla antes de la red y deja motivo auditable.
4. **Escrituras registradas pero denegadas.** Sin una L2/L3 en el catálogo, el criterio
   "un tool L3 es rechazado, no ejecutado" sería vacuo. Ahora se verifica contra algo real
   y `execute()` no tiene ningún camino de código que escriba.
5. **`definition` y `risk_class` son `ClassVar`.** Decidir si algo está permitido no debe
   requerir instanciar el objeto que haría el trabajo.
6. **Timeout con hilo, no `asyncio.wait_for`.** pymysql es bloqueante; además el servidor
   corta por `MAX_EXECUTION_TIME`, así el techo no depende solo del cliente.
7. **Fallo de tool → `status: degraded`**, nunca una excepción que tumbe el turno.
8. **Precedencia de estado:** `denied` > `degraded` > `ok`. Una denegación es una decisión
   de política y debe verse como tal, no disfrazarse de error.
9. **Gates pendientes visibles, no invisibles:** los stubs 1–4/6–7 llevan `assert` ruidoso.

---

## 3. Acceso a datos: cómo quedó

Dos servidores distintos, ambos alcanzados **sin modificar un solo archivo** de los
sistemas productivos:

| Destino | Host | Base | Usuario | Verificado |
|---|---|---|---|---|
| `sicret_pr` | `host.docker.internal:3306` | `sicrePR` (latin1) | `forsis_agent_ro@172.26.%` | ✅ |
| `sicret_gero` | `host.docker.internal:3306` | `sicreGero` | `forsis_agent_ro` | ✅ |
| `trafico` | `trafico-db:3306` | `trafico` (utf8mb4) | `forsis_agent_ro@172.29.%` | ✅ |

- Se añadió el grant acotado a la subred `172.29.%` y la red externa
  `trafico-system_default` al `docker-compose.yml` **del agente** (red externa: no se
  edita el compose de trafico-system).
- `AGENT_RO_PASSWORD` vive solo en `.env` (chmod 600, gitignored). Sin ella el pool
  **aborta el arranque** por diseño.

### Controles SQL verificados (R-1..R-5)

| ID | Control | Evidencia |
|---|---|---|
| R-1 | Usuario sin privilegios de escritura | `CURRENT_USER() = forsis_agent_ro@…` en ambos destinos |
| R-2 | Transacción read-only del servidor | error **1792** "Cannot execute statement in a READ ONLY transaction" |
| R-3 | Allowlist del parser | 8/8 sentencias peligrosas rechazadas; 3/3 lecturas permitidas |
| R-4 | `LIMIT` obligatorio | 3 pedidas → 3 devueltas, `truncated=true` |
| R-5 | Techo de tiempo de consulta | `MAX_EXECUTION_TIME` + techo de 30 s en el runner |

Sentencias rechazadas por R-3: `INSERT`, `UPDATE`, `DELETE`, `DROP`, multi-statement
(`SELECT 1; DROP TABLE guias`), comentario ejecutable (`/*!32302 … */`), `TRUNCATE`, `GRANT`.

---

## 4. Criterios de aceptación

| # | Criterio | Resultado |
|---|---|---|
| A1 | Capability L0 real devuelve datos productivos | ✅ folios `PR-228811`/`PR-228810` reales |
| A2 | Catálogo versionado y auditable | ✅ 3 capabilities, planner solo ve `traf.guias_listar` |
| A3 | Un tool L3 es **rechazado, no ejecutado** | ✅ `denied`, `data=None`, gate `permisos` |
| A3b | Un tool L2 es denegado en esta fase | ✅ `CAPABILITY_DENIED` |
| A4 | RBAC: actor sin permiso no ejecuta | ✅ `missing_permissions=['trafico.guias.read']` |
| A5 | Fallo de tool no tumba el turno | ✅ `status: degraded`, HTTP 200 |
| A6 | Parámetros inválidos se rechazan | ✅ `TOOL_PARAMS_INVALID` (límite fuera de rango, parámetro no declarado, inyección en `order_by`) |
| A7 | Métricas por capability y clase de riesgo | ✅ `tool_calls`, `tool_ok`, `tool_denied`, `tool_calls_l0..l3`, `sql_queries`, `tool_latency` |
| A8 | Sin regresión del Sprint 2 | ✅ smalltalk sigue sin llamar tools (`tools_executed: []`) |

---

## 5. Evidencia end-to-end (HTTPS 8099, respuesta real)

Petición: `"muestrame las ultimas 2 guias de forsis"` · company `FORSIS` · rol `trafico`

```
Encontré 2 guías de FORSIS: (mostrando las primeras 2)

• PR-228811 — 05/10/2026 15:58 — OLAF MENDEZ SERRANO — Por Timbrar
• PR-228810 — 05/10/2026 15:57 — OLAF MENDEZ SERRANO — Por Timbrar
```

```
status: ok
tools: ['traf.guias_listar']
llm_model_real: space-bunny-free     (combo nominal "Forsis")
latency_ms: {'llm': 2224, 'tools': 1, 'total': 2253}
```

La tool resuelve en **1–9 ms**; el coste del turno es la planificación del LLM.

---

## 6. Sistemas productivos: intactos

- `trafico-system`: los 15 archivos con cambios en `git status` tienen fecha
  **2026-10-02** (trabajo previo del usuario, ajeno a este sprint).
- `liquidaciones-system`: ídem, 13 archivos previos.
- Lo único modificado hoy en esos árboles son artefactos de `app/storage/`
  (pases de descarga, PDFs) **generados por las propias aplicaciones en producción**.
- `find -mmin -720` sobre código fuente de ambos sistemas: **sin resultados**.
- El aprovisionamiento del usuario read-only se hizo **dentro de los contenedores**
  (`trafico-php`, `trafico-db`), sin editar archivos del repositorio.

---

## 7. Estado del stack

```
forsis-ai-agent-app     healthy   (FastAPI, 5 redes, jsonschema 4.23.0, pymysql 1.4.6)
forsis-ai-agent-db      healthy   (PostgreSQL 16, sin puertos al host)
forsis-ai-agent-nginx   healthy   (TLS 0.0.0.0:8099 -> 443)
```

Redes de `app`: `ai-network` · `forsis-agent_net` · `forsis-ai-agent_default` ·
`forsis-comunicaciones` · `trafico-system_default` (solo lectura).

`knowledge/` **no existe** en el contenedor (B-5 respetado).

---

## 7b. Incidencias de esta sesión (declaradas, no ocultadas)

1. **Regresión real introducida y corregida.** El primer cableado puso `self.registry` solo
   en `__init__`; la prueba A4.1 del Sprint 2 construye el servicio con `__new__` y rompió
   con `AttributeError: 'AgentService' object has no attribute 'registry'`
   (Sprint 2 bajó a 36/37). **Causa:** estado del proceso guardado como estado de instancia.
   **Fix:** `registry`/`runner` son `ClassVar` con default del proceso; `__init__` solo
   sobrescribe el runner si se le inyecta uno. Sprint 2 volvió a **37/37**.
2. **A4.1 es intermitente por contención de Docker, no por el código.** Lanza un contenedor
   desechable (`docker compose run --rm`) y falla si se ejecuta inmediatamente después de
   otra suite; en ejecución aislada pasa de forma reproducible (37/37 verificado dos veces
   seguidas). **Recomendación:** no encadenar las suites sin pausa entre ellas.
3. **Dependencia faltante detectada antes de usarse.** `jsonschema` no estaba en la imagen;
   la validación de parámetros habría degradado en silencio. Añadido `jsonschema==4.23.0`
   a `requirements.txt` e imagen reconstruida.

---

## 8. Pendiente para los siguientes sprints

- **Gates 1–4 y 6–7 de PlanGuard** siguen como stubs: coherencia de empresa, límites de
  alcance, dry-run obligatorio y confirmación humana (Sprint 7, junto con la escritura real).
- **Más capabilities de lectura** (liquidaciones, `guia_pases_descarga`) y la clase L1.
- **Interfaz web standalone** para validar el agente antes del hito GO/NO-GO.
- **Escrituras** (`traf.guia_liberar`) permanecen denegadas hasta el GO/NO-GO documentado
  en `hito-go-nogo.md`.

---

## 9. Reversión

Quitar el Sprint 3 es borrar las líneas correspondientes de `_CATALOG` en
`app/capabilities/catalog.py`: sin entrada en el catálogo, la capability no existe para el
planner ni para el runner. El usuario `forsis_agent_ro` puede revocarse con
`DROP USER` sin afectar a ningún sistema productivo.
