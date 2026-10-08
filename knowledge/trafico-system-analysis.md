# trafico-system — Análisis Arquitectónico (Fase 0)

> Generado: 2026-10-03 · Fuente: `/home/servidor/trafico-system` (código vivo + BD en ejecución)
> Secretos redactados: todo valor de contraseña/API key aparece como `[REDACTED]`.

---

## 1. Resumen ejecutivo

`trafico-system` (marca interna **FORSIS**) es el ERP operativo-logístico de la empresa: guías de
transporte, planeación de despachos, facturación/CFDI 4.0 Carta Porte, RRHH/nómina, proveedores/CxP,
QHSE, comunicaciones WhatsApp y una consola de control. Es un monolito **PHP 8 sin framework**, con
router propio, organizado en módulos, desplegado por Docker Compose.

Rasgo arquitectónico central: **no es dueño de su dato maestro**. Las guías, facturas y usuarios
históricos viven en las bases MySQL legadas **SICRET** (`192.168.1.209:3306`), compartidas con
`liquidaciones-system`. La BD propia (`trafico`, MariaDB 11 en contenedor) sólo guarda lo que SICRET
no sabe modelar: módulos nuevos, auditoría, staging y metadatos.

| Aspecto | Valor |
|---|---|
| Lenguaje | PHP 8.x, procedural/estático (clases con métodos `static`), sin Composer framework |
| Router | Propio (`app/core/Router.php`), despacho por `path` exacto |
| Vistas | PHP templates en `app/views/` + JS vanilla (`apiFetch`) |
| BD propia | MariaDB 11 (`trafico`), **114 tablas** |
| BD legadas | `sicrePR` (136 tablas), `sicre2PR` (49), `sicreGero` (124), `sicre2Gero` (28) |
| Endpoints | ~**450 rutas** registradas (≈370 bajo `/api/`) |
| Auth | Sesión PHP (`trafico_session`), sin JWT ni API keys para humanos |
| Multiempresa | `CompanyContext`: `FORSIS` / `GERO` |
| Integración externa | **ATLAS** (`tablero-guias`) vía HTTP, HMAC en webhooks entrantes |

---

## 2. Stack tecnológico y topología Docker

`docker-compose.yml` define **15 servicios**. Núcleo:

| Servicio | Imagen/base | Rol |
|---|---|---|
| `nginx` | `nginx:alpine` | Front HTTP. Puerto interno **8091**, *no publicado al host* |
| `php` | build `docker/php` (php:fpm) | Aplicación. Monta `./app` en `/var/www/html` |
| `mariadb` | `mariadb:11` | BD `trafico` (contenedor `trafico-db`), volumen `trafico_mariadb` |
| `redis` | `redis:alpine` | Caché/colas auxiliares |
| `comunicaciones-websocket` | php | WS tiempo real WhatsApp. Sin `ports:` (solo red interna) |

**Workers cron** (patrón uniforme `sh -c 'while true; do php bin/<script>.php; sleep $N; done'`,
cada script es una pasada **idempotente** que sale limpio si no está configurado):

| Worker | Script | Función |
|---|---|---|
| `correo-pases-cron` | `correo-pases-watcher-cli.php` | **Ingesta IMAP de pases de descarga** (60 s) |
| `rrhh-nomina-cron` | `rh-nomina-watcher-cli.php` | Ingesta IMAP de recibos de nómina |
| `motor-watcher` | `motor-timbrado-watcher.php` | Vigila el motor de timbrado CFDI |
| `sicret-guide-cleanup-cron` | `sicret-guide-cleanup-cli.php` | Limpieza de guías huérfanas en SICRET |
| `reseteo-ingestion-cron` | `reseteo-ingestion-cli.php` | Ingesta de eventos de reseteo GPS |
| `comunicaciones-adjuntos-cron` | `comunicaciones-adjuntos-cli.php` | Descarga de adjuntos WhatsApp |
| `perfil-inteligente-cron` | — | Perfilado de timbrado |
| `tipo-cambio-cron` | — | Tipo de cambio Banxico |
| `scheduled-deductions-cron` | `scheduled-deductions-run-cli.php` | Deducciones programadas RRHH |

Redes: `default` + `forsis-comunicaciones` (exclusiva de OpenWA).
Las bases legadas y ATLAS se alcanzan con `extra_hosts: host.docker.internal:host-gateway`
(no comparten red Docker).

---

## 3. Estructura de código

```
app/
├── public/index.php          # front controller: bootstrap + registro de rutas base
├── core/
│   ├── Router.php            # router propio
│   ├── ConnectionManager.php # resuelve conexión por empresa (FORSIS|GERO)
│   ├── CompanyContext.php    # contexto multiempresa en sesión
│   └── *Database.php         # SicretDatabase, Sicret2Database, SicretGero*, Database
├── Auth/
│   ├── LoginController.php          # /login, /logout
│   ├── AuthenticationService.php    # verificación de credenciales
│   ├── AuthorizationService.php     # acceso por rol + ruta de inicio
│   ├── SessionManager.php           # sesión, TTLs
│   ├── CurrentUser.php              # fachada de permisos
│   └── Guard.php                    # middleware: rutas públicas, 401/403, módulos
├── config/                   # database.php, sicret*.php, atlas.php, banxico.php...
├── modules/<modulo>/
│   ├── routes.php            # rutas del módulo
│   ├── controllers/  models/  services/  repositories/
├── integrations/atlas/AtlasClient.php
├── bin/                      # ~40 CLIs: migraciones, watchers, seeds, backfills
└── views/
```

**Módulos**: `guias`, `facturacion`, `planeacion`, `rrhh`, `proveedores`, `unidades`, `ubicaciones`,
`qhse`, `comunicaciones`, `usuarios`, `perfil`, `control`, `reseteo`, `diesel_shortages`,
`integraciones`.

Convención de capas: `routes.php` → `Controller` (valida permiso + entrada, responde JSON) →
`Service` (regla de negocio) → `Model`/`Repository` (SQL). Los controladores **no** contienen cURL ni
URLs externas; eso vive en `integrations/`.

---

## 4. Bases de datos

### 4.1 Mapa de conexiones

| Config | Host | Base | Charset | Contenido |
|---|---|---|---|---|
| `config/database.php` | `mariadb` (interno) | `trafico` | utf8mb4 | Nativa de la app |
| `config/sicret.php` | `host.docker.internal:3306` | `sicrePR` | **latin1** | SICRET FORSIS (guías, facturas) |
| `config/sicret2.php` | `host.docker.internal:3306` | `sicre2PR` | utf8mb4 | SICRET FORSIS v2 |
| `config/sicret_gero.php` | `192.168.1.209:3306` | `sicreGero` | utf8mb4 | SICRET GERO |
| `config/sicret2_gero.php` | `192.168.1.209:3306` | `sicre2Gero` | utf8mb4 | SICRET GERO v2 |

`host.docker.internal` resuelve al host, que enruta a **192.168.1.209** — es el mismo servidor
MySQL que usa `liquidaciones-system`. Credenciales `[REDACTED]`.

⚠️ **Nota de conectividad verificada**: el servidor 192.168.1.209 **no soporta TLS**; los clientes
`mariadb` modernos requieren `--ssl=0` explícito o fallan con
`ERROR 2026 (HY000): TLS/SSL error: SSL is required, but the server does not support it`.

⚠️ **`sicrePR` es latin1**: todo texto leído de ahí requiere transcodificación antes de serializar a
JSON. Es la causa de los `JSON_INVALID_UTF8_SUBSTITUTE` repartidos por el código.

### 4.2 Esquema relevante — `trafico` (114 tablas)

**Autenticación y permisos**
```
usuarios(id, username UNI, password_hash, password_algorithm ENUM('md5_legacy','argon2id','bcrypt'),
         access_forsis, access_sicret, role, role_id FK, employee_id, email,
         session_version, created_by, created_at, updated_at, deactivated_at, last_login_at)
roles(id, nombre, slug, basado_en_legado)
permisos(id, clave, ...)
roles_permisos(role_id, permiso_id)
usuarios_cambio_password_pendiente | usuarios_preferencias | usuarios_sesiones_historial
usuarios_integraciones
```

**Guías (metadatos sobre SICRET)**
```
guia_origen(id, empresa, num_guia, origen_app DEFAULT 'FORSIS', metodo, usuario,
            guia_creada_en, evidencia DEFAULT 'LIVE', tracked_at, updated_at)
guia_origen_auditoria
forsis_guia_creation_registry
guia_soportes            -- documentos de soporte subidos
guia_movimiento_ingreso
folio_override
```

**Pases de descarga (TPT)** — tabla nativa, núcleo del flujo de ingesta por correo:
```
guia_pases_descarga(
  id, empresa, num_guia, folio_pase, contenedor, fecha_cita,
  archivo_original, archivo_guardado, ruta_archivo,
  mime_type DEFAULT 'application/pdf', tamanio, hash_sha256 CHAR(64),
  origen ENUM('correo','manual') DEFAULT 'correo',
  remitente_correo, usuario_carga DEFAULT 'SISTEMA',
  fecha_carga, activo TINYINT DEFAULT 1)
```
`hash_sha256` da idempotencia a la ingesta IMAP; `activo` permite reemplazo lógico.

**Timbrado CFDI**
```
timbrado_captura(id, solicitud_id, empresa, clave_gene, origen, destino, grupo_key,
                 datos_capturados LONGTEXT, usuario, created_at, updated_at)
timbrado_emision(id, folio UNI, solicitud_id, guia, empresa, clave_gene, grupo_key,
                 snapshot_json LONGTEXT, version_snapshot, version_motor,
                 yaml_path, yaml_sha256, yaml_size, uuid, idccp, xml_path, pdf_path,
                 estado ENUM('EN_TRANSITO','CONCLUIDO','FALLIDO') DEFAULT 'EN_TRANSITO',
                 estado_motor, motivo_fallo, reintento_de,
                 fecha_envio, fecha_confirmacion, usuario, ...)
comprobante_emision | comprobante_emision_descartes
perfil_inteligente_timbrado
```

**Planeación / operación**
```
despacho(id, fecha, tc_norm, placas_norm, operador_norm, canonical_unit_id, canonical_num_ope,
         configuracion_viaje ENUM('Sencillo','Doble','Triple','Cuadruple'),
         full_pair_flag, costo_peaje_estimado, dolly_id, dolly_eco, dispatch_group_key, ...)
viajes | operacion_viajes | tramo_carga | evento_operativo
v_operacion_2026_unificada (VIEW)
cat_sellos_stock | cat_peajes_rutas | cat_contenedores_historial(_guias)
cat_map_clientes_2026 | cat_map_operadores_2026 | cat_map_tractores_2026
unidad_monitoreo_checkpoints | cat_unidad_monitoreo_base | unidades_historial
ubicaciones_geo | documentos_archivos
```

**Staging/referencia espejo de SICRET** (sufijo `_2026`): `ref_sicret_guias_2026`,
`ref_sicret_facturas33_2026`, `ref_sicret_contenedores_2026`, `ref_sicret_mercancias_2026`,
`stg_excel_2026_catchup`.

**Otros dominios**: `rrhh_*` (36 tablas: nómina, finiquitos, aguinaldos, vacaciones, préstamos,
tarjeta deudor, expediente), `proveedores_*` (10: facturas, pagos, lotes, workflow, bitácora),
`comunicaciones_*` (7: cuentas, conversaciones, mensajes, adjuntos, contactos, bitácora),
`qhse_*` (6), `reset_*`/`reseteo_*` (7), `cotizaciones*` (7), `diesel_shortage_record`,
`service_heartbeats`, `sicret_cleanup_activation`, `sicret_guide_cleanup_log`, `unit_alias`.

### 4.3 Esquema relevante — SICRET legado

```sql
-- sicrePR.guias  (latin1, PK autoincremental `num`, folio en `num_guia`)
guias(num PK, num_guia VARCHAR(15) MUL, folio_imp, fecha, fecha_c, fecha_d, num_llama,
      estado MUL, nombre, tipo MUL, num_vale, diesel, servicio MUL,
      rem1, placas1, rem2, placas2,
      estatus VARCHAR(250) MUL,      -- ← máquina de estados del negocio
      pedido, comen_pre, factura MUL, manifiesto,
      ticket1, tons1, ticket2, tons2, operador,
      prefactura, factimpresa, linea, km,
      claveproductoSat, claveUnidadSat, do, lid, actualizacion)

-- sicrePR.usuarios  (legado; la app NO autentica aquí, usa trafico.usuarios)
usuarios(nombre_usu PK, contrasena, priv, cajaChica, cajaChicaLetra, correo, num_emp)
```
Otras tablas SICRET consumidas: `facturas33`, `conceptosfacturas33`, `complementopagos*`,
`clientes`, `empleados`, `operadores`, `equipos`, `dollys`, `liquidaciones`, `detliq`, `gastosliq`,
`liquidacion_td_detalle`, `cotizaciones*`, `direcciones`, `lineas`, `estados`.

⚠️ Todas las columnas SICRET son `NOT NULL` sin default: cualquier `INSERT` debe suministrar
**todos** los campos. Es un esquema sin disciplina de nulabilidad.

---

## 5. Autenticación

### 5.1 Flujo

`POST /login` → `LoginController::procesar()`:
1. `AuthenticationService::intentar($usuario, $password)` — consulta `trafico.usuarios`.
2. **Gate de acceso**: rechaza si `access_forsis !== 1` (mensaje genérico, no revela la causa —
   evita enumeración de cuentas).
3. Verificación por `password_algorithm`:
   - `md5_legacy` → `hash_equals($hash, md5($password))` y, si acierta, **rehash transparente**
     a `argon2id` (`UPDATE ... SET password_algorithm='argon2id', last_login_at=NOW()`).
   - `argon2id` → `password_verify()`.
   - Cualquier otro valor → **falla cerrado**.
4. `AuthorizationService::tieneAcceso($priv)`; si no, 403 con `views/403.php`.
5. `UsuariosPendientesCambioRepository::existePendiente()` — se consulta **antes** de crear sesión.
6. `SessionManager::guardarUsuario()` → `session_regenerate_id(true)` (anti fijación de sesión).
7. `SesionesHistorialRepository::registrar($usuario, REMOTE_ADDR, UA)` — sólo logins **exitosos**;
   un fallo aquí nunca impide el login (se traga a `error_log`).
8. Redirección: `?return=` validado → preferencia `pagina_inicio` (si sigue siendo destino válido
   para el rol **actual**) → `AuthorizationService::rutaInicio($priv)`.

### 5.2 Sesión

`SessionManager`, cookie `trafico_session`:

| Parámetro | Valor | Nota |
|---|---|---|
| Inactividad máxima | **8 h** | `ini_set('session.gc_maxlifetime')` explícito antes de `session_start()` |
| Vida absoluta | **12 h** | Desde el login, validada server-side contra `trafico_login_en` |
| Claves | `trafico_usuario`, `trafico_login_en`, `trafico_debe_cambiar_password` | |

Auditoría 2026-08-13: antes heredaba el default de fábrica de `php:fpm` (1440 s = 24 min) con barrido
probabilístico, causando los logouts de ~30 min reportados por usuarios.

**Revocación remota**: el snapshot de sesión lleva `session_version`; `Guard::proteger()` lo compara
en **cada request** contra `trafico.usuarios.session_version`. Incrementar la columna
(`/api/usuarios/sesiones/revocar`, `/api/control/users/force-logout`) mata todas las sesiones del
usuario. La misma consulta revalida `access_forsis`, así que deshabilitar una cuenta expulsa en caliente.

### 5.3 Autenticación servidor-a-servidor

Sin sesión PHP, por **firma HMAC**:
- `POST /api/comunicaciones/webhook/openwa` → `WebhookController::recibir()`
- `POST /api/facturacion/eventos-atlas` → `AtlasEventoController::recibir()`
- `/api/control/*` → `Guard::protegerControlApi()`, superficie propia (app Android *Forsis Control*),
  responde **401** sin caer a valor por defecto.

**Salida hacia ATLAS**: `AtlasClient` usa cURL con `Accept: application/json` y **sin credenciales**
(timeout 5 s, connect 3 s). La confianza es puramente de red/host.

### 5.4 Rutas públicas (`Guard::RUTAS_PUBLICAS`)

`/login`, `/logout`, `/guia-public`, `/guia-public/carta-porte`, `/guia-public/documento-unidad`,
`/guia-movimiento-publico`, `/qhse/vale/validar` (match por prefijo), `/gafete-verificar`,
`/rrhh/tarjetas-deudor/validar-cargo`, `/api/comunicaciones/webhook/openwa`,
`/api/facturacion/eventos-atlas`.

Son endpoints de verificación por QR y webhooks. La defensa de red que lo respalda: nginx escucha en
**8091 sin publicar al host**.

### 5.5 Códigos de error del Guard

| Código | Significado |
|---|---|
| `401 SESSION_EXPIRED` | Sesión vencida o `session_version` desfasado. El front (`apiFetch`) muestra banner y permite relogueo con `?return=` |
| `403 PASSWORD_CHANGE_REQUIRED` | Cambio forzado pendiente; sólo rutas de cambio de contraseña permitidas |
| `403 FORBIDDEN` | Sin permiso sobre el recurso |

---

## 6. Permisos y roles

Modelo **híbrido**: rol legado en texto (`usuarios.role`, heredado de `sicret.usuarios.priv`) +
RBAC nativo (`roles` / `permisos` / `roles_permisos`). `AuthorizationService` decide acceso a módulo
por rol; `CurrentUser::tienePermiso($clave)` consulta el RBAC fino.

### 6.1 Roles y permisos vigentes (consultados en BD)

| ID | Rol | Permisos asignados |
|---|---|---|
| 1 | ADMINISTRADOR | `comunicaciones.asignar/enviar/ver`, `facturacion.cfdi.consultar`, `guias.ver`, `qhse.acceso` |
| 2 | CAPTURISTA | *(ninguno)* |
| 3 | CUENTAS POR PAGAR | *(ninguno)* |
| 4 | FACTURACIÓN | `facturacion.aging.exportar/ver`, `facturacion.cfdi.consultar`, `facturacion.guias_soporte.upload`, `guias.ver`, `modulo.facturacion.acceso` |
| 5 | GERENTE DE OPERACIONES | `diesel_shortages.ver`, `facturacion.cfdi.consultar`, `guias.operar`, `guias.ver` |
| 6 | JEFE DE LIQUIDACIONES | *(ninguno)* |
| 7 | JEFE DE TRÁFICO | *(ninguno)* |
| 8 | LIQUIDACIONES | *(ninguno)* |
| 9 | RECURSOS HUMANOS | `guias.operar` |
| 10 | RESETEOS | `diesel_shortages.escribir/ver` |
| 11 | SISTEMAS | *(ninguno)* |
| 12 | SUPERVISOR DE CUENTAS POR PAGAR | *(ninguno)* |
| 13 | **SUPER USUARIO** | **todos** (15): `comunicaciones.*`, `diesel_shortages.*`, `facturacion.*`, `guias.operar/ver`, `modulo.facturacion.acceso`, `qhse.acceso`, `usuarios.administrar` |
| 14 | TRÁFICO | `diesel_shortages.ver`, `facturacion.cfdi.consultar`, `guias.operar`, `guias.ver` |

⚠️ **Los roles con 0 permisos RBAC no están sin acceso**: su autorización se resuelve por la rama de
rol legado en `AuthorizationService::protegerModulos()` (p. ej. Tráfico "no tiene rama propia aquí,
cae directo al 403 final"). La migración legado→RBAC está **a medias**; nunca deduzcas capacidades
sólo de `roles_permisos`.

### 6.2 Fachada `CurrentUser`

Predicados de rol: `esFacturacion()`, `esSuperUsuario()`, `esAdministrador()`,
`esRecursosHumanos()`, `esProveedores()`, `esReseteo()`.

Predicados de capacidad: `puedeOperarGuias()`, `puedeGestionarSoporteGuia()`,
`puedeConsultarPaseDescarga()`, `puedeVerDieselShortages()`, `puedeEscrituraDieselShortages()`,
`puedeVerComunicaciones()`, `puedeEnviarMensajes()`, `puedeAsignarConversaciones()`,
`puedeAdministrarCuentasWhatsapp()`, y el genérico `tienePermiso(string $clave)`.

Todo controlador de escritura abre con uno de estos y responde 403 JSON. **Es el punto de extensión
correcto para un rol de agente IA.**

---

## 7. Máquina de estados de guías (`GuiaBloqueoService`)

El campo gobernante es `sicrePR.guias.estatus` (texto libre, comparado normalizado).

| Estatus | Semántica |
|---|---|
| `Asignada Al Operador` | **Bloqueante** para edición; es el único estado donde se editan sellos y desde el que se puede *solicitar liberación* |
| `Por Timbrar` | Único estado editable; elegible para *solicitar timbrado* |
| `PAGADA AL OPERADOR` (prefijo) | Elegible para liberación si ya tiene CFDI; para timbrado si **aún no** tiene CFDI |
| `CANCELADA*` (prefijo) | Excluida de guía de ingreso |

Predicados: `bloqueada()`, `puedeEditarse()`, `puedeSolicitarLiberacion($estatus, $tieneCfdi)`,
`puedeSolicitarTimbrado($estatus, $tieneCfdi)`, `puedeEditarSellos()`, `puedeGenerarGuiaIngreso()`,
más `motivo*()` que devuelven el texto exacto mostrado al usuario.

⚠️ **Revalidación obligatoria**: `LiberacionGuiaController::validarSeleccion()` existe porque el
estatus puede cambiar mientras el usuario tiene folios seleccionados. El front revalida al confirmar
el modal **y** en cada refresco automático del listado. Un agente IA debe hacer lo mismo:
`GuiasModel::validarBloqueoPorFolios($folios)` antes de cualquier envío.

---

## 8. Integración con ATLAS (`tablero-guias`)

`app/config/atlas.php`: `base_url = http://host.docker.internal:8097`, `timeout 5`,
`connect_timeout 3`. ATLAS corre en su propio Compose sin red compartida.

| Endpoint ATLAS | Método `AtlasClient` |
|---|---|
| `/api/solicitudes-liberacion.php` | `solicitarLiberacion()`, `obtenerSolicitudLiberacion()`, `responderLiberacion()` |
| `/api/solicitudes-timbrado.php` | `solicitarTimbrado()`, `obtenerSolicitudTimbrado()`, `responderTimbrado()` |
| `/api/facturacion-solicitudes.php` | `consultarEstadosLiberacion()`, `listarFoliosLiberacionPorEstado()` |
| `/api/facturacion-solicitudes-timbrado.php` | `consultarEstadosTimbrado()`, `listarFoliosTimbradoPorEstado()` |
| `/api/timbrado-carta-porte.php` | `descargarCartaPorte()` |
| `/api/reportes/guias-liberadas.php` | `reporteGuiasLiberadas()` |
| `/api/facturacion-kpis.php` | `kpisFacturacion()` |
| `/api/guia-historial.php` | `historialGuia()` |

Optimización: `getMany()` / `listarFoliosPorEstadosEnLote()` paralelizan con `curl_multi` para no
romper el tiempo de respuesta de `/api/guias`.

Errores: `AtlasIntegrationException::timeout()` / `::conexionFallida()` / `::porHttpStatus()`.
Todo fallo se escribe a `error_log` con la URL.

Entrada inversa: ATLAS notifica eventos de dominio a `POST /api/facturacion/eventos-atlas` (HMAC)
para tiempo real en Avisos de Facturación.

---

## 9. Integración actual con forsis-bot

`/home/servidor/forsis-bot` — bot Python de Mattermost, **12 módulos**: `main.py`, `ai.py`,
`actions.py`, `classifier.py`, `model_router.py`, `embeddings.py`, `knowledge_ai.py`,
`personality.py`, `scheduler.py`, `weather.py`, `web_tools.py`, `db.py`.

**Hallazgo clave: no hay integración directa.** El bot **no** se conecta a `trafico` ni a SICRET.

- Su `db.py` usa **PostgreSQL + pgvector** (`DATABASE_URL`, SQLAlchemy), tablas propias:
  `mensajes(id, canal, usuario, mensaje, fecha, embedding vector(768))`, `perfiles_usuarios(...)`.
  Es memoria conversacional, no dato operativo.
- `actions.py` expone sólo: `parece_accion()`, `decidir_accion()`, `_decidir_accion()`,
  `usuarios_autorizados_agy()`, `ejecutar_agy()`.
- El único camino de acción real es **delegar a un agente de shell**: `ejecutar_agy()` lanza
  `subprocess.run(["agy","--print",instruccion,"--sandbox","--dangerously-skip-permissions",
  "--print-timeout","{N}s"])`, timeout 180 s.

**Modelo de autorización del bot** (precedente a respetar):
```python
def usuarios_autorizados_agy():
    crudo = os.getenv("AGY_USUARIOS_AUTORIZADOS", "")
    return {u.strip().lower() for u in crudo.split(",") if u.strip()}
```
Allowlist explícita por variable de entorno, **no auto-aprendida de la conversación** — comentario
textual del código: *"un 'soy de TI' en el chat no debe bastar para autorizar acceso a un agente con
acceso a la base de datos"*. La confirmación humana ocurre en Mattermost **antes** de invocar `agy`;
de ahí `--dangerously-skip-permissions` (un proceso headless nunca podría dar la aprobación interactiva).

**Implicación para Fase 1**: toda acción del agente sobre `trafico-system` debe pasar por su capa
HTTP autenticada (sesión de un usuario de servicio) o por una superficie nueva tipo
`/api/control/*` con auth propia. Hoy no existe ningún puente; hay que construirlo.

---

## 10. Dependencias críticas y riesgos

| # | Dependencia | Riesgo | Mitigación observada |
|---|---|---|---|
| 1 | MySQL `192.168.1.209` (4 bases) | **SPOF absoluto**; compartido con liquidaciones-system | Ninguna. Sin réplica. |
| 2 | TLS ausente en .209 | Clientes modernos fallan | Requiere `--ssl=0` |
| 3 | `sicrePR` en latin1 | Mojibake / JSON inválido | `JSON_INVALID_UTF8_SUBSTITUTE` disperso |
| 4 | ATLAS en `:8097` | Liberación y timbrado **inoperables** si cae | Timeouts cortos (5s/3s) + excepciones tipadas |
| 5 | ATLAS sin auth saliente | Suplantación si la red se expone | Confianza por red/host |
| 6 | IMAP `mail.forsis.com.mx` | Sin pases de descarga ni recibos de nómina | Script sale `skipped` si falta config |
| 7 | OpenWA `openwa-api:2785` | Comunicaciones caídas | Red dedicada |
| 8 | `md5_legacy` en `usuarios` | Hashes MD5 vivos hasta el próximo login | Rehash transparente a argon2id |
| 9 | RBAC a medias | Autorización en dos lugares (rol legado + permisos) | — |
| 10 | Ruta de archivos de pases | Pase no descargable si falta el fichero | `GuiaPaseDescargaStorageService::resolverRutaFisica()` + 404 |
| 11 | Sin suite de tests | Toda regresión es manual | ~40 CLIs idempotentes en `bin/` |
| 12 | Logging sólo `error_log` | Observabilidad pobre (PHP-FPM log) | `service_heartbeats` para workers |

---

## 11. Observaciones para el agente IA (Fase 1)

1. **Nunca escribir directo en `sicrePR`.** Las guías se crean/mutan por los servicios de la app, que
   registran procedencia en `guia_origen` y `forsis_guia_creation_registry`. Un `INSERT` directo
   rompe la auditoría (y el esquema `NOT NULL`-sin-default lo hará fallar).
2. **Revalidar estatus antes de actuar** (`validarBloqueoPorFolios`): el estado cambia bajo los pies.
3. **Respetar `CompanyContext`**: toda operación requiere empresa `FORSIS` o `GERO`; la conexión se
   resuelve por ahí. Omitirla lanza `InvalidArgumentException`.
4. **Usuario de servicio dedicado** con rol propio y permisos mínimos
   (`guias.ver`, `facturacion.cfdi.consultar`), nunca SUPER USUARIO. `access_forsis=1`,
   `password_algorithm='argon2id'`.
5. **Reusar el patrón de allowlist de forsis-bot** (`AGY_USUARIOS_AUTORIZADOS`) para autorizar quién
   puede pedir acciones de escritura.
6. **Idempotencia**: imitar los CLIs de `bin/` (una pasada, salida limpia si no hay nada que hacer).
   Para pases de descarga, `hash_sha256` ya da deduplicación natural.
7. **ATLAS es asíncrono**: `solicitarLiberacion()` crea una solicitud `EN_TRANSITO`; la resolución
   llega por `consultarEstadosLiberacion()` o por el webhook de eventos. No esperar respuesta final.
8. **Preferir lectura**: ~370 endpoints `/api/`, la mayoría GET. Fase 1 debería ser read-only +
   escrituras acotadas con confirmación humana.

---

## 12. Referencias de archivo

| Tema | Ruta |
|---|---|
| Front controller | `app/public/index.php` |
| Router | `app/core/Router.php` |
| Middleware auth | `app/Auth/Guard.php` |
| Login | `app/Auth/LoginController.php`, `AuthenticationService.php` |
| Sesión | `app/Auth/SessionManager.php` |
| Permisos | `app/Auth/CurrentUser.php`, `AuthorizationService.php` |
| Conexiones | `app/core/ConnectionManager.php`, `app/config/*.php` |
| Guías | `app/modules/guias/` (`GuiasModel`, `GuiaBloqueoService`, `LiberacionGuiaController`) |
| Pases descarga | `app/modules/facturacion/controllers/GuiaPaseDescargaController.php`, `bin/correo-pases-watcher-cli.php` |
| ATLAS | `app/integrations/atlas/AtlasClient.php`, `app/config/atlas.php` |
| Seed RBAC | `app/bin/roles-permisos-seed.php` |
| Despliegue | `docker-compose.yml`, `docker/nginx/default.conf` |
