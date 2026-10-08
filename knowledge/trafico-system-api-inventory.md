# trafico-system — Inventario de APIs y Endpoints

> Generado: 2026-10-03 · Fuente: `app/public/index.php` + `app/modules/*/routes.php`
> **518 rutas registradas** (contadas sobre el código, incluidas las declaraciones multilínea).

---

## 0. Cómo consumir esta API

| Aspecto | Detalle |
|---|---|
| Base URL interna | `http://nginx:8091` (contenedor). **No publicada al host** |
| Autenticación | Cookie de sesión `trafico_session` obtenida por `POST /login` |
| Content-Type entrada | `application/x-www-form-urlencoded` (login) / `application/json` (APIs) |
| Content-Type salida | `application/json; charset=utf-8` salvo endpoints de impresión/descarga |
| Multiempresa | `CompanyContext` en sesión; conmutar con `POST /api/guias/empresa` |
| Router | Match **exacto** de path (excepción: `/qhse/vale/validar` por prefijo). Sin parámetros en ruta — todo va por query string o body |

**Formas de respuesta** (conviven dos convenciones, según antigüedad del módulo):
```json
{"ok": true,  "data": {...}}                 // guías, liberación, timbrado
{"ok": false, "error": "mensaje"}
{"success": true, "disponible": true, "pase": {...}}   // pases de descarga
{"success": false, "error": "mensaje"}
```

**Errores del middleware** (`Guard`):

| HTTP | Código | Causa |
|---|---|---|
| 401 | `SESSION_EXPIRED` | Sesión vencida o `session_version` desfasado |
| 403 | `PASSWORD_CHANGE_REQUIRED` | Cambio de contraseña forzado pendiente |
| 403 | `FORBIDDEN` | Sin permiso sobre el recurso |
| 400 | — | Validación de entrada del controlador |
| 404 | — | Recurso/archivo inexistente |
| 500 | — | Excepción no controlada (mensaje de `Throwable`) |

---

## 1. Autenticación y sesión

| Método | Ruta | Controlador | Auth |
|---|---|---|---|
| GET | `/login` | `LoginController::mostrar` | **Pública** |
| POST | `/login` | `LoginController::procesar` | **Pública** |
| POST | `/logout` | `LogoutController::salir` | **Pública** |
| GET | `/api/sesion/heartbeat` | `SesionController::heartbeat` | Sesión |
| GET | `/usuarios/cambiar-password` | vista | Sesión |
| POST | `/api/usuarios/cambiar-password` | — | Sesión |
| POST | `/api/perfil/cambiar-password` | — | Sesión |

**Login**
```
POST /login
Content-Type: application/x-www-form-urlencoded

usuario=<username>&password=<[REDACTED]>&return=/guias
```
Respuesta: `302` a destino + `Set-Cookie: trafico_session=...`.
Falla → `302 /login` con `$_SESSION['login_error']`.
Sin `access_forsis=1` → mismo mensaje genérico (no revela la causa).

`return` se valida contra open-redirect: debe empezar por `/` y **no** por `//` ni `/\`.

---

## 2. Rutas públicas (sin sesión)

| Método | Ruta | Propósito |
|---|---|---|
| GET | `/guia-public` | Vista pública de guía (QR) |
| GET | `/guia-public/carta-porte` | PDF Carta Porte público |
| GET | `/guia-public/documento-unidad` | Documento de unidad |
| GET | `/guia-movimiento-publico` | Movimiento de ingreso público |
| GET | `/qhse/vale/validar` *(prefijo)* | Validación de vale QHSE por QR |
| GET | `/gafete-verificar` | Verificación de gafete de empleado |
| GET | `/rrhh/tarjetas-deudor/validar-cargo` | Validación de cargo por QR |
| POST | `/api/comunicaciones/webhook/openwa` | Webhook OpenWA — **HMAC** |
| POST | `/api/facturacion/eventos-atlas` | Eventos de dominio ATLAS — **HMAC** |

---

## 3. Módulo Guías (`app/modules/guias/`)

### 3.1 Consulta

| Método | Ruta | Controlador | Permiso |
|---|---|---|---|
| GET | `/api/guias` | `GuiasController::listar` | `guias.ver` |
| GET | `/api/guias/detalle` | `GuiasController::detalle` | `guias.ver` |
| GET | `/api/guia` | `GuiasController::obtener` | `guias.ver` |
| GET | `/api/guias/estados` | — | `guias.ver` |
| GET | `/api/guias/kpis` | — | `guias.ver` |
| GET | `/api/guias/exportar` | — | `guias.ver` |
| GET | `/api/guias/carta-porte` | — | `guias.ver` |
| GET | `/api/guias/carta-porte/xml` | — | `guias.ver` |
| GET | `/guias` | vista listado | `guias.ver` |
| GET | `/guias/form` | vista formulario | `guias.operar` |
| GET | `/guia-print`, `/api/guia-print` | `GuiasPrintController::vista/imprimir` | `guias.ver` |

`/api/guias` acepta filtros por query string y consolida estados de ATLAS en lote
(`listarFoliosPorEstadosEnLote` con `curl_multi`) para no degradar el listado.

### 3.2 Contexto de empresa

| Método | Ruta | Efecto |
|---|---|---|
| GET | `/api/guias/empresa` | Devuelve empresa activa (`FORSIS`/`GERO`) |
| POST | `/api/guias/empresa` | Conmuta la empresa en sesión |

⚠️ Cambia la **conexión de BD** de todas las consultas posteriores. Toda acción debe fijar empresa
primero.

### 3.3 Liberación SICRET → ATLAS

| Método | Ruta | Controlador | Permiso |
|---|---|---|---|
| POST | `/api/guias/liberacion/validar` | `LiberacionGuiaController::validarSeleccion` | `puedeOperarGuias()` |
| POST | `/api/guias/liberacion/solicitar` | `LiberacionGuiaController::solicitar` | `puedeOperarGuias()` |

**Validar selección** — revalida estatus vigente en BD:
```json
POST /api/guias/liberacion/validar
{"guias": ["12345", "12346"]}

→ {"ok": true, "data": { /* GuiasModel::validarBloqueoPorFolios() */ }}
```

**Solicitar liberación**:
```json
POST /api/guias/liberacion/solicitar
{"motivo": "Corrección de cliente receptor",
 "guias": [{"num_guia": "12345"}, {"num_guia": "12346"}]}
```
Validación: `motivo` no vacío **y** al menos una guía, si no `400`.
Efectos: `GuiaOriginPolicyService::registrarAccionSiLegado()` por folio →
`SolicitudLiberacionService` → `AtlasClient::solicitarLiberacion()` →
`POST http://host.docker.internal:8097/api/solicitudes-liberacion.php`.
Resultado: solicitud **`EN_TRANSITO`** en ATLAS. **Asíncrono** — no devuelve el desenlace.

### 3.4 Timbrado

| Método | Ruta | Controlador |
|---|---|---|
| POST | `/api/guias/timbrado/validar` | `TimbradoGuiaController::validarSeleccion` |
| POST | `/api/guias/timbrado/solicitar` | `TimbradoGuiaController::solicitar` |

Mismo contrato que liberación; va a `/api/solicitudes-timbrado.php` en ATLAS.

### 3.5 Creación y edición

| Método | Ruta | Controlador |
|---|---|---|
| POST | `/api/guias/crear` | `CrearGuiaController::guardar` |
| POST | `/api/guias/editar` | `CrearGuiaController::editar` |
| GET | `/api/guias/crear/clientes` | `buscarClientes` |
| GET | `/api/guias/crear/ubicaciones` | `buscarUbicaciones` |
| GET | `/api/guias/crear/productos-sat` | `buscarProductosSAT` |
| GET | `/api/guias/crear/unidades-sat` | `buscarUnidadesSAT` |
| GET | `/api/guias/crear/stcc` | `buscarSTCC` |
| GET | `/api/guias/crear/mat-peligroso` | `buscarMatPeligroso` |
| GET | `/api/guias/crear/embalaje` | `buscarEmbalaje` |

⚠️ `editar` sólo procede si `GuiaBloqueoService::puedeEditarse($estatus)` → estatus **`Por Timbrar`**.

### 3.6 Copiar guía

| Método | Ruta | Controlador |
|---|---|---|
| GET | `/api/guias/copiar` | `CopiarGuiaController::obtener` |
| GET | `/api/copiar-guia/operadores` | `buscarOperadores` |
| GET | `/api/copiar-guia/tractos` | `buscarTractos` |
| GET | `/api/copiar-guia/remolques` | `buscarRemolques` |
| POST | `/api/guias/copiar/guardar` | `guardar` |

### 3.7 Sellos / precinto

| Método | Ruta | Controlador |
|---|---|---|
| GET | `/api/guias/sellos` | `EditarSellosController::obtener` |
| POST | `/api/guias/sellos/actualizar` | `EditarSellosController::actualizar` |

⚠️ Sólo guías en **`Asignada Al Operador`** (`puedeEditarSellos()`).

### 3.8 Movimiento de ingreso

| Método | Ruta | Controlador |
|---|---|---|
| POST | `/api/guias/movimiento-ingreso/crear` | `GuiaMovimientoIngresoController::crear` |
| GET | `/guia-movimiento-ingreso-print` | `vistaImpresion` |

⚠️ Excluye guías con estatus `CANCELADA*` o vacío (`puedeGenerarGuiaIngreso()`).
La carga de la guía original reutiliza `/api/guias/detalle`.

---

## 4. Pases de descarga (TPT) — `app/modules/facturacion/`

| Método | Ruta | Controlador | Permiso |
|---|---|---|---|
| GET | `/api/facturacion/guias/pase-descarga` | `GuiaPaseDescargaController::consultar` | `puedeConsultarPaseDescarga()` |
| GET | `/api/facturacion/guias/pase-descarga/descargar` | `GuiaPaseDescargaController::descargar` | `puedeConsultarPaseDescarga()` |

Autorizados: **Facturación, Súper Usuario y Tráfico**.

**Consultar**
```
GET /api/facturacion/guias/pase-descarga?num_guia=12345

200 → {"success": true, "disponible": true,
       "pase": {"id":…, "empresa":"FORSIS", "num_guia":"12345",
                "folio_pase":…, "contenedor":…, "fecha_cita":…,
                "archivo_original":…, "mime_type":"application/pdf",
                "tamanio":…, "hash_sha256":…, "origen":"correo",
                "remitente_correo":…, "usuario_carga":"SISTEMA",
                "fecha_carga":…, "activo":1}}
200 → {"success": true, "disponible": false, "pase": null}
403 → {"success": false, "error": "No tienes permiso para consultar pases de descarga."}
400 → {"success": false, "error": "Falta el folio de la guía."}
```
Fuente: `GuiaPaseDescargaModel::obtenerActivo(CompanyContext::actual(), $numGuia)` — sólo `activo=1`.

**Descargar** — devuelve el binario, **no JSON**:
- `403` texto plano sin permiso · `400` sin folio · `404` sin pase o archivo ausente.
- `GuiaPaseDescargaStorageService::resolverRutaFisica()` lanza si el fichero no existe → `404`
  *"El archivo del pase de descarga no está disponible en el servidor."*
- MIME restringido a **allowlist** `application/pdf | image/jpeg | image/png`; cualquier otro valor
  se fuerza a `application/pdf`. Extensión derivada del MIME, no del nombre.
- Nombre de descarga saneado: se eliminan `"`, `\r`, `\n` de `archivo_original`.

**Ingesta automática**: worker `correo-pases-cron` → `bin/correo-pases-watcher-cli.php` cada **60 s**,
IMAP `mail.forsis.com.mx:993` (SSL), buzón `INBOX`, filtro de asunto **`Tuxpan Ops`**.
Idempotente por `hash_sha256`. Sale con estado `skipped` si faltan credenciales.
`origen` distingue `correo` (automático) de `manual`.

---

## 5. Guías de soporte

| Método | Ruta | Permiso |
|---|---|---|
| GET | `/api/facturacion/guias/soporte` | `facturacion.guias_soporte.upload` |
| GET | `/api/facturacion/guias/soporte/descargar` | idem |
| POST | `/api/facturacion/guias/soporte/subir` | idem |

---

## 6. Facturación / CFDI (82 rutas)

### 6.1 Panel, avisos y CFDI emitidos

| Método | Ruta | Permiso |
|---|---|---|
| GET | `/api/facturacion/panel` | `modulo.facturacion.acceso` |
| GET | `/api/facturacion/avisos` | idem |
| POST | `/api/facturacion/avisos/atender` | idem |
| GET | `/api/facturacion/cfdi-emitidos` | `facturacion.cfdi.consultar` |
| GET | `/api/facturacion/cfdi-emitidos/detalle` | idem |
| GET | `/api/facturacion/cfdi-emitidos/pdf` | idem |
| GET | `/api/facturacion/cfdi-emitidos/xml` | idem |
| GET | `/api/facturacion/rechazos-pendientes` | idem |
| POST | `/api/facturacion/rechazos-pendientes/descartar` | idem |

### 6.2 Emisión

| Método | Ruta | Nota |
|---|---|---|
| GET | `/api/facturacion/factura-normal/guias-disponibles` | Candidatas |
| POST | `/api/facturacion/factura-normal/emitir` | **Timbra CFDI (irreversible)** |
| GET | `/api/facturacion/carta-porte-manual/guias-disponibles` | — |
| POST | `/api/facturacion/carta-porte-manual/emitir` | **Timbra Carta Porte** |
| POST | `/api/facturacion/factura/cancelar` | Cancelación ante SAT |
| POST | `/api/facturacion/nota-credito/emitir` | — |
| GET | `/api/facturacion/nota-credito/buscar-factura` | — |
| GET | `/api/facturacion/pago/facturas-disponibles` | — |
| POST | `/api/facturacion/pago/emitir` | Complemento de pago |
| POST | `/api/facturacion/pago/cancelar` | — |
| POST | `/api/facturacion/pago/importar-excel` | Carga masiva |

### 6.3 Motor de timbrado

| Método | Ruta |
|---|---|
| GET | `/api/facturacion/timbrado/captura` |
| POST | `/api/facturacion/timbrado/captura/guardar` |
| POST | `/api/facturacion/timbrado/captura/emitir` |
| POST | `/api/facturacion/timbrado/emitir` |

Persistencia: `trafico.timbrado_captura` (borrador) → `trafico.timbrado_emision`
(`estado EN_TRANSITO|CONCLUIDO|FALLIDO`, `uuid`, `idccp`, `xml_path`, `pdf_path`, `reintento_de`).
Vigilado por `motor-watcher`.

### 6.4 Clientes, conceptos, cotizaciones

- Clientes (8): `clientes`, `/crear`, `/actualizar`, `/detalle`, `/estatus`, `/catalogos`,
  `/extraer-constancia` *(OCR de Constancia de Situación Fiscal)*
- Conceptos (5): `conceptos`, `/crear`, `/actualizar`, `/eliminar`, `/duplicados`
- Cotizaciones (20): `cotizaciones`, `/crear`, `/actualizar`, `/detalle`, `/duplicar`, `/enviar`,
  `/enviar-correo`, `/revisar`, `/aceptar`, `/rechazar`, `/cancelar`, `/convertir`,
  `/pdf/generar`, `/pdf/descargar`, `/origenes`, `/destinos`, `/terminos-catalogo`(+4)

### 6.5 Refacturación y reportes

| Método | Ruta |
|---|---|
| GET | `/api/facturacion/refacturacion/buscar-por-guia` |
| GET | `/api/facturacion/refacturacion/buscar-manual` |
| GET | `/api/facturacion/reportes/guias-liberadas` → ATLAS `/api/reportes/guias-liberadas.php` |
| GET | `/api/facturacion/reportes/guias-refacturadas` |
| GET | `/api/facturacion/reportes/solicitudes` (+`/detalle`, `/exportar`) |
| GET | `/api/facturacion/aging/*` | `facturacion.aging.ver` / `.exportar` |

### 6.6 Tarjetas deudor (cliente) — 13 rutas

`tarjetas-deudor`, `/crear`, `/detalle`, `/movimientos`, `/cargo`, `/abono`, `/cancelar`,
`/cargos-pendientes`, `/clientes-disponibles`,
`/reportes/saldos`, `/reportes/acumulado`, `/reportes/cuentas-por-cobrar`(+`/exportar`)

---

## 7. Planeación (32 rutas)

**Despachos**: `/api/planeacion/despacho`, `/despacho-detalle`, `/despachos/batch-crear`,
`/despachos/batch-pegar`, `/batch-accion`, `/sustitucion`, `/evento`, `/resumen-jornada`,
`/tramo-quick-edit`, `/complementar-tramo`, `/copiar-plantilla`, `/buscar-catalogo`,
`/buscar-carta-porte`

**Sellos** (13): `/sellos/stock`, `/disponibles`, `/asignados`, `/asignados-guias`, `/asignar`,
`/cambiar-estado`, `/registrar-lote`, `/clientes-disponibles`, `/resumen-kpis`, `/exportar-xlsx`,
`/control-sellos`

**Contenedores**: `/contenedores/disponibles`, `/clientes`, `/guias`, `/resumen`

**Peajes**: `/api/peajes/guardar`, `/detalle`, `/eliminar`, `/api/planeacion/peaje-desglose`

**Reportes**: `/reporte-operativo`, `/reporte-samsung`

---

## 8. Otros módulos (resumen por volumen)

| Módulo | Rutas | Superficies principales |
|---|---|---|
| **RRHH** | **119** | `personal/*` (empleados, operadores, gafete, foto), `nomina/*`, `finiquitos/*` (simular, autorizar, pagar, regenerar), `aguinaldos/*`, `vacaciones/*`, `prestamos/*`, `tarjetas-deudor/*` (17), `deducciones-programadas/*` (9), `expediente/*`, `desarrollo/*`, `catalogos/*` (14), `incidencias`, `auditoria`, `dashboard`, `recibos-nomina/*`, `integraciones/{liquidaciones,qhse,inventario-ti}` |
| **Proveedores** | **63** | `facturas/*` (14, incl. `analizar-xml`, `validar`, `workflow`), `pagos/*` (10), `proveedores/*` (8), `documentos/*`, `dashboard/*` (8), `cuentas-bancarias/*`, `estado-cuenta/*`, `aprobaciones/{aprobar,rechazar}`, `programacion-pagos/*`, `action-center`, `exceptions`, `lifecycle`, `bitacora`; impresión: cheque, póliza, transferencia, estado-cuenta, resumen-cxp |
| **Unidades** | **29** | CRUD `tractos`/`remolques`/`dollys`/`utilitarios` (listar, crear, actualizar, actualizar-completo), `documento/*` (crear, renovar, archivo subir/eliminar), `catalogos`, `historial` |
| **Reseteo** | **27** | `events/*` (analyze, reprocess, review, analysis), `anomalies/*`, `cases/*` (assign, resolve, close, reopen, notes, evidence), `unit-aliases/*`, `timestamp-quality/*`, `units/{search,analyze}`, `run-ingestion`, `timeline` |
| **Usuarios** | **20** | `usuarios`, `/detalle`, `/editar`, `/deshabilitar`, `/restablecer`, `/cambiar-password`, `forsis/{habilitar,deshabilitar}`, `sicret/{habilitar,deshabilitar}`, `sesiones/revocar`, `roles*` (6), `roles-nativos`, `empleados/{buscar,sugerir-gero}` — permiso `usuarios.administrar` |
| **QHSE** | **18** | `entregas*`, `equipos*`, `categorias`, `conteos`, `tipos-movimiento`, `revision*`, `historial/{persona,unidad}`, `personas/buscar`, `unidades/buscar`, `vale-print`, `vale/validar` — permiso `qhse.acceso` |
| **Integraciones** | **15** | `whatsapp/*` (10: cuentas, crear, eliminar, qr, sincronizar, estado, desconectar, cerrar-sesion, probar), `spotify/*` (5), `estado` |
| **Comunicaciones** | **14** | `conversaciones`, `conversacion/{asignar,vincular,candidatos}`, `mensajes/{enviar-texto,enviar-media,reintentar}`, `adjunto*`, `sincronizar`, `sync-estado`, `ws-token`, `webhook/openwa` |
| **Ubicaciones** | **11** | `origenes*`, `destinos*` (crear/actualizar/detalle), `domicilio`, `resolver-maps`, `extraer-constancia` |
| **Perfil** | **5** | `preferencias`, `correo`, `foto`, `cambiar-password` |
| **Diesel shortages** | **5** | `diesel-shortages`, `/detail`, `/reset-events`(+`/detail`) — `diesel_shortages.ver/.escribir` |
| **Control** | **6** | `overview`, `activity`, `sessions`, `pipelines`, `users/force-logout`, `users/toggle-access` — **auth propia** (`protegerControlApi`, 401) |
| **Monitoreo** | **3** | `tablero`, `guardar-checkpoint`, `exportar` |

Rutas de vista sueltas: `/`, `/home`, `/dashboard`, `/reportes`, `/monitoreo-diario`,
`/buscar-viajes`, `/api/viajes`, `/guardar-operacion`.

---

## 9. API saliente: ATLAS

| Método `AtlasClient` | Endpoint ATLAS | Verbo |
|---|---|---|
| `solicitarLiberacion()` | `/api/solicitudes-liberacion.php` | POST |
| `obtenerSolicitudLiberacion(id)` | idem | GET/POST |
| `responderLiberacion(id, accion, actor, motivo)` | idem | PATCH |
| `solicitarTimbrado()` | `/api/solicitudes-timbrado.php` | POST |
| `obtenerSolicitudTimbrado(id)` | idem | POST |
| `responderTimbrado(id, accion, actor, motivo)` | idem | PATCH |
| `consultarEstadosLiberacion(numGuias[])` | `/api/facturacion-solicitudes.php` | GET |
| `listarFoliosLiberacionPorEstado(estado, perPage=1000)` | idem | GET |
| `consultarEstadosTimbrado(numGuias[])` | `/api/facturacion-solicitudes-timbrado.php` | GET |
| `listarFoliosTimbradoPorEstado(estado, perPage=1000)` | idem | GET |
| `descargarCartaPorte(numGuia)` | `/api/timbrado-carta-porte.php` | GET |
| `reporteGuiasLiberadas(filtros)` | `/api/reportes/guias-liberadas.php` | GET |
| `kpisFacturacion()` | `/api/facturacion-kpis.php` | GET |
| `historialGuia(numGuia)` | `/api/guia-historial.php` | GET |
| `listarFoliosPorEstadosEnLote(solicitudes[])` | mixto | GET paralelo (`curl_multi`) |
| `listarSolicitudesReporteEnLote(filtros)` | mixto | GET paralelo |

Transporte: cURL, `Accept: application/json`, timeout 5 s / connect 3 s, **sin credenciales**.
Base: `http://host.docker.internal:8097` (`app/config/atlas.php`).

---

## 10. Superficies sin HTTP (CLI)

Alternativa a la API para automatización local: `docker compose exec php php bin/<script>.php`.
~40 scripts en `app/bin/`, todos **idempotentes y de una sola pasada**.

| Script | Función |
|---|---|
| `correo-pases-watcher-cli.php` | Ingesta IMAP de pases de descarga |
| `rh-nomina-watcher-cli.php` | Ingesta IMAP de recibos de nómina |
| `motor-timbrado-watcher.php` | Vigilancia del motor de timbrado |
| `sicret-guide-cleanup-cli.php` | Limpieza de guías SICRET |
| `reseteo-ingestion-cli.php` | Ingesta de eventos de reseteo |
| `comunicaciones-{sync,adjuntos}-cli.php` | Sincronización WhatsApp |
| `scheduled-deductions-run-cli.php` | Deducciones programadas |
| `roles-permisos-seed.php` | Seed del RBAC |
| `backfill-guia-origen.php`, `backfill-ccp-pdf.php` | Backfills |
| `*-migrate.php` (9) | Migraciones por módulo |
| `reconciliar-pago-uuids.php` | Reconciliación de UUIDs de pago |

---

## 11. Notas para integración del agente IA

1. **Sin API key**: la única autenticación para humanos/bots es la cookie de sesión. Un agente debe
   hacer `POST /login` con un usuario de servicio y conservar la cookie (vida: 8 h inactividad /
   12 h absoluta), renovando con `GET /api/sesion/heartbeat`.
2. **No hay versionado de API** ni OpenAPI/Swagger. Los contratos sólo están en el código.
3. **Dos convenciones de respuesta** (`ok`/`data` vs `success`) — normalizar en el cliente.
4. **Fijar empresa antes de operar** (`POST /api/guias/empresa`): determina la BD destino.
5. **Endpoints irreversibles** — exigir confirmación humana:
   `facturacion/*/emitir`, `factura/cancelar`, `pago/emitir|cancelar`, `nota-credito/emitir`,
   `timbrado/*/emitir`, `rrhh/{nomina,finiquitos,aguinaldos}/{autorizar,pagar}`,
   `proveedores/pagos/{aplicar,crear-lote}`, `control/users/force-logout`.
6. **Liberación y timbrado son asíncronos**: tras `solicitar`, consultar
   `/api/facturacion/reportes/solicitudes` o esperar el evento de ATLAS.
7. **Revalidar siempre antes de enviar**: `POST /api/guias/liberacion/validar` (o `timbrado/validar`).
8. **Considerar `/api/control/*`** como plantilla para una superficie de agente con autenticación
   propia, desacoplada de la sesión de navegador.
