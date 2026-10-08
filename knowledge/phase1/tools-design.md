# Forsis AI Agent — Diseño de Herramientas (Tools / Actions)

**Fase:** 1 (diseño arquitectónico) · **Agente:** 3 · **Fecha:** 2026-10-05
**Entregable hermano:** `permissions.md` (matriz de permisos y auth)

**Fuentes citadas (Fase 0):**
- `trafico-system-analysis.md` (TSA) · `trafico-system-actions.md` (TSAC) · `trafico-system-api-inventory.md` (TSAPI)
- `liquidaciones-system-analysis.md` (LSA) · `liquidaciones-system-actions.md` (LSAC) · `liquidaciones-system-api-inventory.md` (LSAPI)
- `liquidaciones-security-strategy.md` (LSS) · `data-access-strategy-analysis.md` (DAS) · `omniroute-config.md` (OMC)
- `PHASE-1-BRIEF.md` (decisiones 1–5)

> **Credenciales:** ningún valor real aparece aquí. Todo secreto se referencia como variable de
> entorno (`${VAR}`) o `[REDACTED]`.

---

## 0. Resumen ejecutivo

| Métrica | Valor |
|---|---|
| Tools totales del catálogo MVP | **32** |
| L0 — lectura segura | 19 |
| L1 — lectura con inferencia / agregación | 5 |
| L2 — escritura reversible o con gate humano nativo | 7 |
| L3 — escritura irreversible | **1** (solo registrada como *denied-by-default*, no expuesta) |
| Tools que escriben en MySQL de negocio directamente | **0** |
| Tools de escritura sin dry-run | **0** |

**Tres reglas que gobiernan todo el catálogo:**

1. **Regla de corte de canal** (DAS §1): *lecturas* → conexión DB **read-only**; *escrituras* →
   **API REST** del sistema dueño. Ninguna tool mezcla ambos canales.
2. **Regla de gate** (LSS §4, PHASE-1-BRIEF decisión 4): toda acción irreversible se materializa
   como **solicitud** en el workflow existente (`solicitudes_cancelacion` en liquidaciones,
   `solicitudes-liberacion` / `solicitudes-timbrado` vía ATLAS en tráfico). El agente **crea la
   solicitud**; un humano con rol exacto la aprueba. El agente nunca ejecuta el acto final.
3. **Regla de dry-run** (PHASE-1-BRIEF §Reglas): toda tool de clase ≥ L2 acepta `dry_run: bool`
   y **el planner la invoca primero con `dry_run=true` siempre**. El Executor rechaza (fail-closed)
   cualquier invocación L2/L3 que no venga precedida de un dry-run válido en la misma traza.

---

## 1. Taxonomía de riesgo (L0–L3)

Unifica las dos escalas de Fase 0 (🟢🟡🔴 de TSAC §0.3 y L0–L3 de LSAC §0) en una sola:

| Clase | Nombre | Efecto | Dry-run | Confirmación humana | Auditoría |
|---|---|---|---|---|---|
| **L0** | Lectura segura | Ninguno. Idempotente, reintentable | n/a | No | Log de consulta (sin payload de datos) |
| **L1** | Lectura con inferencia / agregación | Ninguno, pero el resultado **condiciona decisiones**: requiere criterios explícitos y citación de fuente | n/a | No | Log + SQL ejecutado + reglas aplicadas |
| **L2** | Escritura reversible, o escritura cuyo único efecto es **encolar** una solicitud | Reversible por re-edición, rechazo o cancelación documentada | **Obligatorio** | **Sí** (operador en allowlist confirma el plan) | Log completo: plan, payload, respuesta, actor humano |
| **L3** | Escritura irreversible | Cascada sin reversa vía API (FIFO sobre `tarjeta_contenido`, CFDI ante SAT, pagos de nómina) | Obligatorio | **No basta**: prohibido en MVP | Registrado como intento denegado |

**Política MVP (fail-closed):**
- L0, L1 → disponibles a todo operador autorizado.
- L2 → disponibles tras dry-run + confirmación explícita.
- **L3 → NO EXPUESTO.** El Registry no las registra como invocables; existen en el catálogo
  únicamente para que el planner pueda responder *"esto requiere a un humano, aquí está la
  solicitud que puedo crear en su lugar"* (degradación a la L2 equivalente).

### 1.1 Degradación L3 → L2 (patrón central del diseño)

| Intención del usuario | L3 prohibida | L2 que el agente ejecuta en su lugar |
|---|---|---|
| "Autoriza la liquidación LQ-12345" | `POST /api/autorizar_liquidacion.php` (LSAC L3-1) | `liq.solicitud_crear` con `modulo=LIQUIDACIONES`, `tipo=AUTORIZACION` → **BLOQUEANTE B-02** (módulo no existe aún, LSS §2) |
| "Cancela el vale de caja PR-00123" | `POST /api/vale_caja_cancelacion.php` (L3-7) | `liq.solicitud_crear` con `modulo=CAJA_CHICA`, `tipo=CANCELACION` |
| "Abona $5,000 a la tarjeta 412" | `POST /api/movimiento_tarjeta.php` (L3-3) | `liq.solicitud_crear` con `modulo=TARJETA_DEUDOR` |
| "Timbra la guía 98765" | `POST /api/facturacion/carta-porte-manual/emitir` (TSAC §3.3) | `traf.timbrado_solicitar` (crea solicitud en ATLAS, L2) |
| "Libera las guías 1,2,3" | — (no hay L3; el flujo ya es solicitud) | `traf.liberacion_solicitar` (L2) |
| "Paga la nómina de la quincena" | `rrhh/nomina/pagar` (TSAC §7) | **Ninguna.** Fuera de alcance: el agente responde con el link a la UI |

---

## 2. Contrato común de toda tool

### 2.1 Envelope de entrada

```json
{
  "tool": "traf.guias_listar",
  "trace_id": "01JD…",
  "actor": {
    "human_id": "jsalazar",
    "channel": "mattermost|widget",
    "channel_user_id": "…",
    "allowlisted": true
  },
  "context": {
    "empresa": "FORSIS",
    "sistema": "trafico|liquidaciones"
  },
  "args": { "...": "específicos de la tool" },
  "dry_run": false,
  "confirmation_token": null,
  "idempotency_key": null
}
```

**Campos invariantes:**

| Campo | Regla |
|---|---|
| `trace_id` | ULID por turno de conversación. Encadena dry-run → confirmación → ejecución |
| `actor.human_id` | **Siempre el humano**, nunca el usuario de servicio. Es lo que se escribe en auditoría |
| `actor.allowlisted` | Derivado server-side de `AGENT_ALLOWLIST_*`, **nunca** del contenido de la conversación (TSAC §0.4) |
| `context.empresa` | **Obligatorio y explícito en toda tool**, incluso L0. Ver §2.4 |
| `dry_run` | Rechazado con `400 DRY_RUN_NOT_APPLICABLE` en L0/L1; obligatorio en primera llamada L2 |
| `confirmation_token` | Opaco, emitido por el dry-run, TTL 300 s, un solo uso, ligado a `(trace_id, tool, hash(args))` |
| `idempotency_key` | Obligatorio en L2. Si se repite, devuelve el resultado cacheado sin reejecutar |

### 2.2 Envelope de salida

```json
{
  "ok": true,
  "tool": "traf.liberacion_solicitar",
  "trace_id": "01JD…",
  "class": "L2",
  "mode": "execute",
  "data": { "...": "…" },
  "plan": null,
  "sources": [
    {"kind": "api", "system": "trafico", "endpoint": "POST /api/guias/liberacion/solicitar"},
    {"kind": "db",  "system": "sicrePR", "query_hash": "sha256:…"}
  ],
  "warnings": ["…"],
  "audit_id": 48213,
  "duration_ms": 412
}
```

Error:

```json
{
  "ok": false,
  "error": {
    "code": "FORBIDDEN|VALIDATION|STATE_CONFLICT|UPSTREAM_TIMEOUT|CONFIRMATION_REQUIRED|
             CONFIRMATION_EXPIRED|SESSION_EXPIRED|DRY_RUN_REQUIRED|BLOCKED_L3|EMPRESA_UNSET",
    "message": "…",
    "retryable": false,
    "upstream": {"status": 502, "body_excerpt": "…"}
  },
  "audit_id": 48214
}
```

**Normalización obligatoria** (TSAC §12.8): trafico-system convive con dos convenciones
(`{ok,data}` en guías/liberación/timbrado y `{success,…}` en pases de descarga); liquidaciones usa
`{ok,message}` y formato DataTables (`{draw,recordsTotal,data[]}`). **Ninguna de estas formas se
filtra al LLM**: el adapter las traduce al envelope único de arriba.

### 2.3 Resultado de un dry-run

```json
{
  "ok": true,
  "mode": "dry_run",
  "class": "L2",
  "plan": {
    "summary": "Solicitar liberación de 3 guías en FORSIS",
    "effects": [
      {"system":"trafico","target":"solicitud_liberacion","op":"INSERT","rows":1},
      {"system":"atlas","target":"/api/solicitudes-liberacion.php","op":"POST","rows":1},
      {"system":"trafico","target":"guia_origen_auditoria","op":"INSERT","rows":3}
    ],
    "preconditions": [
      {"check":"guias.estatus elegible","result":"pass","detail":"3/3 válidas"},
      {"check":"motivo no vacío","result":"pass"},
      {"check":"sin solicitud duplicada abierta","result":"pass"}
    ],
    "reversibility": "Reversible: la solicitud puede rechazarse en ATLAS antes de aprobarse",
    "blast_radius": {"guias": ["12345","12346","12347"], "importe_mxn": null},
    "payload_preview": {"motivo":"…","guias":[{"num_guia":"12345"}, "…"]}
  },
  "confirmation_token": "ct_…",
  "expires_at": "2026-10-05T18:34:12Z"
}
```

### 2.4 Guardarraíl de empresa (el más importante)

Verificado en Fase 0 y **común a los dos sistemas**:

- trafico-system: `POST /api/guias/empresa` conmuta la conexión de BD de **todas** las consultas
  posteriores de la sesión (TSAPI §3.2).
- liquidaciones-system: `ConnectionManager` resuelve empresa inválida o ausente **silenciosamente a
  `forsis`** (LSA §3.2; LSAC §1 lo llama *"el guardarraíl más importante"*).

**Reglas derivadas, no negociables:**

| # | Regla |
|---|---|
| E1 | `context.empresa` es obligatorio en el envelope. Ausente → `400 EMPRESA_UNSET`. No hay default |
| E2 | **Una cookie jar por `(sistema, empresa)`**, aislada y nunca compartida con sesiones humanas (LSAC §13.4) |
| E3 | Antes de cada acción el adapter reafirma empresa (`POST /api/guias/empresa` / `POST /api/set_empresa.php`) y **verifica el eco** de la respuesta. Discrepancia → abortar |
| E4 | En lecturas DB, la empresa determina el **DSN** (`sicrePR` vs `sicreGero`, `sicre2PR` vs `sicre2Gero`), no un `WHERE` |
| E5 | Los usuarios `CARLOSD`, `FATIMA`, `RUBISEL01` están forzados a FORSIS por código (LSA §3.2). El usuario de servicio del agente **no** debe llamarse así ni heredar ese caso |

### 2.5 Reglas semánticas obligatorias (anti–"dato plausible pero falso")

Heredadas de LSAC §8 (R1–R12) y TSA §4. **El Executor las aplica en la capa de datos, no el LLM.**

| # | Regla | Dónde se aplica |
|---|---|---|
| S1 | Saldo de operador = `SUM(tarjeta_contenido.importeRestante)`. **Nunca** `tarjeta_deudor.saldo` (caché divergente) | `liq.td_saldo_real`, `liq.reconciliar_cuenta_corriente` |
| S2 | BONO/COBRO **por tabla de origen** (`premiosliq`=bono, `gastosliq`=cobro), nunca por el texto de `concepto` | `liq.liquidacion_detalle`, `liq.reconciliar_premios_cobros` |
| S3 | Importes conviven como `varchar`/`double`/`*Letra`: normalizar con `(float)str_replace(['$',','],'',$v)` | todo adapter de liquidaciones |
| S4 | Estados son texto libre heredado: filtrar con `LIKE 'CANCELADO%'` / `stripos(...,'Cancelad')`, nunca `=` | todos los listados |
| S5 | `sicrePR` es **latin1**: transcodificar a UTF-8 antes de serializar (TSA §4.1) | todo adapter de lectura SICRET |
| S6 | Ralentí se detecta con `UPPER(concepto) LIKE '%RELENTI%'` (grafía legacy) | `liq.reportes_reseteo_listar` |
| S7 | Estatus de guía gobierna elegibilidad; revalidar **inmediatamente antes** de actuar, no al consultar (TSAC §2.2) | `traf.liberacion_*`, `traf.timbrado_*` |
| S8 | Reseteos con `estado='BORRADOR'` o `requiere_revision=1` **no cuentan para reportes** | `liq.reportes_reseteo_listar` |
| S9 | `folio_imp` es único **lógico** (validado en app, no en BD): colisión lanza excepción | `liq.recepcion_guia_guardar` |
| S10 | Toda respuesta del agente que cite cifras debe adjuntar `sources[]`; sin fuente, no se afirma | capa de respuesta |

---

## 3. Canal A — Lecturas DB read-only

### 3.1 Conexiones

| Alias | DSN (env) | Base | Charset | Uso |
|---|---|---|---|---|
| `db.sicret_forsis` | `${DB_SICRET_FORSIS_DSN}` | `sicrePR` | **latin1** | Guías, facturas, liquidaciones, TD — FORSIS |
| `db.sicret2_forsis` | `${DB_SICRET2_FORSIS_DSN}` | `sicre2PR` | utf8mb4 | SICRET v2 FORSIS |
| `db.sicret_gero` | `${DB_SICRET_GERO_DSN}` | `sicreGero` | utf8mb4 | GERO |
| `db.sicret2_gero` | `${DB_SICRET2_GERO_DSN}` | `sicre2Gero` | utf8mb4 | GERO v2 |
| `db.trafico` | `${DB_TRAFICO_DSN}` | `trafico` (MariaDB 11) | utf8mb4 | Pases de descarga, timbrado, planeación, auditoría |

Credenciales: usuario **`forsis_agent_ro`**, `[REDACTED]`, inyectado por env. Ver `permissions.md` §4.

**Nota de conectividad verificada** (TSA §4.1): `192.168.1.209` **no soporta TLS**. El cliente debe
forzar `ssl=0` / `--ssl=0`, o falla con `ERROR 2026 TLS/SSL error`. Debe quedar en el DSN y en los
healthchecks.

### 3.2 Defensa en profundidad del read-only

Cinco capas, porque una sola basta para un accidente:

| # | Capa | Implementación |
|---|---|---|
| R-1 | Privilegio de BD | `GRANT SELECT ON sicrePR.* TO 'forsis_agent_ro'@'…'` y análogos. **Sin** INSERT/UPDATE/DELETE/CREATE/DROP/FILE/PROCESS |
| R-2 | Sesión | `SET SESSION TRANSACTION READ ONLY` + `autocommit=1` al abrir cada conexión |
| R-3 | Parser | Allowlist de sentencias: solo `SELECT` / `SHOW` / `EXPLAIN` / `DESCRIBE`. Rechazo de `;` múltiple, de comentarios `/*! */`, y de todo token en `{INSERT,UPDATE,DELETE,REPLACE,MERGE,TRUNCATE,DROP,ALTER,CREATE,GRANT,SET,LOAD,INTO OUTFILE,CALL,HANDLER,LOCK,FLUSH}` |
| R-4 | Catálogo de consultas | El LLM **no escribe SQL libre**. Solo elige una `query_id` de un catálogo versionado y pasa parámetros tipados (ver §3.3) |
| R-5 | Límites de ejecución | `MAX_EXECUTION_TIME=5000` ms, `LIMIT` forzado ≤ 1000 filas, pool máx 4 conexiones, 2 queries concurrentes por traza |

> **Decisión:** R-4 (catálogo cerrado) es preferible a "text-to-SQL con validador". Un validador es
> una allowlist de sintaxis; el catálogo es una allowlist de **semántica**, y además hace las
> consultas auditables, cacheables y testeables por contrato.

### 3.3 Catálogo de consultas parametrizadas (`db.query`)

Única tool genérica de BD. `args = {query_id, params, empresa}`.

| `query_id` | Clase | Base | Params | Devuelve |
|---|---|---|---|---|
| `guias.por_estatus_y_rango` | L0 | sicret | `estatus[]`, `fecha_ini`, `fecha_fin`, `limit` | folio, fecha, cliente, estatus, operador, placas |
| `guias.detalle_por_folio` | L0 | sicret | `num_guia` | fila completa normalizada a UTF-8 |
| `guias.sin_pase_descarga` | **L1** | sicret + trafico | `dias_min`, `fecha_ini`, `fecha_fin` | `LEFT JOIN` guías ↔ `guia_pases_descarga(activo=1)` → huecos. *Pregunta que ningún endpoint responde (DAS §2.2)* |
| `guias.aging_por_cliente` | L1 | sicret | `cliente`, `dias_min` | antigüedad por estatus |
| `pases.cobertura_por_periodo` | L1 | trafico | `fecha_ini`, `fecha_fin` | % guías con pase, por origen (`correo`/`manual`) |
| `td.saldo_real_por_tarjeta` | **L1** | sicret | `tarjeta` | `SUM(importeRestante)` + comparación contra `tarjeta_deudor.saldo` → `divergencia` (regla S1) |
| `td.aging_cargos_pendientes` | L1 | sicret | `dias_min`, `tarjeta?` | cargos `<Por Pagar>` por antigüedad |
| `liq.cola_por_autorizar` | L0 | sicret | `limit` | liquidaciones en `<Por Autorizar>` con importe y antigüedad |
| `liq.descuadre_totales` | **L1** | sicret | `folio` | recálculo aritmético vs `total`/`totalLetra` (regla S3) |
| `liq.vales_diesel_doble_liquidacion` | L1 | sicret | `fecha_ini`, `fecha_fin` | vales cuyas guías aparecen en >1 `folio_Liq` → inconsistencia (LSAC §7.1) |
| `reseteos.pendientes_revision` | L0 | sicret | `limit` | `estado='BORRADOR' OR requiere_revision=1` (regla S8) |
| `kpi.guias_por_estatus` | L0 | sicret | `fecha_ini`, `fecha_fin` | conteos agregados |
| `kpi.operacion_unificada` | L0 | trafico | `fecha_ini`, `fecha_fin` | lectura de la vista `v_operacion_2026_unificada` |
| `audit.guia_origen` | L0 | trafico | `num_guia` | trazabilidad de origen/auditoría de la guía |

Cada `query_id` vive en `sql/catalog/<id>.sql` con: SQL con placeholders nombrados, firma de
parámetros, `max_rows`, clase de riesgo y un test de contrato contra la instancia real.

---

## 4. Canal B — Escrituras vía API REST

### 4.1 Endpoints base

| Sistema | Base URL (interno) | Auth | Nota |
|---|---|---|---|
| trafico-system | `http://nginx:8091` (red `forsis-comunicaciones`) | Cookie `trafico_session` vía `POST /login` | No publicado al host (TSAPI §0) |
| liquidaciones-system | `http://liquidaciones-nginx:8081` (red `liquidaciones-system_default`) | Cookie `PHPSESSID` vía `POST /api/login.php` | Listener interno HTTP plano; evita TLS y no amplía superficie pública (LSA §2.1) |
| ATLAS | `http://host.docker.internal:8097` | **Sin credenciales** (confianza de red) | **Solo indirecto**: el agente nunca llama a ATLAS, llama a trafico-system que delega (TSAC §2.3) |
| Omniroute (LLM) | `http://host.docker.internal:20129` (prod: `20131`) | `Authorization: Bearer ${OMNIROUTE_API_KEY}` | **No es un tool**: es el proveedor del planner. `20130` es el dashboard (OMC) |

### 4.2 Gestión de sesión del adapter

```
login() → cookie jar aislada por (sistema, empresa)
  trafico:        POST /login (form-urlencoded) → trafico_session
                  GET  /api/sesion/heartbeat cada 30 min (vida 8h inact / 12h abs)
                  POST /api/guias/empresa  ← antes de CADA acción
  liquidaciones:  POST /api/login.php (JSON) → PHPSESSID (vida 8h)
                  POST /api/set_empresa.php ← antes de CADA acción, con verificación de eco
```

Reintento: **un solo** reintento tras `401 SESSION_EXPIRED` con re-login. Si vuelve a fallar →
`SESSION_EXPIRED` al usuario, sin loop. `403 PASSWORD_CHANGE_REQUIRED` es **fatal sin reintento**
(significa que alguien marcó cambio forzado a la cuenta de servicio: alertar a operaciones).

### 4.3 Protocolo de reintentos y duplicados

| Situación | Acción |
|---|---|
| Timeout de red en una tool **L0/L1** | Reintentar hasta 2 veces con backoff 0.5s/2s |
| Timeout o 5xx en una tool **L2** | **NO reintentar ciegamente.** Un 5xx de ATLAS no implica que la solicitud no se creara (TSAC §2.5). Procedimiento: (1) esperar 3 s, (2) consultar `traf.solicitudes_listar` / `liq.solicitudes_pendientes` filtrando por `idempotency_key`/folios+motivo, (3) si existe → devolver éxito con `warnings:["recuperado_por_verificacion"]`, (4) si no existe → reintentar una vez |
| `AtlasIntegrationException::timeout()` / `::conexionFallida()` / `::porHttpStatus()` | Mapear a `UPSTREAM_TIMEOUT` con `retryable` según la tabla anterior; nunca a `ok:true` |
| `idempotency_key` repetida | Devolver respuesta cacheada (TTL 24 h) sin tocar el upstream |

---

## 5. Catálogo de tools — trafico-system

Prefijo `traf.`. Columna **Canal**: `DB` = lectura read-only, `API` = REST.

### 5.1 Consulta de guías y estado (L0/L1)

| Tool | Clase | Canal | Input | Output | Respaldo |
|---|---|---|---|---|---|
| `traf.guias_buscar` | L0 | DB (`guias.por_estatus_y_rango`) | `{empresa, estatus?[], fecha_ini, fecha_fin, cliente?, operador?, limit≤200}` | `{total, items[{num_guia,fecha,cliente,estatus,operador,placas,factura}]}` | DAS §2.2 (listado cruzado sin endpoint), TSA §4.3 |
| `traf.guia_detalle` | L0 | DB + API fallback | `{empresa, num_guia}` | `{guia{…}, cfdi?{uuid,estado}, pase_descarga?{disponible,folio_pase,fecha_cita}, elegibilidad{editable,liberacion,timbrado}}` | TSAC §1.1, §1.2 |
| `traf.guias_estados_catalogo` | L0 | API `GET /api/guias/estados` | `{empresa}` | `{estados[]}` | TSAPI §3.1 |
| `traf.guia_elegibilidad` | L1 | DB + lógica `GuiaBloqueoService` | `{empresa, num_guia[]}` | por guía: `{bloqueada, puede_editarse, puede_liberacion, puede_timbrado, razon}` | TSA §7, TSAC §1.2 |
| `traf.guias_kpis` | L0 | API `GET /api/guias/kpis` | `{empresa, fecha_ini?, fecha_fin?}` | `{kpis{…}}` | TSAPI §3.1 |
| `traf.guias_kpis_extendido` | L1 | DB (`kpi.guias_por_estatus`, `kpi.operacion_unificada`) | `{empresa, fecha_ini, fecha_fin, dimension: "estatus"\|"cliente"\|"operador"}` | `{series[], totales{}, metodologia}` | DAS §2.2 |
| `traf.guias_exportar` | L0 | API `GET /api/guias/exportar` | `{empresa, filtros{…}, formato:"xlsx"\|"csv"}` | `{artifact_id, filename, bytes, mime, expires_at}` | TSAPI §3.1 |
| `traf.carta_porte_obtener` | L0 | API `GET /api/guias/carta-porte[/xml]` | `{empresa, num_guia, formato:"pdf"\|"xml"}` | `{artifact_id, …}` | TSAPI §3.1 |
| `traf.cfdi_consultar` | L0 | API `GET /api/facturacion/cfdi-emitidos[/detalle]` | `{empresa, num_guia?, uuid?, fecha_ini?, fecha_fin?}` | `{items[{uuid,folio,estado,fecha,total}]}` | TSAC §3.4 |

> **Artefactos binarios:** las tools de exportación/descarga **nunca** devuelven bytes al LLM.
> Guardan el fichero en el almacén del agente y devuelven `artifact_id` + metadatos; el canal
> (Mattermost / widget) resuelve el `artifact_id` a un adjunto. TTL 24 h.

### 5.2 Estado de liberación (L0/L1 + L2)

| Tool | Clase | Canal | Input | Output |
|---|---|---|---|---|
| `traf.liberacion_estado` | L0 | API `GET /api/facturacion/reportes/solicitudes[/detalle]` | `{empresa, num_guia?[], folio_solicitud?, estado?, page?}` | `{items[{folio_solicitud,guias[],estado,motivo,fecha,solicitante}]}` |
| `traf.liberacion_validar` | L1 | API `POST /api/guias/liberacion/validar` | `{empresa, guias[≤50]}` | `{validas[], invalidas[{num_guia,razon}]}` |
| `traf.guias_liberadas_reporte` | L0 | API `GET /api/facturacion/reportes/guias-liberadas` | `{empresa, fecha_ini, fecha_fin}` | `{items[]}` |
| **`traf.liberacion_solicitar`** | **L2** | API `POST /api/guias/liberacion/solicitar` | `{empresa, motivo (≥15 chars), guias[{num_guia}] (1..50), dry_run, confirmation_token?, idempotency_key}` | `{folio_solicitud, estado:"EN_TRANSITO", guias_enviadas[]}` |

**`traf.liberacion_solicitar` — contrato detallado**

```
Precondiciones (evaluadas en dry-run, re-evaluadas en execute):
  P1 actor.allowlisted == true                                   → FORBIDDEN
  P2 empresa fijada y verificada por eco                         → EMPRESA_UNSET
  P3 motivo no vacío, ≥15 caracteres, sin placeholders del LLM   → VALIDATION
  P4 1 ≤ len(guias) ≤ 50, folios únicos                          → VALIDATION
  P5 POST /api/guias/liberacion/validar → invalidas == []        → STATE_CONFLICT
     (OBLIGATORIO antes de cada envío: el estatus cambia entre consulta y acción — TSAC §2.2)
  P6 ninguna guía con solicitud abierta (consultar liberacion_estado) → STATE_CONFLICT
Efectos declarados en el plan:
  trafico.solicitud_liberacion  INSERT 1  (estado EN_TRANSITO)
  trafico.guia_origen_auditoria INSERT n  (GuiaOriginPolicyService)
  atlas  POST /api/solicitudes-liberacion.php  (asíncrono, resultado por webhook HMAC)
Reversibilidad: la solicitud puede rechazarse en ATLAS antes de aprobarse → L2, no L3
Fallo 5xx: NO reintentar sin verificar duplicado (§4.3)
```

### 5.3 Pases de descarga (L0)

| Tool | Clase | Canal | Input | Output |
|---|---|---|---|---|
| `traf.pase_descarga_consultar` | L0 | API `GET /api/facturacion/guias/pase-descarga` | `{empresa, num_guia}` | `{disponible, pase?{folio_pase,contenedor,fecha_cita,origen,remitente_correo,fecha_carga,hash_sha256}}` |
| `traf.pase_descarga_descargar` | L0 | API `…/pase-descarga/descargar` | `{empresa, num_guia}` | `{artifact_id, filename, mime}` — MIME restringido a `application/pdf\|image/jpeg\|image/png` |
| `traf.pases_cobertura` | L1 | DB (`pases.cobertura_por_periodo`, `guias.sin_pase_descarga`) | `{empresa, fecha_ini, fecha_fin, dias_min?}` | `{cobertura_pct, faltantes[{num_guia,dias_sin_pase,cliente}], por_origen{correo,manual}}` |
| `traf.pases_ingesta_salud` | L0 | DB `trafico.service_heartbeats` + conteo últimas 24 h | `{}` | `{worker:"correo-pases-cron", ultimo_latido, pases_24h, estado:"ok"\|"degradado"\|"sin_datos"}` |

> `traf.pases_cobertura` es el caso de uso canónico de por qué la lectura va por DB: requiere un
> `LEFT JOIN` entre `sicrePR.guias` y `trafico.guia_pases_descarga`, **dos bases distintas**, sin
> endpoint equivalente (DAS §2.2).
> `traf.pases_ingesta_salud` cubre un modo de fallo silencioso real: el watcher IMAP corre y no
> procesa nada (TSA §2).

### 5.4 Timbrado — solo solicitud (L2) y consulta (L0)

| Tool | Clase | Canal | Input | Output |
|---|---|---|---|---|
| `traf.timbrado_validar` | L1 | API `POST /api/guias/timbrado/validar` | `{empresa, guias[]}` | `{validas[], invalidas[]}` |
| `traf.timbrado_estado` | L0 | API reportes de solicitudes | `{empresa, num_guia?[], folio_solicitud?}` | `{items[]}` |
| **`traf.timbrado_solicitar`** | **L2** | API `POST /api/guias/timbrado/solicitar` | igual contrato que liberación (`motivo` + `guias[]` + dry-run + token) | `{folio_solicitud, estado}` |
| `traf.cfdi_emitir_*` · `traf.cfdi_cancelar` · `traf.pago_emitir/cancelar` | **L3** | — | — | **NO EXPUESTAS.** CFDI ante SAT es irreversible (TSAC §3.3). El agente responde con la solicitud L2 equivalente o el enlace a la UI |

### 5.5 Tools explícitamente fuera de alcance en MVP

Registradas como *denied* para que el planner las explique en vez de improvisar:

| Dominio | Motivo |
|---|---|
| RRHH: `nomina/*`, `finiquitos/*`, `aguinaldos/*`, `deducciones-programadas/*`, tarjetas deudor de empleado | `pagar` no es reversible (TSAC §7) |
| Facturación: emisión/cancelación de CFDI, notas de crédito, complementos de pago | L3 fiscal |
| Administración: `usuarios/*`, `roles*`, `sesiones/revocar`, `control/users/*` | `session_version++` mata sesiones humanas en caliente e invisiblemente (TSAC §9) |
| Proveedores: `pagos/*`, `aprobaciones/*` | L3 financiero |
| Planeación: `despachos/batch-*`, `sellos/*`, `peajes/*` | Escritura masiva; candidata a Fase 2 con dry-run por lote |
| Comunicaciones/WhatsApp: `mensajes/enviar-*` | El agente no debe emitir mensajes a terceros en MVP |
| Crear/editar/copiar guía (`/api/guias/crear`, `/editar`, `/sellos/actualizar`, `/copiar/guardar`) | Son L2 técnicamente y **candidatas de Fase 2**; fuera del MVP porque `INSERT` en `sicrePR.guias` exige **todos** los campos (todas las columnas son `NOT NULL` sin default — TSA §4.3) y el riesgo de dato basura supera el valor |

---

## 6. Catálogo de tools — liquidaciones-system

Prefijo `liq.`.

### 6.1 Consulta de liquidaciones (L0/L1)

| Tool | Clase | Canal | Input | Output |
|---|---|---|---|---|
| `liq.liquidaciones_listar` | L0 | API `GET /api/liquidaciones.php` | `{empresa, estatus?, search?, page, length≤100, order_col?, order_dir?}` | `{total, items[{folio_liq,fecha,unidad,tarjeta,operador,total,estatus}]}` |
| `liq.liquidacion_detalle` | L0 | API `GET /api/liquidacion_detalle.php` | `{empresa, folio}` | `{cabecera{}, viajes[], premios[/*BONO*/], gastos[/*COBRO*/], td_detalle[], vales[], vales_diesel[]}` — clasificación por tabla de origen (regla S2) |
| `liq.liquidacion_estado` | L0 | API + DB (`liq.cola_por_autorizar`) | `{empresa, folio?}` | `{folio_liq, estatus, transiciones_posibles[], bloqueos[], antiguedad_dias}` |
| `liq.cola_por_autorizar` | **L1** | DB | `{empresa, limit≤100}` | `{items[{folio_liq,importe,operador,dias_en_cola}], total, importe_total}` — **el valor real del agente: detectar y priorizar, no autorizar** (LSAC §13.1) |
| `liq.td_estado_cuenta` | L0 | API `GET /api/tarjeta_deudor.php` | `{empresa, tarjeta, filter?, page?}` | `{movimientos[], paginacion{}}` |
| `liq.td_saldo_real` | **L1** | DB (`td.saldo_real_por_tarjeta`) | `{empresa, tarjeta}` | `{saldo_real, saldo_cacheado, divergencia, cargos_pendientes[], metodo:"SUM(importeRestante)"}` — regla S1 |
| `liq.operador_buscar` | L0 | API `GET /api/buscar_operadores.php` | `{empresa, nombre}` | `{items[{tarjeta,num_ope,nombreCompleto,estatus}]}` |
| `liq.vale_diesel_detalle` | L0 | API `GET /api/vale_diesel_detalle.php` | `{empresa, folio}` | `{vale{}, guias[]}` |
| `liq.caja_chica_detalle` | L0 | API `GET /api/caja_chica_detalle.php` | `{empresa, folio}` | `{vale{}, es_cancelable, titular}` |
| `liq.reportes_reseteo_listar` | L0 | DB (`reseteos.pendientes_revision`) | `{empresa, solo_pendientes?, limit}` | `{items[{id,num_tracto,estado,requiere_revision,porcentaje_ralenti}]}` — reglas S6/S8 |

### 6.2 Reconciliación (L1 — el núcleo de valor del agente)

Todas son **lectura pura**. Producen hallazgos con evidencia, nunca correcciones.

| Tool | Clase | Input | Output | Respaldo |
|---|---|---|---|---|
| `liq.reconciliar_cuenta_corriente` | L1 | `{empresa, tarjeta?, dias_aging?=30}` | `{divergencias[{tarjeta,saldo_real,saldo_cacheado,delta}], aging[{mov,concepto,importeRestante,dias}], resumen{}}` | LSAC §7.3 |
| `liq.reconciliar_premios_cobros` | L1 | `{empresa, folio}` | `{bonos[], cobros[], total_calculado, total_declarado, descuadre, componentes{diesel,premios,autopistas,propinas,llantas,gastosTotal,gastosAsig,gastosDif,viajesForaneos,subtotal,total}}` | LSAC §7.2 |
| `liq.reconciliar_diesel_guias` | L1 | `{empresa, fecha_ini, fecha_fin}` | `{inconsistencias[{folio_vale,guias_dobles[],folios_liq[]}], litros_vs_detliq[], kmlt_fuera_rango[]}` | LSAC §7.1 |
| `liq.reconciliar_liquidacion_completa` | L1 | `{empresa, folio}` | Compuesta: ejecuta las tres anteriores sobre un folio y devuelve `{hallazgos[{severidad,regla,evidencia,fuente}], veredicto:"cuadra"\|"descuadre"\|"indeterminado"}` | composición |

**Contrato de un hallazgo** (uniforme, citable):

```json
{
  "severidad": "alta|media|baja",
  "regla": "S1|S2|S3|R4|…",
  "titulo": "Saldo cacheado divergente en tarjeta 412",
  "evidencia": {"saldo_real": 18450.0, "saldo_cacheado": 19100.0, "delta": -650.0},
  "fuente": {"kind":"db","system":"sicrePR","query_id":"td.saldo_real_por_tarjeta"},
  "accion_sugerida": {"tool":"liq.solicitud_crear","args_preview":{"modulo":"TARJETA_DEUDOR","tipo":"EDICION"}}
}
```

### 6.3 Reportes (L0)

| Tool | Clase | Canal | Input | Output |
|---|---|---|---|---|
| `liq.reporte_operador` | L0 | API `GET /api/reportes_operador_listado.php` | `{empresa, desde, hasta, page, length, search?}` | `{items[], totales{}}` |
| `liq.reporte_exportar` | L0 | Composición DB + render propio | `{empresa, tipo:"operador"\|"cola_autorizar"\|"td_aging"\|"reconciliacion", params{}, formato:"xlsx"\|"csv"\|"md"}` | `{artifact_id, filename, filas, generado_en}` |
| `liq.liquidacion_pdf` | L0 | API `pdf_liquidacion.php` (Chromium headless, listener `:8081`) | `{empresa, folio}` | `{artifact_id, mime:"application/pdf"}` |

> `liq.reporte_exportar` **renderiza en el agente**, no en liquidaciones-system: los reportes
> interesantes son agregaciones que no existen como endpoint (DAS §2.2). Por eso lee por DB y
> construye el fichero localmente.

### 6.4 Escritura — solicitudes (L2)

| Tool | Clase | Canal | Input | Output |
|---|---|---|---|---|
| **`liq.solicitud_crear`** | **L2** | API `POST /api/solicitud_cancelacion.php?action=crear` | `{empresa, modulo, referencia_id, folio_texto, monto, motivo (≥15 chars), tipo, dry_run, confirmation_token?, idempotency_key}` | `{solicitud_id, estatus:"PENDIENTE", revisor_requerido:"SUPER USUARIO"}` |
| `liq.solicitudes_pendientes` | L0 | API `?action=listar_pendientes` | `{empresa}` | `{items[{id,modulo,referencia_id,folio_texto,monto,solicitante,motivo,fecha_solicitud}]}` |
| `liq.solicitudes_conteo` | L0 | API `?action=conteo_pendientes` | `{empresa}` | `{pendientes}` |
| `liq.solicitud_aprobar` / `liq.solicitud_rechazar` | **L3** | — | — | **NO EXPUESTAS.** `aprobar` ejecuta la cancelación real en MySQL (LSAC L3-4). Exclusivo de humano `SUPER USUARIO` |

**`liq.solicitud_crear` — contrato detallado**

```
Dominios válidos (verificados en código, LSAC §6.12):
  modulo ∈ {CAJA_CHICA, TARJETA_DEUDOR, RECEPCION_GUIAS}   ← valor fuera de esto lanza
                                                              "Módulo desconocido" (LSS §2)
  tipo   ∈ {CANCELACION, EDICION, CONVERTIR_TD, CONVERTIR_DIRECTO}
Precondiciones:
  P1 actor.allowlisted
  P2 empresa fijada y verificada
  P3 motivo ≥15 chars, redactado por el humano o confirmado por él — NO autogenerado por el LLM
  P4 modulo ∈ dominio  → VALIDATION  (incluye el caso BLOQUEANTE B-02 de LIQUIDACIONES)
  P5 unicidad lógica: no debe existir otra PENDIENTE con la misma tripleta
     (empresa, modulo, referencia_id) → STATE_CONFLICT (LSAC §3.7)
  P6 referencia_id y folio_texto verificados contra el detalle real (no inventados):
     el dry-run resuelve el folio y muestra titular + monto para que el humano lo reconozca
Efectos: solicitudes_workflow.sqlite → solicitudes_cancelacion INSERT 1 (PENDIENTE)
         MySQL de negocio: INTACTO
Reversibilidad: alta — ?action=rechazar con motivo
```

> **Por qué esta tool es la pieza central** (LSAC §4, LSS §4): el sistema **ya tiene** un workflow
> de aprobación con cola, análisis por módulo y auditoría de revisor (`revisado_por`,
> `fecha_revision`, `motivo_rechazo`), y con chequeo de rol por **match exacto**
> (`if ($priv !== 'SUPER USUARIO')`), que es más estricto que `esUsuarioAdminGlobal()`. Reutilizarlo
> es más seguro que inventar un gate propio. El agente entra por la puerta que ya existe.

### 6.5 Escritura — operativa de bajo impacto (L2, opcional en MVP)

Se diseñan pero se despliegan **desactivadas por feature flag** (`AGENT_TOOLS_L2_OPERATIVAS=false`):

| Tool | Clase | Endpoint | Nota |
|---|---|---|---|
| `liq.reseteo_actualizar` | L2 | `POST /api/reportes_reseteo_actualizar.php` | Corrige datos parseados de un PDF. Reversible por re-edición. Emite WebSocket. Dry-run muestra diff campo a campo contra el valor actual |
| `liq.recepcion_guia_guardar` | L2 | `POST /api/guardar_recepcion_guia.php` | `folio_imp` único lógico → el dry-run debe llamar `?action=check_folio_imp` (regla S9) |
| `liq.premio_categoria_guardar` | L2 | `POST /api/reportes_premios_categorias.php` | `patron` es UNIQUE; `id=null` crea |
| `liq.reseteo_eliminar` | **L3** | `POST /api/reportes_reseteo_eliminar.php` | **NO EXPUESTA**: no recuperable (LSAC L2-3 lo marca L2 pero sin reversa → reclasificado a L3 aquí) |

> **Reclasificación deliberada:** LSAC lista `reportes_reseteo_eliminar` como L2 "con reversa no
> recuperable". Un borrado sin reversa es L3 por definición de esta taxonomía (§1). Se corrige.

---

## 7. Protocolo de dry-run

### 7.1 Máquina de estados

```
            ┌──────────────────────────────────────────────┐
            │ 1. PLAN      el planner elige tool + args    │
            └───────────────────────┬──────────────────────┘
                                    ▼
            ┌──────────────────────────────────────────────┐
            │ 2. DRY-RUN   dry_run=true (SIEMPRE, L2+)     │
            │   · evalúa TODAS las precondiciones          │
            │   · resuelve referencias contra datos reales │
            │   · declara effects[] / blast_radius         │
            │   · emite confirmation_token (TTL 300 s)     │
            │   · NO escribe nada aguas arriba             │
            └───────────────────────┬──────────────────────┘
                                    ▼
            ┌──────────────────────────────────────────────┐
            │ 3. CONFIRM   humano en allowlist aprueba     │
            │   · ve summary + effects + blast_radius      │
            │   · botón/comando explícito, no "sí" en      │
            │     lenguaje natural ambiguo                 │
            └───────────────────────┬──────────────────────┘
                                    ▼
            ┌──────────────────────────────────────────────┐
            │ 4. EXECUTE   dry_run=false + token + idem_key │
            │   · RE-EVALÚA las precondiciones (el estado   │
            │     cambió entre 2 y 4 — regla S7)           │
            │   · si cambió → abort STATE_CONFLICT, vuelve  │
            │     a 2 con el plan nuevo                     │
            └───────────────────────┬──────────────────────┘
                                    ▼
            ┌──────────────────────────────────────────────┐
            │ 5. VERIFY    lee el efecto para confirmarlo   │
            │   · liberación → traf.liberacion_estado       │
            │   · solicitud  → liq.solicitudes_pendientes   │
            └──────────────────────────────────────────────┘
```

### 7.2 Reglas de implementación

| # | Regla |
|---|---|
| D1 | **El dry-run no es una simulación en memoria**: ejecuta las validaciones *reales* del sistema upstream cuando existen sin efecto lateral (`liberacion/validar`, `timbrado/validar`, `check_folio_imp`, `listar_pendientes`). Un dry-run que no consulta no vale |
| D2 | El dry-run **nunca** emite POST que escriba. Si el único modo de validar fuera escribir, la tool no puede tener dry-run → se degrada a L3 → no se expone |
| D3 | `confirmation_token` está ligado a `hash(tool, args_canonicalizados, empresa, actor)`. Cambiar un solo argumento invalida el token |
| D4 | TTL 300 s. Expirado → `CONFIRMATION_EXPIRED`, nuevo dry-run obligatorio |
| D5 | Token de un solo uso. Reintento legítimo → se usa `idempotency_key`, no el token |
| D6 | **Re-evaluación en execute (paso 4) obligatoria.** Es el aprendizaje de `validarSeleccion()`: el estatus puede cambiar entre la consulta y la acción (TSAC §2.2) |
| D7 | El plan presentado al humano se renderiza desde `effects[]` estructurado, **no** desde prosa del LLM. El LLM no puede mentir sobre lo que la tool hará |
| D8 | `blast_radius` es obligatorio y cuantitativo: folios afectados, filas, importe en MXN. Si el agente no puede acotarlo, no ejecuta |
| D9 | Si `effects[]` del execute difiere de los del dry-run → se registra `warnings:["effects_drift"]` y se alerta en el canal |

### 7.3 Plantilla de confirmación presentada al humano

```
⚠️  Acción L2 — requiere tu confirmación

Tool        traf.liberacion_solicitar
Sistema     trafico-system · empresa FORSIS
Solicitado  jsalazar (vía Mattermost)
Trace       01JD7X…

Qué hará
  • Crear 1 solicitud de liberación (estado EN_TRANSITO)
  • Registrar 3 entradas de auditoría en guia_origen_auditoria
  • Enviar la solicitud a ATLAS (resultado asíncrono)

Alcance     3 guías: 12345, 12346, 12347
Motivo      "Corrección de datos del cliente receptor en destino Tuxpan"
Reversible  Sí — puede rechazarse en ATLAS antes de aprobarse

Precondiciones  ✅ 3/3 guías elegibles  ✅ motivo válido  ✅ sin solicitud duplicada

[Confirmar]  [Cancelar]        expira en 4:52
```

---

## 8. Protocolo de auditoría

### 8.1 Tabla `agente_acciones` (BD propia del agente)

Realiza la recomendación de TSAC §10. **Toda** invocación de tool escribe aquí, incluidas L0 y los
intentos denegados.

| Columna | Tipo | Nota |
|---|---|---|
| `id` | BIGINT PK AI | |
| `trace_id` | CHAR(26) IDX | ULID del turno; encadena dry-run → execute |
| `parent_audit_id` | BIGINT NULL | enlaza execute con su dry-run |
| `ts_inicio` / `ts_fin` | DATETIME(3) | |
| `duration_ms` | INT | |
| `actor_human_id` | VARCHAR(64) IDX | **el humano**, nunca el usuario de servicio |
| `actor_channel` | ENUM('mattermost','widget','cron','api') | |
| `actor_allowlisted` | TINYINT | estado de la allowlist al momento de ejecutar |
| `sistema` | ENUM('trafico','liquidaciones','agente') | |
| `empresa` | ENUM('FORSIS','GERO') | nunca NULL |
| `tool` | VARCHAR(64) IDX | |
| `tool_version` | VARCHAR(16) | versión del contrato |
| `clase_riesgo` | ENUM('L0','L1','L2','L3') IDX | |
| `mode` | ENUM('dry_run','execute','denied') | |
| `canal_datos` | ENUM('db_ro','api','mixto') | |
| `args_json` | JSON | **con PII/secretos enmascarados** (§8.3) |
| `plan_json` | JSON NULL | `effects[]`, `preconditions[]`, `blast_radius` del dry-run |
| `request_endpoint` | VARCHAR(255) NULL | endpoint o `query_id` |
| `query_hash` | CHAR(71) NULL | `sha256:` del SQL ejecutado |
| `rows_leidas` | INT NULL | |
| `resultado` | ENUM('ok','error','denegado','conflicto') IDX | |
| `error_code` | VARCHAR(48) NULL | |
| `response_json` | JSON NULL | **truncado a 8 KB**, con enmascarado |
| `upstream_status` | SMALLINT NULL | |
| `confirmation_token_hash` | CHAR(64) NULL | nunca el token en claro |
| `idempotency_key` | VARCHAR(64) NULL UNIQUE(tool,key) | |
| `prev_hash` / `row_hash` | CHAR(64) | **cadena de integridad** (§8.2) |

Índices: `(trace_id)`, `(actor_human_id, ts_inicio)`, `(tool, ts_inicio)`,
`(clase_riesgo, resultado, ts_inicio)`, `(sistema, empresa, ts_inicio)`.

### 8.2 Integridad y retención

| # | Regla |
|---|---|
| A1 | `row_hash = sha256(prev_hash ‖ campos_canonicalizados)`. Cadena verificable; un `UPDATE` posterior se detecta |
| A2 | Tabla **append-only** a nivel de aplicación: el usuario de BD del agente tiene `INSERT, SELECT` y **no** `UPDATE/DELETE` sobre ella |
| A3 | Retención: 24 meses en línea; archivado mensual a fichero firmado |
| A4 | Verificador de cadena en cron diario; ruptura → alerta P1 |
| A5 | **Fail-closed de auditoría:** si el INSERT de auditoría falla en una tool L2, la tool **no se ejecuta**. Para L0/L1 se degrada a log a disco + alerta (no bloquea lectura) |

### 8.3 Enmascarado obligatorio antes de persistir

| Patrón | Tratamiento |
|---|---|
| Campos `password`, `contrasena`, `token`, `api_key`, `secret`, `cookie`, `authorization` | `[REDACTED]` |
| Cookies de sesión (`trafico_session`, `PHPSESSID`) | `sha256` de los primeros 8 bytes, nunca el valor |
| `confirmation_token` | solo su hash |
| Datos personales de operadores/empleados (CURP, RFC, cuenta bancaria, teléfono) | enmascarado parcial `XXXX…1234` |
| Payloads binarios | se sustituyen por `{artifact_id, bytes, sha256}` |

### 8.4 Correlación aguas arriba

La auditoría del agente no sustituye la de los sistemas; se **correlaciona** con ella:

| Sistema | Rastro nativo | Clave de correlación |
|---|---|---|
| trafico-system | `guia_origen`, `guia_origen_auditoria`, `forsis_guia_creation_registry`, `usuarios_sesiones_historial` | `num_guia` + ventana temporal + `usuario='agente_ia'` |
| liquidaciones-system | `solicitudes_cancelacion` (`solicitante`, `revisado_por`, `fecha_revision`), `liquidaciones.usuario`, `tarjeta_contenido.observaciones` | `solicitud_id` + `solicitante='agente_ia'` |
| ATLAS | solicitudes de liberación/timbrado | `folio_solicitud` |

**Regla:** toda tool L2 escribe en `response_json` el identificador nativo del rastro aguas arriba
(`folio_solicitud`, `solicitud_id`). Sin ese enlace, la acción se marca `warnings:["sin_correlacion_upstream"]`.

### 8.5 Métricas y alertas derivadas

| Métrica | Umbral de alerta |
|---|---|
| Tasa de error por tool | >10 % en 15 min |
| Dry-runs sin confirmación (abandonados) | informativo: mide fricción, no fallo |
| `STATE_CONFLICT` en execute tras dry-run OK | >5 % → el sistema cambia más rápido que el TTL; bajar TTL |
| Invocaciones `mode='denied'` sobre L3 | cualquier pico → alguien pide lo prohibido de forma sistemática |
| Latencia p95 por canal (db_ro vs api) | db_ro >2 s · api >5 s |
| Ruptura de cadena `row_hash` | P1 inmediato |
| Lecturas DB con `rows_leidas = max_rows` | revisar: resultado truncado silenciosamente |

---

## 9. Registro, versionado y pruebas de las tools

### 9.1 Declaración (Registry)

Cada tool es un fichero declarativo + un adapter. El Registry (diseño del Agente 2) carga solo las
que cumplen:

```yaml
name: traf.liberacion_solicitar
version: "1.0.0"
class: L2
systems: [trafico, atlas]
channel: api
empresa_required: true
dry_run: required
idempotent: true
confirmation: human_allowlisted
permissions: [agent.trafico.liberacion.solicitar]
upstream:
  method: POST
  path: /api/guias/liberacion/solicitar
  preflight:
    - POST /api/guias/empresa
    - POST /api/guias/liberacion/validar
input_schema:  { $ref: schemas/traf.liberacion_solicitar.input.json }
output_schema: { $ref: schemas/traf.liberacion_solicitar.output.json }
rate_limit: { per_actor: "5/hour", global: "20/hour" }
timeout_ms: 15000
audit: mandatory
```

**Fail-closed del Registry:** tool sin `class`, sin `permissions`, sin schemas, o con `class ≥ L2` y
`dry_run != required` → **no se registra** y arranque falla con error, no con warning.

### 9.2 Versionado

- SemVer por tool. Cambio incompatible de input/output → mayor y nombre nuevo coexistente
  (`…_v2`) durante una ventana de transición.
- `tool_version` se persiste en auditoría: una acción pasada es reproducible con su contrato.

### 9.3 Pruebas obligatorias antes de habilitar una tool

| # | Prueba |
|---|---|
| T1 | **Test de contrato contra la instancia real** por cada endpoint/`query_id` usado (TSAC §12.10). Un cambio silencioso aguas arriba debe romper CI, no producción |
| T2 | Test de normalización: respuesta `{ok,data}`, `{success,…}` y DataTables → mismo envelope |
| T3 | Test de latin1→UTF-8 con un registro real con acentos de `sicrePR` (regla S5) |
| T4 | Test de empresa: la misma tool con `FORSIS` y `GERO` devuelve conjuntos distintos y **nunca** el default silencioso |
| T5 | Test de read-only: cada sentencia del catálogo intentada con `INSERT` encubierto (`SELECT … INTO OUTFILE`, `;DELETE`, comentario ejecutable) → rechazada por R-3 y por R-1 |
| T6 | Test de dry-run: ninguna tool L2 en `dry_run=true` produce efecto observable aguas arriba (verificado por conteo antes/después) |
| T7 | Test de token: expirado, reutilizado y con args mutados → los tres rechazados |
| T8 | Test de idempotencia: dos ejecuciones con la misma `idempotency_key` → una sola escritura upstream |
| T9 | Test de fail-closed: auditoría caída + tool L2 → la tool no ejecuta |
| T10 | Test de degradación L3: petición de "autorizar liquidación" → responde con `liq.solicitud_crear`, nunca con `autorizar_liquidacion.php` |

---

## 10. Límites operativos

| Límite | Valor | Razón |
|---|---|---|
| Filas por lectura DB | 1000 (default 200) | Proteger el MySQL compartido con dos sistemas de producción (LSA §9.8) |
| `MAX_EXECUTION_TIME` | 5 s | Ídem |
| Conexiones DB concurrentes | 4 | El agente es un tercer lector, no el principal |
| Queries concurrentes por traza | 2 | |
| Tools L2 por actor | 5 / hora | Evita inundar el buzón del revisor (LSS hallazgo #5) |
| Tools L2 globales | 20 / hora | |
| Guías por solicitud de liberación/timbrado | 50 | Acota el blast radius |
| Tamaño de artefacto | 25 MB · TTL 24 h | |
| Timeout API trafico/liquidaciones | 15 s | |
| Timeout ATLAS (indirecto) | 5 s connect 3 s | Valores que ya usa `AtlasClient` (TSAC §2.5) |

---

## 11. BLOQUEANTES

| # | Bloqueante | Impacto | Qué se necesita para desbloquear |
|---|---|---|---|
| **B-01** | **Endpoint de Omniroute sin confirmar.** `omniroute-config.md` corrigió `20130` (dashboard) → `20129` (API dev) / `20131` (prod API), pero **no hay verificación en vivo de `POST /v1/chat/completions` con el combo `Forsis` autenticado**, ni confirmación de cuál puerto atiende producción, ni de la vigencia de `${OMNIROUTE_API_KEY}` | El planner no puede ejecutarse. **Afecta a todas las tools indirectamente** (sin planner no hay invocación), aunque los contratos de este documento son independientes del LLM | Prueba en vivo: `POST {base}/v1/chat/completions` con `Authorization: Bearer ${OMNIROUTE_API_KEY}` y `{"model":"Forsis","messages":[…]}` → 200. Confirmar puerto de producción y política de rotación de la key. **No asumir `20129`** |
| **B-02** | **El workflow `solicitudes_cancelacion` no tiene módulo `LIQUIDACIONES`** (LSS §2, verificado en `solicitud_cancelacion.php:390` → `throw "Módulo desconocido"`) | La acción más irreversible y de mayor valor (autorizar liquidación) **no tiene L2 equivalente**. El agente no puede ni *pedir* aprobación para ella: solo detectar y listar la cola | Añadir `LIQUIDACIONES` al workflow (tarea B6 de LSS §4) con `tipo=AUTORIZACION`. Hasta entonces `liq.solicitud_crear` con `modulo=LIQUIDACIONES` **falla en validación P4 por diseño** y el agente responde con la cola priorizada + enlace a la UI |
| **B-03** | **Usuarios de servicio no existen.** `agente_ia` en `trafico.usuarios` y en `liquidaciones.usuarios` están propuestos (TSAC §0.2) pero **no creados**, y sus permisos efectivos no están verificados | Ninguna tool de canal API es ejecutable | Crear ambos + `forsis_agent_ro` en MySQL. Ver `permissions.md` §3–§4 |
| **B-04** | **P0 de seguridad de liquidaciones sin aplicar** (LSS §4 Fase A: A1 8 endpoints sin gate, A2 `priv` en `autorizar_liquidacion.php`, A3 `priv` en `action=crear`) | Las tools L0 del agente funcionarían hoy **incluso sin sesión** por los endpoints abiertos — lo que hace que la auditoría del agente sea la única traza existente, y que la allowlist sea el único control real | Aplicar A1–A3 antes de habilitar `liq.solicitud_crear`. A1/A2 son riesgo de rotura ≈ nulo según LSS §3 |
| **B-05** | **Grants de BD read-only no aplicados ni verificados** sobre `sicrePR`, `sicre2PR`, `sicreGero`, `sicre2Gero`, `trafico` | Todo el canal A (19 de 32 tools) es inejecutable | Aplicar `GRANT SELECT` y verificar que un `INSERT` de prueba es rechazado por el servidor, no solo por el parser |
| **B-06** | **Conectividad sin TLS a `192.168.1.209`** confirmada como limitación del servidor (TSA §4.1) | Los DSN deben forzar `ssl=0`; las credenciales viajan en claro por la LAN | Decisión explícita de aceptación de riesgo o plan de TLS en el servidor MySQL |

---

## 12. Resumen del catálogo

| # | Tool | Clase | Sistema | Canal |
|---|---|---|---|---|
| 1 | `db.query` (14 `query_id`) | L0/L1 | ambos | DB |
| 2 | `traf.guias_buscar` | L0 | trafico | DB |
| 3 | `traf.guia_detalle` | L0 | trafico | DB+API |
| 4 | `traf.guias_estados_catalogo` | L0 | trafico | API |
| 5 | `traf.guia_elegibilidad` | L1 | trafico | DB |
| 6 | `traf.guias_kpis` | L0 | trafico | API |
| 7 | `traf.guias_kpis_extendido` | L1 | trafico | DB |
| 8 | `traf.guias_exportar` | L0 | trafico | API |
| 9 | `traf.carta_porte_obtener` | L0 | trafico | API |
| 10 | `traf.cfdi_consultar` | L0 | trafico | API |
| 11 | `traf.liberacion_estado` | L0 | trafico | API |
| 12 | `traf.liberacion_validar` | L1 | trafico | API |
| 13 | `traf.guias_liberadas_reporte` | L0 | trafico | API |
| 14 | **`traf.liberacion_solicitar`** | **L2** | trafico+atlas | API |
| 15 | `traf.pase_descarga_consultar` | L0 | trafico | API |
| 16 | `traf.pase_descarga_descargar` | L0 | trafico | API |
| 17 | `traf.pases_cobertura` | L1 | trafico | DB |
| 18 | `traf.pases_ingesta_salud` | L0 | trafico | DB |
| 19 | `traf.timbrado_validar` | L1 | trafico | API |
| 20 | `traf.timbrado_estado` | L0 | trafico | API |
| 21 | **`traf.timbrado_solicitar`** | **L2** | trafico+atlas | API |
| 22 | `liq.liquidaciones_listar` | L0 | liquidaciones | API |
| 23 | `liq.liquidacion_detalle` | L0 | liquidaciones | API |
| 24 | `liq.liquidacion_estado` | L0 | liquidaciones | API+DB |
| 25 | `liq.cola_por_autorizar` | L1 | liquidaciones | DB |
| 26 | `liq.td_estado_cuenta` | L0 | liquidaciones | API |
| 27 | `liq.td_saldo_real` | L1 | liquidaciones | DB |
| 28 | `liq.operador_buscar` | L0 | liquidaciones | API |
| 29 | `liq.reconciliar_cuenta_corriente` | L1 | liquidaciones | DB |
| 30 | `liq.reconciliar_premios_cobros` | L1 | liquidaciones | DB |
| 31 | `liq.reconciliar_diesel_guias` | L1 | liquidaciones | DB |
| 32 | `liq.reconciliar_liquidacion_completa` | L1 | liquidaciones | DB |
| 33 | `liq.reporte_operador` | L0 | liquidaciones | API |
| 34 | `liq.reporte_exportar` | L0 | liquidaciones | DB |
| 35 | `liq.liquidacion_pdf` | L0 | liquidaciones | API |
| 36 | `liq.reportes_reseteo_listar` | L0 | liquidaciones | DB |
| 37 | `liq.solicitudes_pendientes` | L0 | liquidaciones | API |
| 38 | `liq.solicitudes_conteo` | L0 | liquidaciones | API |
| 39 | **`liq.solicitud_crear`** | **L2** | liquidaciones | API |
| 40 | `liq.reseteo_actualizar` ⚑flag | L2 | liquidaciones | API |
| 41 | `liq.recepcion_guia_guardar` ⚑flag | L2 | liquidaciones | API |
| 42 | `liq.premio_categoria_guardar` ⚑flag | L2 | liquidaciones | API |

⚑flag = desplegada desactivada en MVP (`AGENT_TOOLS_L2_OPERATIVAS=false`).

**Habilitadas en MVP:** 36 L0/L1 + **3 L2** (`traf.liberacion_solicitar`, `traf.timbrado_solicitar`,
`liq.solicitud_crear`). **0 L3.**

---

**Documentos relacionados:** `permissions.md` (este mismo directorio) ·
`architecture.md` / `db-schema.md` (Agente 1) · `agent-core.md` / `llm-provider.md` (Agente 2) ·
`channels.md` / `sprint-plan.md` (Agente 4)
