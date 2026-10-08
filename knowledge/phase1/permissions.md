# Forsis AI Agent — Modelo de Permisos, Identidad y Autenticación

**Fase:** 1 (diseño arquitectónico) · **Entregable hermano:** `tools-design.md` (catálogo de 42 tools, clases L0–L3)
**Fecha:** 2026-10-05

**Fuentes citadas (Fase 0 y Fase 1):**

| Sigla | Archivo |
|---|---|
| **TSA** | `trafico-system-analysis.md` |
| **TSAC** | `trafico-system-actions.md` |
| **TSAPI** | `trafico-system-api-inventory.md` |
| **LSA** | `liquidaciones-system-analysis.md` |
| **LSAC** | `liquidaciones-system-actions.md` |
| **LSAPI** | `liquidaciones-system-api-inventory.md` |
| **LSS** | `liquidaciones-security-strategy.md` |
| **DAS** | `data-access-strategy-analysis.md` |
| **DEP** | `deployment-strategy.md` |
| **MIS** | `mattermost-integration-strategy.md` |
| **ARQ** | `phase1/architecture.md` · **DBS** `phase1/db-schema.md` · **TD** `phase1/tools-design.md` |

> **Credenciales:** ningún valor real aparece en este documento. Todo secreto se referencia como
> variable de entorno (`${VAR}`) o `[REDACTED]`.
> **Restricción de alcance:** este diseño **no modifica código** de `trafico-system` ni de
> `liquidaciones-system`. Todo lo que aquí se especifica se implementa en el agente, en grants de
> MySQL, o en filas de datos de usuarios de servicio.

---

## 0. Resumen ejecutivo

| Decisión | Valor |
|---|---|
| Identidad que autoriza | **El humano**, resuelto en el agente contra los roles reales de cada sistema |
| Identidad que ejecuta | **Usuario de servicio** (`agente_ia`), uno por sistema, nunca credenciales personales (TSAC §0.2, LSS §4 Fase C) |
| Autorización efectiva | `min(permiso_del_humano, permiso_del_servicio, matriz_tool×rol, allowlist)` — intersección, nunca unión |
| Roles de tráfico usados | Los **14** reales de `trafico.roles` (TSA §6.1) |
| Roles de liquidaciones usados | Los **9** valores reales de `usuarios.priv`, incluido el vacío (LSA §5.1) |
| `priv` vacío (77 usuarios) | **DENY total**, sin excepción (regla D-1, §5) |
| `esUsuarioAdminGlobal()` por substring | **No se usa.** El agente reimplementa el chequeo por **match exacto** (regla D-4) |
| Canal de lectura | Usuario MySQL `forsis_agent_ro` con `GRANT SELECT` sobre 5 bases (§4.3) |
| Canal de escritura | API REST con cookie de sesión del usuario de servicio (§4.1, §4.2) |
| Tools L3 | **0 expuestas** (TD §1) |
| Auditoría | `agente_acciones` en PostgreSQL propio, append-only, cadena de hashes (§6) |
| Bloqueantes abiertos | **7** (§7) |

**El problema central y su respuesta en una línea:** ambos sistemas solo tienen sesión PHP y ninguna
forma de delegación ni *on-behalf-of* (TSA §5, LSA §4.1; no hay JWT ni API keys para humanos —
TSA §2 tabla "Auth"). Por tanto **la identidad del humano no puede viajar al sistema destino**. La
respuesta es **separar autorización de ejecución**: el agente decide con la identidad del humano
(datos de rol leídos por el canal read-only) y ejecuta con la identidad del servicio, dejando la
atribución al humano en su propia auditoría y en los campos nativos (`solicitante`, `motivo`) del
sistema destino.

---

## 1. Modelo de identidad del agente

### 1.1 Las cuatro identidades (no confundirlas nunca)

| # | Identidad | Dónde vive | Para qué sirve |
|---|---|---|---|
| **I1** | **Humano final** | `forsis-bot` / Mattermost (`MIS §Allowlist`), espejado en `agent_sessions.user_id` (DBS §Sesiones) | **Autoriza.** Es la que se evalúa contra la matriz del §3 y se escribe en `actor_human_id` |
| **I2** | **Login propio del agente** | PostgreSQL del agente, tabla `agent_identities` (nueva, §1.3) | **Vincula** I1 con I3/I4 y guarda el rol efectivo cacheado. No es una credencial para los ERP |
| **I3** | **Servicio en trafico-system** | Fila `agente_ia` en `trafico.usuarios` (TSAC §0.2) | **Ejecuta** el canal API de tráfico |
| **I4** | **Servicio en liquidaciones-system** | Fila `agente_ia` en `liquidaciones`→`usuarios` (`nombre_usu`, LSA §3.6) | **Ejecuta** el canal API de liquidaciones |

Y una quinta, de datos:

| **I5** | **Usuario SQL read-only** | `forsis_agent_ro` en MySQL `192.168.1.209:3306` y en la BD `trafico` | **Lee.** Nunca escribe (§4.3) |

> **Invariante de auditoría** (TD §2.1, TSAC §10): `actor_human_id` es **siempre I1**. I3/I4 jamás
> aparecen como actor lógico; aparecen como `executor_service_account`. Un registro de auditoría con
> `actor_human_id = 'agente_ia'` es un bug y debe fallar la validación de esquema.

### 1.2 Por qué no hay impersonación (y qué se hace en su lugar)

Hechos verificados que cierran la puerta a la suplantación:

| Hecho | Fuente |
|---|---|
| trafico-system autentica **solo** por `POST /login` → cookie `trafico_session`; "sin JWT ni API keys para humanos" | TSA §2, §5.1, §5.2 |
| La única auth servidor-a-servidor es **HMAC** y está acotada a 3 superficies: webhook OpenWA, eventos ATLAS y `/api/control/*` (`Guard::protegerControlApi()`), ninguna de las cuales expone guías, liberación, timbrado ni facturación | TSA §5.3, TSAPI §Control (6 endpoints) |
| liquidaciones-system autentica por `POST /api/login.php` → `PHPSESSID`; "No existe API de ..." tokens, sin CSRF, sin rate limit | LSA §3 (hallazgo 3), §4.1, §4.2 |
| ATLAS se llama **sin credenciales** (confianza de red) y solo indirectamente vía trafico-system | TSA §5.3, TSAC §2.3 |

Consecuencia: **cualquier** esquema que quisiera propagar la identidad del humano exigiría tocar
código de los ERP, lo que está fuera de alcance. Por tanto:

| # | Regla de identidad | Justificación |
|---|---|---|
| **ID-1** | El agente mantiene **una cookie jar propia por `(sistema, empresa)`**, nunca la sesión de un humano, nunca compartida (LSAC §13.4: *"un bug del agente cambia el contexto de datos de una sesión humana si comparte cookie jar"*) | Aislamiento de contexto de empresa |
| **ID-2** | El agente **nunca** pide, recibe, almacena ni reutiliza la contraseña ni la cookie de un usuario humano | No hay caso de uso que lo requiera y crearía un almacén de credenciales humanas |
| **ID-3** | La **autorización se evalúa antes** de salir al ERP, con la identidad I1 y los datos de rol leídos por I5 | El ERP no puede hacerlo: recibiría a `agente_ia` y aplicaría los permisos de `agente_ia` |
| **ID-4** | El usuario de servicio se dimensiona al **techo** de lo que el agente puede necesitar; la **matriz del §3 es el control real**. Esto es explícito y asumido: es la consecuencia inevitable de no tener delegación | TSAC §0.2 ("nunca rol con permisos que el agente no necesite"), LSS (allowlist como control real) |
| **ID-5** | Atribución aguas arriba: toda escritura L2 inyecta el `human_id` en los campos de texto nativos que el sistema ya tiene (`motivo` de liberación/timbrado, `motivo` + `solicitante` de `solicitudes_cancelacion`) con el prefijo canónico `[AI/{human_id}/{trace_id}]` | Permite correlacionar sin tocar código (TD §8.4) |
| **ID-6** | La autorización **nunca** se deriva del contenido de la conversación. Un *"soy de sistemas"* en el chat no concede nada | TSAC §0.4; MIS §132 (*"un 'soy de TI' en el chat no debe bastar"*) |

### 1.3 Tabla de vinculación `agent_identities` (PostgreSQL del agente)

Vive en la BD propia del agente (ARQ §Persistencia propia e independiente). **No** replica
permisos: replica el *mapeo* y un caché con TTL del rol resuelto.

| Columna | Tipo | Nota |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `human_id` | VARCHAR(64) UNIQUE NOT NULL | Identidad canónica I1 (handle corporativo) |
| `mm_user_id` | VARCHAR(32) NULL UNIQUE | ID de Mattermost, para resolver el autor de un post |
| `traf_username` | VARCHAR(64) NULL | FK lógica a `trafico.usuarios.username` |
| `traf_role_legacy` | VARCHAR(48) NULL | Caché de `trafico.usuarios.role` (rol **legado**) |
| `traf_role_id` | SMALLINT NULL | Caché de `trafico.usuarios.role_id` (1–14, TSA §6.1) |
| `traf_permisos_rbac` | JSONB NULL | Caché de claves de `roles_permisos`. **Informativo, nunca la única fuente** (TSA §6.1 ⚠️) |
| `traf_access_forsis` | BOOLEAN NULL | Gate de login de tráfico (TSA §5.1 paso 2) |
| `traf_session_version` | INT NULL | Para detectar revocación (TSA §5.2) |
| `liq_nombre_usu` | VARCHAR(64) NULL | FK lógica a `usuarios.nombre_usu` de liquidaciones |
| `liq_priv` | VARCHAR(48) NULL | Caché de `usuarios.priv` (texto libre, LSA §5.1). `''` es un valor legítimo y significa DENY |
| `liq_password_empty` | BOOLEAN NULL | `contrasena = ''` → cuenta comprometida por diseño (LSA §4.1) |
| `rol_agente` | VARCHAR(32) NOT NULL | Rol **canónico del agente**, derivado (§2.3) |
| `write_allowlisted` | BOOLEAN NOT NULL DEFAULT false | Espejo de `AGENT_WRITE_ALLOWLIST`; **fail-closed** (DEP §8) |
| `resolved_at` | TIMESTAMPTZ NOT NULL | Momento de la última resolución |
| `resolution_ttl_s` | INT NOT NULL DEFAULT 300 | TTL del caché |
| `estado` | ENUM(`activo`,`suspendido`,`no_mapeado`) | `no_mapeado` ⇒ DENY |

**Unicidad y seguridad del mapeo:**

| # | Regla |
|---|---|
| M-1 | `human_id` ↔ `traf_username` ↔ `liq_nombre_usu` es **1:1:1**. Un mapeo N:1 (dos humanos al mismo usuario de ERP) se rechaza en el alta |
| M-2 | El mapeo se **siembra manualmente** en el despliegue (lista revisada por el dueño del sistema) y se versiona en la auditoría. **No hay auto-descubrimiento por coincidencia de nombre**: `trafico.usuarios.username` y `liquidaciones.usuarios.nombre_usu` no comparten namespace garantizado y adivinar es un vector de escalada |
| M-3 | Un humano puede estar mapeado a **un solo** sistema. En ese caso solo ve las tools de ese sistema; las del otro responden `FORBIDDEN / ROL_NO_MAPEADO` |
| M-4 | El mapeo es **de solo lectura en caliente**: el proceso del agente no puede crear vinculaciones; solo un comando administrativo fuera de banda |

### 1.4 Secuencia de resolución de identidad (por cada turno)

```
1.  Canal entrega (mm_user_id | widget_session) y el texto
2.  forsis-bot evalúa su allowlist AGY_USUARIOS_AUTORIZADOS  ← única evaluación (MIS §232)
       vacía → ninguna acción de escritura. Fail-closed.
3.  Agente: mm_user_id → agent_identities → human_id
       sin fila o estado != activo → DENY (D-2)
4.  Si resolved_at + ttl < now()  → RE-RESOLVER por I5 (SELECT read-only):
       trafico:       SELECT username, role, role_id, access_forsis, session_version
                      FROM trafico.usuarios WHERE username = :traf_username
       trafico RBAC:  SELECT p.clave FROM roles_permisos rp JOIN permisos p …
                      WHERE rp.role_id = :role_id            ← informativo (TSA §6.1 ⚠️)
       liquidaciones: SELECT nombre_usu, priv, (contrasena = '') AS pwd_empty
                      FROM usuarios WHERE nombre_usu = :liq_nombre_usu
5.  Derivar rol_agente (§2.3). Aplicar reglas de denegación del §5 (D-1…D-12)
6.  Resolver context.empresa EXPLÍCITAMENTE. Ausente → EMPRESA_UNSET (TD §2.4 E1)
7.  El planner recibe únicamente el SUBCONJUNTO de tools permitido por la matriz del §3
       (filtrado del Registry, no instrucción en el prompt — §3.1)
```

> **Punto fino, deliberado:** el paso 4 lee `trafico.usuarios` y `liquidaciones.usuarios` por el
> canal read-only, **no** por API. Es lectura ⇒ canal A, coherente con DAS §1. Además evita que el
> agente necesite permisos de administración de usuarios en el ERP, que están explícitamente fuera
> de alcance por el riesgo de `session_version++` (TSAC §9, TD §5.5).

### 1.5 El rol legado manda: regla de resolución híbrida

`trafico-system` tiene autorización en **dos** lugares: la rama de rol legado de
`AuthorizationService::protegerModulos()` y el RBAC fino de `CurrentUser::tienePermiso()`
(TSA §6). Y **8 de los 14 roles tienen 0 permisos en `roles_permisos`**: CAPTURISTA,
CUENTAS POR PAGAR, JEFE DE LIQUIDACIONES, JEFE DE TRÁFICO, LIQUIDACIONES, SISTEMAS,
SUPERVISOR DE CUENTAS POR PAGAR y… (TSA §6.1 lista 8 filas con *(ninguno)*).

> ⚠️ TSA §6.1 es explícito: *"Los roles con 0 permisos RBAC no están sin acceso: su autorización se
> resuelve por la rama de rol legado… La migración legado→RBAC está a medias; **nunca deduzcas
> capacidades sólo de `roles_permisos`**"*.

| # | Regla |
|---|---|
| **H-1** | La fuente primaria de rol en tráfico es **`usuarios.role` (texto legado)** + `role_id`. `traf_permisos_rbac` es **enriquecimiento**, nunca la única fuente |
| **H-2** | Si `role_id` no está en 1..14 o `role` no coincide con `roles.nombre` del `role_id` → **DENY `ROL_INCONSISTENTE`** (D-5). El agente no "elige el más permisivo" |
| **H-3** | Si el rol tiene 0 permisos RBAC, el agente **no infiere** capacidades: usa exclusivamente la fila del rol en la matriz del §3, que fue construida a mano desde la rama legado documentada |
| **H-4** | La matriz del §3 es **más restrictiva o igual** que lo que el ERP concedería. Nunca más permisiva. Si hay duda sobre un rol × tool, la celda es `—` (deny) |

---

## 2. Vocabulario de roles

### 2.1 Roles reales de trafico-system (`trafico.roles`, TSA §6.1)

| Código | ID | Rol | Permisos RBAC asignados hoy |
|---|---|---|---|
| **T1** | 1 | ADMINISTRADOR | `comunicaciones.asignar/enviar/ver`, `facturacion.cfdi.consultar`, `guias.ver`, `qhse.acceso` |
| **T2** | 2 | CAPTURISTA | *(ninguno — resuelve por rol legado)* |
| **T3** | 3 | CUENTAS POR PAGAR | *(ninguno)* |
| **T4** | 4 | FACTURACIÓN | `facturacion.aging.exportar/ver`, `facturacion.cfdi.consultar`, `facturacion.guias_soporte.upload`, `guias.ver`, `modulo.facturacion.acceso` |
| **T5** | 5 | GERENTE DE OPERACIONES | `diesel_shortages.ver`, `facturacion.cfdi.consultar`, `guias.operar`, `guias.ver` |
| **T6** | 6 | JEFE DE LIQUIDACIONES | *(ninguno)* |
| **T7** | 7 | JEFE DE TRÁFICO | *(ninguno)* |
| **T8** | 8 | LIQUIDACIONES | *(ninguno)* |
| **T9** | 9 | RECURSOS HUMANOS | `guias.operar` |
| **T10** | 10 | RESETEOS | `diesel_shortages.escribir/ver` |
| **T11** | 11 | SISTEMAS | *(ninguno)* |
| **T12** | 12 | SUPERVISOR DE CUENTAS POR PAGAR | *(ninguno)* |
| **T13** | 13 | **SUPER USUARIO** | **los 15** |
| **T14** | 14 | TRÁFICO | `diesel_shortages.ver`, `facturacion.cfdi.consultar`, `guias.operar`, `guias.ver` |

### 2.2 Valores reales de `priv` en liquidaciones-system (LSA §5.1)

| Código | `priv` | Usuarios | Admin global según `esUsuarioAdminGlobal()` (LSA §5.2) | Trato en el agente |
|---|---|---|---|---|
| **L∅** | *(vacío)* | **77** | No | **DENY total** (D-1) |
| **LSU** | SUPER USUARIO | 8 | Sí (exacto + substring `SUPER`) | Máximo rol; único que aprueba solicitudes (**fuera del agente**) |
| **LLQ** | LIQUIDACIONES | 3 | Sí (exacto + substring `LIQUIDAC`) | Lectura y reconciliación plenas; crear solicitudes |
| **LFA** | FACTURACIÓN | 2 | Sí (exacto) | Lectura de liquidaciones y guías; sin tarjeta deudor de escritura |
| **LCP** | CUENTAS POR PAGAR | 1 | Sí (exacto) | Lectura financiera + solicitudes de caja chica |
| **LSC** | SUPERVISOR DE CUENTAS POR PAGAR | 1 | Sí (exacto) | Igual a LCP + reconciliaciones |
| **LRH** | RECURSOS HUMANOS | 1 | No | Lectura muy acotada |
| **LTR** | TRÁFICO | 1 | No | Lectura operativa de guías/recepción |
| **LAD** | ADMINISTRADOR | 1 | Sí (exacto + substring `ADMIN`) | Lectura plena; solicitudes |

> ⚠️ Nota crítica: `esUsuarioAdminGlobal()` concede admin global si `priv` **contiene** los
> substrings `SUPER` / `LIQUIDAC` / `ADMIN`; LSA §5.2 documenta que `"AUXILIAR ADMINISTRATIVO"`
> **concede admin global**. El agente **no replica esta lógica** (regla D-4).

### 2.3 Rol canónico del agente (`rol_agente`) — derivación

Capa de traducción propia para no duplicar la matriz 42 × 23. Derivada, no declarada.

| `rol_agente` | Se deriva de | Semántica |
|---|---|---|
| `AGENT_SUPERUSER` | T13 **y/o** LSU | Todas las tools habilitadas en MVP |
| `AGENT_TRAFICO_OPS` | T14, T5, T7 · o LTR | Guías, liberación, timbrado, pases |
| `AGENT_FACTURACION` | T4, T1 · o LFA | CFDI (consulta), carta porte, liberación, reportes |
| `AGENT_LIQUIDACIONES` | T8, T6 · o LLQ | Liquidaciones, tarjeta deudor, reconciliación, solicitudes |
| `AGENT_CXP` | T3, T12 · o LCP, LSC | Caja chica, aging de TD, reportes financieros |
| `AGENT_RESETEOS` | T10 | Reseteos / ralentí y diesel shortages |
| `AGENT_RRHH` | T9 · o LRH | Lectura mínima (no RRHH: fuera de alcance, TD §5.5) |
| `AGENT_LECTOR` | T2, T11 | Solo L0 de consulta puntual, sin exportes masivos |
| `AGENT_DENY` | L∅, `no_mapeado`, inconsistencia | Nada. Responde explicando y escala |

**Reglas de derivación:**

| # | Regla |
|---|---|
| RD-1 | Se derivan **ambos** sistemas por separado. Un humano puede ser `AGENT_TRAFICO_OPS` en tráfico y `AGENT_DENY` en liquidaciones — y entonces no ve ninguna tool `liq.*` |
| RD-2 | **Intersección, no unión:** si está mapeado a los dos, el permiso de una tool `traf.*` sale solo de su rol de tráfico y el de una `liq.*` solo de su rol de liquidaciones. Nunca se usa el rol de un sistema para habilitar tools del otro |
| RD-3 | `AGENT_DENY` **gana sobre cualquier otro**. Si cualquiera de los dos lados dispara una regla del §5 que no sea de sistema (p. ej. `write_allowlisted=false` o suspensión), se aplica al turno completo |
| RD-4 | `AGENT_SUPERUSER` **no desactiva** la allowlist de escritura, el dry-run, la confirmación ni el bloqueo de L3 (TD §1, §7). Es un rol de alcance, no un bypass |

---

## 3. Matriz de permisos **tool × rol**

### 3.1 Cómo se aplica

| # | Regla |
|---|---|
| **P-1** | El filtrado ocurre en el **Registry/Executor** (server-side). El planner **solo ve** las tools permitidas: una tool no autorizada no está en el catálogo de ese turno, no es que el LLM "decida no usarla" (TD §9.1) |
| **P-2** | Doble chequeo: el Executor **re-verifica** el permiso en el momento de la invocación, por si el rol cambió dentro del turno (TTL 300 s, §1.3) |
| **P-3** | Celda vacía (`—`) = **DENY**. La matriz es una **allowlist**: lo no listado está prohibido (fail-closed, TD §1) |
| **P-4** | `R` = puede invocar. `W` = puede invocar y la tool escribe ⇒ **además** exige `write_allowlisted=true` + dry-run + `confirmation_token` + `idempotency_key` (TD §2.1, §7) |
| **P-5** | Ninguna celda `W` existe para una tool L3: **las L3 no están en la matriz** porque no están registradas (TD §1) |
| **P-6** | Rate limits de TD §10 se aplican **por `human_id`** (5 L2/hora/actor, 20 L2/hora global), nunca por usuario de servicio: si no, un actor consumiría la cuota de todos |

### 3.2 Tools de `trafico-system` × roles de tráfico (T1–T14)

| # | Tool | Clase | T1 ADMIN | T2 CAPT | T3 CXP | T4 FACT | T5 GteOps | T6 JefeLiq | T7 JefeTraf | T8 LIQ | T9 RRHH | T10 RESET | T11 SIST | T12 SupCXP | T13 **SU** | T14 TRÁF |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2 | `traf.guias_buscar` | L0 | R | R | R | R | R | R | R | R | R | — | R | R | R | R |
| 3 | `traf.guia_detalle` | L0 | R | R | R | R | R | R | R | R | R | — | R | R | R | R |
| 4 | `traf.guias_estados_catalogo` | L0 | R | R | R | R | R | R | R | R | R | R | R | R | R | R |
| 5 | `traf.guia_elegibilidad` | L1 | R | — | — | R | R | — | R | — | — | — | — | — | R | R |
| 6 | `traf.guias_kpis` | L0 | R | — | R | R | R | R | R | R | — | — | R | R | R | R |
| 7 | `traf.guias_kpis_extendido` | L1 | R | — | R | R | R | R | R | R | — | — | — | R | R | R |
| 8 | `traf.guias_exportar` | L0 | R | — | R | R | R | R | R | R | — | — | — | R | R | R |
| 9 | `traf.carta_porte_obtener` | L0 | R | R | — | R | R | — | R | — | — | — | — | — | R | R |
| 10 | `traf.cfdi_consultar` | L0 | R | — | R | R | R | — | R | — | — | — | — | R | R | R |
| 11 | `traf.liberacion_estado` | L0 | R | — | — | R | R | — | R | — | — | — | — | — | R | R |
| 12 | `traf.liberacion_validar` | L1 | — | — | — | R | R | — | R | — | — | — | — | — | R | R |
| 13 | `traf.guias_liberadas_reporte` | L0 | R | — | R | R | R | R | R | R | — | — | — | R | R | R |
| **14** | **`traf.liberacion_solicitar`** | **L2** | — | — | — | **W** | **W** | — | **W** | — | — | — | — | — | **W** | **W** |
| 15 | `traf.pase_descarga_consultar` | L0 | R | R | R | R | R | — | R | — | — | — | — | R | R | R |
| 16 | `traf.pase_descarga_descargar` | L0 | R | R | R | R | R | — | R | — | — | — | — | R | R | R |
| 17 | `traf.pases_cobertura` | L1 | R | — | — | R | R | — | R | — | — | — | — | — | R | R |
| 18 | `traf.pases_ingesta_salud` | L0 | R | — | — | R | R | — | R | — | — | — | R | — | R | R |
| 19 | `traf.timbrado_validar` | L1 | — | — | — | R | R | — | R | — | — | — | — | — | R | R |
| 20 | `traf.timbrado_estado` | L0 | R | — | — | R | R | — | R | — | — | — | — | — | R | R |
| **21** | **`traf.timbrado_solicitar`** | **L2** | — | — | — | **W** | — | — | **W** | — | — | — | — | — | **W** | — |

**Notas de celdas que no son obvias:**

| Celda | Razón | Fuente |
|---|---|---|
| T10 RESETEOS casi todo `—` | Su RBAC es exclusivamente `diesel_shortages.escribir/ver`; no tiene `guias.ver`. Darle guías sería más permisivo que el ERP (regla H-4) | TSA §6.1 |
| T9 RRHH solo L0 básicas | Tiene `guias.operar` pero **no** `guias.ver`; el dominio RRHH está fuera de alcance del MVP | TSA §6.1, TD §5.5 |
| T2 CAPTURISTA / T11 SISTEMAS: 0 permisos RBAC | Se les concede solo consulta puntual (`AGENT_LECTOR`), **nunca** export masivo ni L2. No se infiere nada de su rama legado | TSA §6.1 ⚠️, regla H-3 |
| `traf.timbrado_solicitar` sin T5 ni T14 | Timbrado es la antesala de un CFDI (irreversible ante el SAT): se restringe al dominio de facturación + jefatura de tráfico + SU, más estrecho que `guias.operar` | TSAC §3.3, TD §5.4 |
| `traf.liberacion_validar` / `timbrado_validar` sin T1 | Son pasos preflight de una L2 que T1 no puede ejecutar; exponerlos sin la acción solo crea ruido | TD §5.2 P5 |
| Ninguna celda de creación/edición de guía | `/api/guias/crear`, `/editar`, `/copiar/guardar`, `/sellos/actualizar` están **fuera del MVP** para todos los roles | TD §5.5 (todas las columnas de `sicrePR.guias` son `NOT NULL` sin default — TSA §4.3) |

### 3.3 Tools de `liquidaciones-system` × `priv` real

| # | Tool | Clase | L∅ *(77)* | LSU | LLQ | LFA | LCP | LSC | LRH | LTR | LAD |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 22 | `liq.liquidaciones_listar` | L0 | — | R | R | R | R | R | — | R | R |
| 23 | `liq.liquidacion_detalle` | L0 | — | R | R | R | R | R | — | — | R |
| 24 | `liq.liquidacion_estado` | L0 | — | R | R | R | R | R | — | — | R |
| 25 | `liq.cola_por_autorizar` | L1 | — | R | R | — | R | R | — | — | R |
| 26 | `liq.td_estado_cuenta` | L0 | — | R | R | — | R | R | — | — | R |
| 27 | `liq.td_saldo_real` | L1 | — | R | R | — | R | R | — | — | R |
| 28 | `liq.operador_buscar` | L0 | — | R | R | R | R | R | R | R | R |
| 29 | `liq.reconciliar_cuenta_corriente` | L1 | — | R | R | — | R | R | — | — | R |
| 30 | `liq.reconciliar_premios_cobros` | L1 | — | R | R | R | R | R | — | — | R |
| 31 | `liq.reconciliar_diesel_guias` | L1 | — | R | R | — | — | R | — | — | R |
| 32 | `liq.reconciliar_liquidacion_completa` | L1 | — | R | R | — | — | R | — | — | R |
| 33 | `liq.reporte_operador` | L0 | — | R | R | R | R | R | — | — | R |
| 34 | `liq.reporte_exportar` | L0 | — | R | R | R | R | R | — | — | R |
| 35 | `liq.liquidacion_pdf` | L0 | — | R | R | R | R | R | — | — | R |
| 36 | `liq.reportes_reseteo_listar` | L0 | — | R | R | — | — | — | — | R | R |
| 37 | `liq.solicitudes_pendientes` | L0 | — | R | R | — | R | R | — | — | R |
| 38 | `liq.solicitudes_conteo` | L0 | — | R | R | — | R | R | — | — | R |
| **39** | **`liq.solicitud_crear`** | **L2** | — | **W** | **W** | — | **W**¹ | **W**¹ | — | — | **W** |
| 40 | `liq.reseteo_actualizar` ⚑ | L2 | — | **W** | **W** | — | — | — | — | — | — |
| 41 | `liq.recepcion_guia_guardar` ⚑ | L2 | — | **W** | **W** | — | — | — | — | **W** | — |
| 42 | `liq.premio_categoria_guardar` ⚑ | L2 | — | **W** | **W** | — | — | — | — | — | — |

¹ **Restricción por `modulo`** dentro de `liq.solicitud_crear` — el permiso no es la tool entera:

| `rol_agente` / `priv` | `modulo` permitido en `args` |
|---|---|
| LSU, LLQ, LAD | `CAJA_CHICA`, `TARJETA_DEUDOR`, `RECEPCION_GUIAS` |
| LCP, LSC | **solo** `CAJA_CHICA` |
| cualquiera | `LIQUIDACIONES` → **siempre DENY** por `VALIDATION`: el módulo **no existe** en el workflow (B-02; LSS §2, `solicitud_cancelacion.php:390` → `throw "Módulo desconocido"`) |

⚑ = desplegada **desactivada** por feature flag `AGENT_TOOLS_L2_OPERATIVAS=false` (TD §6.5). La
celda `W` solo surte efecto si alguien activa el flag; con el flag en `false` la tool no está
registrada y la matriz es irrelevante.

**Notas de celdas:**

| Celda | Razón | Fuente |
|---|---|---|
| **Columna L∅ enteramente `—`** | 77 usuarios con `priv` vacío **son exactamente los 77 con contraseña vacía** (LSA §4.1 + §5.1): cualquiera puede autenticarse como ellos. Conceder una sola lectura financiera a esa columna convierte el agente en un canal de exfiltración anónimo. Regla **D-1** | LSA §4.1, §5.1 |
| LRH casi todo `—` | RRHH no tiene admin global ni caso de uso en liquidaciones dentro del MVP | LSA §5.2 |
| LFA sin tarjeta deudor | Facturación no opera cuenta corriente de operadores | LSA §5.3 |
| `liq.solicitud_aprobar` / `_rechazar` ausentes | **L3**, no registradas: `aprobar` ejecuta la cancelación real en MySQL y es exclusiva de un humano `SUPER USUARIO` con **match exacto** (`if ($priv !== 'SUPER USUARIO')`) | TD §6.4, LSAC §6.12 |
| `autorizar_liquidacion.php` ausente en toda la matriz | L3 sin reversa y **sin validación de `priv`** (cualquier sesión autoriza). Nunca invocable por el agente | LSA §5.4, LSAC §13.1 |

### 3.4 `db.query` (tool 1) — permisos por `query_id`

`db.query` **no** se autoriza como una tool única: se autoriza **por `query_id`**, porque cada uno
tiene un dominio de datos distinto (TD §3.3).

| `query_id` | Clase | Dominio | Roles de tráfico | `priv` de liquidaciones |
|---|---|---|---|---|
| `guias.por_estatus_y_rango` | L0 | Guías | T1,T4,T5,T7,T13,T14 | LSU,LLQ,LTR,LAD |
| `guias.detalle_por_folio` | L0 | Guías | T1,T4,T5,T7,T13,T14 | LSU,LLQ,LTR,LAD |
| `guias.sin_pase_descarga` | L1 | Guías + pases | T4,T5,T7,T13,T14 | — |
| `guias.aging_por_cliente` | L1 | Guías | T4,T13 | LSU,LAD |
| `pases.cobertura_por_periodo` | L1 | Pases | T4,T5,T7,T13,T14 | — |
| `td.saldo_real_por_tarjeta` | L1 | **Financiero TD** | T13 | LSU,LLQ,LCP,LSC,LAD |
| `td.aging_cargos_pendientes` | L1 | **Financiero TD** | T13 | LSU,LLQ,LCP,LSC,LAD |
| `liq.cola_por_autorizar` | L0 | **Financiero** | T6,T8,T13 | LSU,LLQ,LCP,LSC,LAD |
| `liq.descuadre_totales` | L1 | **Financiero** | T6,T8,T13 | LSU,LLQ,LSC,LAD |
| `liq.vales_diesel_doble_liquidacion` | L1 | **Financiero** | T6,T8,T13 | LSU,LLQ,LSC,LAD |
| `reseteos.pendientes_revision` | L0 | Reseteos | T10,T13 | LSU,LLQ,LTR |
| `kpi.guias_por_estatus` | L0 | Agregado | T1,T3,T4,T5,T6,T7,T8,T12,T13,T14 | LSU,LLQ,LFA,LCP,LSC,LAD |
| `kpi.operacion_unificada` | L0 | Agregado | T1,T5,T7,T13 | LSU,LAD |
| `audit.guia_origen` | L0 | Auditoría | T1,T11,T13 | LSU |

| # | Regla |
|---|---|
| Q-1 | `query_id` no listado o no presente en `sql/catalog/` → `FORBIDDEN / QUERY_NO_CATALOGADA`. **El LLM nunca escribe SQL** (TD §3.2 R-4) |
| Q-2 | `params` se validan contra la firma tipada del fichero del catálogo antes de bindear. Rechazo por `VALIDATION`, no coerción silenciosa |
| Q-3 | `empresa` determina el **DSN**, no un `WHERE` (TD §2.4 E4). Una `query_id` de dominio `trafico` ignora empresa porque la BD `trafico` es única |
| Q-4 | `limit` efectivo = `min(limit_solicitado, max_rows del catálogo, 1000)`. `rows_leidas == max_rows` emite `warnings:["resultado_truncado"]` (TD §8.5) |

---

## 4. Método de autenticación por sistema

### 4.1 trafico-system (canal API, escrituras y algunas lecturas)

| Parámetro | Valor |
|---|---|
| Base URL | `http://nginx:8091` por la red Docker `forsis-comunicaciones`. **No publicado al host** (TSAPI §0) |
| Mecanismo | Login de formulario → cookie `trafico_session` (TSA §5.1, §5.2) |
| Endpoint de login | `POST /login`, `Content-Type: application/x-www-form-urlencoded` (TSAPI §Login) |
| Credenciales | `${TRAFICO_AGENT_USER}` = `agente_ia`, `${TRAFICO_AGENT_PASSWORD}` = `[REDACTED]` |
| Vida de sesión | **8 h** de inactividad / **12 h** absoluta (TSA §5.2) |
| Renovación | `GET /api/sesion/heartbeat` cada 30 min (TSAC §0.2) |
| Fijación de empresa | `POST /api/guias/empresa` **antes de cada acción**, con verificación de eco (TD §2.4 E3) |
| Revocación | `UPDATE trafico.usuarios SET session_version = session_version + 1` vía `/api/usuarios/sesiones/revocar` por un humano SU, o `/api/control/users/toggle-access` sobre `access_forsis` (TSA §5.2) |

**Usuario de servicio I3 — definición (propuesta de TSAC §0.2, adaptada):**

```sql
-- Ejecutar UNA VEZ, fuera del agente, por un administrador. NO es código del ERP.
INSERT INTO trafico.usuarios
  (username, password_hash, password_algorithm, access_forsis, access_sicret,
   role, role_id, session_version, created_at)
VALUES ('agente_ia', '[REDACTED: argon2id]', 'argon2id', 1, 1,
        'FACTURACIÓN', 4, 1, NOW());
```

| # | Decisión y razón |
|---|---|
| S3-1 | `password_algorithm = 'argon2id'`, **nunca** `md5_legacy`. Cualquier otro valor **falla cerrado** en el login, lo cual es deseable (TSA §5.1 paso 3) |
| S3-2 | **Rol `FACTURACIÓN` (role_id 4), no `SUPER USUARIO`.** TSAC §0.2 propone `SUPER USUARIO` para que `AuthorizationService` conceda por rol legado; se **reduce deliberadamente** a `FACTURACIÓN`, que es el rol con RBAC poblado (`facturacion.*`, `guias.ver`, `modulo.facturacion.acceso`) que cubre el 100% de las tools L0/L1/L2 registradas de tráfico, y **no** incluye `usuarios.administrar` ni `comunicaciones.enviar` — ambos fuera de alcance (TD §5.5). **Riesgo aceptado:** las tools que requieren `guias.operar` (no incluido en FACTURACIÓN) deben verificarse en vivo → **BLOQUEANTE B-07** |
| S3-3 | `access_forsis = 1` es obligatorio: el login lo exige antes de nada y el mensaje de rechazo es genérico (TSA §5.1 paso 2) |
| S3-4 | **Nunca marcar cambio de contraseña pendiente** sobre la cuenta: `403 PASSWORD_CHANGE_REQUIRED` es **fatal sin reintento** y mata al agente en silencio (TD §4.2, TSA §5.5) |
| S3-5 | Una cuenta **por empresa no es necesaria** (la empresa se conmuta por endpoint), pero **sí** una cookie jar por empresa (ID-1) |
| S3-6 | El nombre de la cuenta **no puede ser** `CARLOSD`, `FATIMA` ni `RUBISEL01`: están forzados a FORSIS por código y comparten visibilidad de datos (LSA §5.3, TD §2.4 E5) |

**Manejo de errores de sesión (TD §4.2):**

| Respuesta | Acción |
|---|---|
| `401 SESSION_EXPIRED` | **Un** re-login + un reintento. Segundo fallo → error al usuario, sin loop |
| `403 PASSWORD_CHANGE_REQUIRED` | **Fatal, sin reintento.** Alerta P1 a operaciones: alguien tocó la cuenta de servicio |
| `403 FORBIDDEN` | No es un fallo de sesión: es la matriz del §3 desalineada con el rol real del servicio. Alerta + registro `mode='denied'` |

### 4.2 liquidaciones-system (canal API)

| Parámetro | Valor |
|---|---|
| Base URL | `http://liquidaciones-nginx:8081`, uniendo el contenedor del agente a la red `liquidaciones-system_default` (LSA §2.1, LSS §4 Fase C) |
| Mecanismo | `POST /api/login.php` con **body JSON** `{username, password}` → cookie `PHPSESSID` (LSA §4.1) |
| Credenciales | `${LIQ_AGENT_USER}` = `agente_ia`, `${LIQ_AGENT_PASSWORD}` = `[REDACTED]` |
| Vida de sesión | 8 h (`gc_maxlifetime` 28800, cookie lifetime 28800) (LSA §4.2) |
| Fijación de empresa | `POST /api/set_empresa.php` **antes de cada acción**, con verificación de eco. El default silencioso es `forsis` (LSA §3.2) |
| TLS | **No.** Listener HTTP plano interno; se acepta a propósito para no ampliar superficie pública (LSA §2.1, TD §4.1) |
| CSRF / rate limit / lockout | **No existen** (LSA §4.2). El agente añade su propio rate limit (TD §10) |
| Revocación | **No hay mecanismo nativo** (no hay `session_version`). Ver **BLOQUEANTE B-08** y el kill-switch del §4.4 |

**Usuario de servicio I4 — definición:**

```sql
-- Fila de DATOS en liquidaciones.usuarios. No modifica código del ERP.
INSERT INTO usuarios (nombre_usu, contrasena, priv, correo, num_emp)
VALUES ('agente_ia', MD5('[REDACTED]'), 'LIQUIDACIONES', '[REDACTED]', NULL);
```

| # | Decisión y razón |
|---|---|
| S4-1 | `contrasena` **jamás** vacía. `contrasena === ''` concede acceso sin validar y es el hallazgo *Alta* del sistema (LSA §4.1). La cuenta de servicio con contraseña vacía sería una puerta anónima al agente |
| S4-2 | El hash es **MD5 sin salt** porque es lo que el código compara (`$user['contrasena'] === md5($password)`) y **no se puede cambiar sin tocar código** (B2 de LSS §4 está fuera de alcance). Mitigación: contraseña de ≥32 caracteres aleatorios, rotación trimestral, y el hecho de que el listener no sale de la red Docker. **Riesgo residual explícito** |
| S4-3 | `priv = 'LIQUIDACIONES'` — exacto, sin substring accidental. Concede admin global por match **exacto** en `esUsuarioAdminGlobal()`, lo que es necesario para ver datos de todos los operadores en reconciliación (`obtenerUsuariosVisibles()` → `[]` = ve todo, LSA §5.3). Sin esto, el agente solo vería sus propios registros (ninguno) y toda reconciliación devolvería vacío — un fallo silencioso peor que un 403 |
| S4-4 | `priv` **nunca** `'SUPER USUARIO'`: es el único valor que el chequeo por match exacto de `solicitud_cancelacion.php` acepta para **aprobar** (`if ($priv !== 'SUPER USUARIO')`). Darle SU al servicio pondría a un `aprobar` accidental a un bug de distancia (LSAC §6.12, TD §6.4) |
| S4-5 | `priv` nunca debe contener texto adicional (p. ej. `'LIQUIDACIONES IA'`): funcionaría por substring, pero dependería del comportamiento que este diseño rechaza (D-4) |
| S4-6 | 8 de los endpoints usados **no incluyen `auth.php`** y responderían incluso sin sesión (`liquidaciones.php`, `liquidacion_detalle.php`, `tarjeta_deudor.php`, `buscar_operadores.php`, `set_empresa.php`, …, LSA §4.3). El agente **mantiene y envía la sesión de todos modos**: para que `obtenerUsuariosVisibles()` resuelva y para que exista traza nativa. Nunca se explota la ausencia de gate (regla D-9) |

### 4.3 Bases de datos read-only (canal A)

| Parámetro | Valor |
|---|---|
| Usuario SQL | **`forsis_agent_ro`** (identidad I5) |
| Contraseña | `${DB_AGENT_RO_PASSWORD}` = `[REDACTED]`, inyectada por `.env` (modo 600, gitignored — DEP §Compose) |
| Hosts origen permitidos | Solo la IP/subred del contenedor del agente, en la cláusula `@'host'` del grant. Nunca `@'%'` |
| TLS | **No disponible**: `192.168.1.209` no soporta TLS; el cliente debe forzar `ssl=0` o falla con `ERROR 2026 TLS/SSL error` (TSA §4.1, TD §4.1). Debe constar en el DSN y en los healthchecks |

**Scope exacto de los grants:**

| Alias | DSN (env) | Base | Motor / host | Charset | Grant |
|---|---|---|---|---|---|
| `db.sicret_forsis` | `${DB_SICRET_FORSIS_DSN}` | `sicrePR` (136 tablas) | MySQL `192.168.1.209:3306` | **latin1** | `SELECT` |
| `db.sicret2_forsis` | `${DB_SICRET2_FORSIS_DSN}` | `sicre2PR` (49) | ídem | utf8mb4 | `SELECT` |
| `db.sicret_gero` | `${DB_SICRET_GERO_DSN}` | `sicreGero` (124) | ídem | utf8mb4 | `SELECT` |
| `db.sicret2_gero` | `${DB_SICRET2_GERO_DSN}` | `sicre2Gero` (28) | ídem | utf8mb4 | `SELECT` |
| `db.trafico` | `${DB_TRAFICO_DSN}` | `trafico` (MariaDB 11) | red Docker | utf8mb4 | `SELECT` |

```sql
-- Ejecutar por un DBA. Fuera del agente. Sin INSERT/UPDATE/DELETE/CREATE/DROP/FILE/PROCESS.
CREATE USER 'forsis_agent_ro'@'<ip_contenedor_agente>' IDENTIFIED BY '[REDACTED]';
GRANT SELECT ON `sicrePR`.*    TO 'forsis_agent_ro'@'<ip_contenedor_agente>';
GRANT SELECT ON `sicre2PR`.*   TO 'forsis_agent_ro'@'<ip_contenedor_agente>';
GRANT SELECT ON `sicreGero`.*  TO 'forsis_agent_ro'@'<ip_contenedor_agente>';
GRANT SELECT ON `sicre2Gero`.* TO 'forsis_agent_ro'@'<ip_contenedor_agente>';
GRANT SELECT ON `trafico`.*    TO 'forsis_agent_ro'@'<ip_contenedor_agente>';
FLUSH PRIVILEGES;
```

**Restricciones de tabla por encima del grant** (el grant es por base; el agente estrecha más):

| Ámbito | Política |
|---|---|
| Tablas consultables | **Solo** las que aparecen en algún fichero de `sql/catalog/` (TD §3.3). El catálogo es la allowlist de tablas efectiva |
| `sicrePR.usuarios`, `trafico.usuarios`, `trafico.roles`, `trafico.roles_permisos`, `trafico.permisos`, `usuarios` (liquidaciones) | Lectura permitida **solo** desde el resolvedor de identidad del §1.4, con una consulta fija por `username`/`nombre_usu`. **Nunca** expuestas al planner ni listables. Columnas `contrasena` / `password_hash` **nunca** se seleccionan; solo el predicado derivado `(contrasena = '')` |
| Tablas de RRHH, nómina, finiquitos, aguinaldos, tarjetas deudor de empleado | **Sin `query_id`** ⇒ inalcanzables, aunque el grant técnicamente las cubra (TD §5.5) |
| `información_schema` / `mysql.*` | No se concede `mysql.*`. `SHOW`/`DESCRIBE` se permiten solo en el modo de test de contrato (T1), no en producción |

**Defensa en profundidad (TD §3.2, se reafirma aquí como política de permisos):**

| # | Capa |
|---|---|
| R-1 | `GRANT SELECT` únicamente. Es la barrera **fuerte**: inmune a bugs del agente (DAS §203) |
| R-2 | `SET SESSION TRANSACTION READ ONLY` + `autocommit=1` al abrir cada conexión |
| R-3 | Parser con allowlist `SELECT`/`SHOW`/`EXPLAIN`/`DESCRIBE`; rechazo de `;` múltiple, comentarios ejecutables `/*! */`, `INTO OUTFILE`, `LOAD`, `CALL`, `HANDLER`, `LOCK`, `FLUSH`, `SET`, DDL y DML |
| R-4 | Catálogo cerrado de `query_id`: el LLM no escribe SQL |
| R-5 | `MAX_EXECUTION_TIME=5000` ms, `LIMIT` ≤ 1000, pool ≤ 4 conexiones, 2 queries concurrentes por traza (TD §10; el agente es "un tercer lector, no el principal" sobre una BD de producción compartida — LSA §9.8) |

### 4.4 Revocación y kill-switch

| Vía | Alcance | Latencia | Fuente |
|---|---|---|---|
| `session_version++` en `trafico.usuarios` (o `access_forsis=0`) | Mata todas las sesiones del servicio en tráfico; `Guard::proteger()` lo revalida **en cada request** | Inmediata | TSA §5.2 |
| `REVOKE SELECT` / `DROP USER forsis_agent_ro` | Mata el canal A completo (19+ tools) | Inmediata en conexiones nuevas; cerrar el pool | §4.3 |
| `AGENT_WRITE_ALLOWLIST=""` + reinicio | Cero escrituras, lecturas intactas. Es el **default** | Segundos | DEP §8 |
| `AGY_USUARIOS_AUTORIZADOS=""` en `forsis-bot` | Cero acciones desde Mattermost, una sola lista | Segundos | MIS §43, §232 |
| `AGENT_KILL_SWITCH=true` (nuevo) | El Executor rechaza **toda** tool con `SERVICE_DISABLED` y el Registry no carga nada. Necesario porque **liquidaciones no tiene revocación de sesión nativa** (B-08) | Segundos | este documento |

> **No usar `session_version++` como castigo rutinario:** mata el trabajo en curso de forma
> invisible (TSAC §9). Para el agente es aceptable porque no hay humano detrás de la sesión I3.

---

## 5. Reglas de denegación (fail-closed)

Toda regla produce `ok:false` con el `error.code` indicado, **registro de auditoría con
`mode='denied'`**, y una respuesta al usuario que explica la causa y la vía humana alternativa.
Ninguna regla admite override por el contenido de la conversación.

| # | Situación | `error.code` | Fuente |
|---|---|---|---|
| **D-1** | `liq_priv = ''` (vacío) — los **77** usuarios | `FORBIDDEN / PRIV_VACIO` | LSA §5.1 (77 con `priv` vacío) + §4.1 (los mismos 77 con `contrasena = ''` ⇒ autenticables por cualquiera). 81% del padrón: conceder algo a esta columna anula el modelo |
| **D-2** | `human_id` sin fila en `agent_identities`, o `estado != 'activo'`, o `traf_username` y `liq_nombre_usu` ambos nulos | `FORBIDDEN / ROL_NO_MAPEADO` | M-2, M-3 |
| **D-3** | `rol_agente` derivado = `AGENT_DENY`, o la celda `(tool, rol)` de la matriz del §3 es `—` | `FORBIDDEN / TOOL_NO_AUTORIZADA` | P-3 |
| **D-4** | El rol del humano se resolvería **solo** por substring (`SUPER`/`LIQUIDAC`/`ADMIN` dentro de otro texto, p. ej. `"AUXILIAR ADMINISTRATIVO"`) y **no** por match exacto contra §2.2 | `FORBIDDEN / PRIV_SUBSTRING_MATCH` | LSA §5.2 (hallazgo *Media*). El agente **no replica** `esUsuarioAdminGlobal()` |
| **D-5** | `traf.role_id` fuera de 1..14, o `role` (texto) que no corresponde al `role_id`, o rol inexistente en `trafico.roles` | `FORBIDDEN / ROL_INCONSISTENTE` | H-2, TSA §6.1 |
| **D-6** | Se intentó deducir una capacidad de tráfico **solo** de `roles_permisos` para un rol con 0 permisos | `FORBIDDEN / RBAC_INCOMPLETO` (defecto de implementación: falla en CI, no en runtime) | TSA §6.1 ⚠️ *"nunca deduzcas capacidades sólo de `roles_permisos`"* |
| **D-7** | `context.empresa` ausente, vacía, no en {`FORSIS`,`GERO`}, o el **eco** de `set_empresa`/`/api/guias/empresa` no coincide con lo pedido | `EMPRESA_UNSET` / `EMPRESA_MISMATCH` | TD §2.4 E1/E3; LSA §3.2 (default silencioso a `forsis`); LSAC §1 lo llama *"el guardarraíl más importante"* |
| **D-8** | Tool de clase **L3**, o endpoint de la lista de fuera de alcance (`autorizar_liquidacion.php`, `movimiento_tarjeta.php`, CFDI emitir/cancelar, `nomina/*`, `usuarios/*`, `sesiones/revocar`, `reportes_reseteo_eliminar.php`, `mensajes/enviar-*`) | `BLOCKED_L3` | TD §1, §5.4, §5.5, §6.4, §6.5 |
| **D-9** | La tool alcanzaría un endpoint **sin gate de auth** aprovechando esa ausencia (sin sesión válida del servicio) | `FORBIDDEN / SESION_REQUERIDA` | LSA §4.3; B-04 de TD §11. El agente nunca explota el bug |
| **D-10** | Escritura (`W`) con `write_allowlisted = false` o `AGENT_WRITE_ALLOWLIST` vacía | `FORBIDDEN / NO_ALLOWLIST` | DEP §8 (*"Fail-closed: sin usuarios en la allowlist, cero acciones de escritura"*), TSAC §0.4 |
| **D-11** | Escritura sin dry-run previo válido en la misma traza, o `confirmation_token` expirado (>300 s), reutilizado, o con `hash(args)` distinto | `DRY_RUN_REQUIRED` / `CONFIRMATION_EXPIRED` / `CONFIRMATION_REQUIRED` | TD §7.2 D1–D5 |
| **D-12** | `liq.solicitud_crear` con `modulo` fuera de `{CAJA_CHICA, TARJETA_DEUDOR, RECEPCION_GUIAS}` — incluido `LIQUIDACIONES` | `VALIDATION / MODULO_DESCONOCIDO` | LSA §3.7; LSS §2 (`solicitud_cancelacion.php:390`); **B-02** |
| **D-13** | `modulo` válido pero no permitido para el `priv` del actor (p. ej. LCP pidiendo `TARJETA_DEUDOR`) | `FORBIDDEN / MODULO_NO_AUTORIZADO` | §3.3 nota ¹ |
| **D-14** | `query_id` no catalogado, SQL libre, o `params` que no validan contra la firma tipada | `FORBIDDEN / QUERY_NO_CATALOGADA` · `VALIDATION` | Q-1, Q-2, TD §3.2 R-3/R-4 |
| **D-15** | `motivo` ausente, < 15 caracteres, o detectado como **autogenerado por el LLM** (plantilla, placeholder, o no confirmado por el humano) | `VALIDATION / MOTIVO_INVALIDO` | TD §5.2 P3, §6.4 P3 |
| **D-16** | Existe una solicitud `PENDIENTE` con la misma tripleta `(empresa, modulo, referencia_id)`, o una solicitud de liberación/timbrado abierta para alguna de las guías | `STATE_CONFLICT` | LSA §3.7 (unicidad lógica), TD §5.2 P6 |
| **D-17** | Precondición de estado que cambió entre dry-run y execute (`estatus` de guía ya no elegible) | `STATE_CONFLICT` | TSA §7 ⚠️ `validarSeleccion()`; TD §7.2 D6; regla S7 |
| **D-18** | `rows_leidas` alcanzaría un volumen fuera de límite, o > 2 queries concurrentes por traza, o > 4 conexiones | `VALIDATION / LIMITE_EXCEDIDO` | TD §10, LSA §9.8 |
| **D-19** | Rate limit por actor (5 L2/h) o global (20 L2/h) excedido | `FORBIDDEN / RATE_LIMITED` | TD §10 (LSS hallazgo #5: no inundar el buzón del revisor) |
| **D-20** | El INSERT de auditoría falla y la tool es **L2** | `FORBIDDEN / AUDIT_UNAVAILABLE` — la tool **no se ejecuta** | TD §8.2 A5 |
| **D-21** | `403 PASSWORD_CHANGE_REQUIRED` desde cualquiera de los dos sistemas | `FORBIDDEN / SERVICE_ACCOUNT_LOCKED`, **sin reintento**, alerta P1 | TSA §5.5, TD §4.2 |
| **D-22** | `AGENT_KILL_SWITCH=true`, o el healthcheck del canal detecta que el usuario de servicio tiene `access_forsis = 0` / `session_version` desfasado | `SERVICE_DISABLED` | §4.4 |
| **D-23** | El usuario de servicio se llama `CARLOSD`, `FATIMA` o `RUBISEL01`, o su `priv` es `SUPER USUARIO` | Arranque **falla**, no warning | LSA §5.3, TD §2.4 E5, S4-4 |
| **D-24** | La autorización procede de texto del usuario, de un argumento de la tool (`actor.allowlisted` llegando en el payload) o del historial de conversación | `FORBIDDEN / AUTORIZACION_NO_DERIVABLE` + alerta de posible inyección | TSAC §0.4, MIS §132, ID-6 |

**Orden de evaluación** (cortocircuita en la primera denegación, y ese es el código reportado):

```
D-22 kill-switch → D-21 cuenta de servicio → D-2 mapeo → D-1 priv vacío → D-4 substring
  → D-5 consistencia de rol → D-3 matriz tool×rol → D-7 empresa → D-8 L3
  → D-14 catálogo (lecturas) → D-10 allowlist → D-11 dry-run/token → D-12/D-13 módulo
  → D-15 motivo → D-16 duplicado → D-18/D-19 límites → D-20 auditoría → EJECUTA → D-17 re-chequeo
```

> **Sobre fugas de información:** el mensaje al usuario dice *qué* falló y *a quién acudir*, nunca
> el nombre del usuario de servicio, el DSN, el `priv` de otros usuarios ni la fila de la matriz de
> otro rol. El código exacto y el detalle quedan en la auditoría. Es el mismo criterio que usa el
> login de tráfico al no revelar la causa del rechazo para evitar enumeración (TSA §5.1 paso 2).

---

## 6. Protocolo de auditoría

### 6.1 Qué se registra en **cada** invocación

Una fila en `agente_acciones` (BD PostgreSQL propia del agente; esquema completo en TD §8.1,
coherente con `audit_records` de DBS §Auditoría). **Toda** invocación, incluidas L0 y los intentos
denegados. Campos agrupados por pregunta que responden:

| Pregunta | Campos |
|---|---|
| **¿Quién?** (actor) | `actor_human_id` (**el humano**, nunca el servicio), `actor_channel` ∈ {`mattermost`,`widget`,`cron`,`api`}, `channel_user_id`, `actor_allowlisted` (estado **al momento de ejecutar**), `rol_agente`, `traf_role_id`, `liq_priv` (valor usado para decidir), `executor_service_account` (`agente_ia`), `identity_resolved_at` |
| **¿Qué?** (tool) | `tool`, `tool_version`, `clase_riesgo` (L0–L3), `mode` ∈ {`dry_run`,`execute`,`denied`}, `canal_datos` ∈ {`db_ro`,`api`,`mixto`}, `sistema`, `empresa` (**nunca NULL**) |
| **¿Con qué argumentos?** | `args_json` con **enmascarado obligatorio** (§6.3), `args_hash` = `sha256(args canonicalizados)` — el hash permite comparar sin exponer |
| **¿Dry-run?** | `mode`, `parent_audit_id` (enlaza el `execute` con su `dry_run`), `plan_json` (`effects[]`, `preconditions[]`, `blast_radius`, `reversibility`), `confirmation_token_hash` (**nunca el token en claro**), `confirmation_expires_at`, `confirmed_by_human_id`, `confirmed_at` |
| **¿Contra qué?** | `request_endpoint` (ruta HTTP o `query_id`), `query_hash` = `sha256:` del SQL ejecutado, `db_alias`, `rows_leidas`, `upstream_status` |
| **¿Resultado?** | `resultado` ∈ {`ok`,`error`,`denegado`,`conflicto`}, `error_code`, `response_json` (truncado a 8 KB, enmascarado), `warnings[]`, `ts_inicio`, `ts_fin`, `duration_ms`, `idempotency_key` |
| **¿Correlación aguas arriba?** | `upstream_ref` (`folio_solicitud` de ATLAS, `solicitud_id` de `solicitudes_cancelacion`). Ausente en una L2 ⇒ `warnings:["sin_correlacion_upstream"]` (TD §8.4) |
| **¿Integridad?** | `prev_hash`, `row_hash` |

### 6.2 Cadena de integridad (hash)

```
row_hash = sha256(
    prev_hash                    ‖  -- row_hash de la fila anterior (cadena)
    trace_id ‖ parent_audit_id   ‖
    actor_human_id ‖ rol_agente  ‖
    sistema ‖ empresa            ‖
    tool ‖ tool_version ‖ clase_riesgo ‖ mode ‖
    args_hash                    ‖  -- no args_json: el hash es estable al enmascarado
    request_endpoint ‖ query_hash ‖
    resultado ‖ error_code ‖ upstream_status ‖ upstream_ref ‖
    ts_inicio_iso8601_utc
)
```

| # | Regla |
|---|---|
| A1 | Un `UPDATE` posterior sobre cualquier campo cubierto rompe la cadena y es detectable |
| A2 | **Append-only a nivel de motor**: el rol PostgreSQL del agente tiene `INSERT, SELECT` sobre `agente_acciones` y **no** `UPDATE/DELETE`. La integridad no depende del código de la aplicación |
| A3 | Retención 24 meses en línea; archivado mensual a fichero firmado |
| A4 | Verificador de cadena en cron diario; ruptura → **alerta P1** |
| A5 | **Fail-closed de auditoría:** si el INSERT falla en una L2, la tool no se ejecuta (D-20). En L0/L1 se degrada a log en disco + alerta, sin bloquear la lectura |
| A6 | `args_hash` se calcula sobre los argumentos **originales** (pre-enmascarado) para que dos invocaciones idénticas den el mismo hash, pero el hash **no se usa como oráculo**: no se persiste nada que permita reconstruir un secreto por fuerza bruta sobre un dominio pequeño (los secretos nunca entran en `args`) |

### 6.3 Enmascarado obligatorio antes de persistir

| Patrón | Tratamiento |
|---|---|
| `password`, `contrasena`, `token`, `api_key`, `secret`, `cookie`, `authorization` | `[REDACTED]` |
| Cookies de sesión (`trafico_session`, `PHPSESSID`) | `sha256` de los primeros 8 bytes. **Nunca** el valor |
| `confirmation_token` | Solo su hash |
| PII de operadores/empleados (CURP, RFC, cuenta bancaria, teléfono) | Enmascarado parcial `XXXX…1234` |
| Payloads binarios | Sustituidos por `{artifact_id, bytes, sha256}` |
| Contraseñas de la BD del resolvedor de identidad | **No se seleccionan jamás**; solo el booleano `(contrasena = '')` |

### 6.4 Lo que la auditoría del agente **no** sustituye

Se **correlaciona** con el rastro nativo, no lo reemplaza (TD §8.4):

| Sistema | Rastro nativo | Clave de correlación |
|---|---|---|
| trafico-system | `guia_origen`, `guia_origen_auditoria`, `forsis_guia_creation_registry`, `usuarios_sesiones_historial` | `num_guia` + ventana temporal + `usuario='agente_ia'` |
| liquidaciones-system | `solicitudes_cancelacion` (`solicitante`, `revisado_por`, `fecha_revision`, `motivo_rechazo`) | `solicitud_id` + `solicitante='agente_ia'` + prefijo `[AI/{human_id}/{trace_id}]` en `motivo` (ID-5) |
| ATLAS | Solicitudes de liberación/timbrado | `folio_solicitud` |

> **Advertencia operativa de B-04:** mientras los 8 endpoints sin gate de liquidaciones sigan
> abiertos (LSA §4.3, LSS §4 Fase A), **la auditoría del agente es la única traza existente** de
> esas lecturas y la allowlist es el único control real. Eso eleva A5 de "buena práctica" a
> requisito.

### 6.5 Métricas y alertas derivadas de permisos

| Métrica | Umbral |
|---|---|
| `mode='denied'` con `error_code='BLOCKED_L3'` | Cualquier pico → alguien pide sistemáticamente lo prohibido |
| `FORBIDDEN / PRIV_VACIO` por actor | > 3 en 24 h → el mapeo de ese humano está mal o hay sondeo |
| `FORBIDDEN / PRIV_SUBSTRING_MATCH` | Cualquier ocurrencia → documentar el `priv` real y escalar a B3 de LSS |
| `FORBIDDEN / ROL_INCONSISTENTE` | Cualquier ocurrencia → desfase legado↔RBAC en `trafico.usuarios` |
| `403 FORBIDDEN` del ERP tras pasar la matriz | Cualquier ocurrencia → la matriz es **más permisiva** que el ERP: violación de H-4, corregir la celda |
| `EMPRESA_MISMATCH` | Cualquier ocurrencia → P1: riesgo de contaminación cruzada de empresa (LSAC §13.4) |
| `STATE_CONFLICT` en execute tras dry-run OK | > 5 % → bajar el TTL de 300 s |
| Ruptura de cadena `row_hash` | P1 inmediato |

---

## 7. BLOQUEANTES

Lo que **no se pudo verificar** con la información de Fase 0 y bloquea o condiciona este diseño.
B-01…B-06 se heredan de `tools-design.md` §11 (se repiten solo los que afectan a permisos/auth);
B-07…B-12 son nuevos de este documento.

| # | Bloqueante | Impacto sobre permisos/auth | Qué se necesita para desbloquear |
|---|---|---|---|
| **B-02** | El workflow `solicitudes_cancelacion` **no tiene módulo `LIQUIDACIONES`** (LSS §2; `solicitud_cancelacion.php:390` → `throw "Módulo desconocido"`) | La acción de mayor valor (autorizar liquidación) **no tiene L2 equivalente**: no hay celda posible en la matriz. Regla D-12 la deniega por diseño | Añadir `LIQUIDACIONES` al workflow con `tipo=AUTORIZACION` (tarea B6 de LSS §4). Hasta entonces el agente solo **detecta y prioriza** la cola |
| **B-03** | **Usuarios de servicio no existen.** `agente_ia` en `trafico.usuarios` y en `usuarios` de liquidaciones están propuestos (TSAC §0.2) pero **no creados**, y sus permisos efectivos **no verificados** | Todo el canal API (I3/I4) es inejecutable. Las decisiones S3-2 y S4-3 son **teóricas hasta la verificación** | Crear ambas filas y ejecutar una prueba de humo por cada endpoint de la matriz, registrando el status real |
| **B-04** | **P0 de seguridad de liquidaciones sin aplicar** (LSS §4 Fase A: A1 ocho endpoints sin gate, A2 `priv` en `autorizar_liquidacion.php`, A3 `priv` en `action=crear`) | Las lecturas L0 del agente funcionarían **sin sesión**; la allowlist y la auditoría del agente son el único control. Condiciona D-9 y A5 | Aplicar A1–A3 **antes** de habilitar `liq.solicitud_crear`. Riesgo de rotura ≈ nulo según LSS §3 |
| **B-05** | **Grants read-only no aplicados ni verificados** sobre `sicrePR`, `sicre2PR`, `sicreGero`, `sicre2Gero`, `trafico` | Todo el canal A (I5) es inejecutable; además el resolvedor de identidad del §1.4 **no puede funcionar** ⇒ ninguna autorización es computable ⇒ todo deniega por D-2 | Aplicar los `GRANT SELECT` del §4.3 y **verificar que un `INSERT` de prueba lo rechaza el servidor**, no solo el parser (prueba T5 de TD §9.3) |
| **B-06** | **Sin TLS a `192.168.1.209`** (limitación del servidor, TSA §4.1) | La contraseña de `forsis_agent_ro` viaja **en claro** por la LAN en cada conexión. `ssl=0` forzado | Decisión explícita de aceptación de riesgo firmada, o plan de TLS en el servidor MySQL |
| **B-07** | **Rol del usuario de servicio de tráfico no validado.** S3-2 elige `FACTURACIÓN` (role_id 4) en vez del `SUPER USUARIO` que propone TSAC §0.2. No se verificó si `FACTURACIÓN` pasa `AuthorizationService::tieneAcceso()` para las rutas de liberación/timbrado, ni si alguna tool exige `guias.operar` (que `FACTURACIÓN` **no tiene**) | Si falta un permiso, las tools 12, 14, 19, 21 devuelven `403 FORBIDDEN` con el agente aparentemente sano. Si se cae a `SUPER USUARIO`, el servicio obtiene `usuarios.administrar` y `comunicaciones.enviar` — ambos fuera de alcance (TD §5.5) y mitigables solo por la matriz (ID-4) | Prueba en vivo con la cuenta de servicio: `POST /login` + `GET /api/guias`, `POST /api/guias/liberacion/validar`, `POST /api/guias/timbrado/validar`, `GET /api/facturacion/reportes/solicitudes`. Si falla, evaluar añadir **`guias.operar` al rol 4** (cambio de datos en `roles_permisos`, no de código) frente a usar role_id 13 |
| **B-08** | **liquidaciones-system no tiene revocación de sesión.** No existe `session_version` ni equivalente (LSA §4.2 no lo menciona; sí existe en tráfico, TSA §5.2) | Una cookie `PHPSESSID` del servicio robada es válida hasta 8 h **sin forma de invalidarla** salvo reiniciar PHP-FPM o cambiar `contrasena` en BD. Única mitigación: `AGENT_KILL_SWITCH` del lado del agente (§4.4), que no invalida la cookie ya emitida | Confirmar si reiniciar el contenedor PHP de liquidaciones purga las sesiones (depende de `session.save_handler`/`save_path`). Documentar el procedimiento de emergencia real |
| **B-09** | **Mapeo humano↔ERP inexistente.** No hay ninguna fuente en Fase 0 que relacione `trafico.usuarios.username`, `liquidaciones.usuarios.nombre_usu` y el `username` de Mattermost. Los dos padrones (≈95 usuarios en liquidaciones, N en tráfico) **no se verificó que compartan convención de nombres** | Sin el mapeo, todo humano cae en D-2 y el agente es inútil para escritura. **No se puede autodescubrir** (M-2) | Volcado de los tres padrones y validación manual con el dueño del sistema. Entregable: fichero de siembra de `agent_identities` revisado y firmado |
| **B-10** | **La matriz del §3 no fue validada contra el comportamiento real** de `AuthorizationService::protegerModulos()`. Para los 8 roles con 0 permisos RBAC, las celdas se derivaron de la descripción textual de TSA §6.1, no de la lectura del código de la rama legado (fuera de alcance: no modificar ni auditar código) | Riesgo en **ambas direcciones**: celdas `R` que el ERP negaría (ruido, 403 inesperados) y, peor, criterio de H-4 no demostrado para esos 8 roles | Leer `AuthorizationService::protegerModulos()` (solo lectura) y construir una tabla rol→módulo autoritativa. Alternativa barata: una prueba de humo por rol con una cuenta de prueba por rol |
| **B-11** | **Engine de las tablas de la cascada no confirmado (MyISAM).** LSS §8 lo declara por comentarios del código pero no lo verificó | Afecta la clasificación de riesgo: si `liquidaciones`/`detliq`/`tarjeta_contenido` son MyISAM, `beginTransaction()`/`FOR UPDATE` de `autorizar_liquidacion.php` son **best-effort sin rollback**, lo que refuerza mantener L3 fuera (D-8) pero también significa que una L2 futura sobre esas tablas no tendría atomicidad | `SHOW TABLE STATUS` sobre las tablas de la cascada (es un `SHOW`, permitido por R-3 en modo test) |
| **B-12** | **Omniroute sin verificación en vivo** (B-01 de TD §11): puerto de producción (`20129` dev / `20131` prod, pero `deployment-strategy.md` todavía dice `20130`, que es el dashboard) y vigencia de `${OMNIROUTE_API_KEY}` sin confirmar | No afecta la corrección de este modelo de permisos (el Executor autoriza con o sin LLM), pero sin planner no hay invocaciones que autorizar. **Además hay una discrepancia de configuración documentada que debe resolverse** | `POST {base}/v1/chat/completions` con `Authorization: Bearer ${OMNIROUTE_API_KEY}` y `{"model":"Forsis",…}` → 200. **No asumir `20129`** |

### 7.1 Lo que este documento afirma sin poder verificarlo (declaración explícita)

| Afirmación | Estado |
|---|---|
| Los 14 roles y sus permisos RBAC de §2.1 | **Verificado en BD** por TSA §6.1 (cita: *"consultados en BD"*) |
| La distribución de `priv` de §2.2 (77 vacíos, 8 SU, …) | **Verificado en BD** por LSA §5.1 (incluye el snippet de la consulta `GROUP BY priv`) |
| Que los 77 con `priv` vacío **son los mismos 77** con `contrasena` vacía | **Dado como premisa de la tarea**; LSA documenta ambos hechos (§4.1, §5.1) pero **no publica el join que lo demuestra**. La regla D-1 es correcta en cualquier caso, porque deniega por `priv` vacío sin depender de la correlación |
| Que `FACTURACIÓN` basta para el canal API de tráfico | **No verificado** → B-07 |
| Que existe un mapeo nombre-a-nombre entre padrones | **No verificado** → B-09 |
| Las celdas de los 8 roles sin RBAC | **Derivadas de documentación**, no del código → B-10 |
| Que liquidaciones no puede revocar sesiones | **Inferido por ausencia** en LSA §4.2 → B-08 |

---

## 8. Checklist de habilitación (orden obligatorio)

Ninguna tool de escritura se habilita antes de completar los pasos previos.

| # | Paso | Desbloquea | Depende de |
|---|---|---|---|
| 1 | Aplicar `GRANT SELECT` del §4.3 y verificar rechazo de `INSERT` por el servidor | Canal A + resolvedor de identidad | B-05 |
| 2 | Volcar los tres padrones y sembrar `agent_identities` revisado | Toda autorización | B-09 |
| 3 | Validar la matriz del §3 contra la rama legado o por humo por rol | Corrección de H-4 | B-10 |
| 4 | Crear `agente_ia` en tráfico (role_id 4) y probar los endpoints de la matriz | Canal API de tráfico | B-03, B-07 |
| 5 | Aplicar A1–A3 de LSS §4 Fase A (P0 de liquidaciones) | Confianza en la auditoría | B-04 |
| 6 | Crear `agente_ia` en liquidaciones con `priv='LIQUIDACIONES'` y contraseña no vacía | Canal API de liquidaciones | B-03, paso 5 |
| 7 | Documentar el procedimiento de revocación de sesión de liquidaciones | Respuesta a incidentes | B-08 |
| 8 | Habilitar tools L0/L1 con `AGENT_WRITE_ALLOWLIST=""` | Lectura en producción | 1–6 |
| 9 | Poblar la allowlist con los primeros operadores y habilitar las **3** L2 | Escritura | 1–8 |
| 10 | Añadir el módulo `LIQUIDACIONES` al workflow (B6 de LSS) | Gate para autorización de liquidaciones | B-02 |

---

**Documentos relacionados:** `tools-design.md` (catálogo de tools y clases de riesgo, mismo
directorio) · `architecture.md` / `db-schema.md` · `agent-core.md` / `llm-provider.md` ·
`deployment-strategy.md` · `liquidaciones-security-strategy.md`
