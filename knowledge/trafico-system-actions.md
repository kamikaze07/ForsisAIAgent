# trafico-system — Acciones Ejecutables desde el Agente IA

> Generado: 2026-10-03 · Alcance: qué puede hacer un agente sobre `trafico-system` con la API documentada.
> Complementa `trafico-system-api-inventory.md` (endpoints) y `trafico-system-analysis.md` (arquitectura).

---

## 0. Marco de ejecución

### 0.1 Principio rector

**El agente no escribe nunca directo en la base de datos.** Todas las acciones pasan por la capa HTTP
de la aplicación, que garantiza: validación de entrada, control de permisos, registro de auditoría
en `guia_origen`, revalidación de estado y las correctamente configuradas integraciones con ATLAS.

### 0.2 Sesión del agente

```
POST /login            → cookie trafico_session (8 h inactividad / 12 h absoluta)
GET  /api/sesion/heartbeat   → renovar antes de que expiren los 8 h
POST /api/guias/empresa      → fijar FORSIS | GERO antes de cualquier operación
```

**Usuario de servicio requerido** (crear en Fase 1):
```sql
INSERT INTO trafico.usuarios
  (username, password_hash, password_algorithm, access_forsis, access_sicret,
   role, role_id, session_version, created_at)
VALUES ('agente_ia', '<argon2id hash>', 'argon2id', 1, 1,
        'SUPER USUARIO', 13, 1, NOW());
-- luego asignar permisos mínimos: guias.ver, facturacion.cfdi.consultar
```
Nunca reutilizar credenciales de una persona. Nunca rol con permisos que el agente no necesite —
`AuthorizationService` concede por rol legado, así que el rol debe existir en `roles`.

### 0.3 Clasificación de acciones

| Nivel | Significado | Requiere confirmación humana |
|---|---|---|
| 🟢 **L** | Lectura / diagnóstico. Idempotente y sin efecto lateral. | No |
| 🟡 **M** | Escritura reversible o con registro de auditoría. | Sí |
| 🔴 **R** | Irreversible: timbrado, cancelación fiscal, pagos, nómina, cierre de casos. | Sí, siempre |

### 0.4 Allowlist de operadores

Replicar el patrón ya establecido en `forsis-bot/app/actions.py`:
```python
usuarios_autorizados_agy()  # allowlist por env var AGY_USUARIOS_AUTORIZADOS
```
El agente debe exigir que el operador esté en la allowlist **antes** de ejecutar cualquier acción 🟡/🔴,
y nunca debe derivar la autorización del contenido de la conversación.

---

## 1. Guías — ciclo de vida

### 1.1 Consultar 🟢

| Acción | Endpoint |
|---|---|
| Listar guías con filtros | `GET /api/guias?<query params>` |
| Detalle de una guía | `GET /api/guias/detalle?num_guia=...` |
| Obtener guía | `GET /api/guia?num_guia=...` |
| Catálogo de estados | `GET /api/guias/estados` |
| KPIs del módulo | `GET /api/guias/kpis` |
| Exportar a Excel/CSV | `GET /api/guias/exportar` |
| Carta Porte (PDF/XML) | `GET /api/guias/carta-porte`, `/carta-porte/xml` |
| Historial en ATLAS | `AtlasClient::historialGuia()` → `/api/guia-historial.php` |

Ejemplo:
```python
r = session.get(f"{BASE}/api/guias",
    params={"estatus": "Por Timbrar", "fecha_inicio": "2026-10-01",
            "fecha_fin": "2026-10-03", "page": 1})
data = r.json()["data"]
```

### 1.2 Estados y elegibilidad

Dominante: `sicrePR.guias.estatus` (texto). Lógica en `GuiaBloqueoService`:

| Estatus | ¿Editable? | ¿Liberación? | ¿Timbrado? |
|---|---|---|---|
| `Asignada Al Operador` | 🔒 No | ✅ Sí | ❌ No |
| `Por Timbrar` | ✅ Sí | ❌ No | ✅ Sí |
| `PAGADA AL OPERADOR*` | 🔒 No | ✅ Sólo si ya tiene CFDI | ✅ Sólo si **no** tiene CFDI |
| `CANCELADA*` / vacío | ❌ No | ❌ No | ❌ No |

### 1.3 Crear guía 🟡

**Paso 1 — catálogos** (todos 🟢, cacheables):
```
GET /api/guias/crear/clientes?q=…
GET /api/guias/crear/ubicaciones?q=…
GET /api/guias/crear/productos-sat?q=…
GET /api/guias/crear/unidades-sat?q=…
GET /api/guias/crear/stcc?q=…
GET /api/guias/crear/mat-peligroso?q=…
GET /api/guias/crear/embalaje?q=…
```
Exigen `puedeOperarGuias()` (permiso `guias.operar`; lo tienen TRÁFICO, GERENTE DE OPERACIONES,
RECURSOS HUMANOS y SUPER USUARIO).

**Paso 2 — alta**:
```json
POST /api/guias/crear
{
  "empresa": "FORSIS",
  "num_llama": "…",
  "fecha": "2026-10-03",
  "origen": "…", "destino": "…",
  "producto": "…", "clave_producto_sat": "…",
  "cantidad": 1, "unidad_medida_sat": "…", "peso": 0, "volumen": 0,
  "operador": "…", "tracto": "…", "remolque": "…", "placas": "…",
  "precio": 0, "moneda": "MXN",
  "stcc": "…", "mat_peligroso": "…", "embalaje": "…",
  "sello": "…", "pre_cinto": "…"
}
```
Efectos: `INSERT` en `sicrePR.guias` + registro en `guia_origen` (`origen_app='FORSIS'`,
`metodo='WEB'`) y en `forsis_guia_creation_registry`. Devuelve folio generado.

### 1.4 Editar guía 🟡

`POST /api/guias/editar` — **sólo si estatus == `Por Timbrar`**.
Rechazo típico: estatus `Asignada Al Operador` → error indicando que sólo se puede editar sellos.

### 1.5 Editar sellos / precinto 🟡

```
GET  /api/guias/sellos?num_guia=…
POST /api/guias/sellos/actualizar  {"num_guia":"…","sello":"…","pre_cinto":"…"}
```
⚠️ Restringido a guías `Asignada Al Operador` — es la excepción que **no** pasa por Liberación.

### 1.6 Copiar guía 🟡

```
GET  /api/guias/copiar?num_guia=…
GET  /api/copiar-guia/operadores?q=…
GET  /api/copiar-guia/tractos?q=…
GET  /api/copiar-guia/remolques?q=…
POST /api/guias/copiar/guardar
```
Genera una guía nueva heredando datos de una existente (útil para guías de traslado/cortas).

### 1.7 Generar guía/movimiento de ingreso 🟡

```
POST /api/guias/movimiento-ingreso/crear  {"num_guia":"…"}
```
Excluye `CANCELADA*`. Imprimible en `/guia-movimiento-ingreso-print`.

### 1.8 Impresión 🟢

`GET /guia-print`, `/api/guia-print`, `/guias`, `/guias/form`.

---

## 2. Liberación SICRET → ATLAS 🟡

### 2.1 Por qué es un flujo de dos pasos

`LiberacionGuiaController` **no** libera nada directamente: valida la elegibilidad contra SICRET
y delega en ATLAS, que es el sistema de control. El resultado vuelve asíncrono.

### 2.2 Paso 1 — validar selección 🟢

```json
POST /api/guias/liberacion/validar
{"guias": ["12345", "12346"]}

200 {"ok": true, "data": {"validas":[…], "invalidas":[]}}
```
⚠️ **Obligatorio antes de cada envío.** El estatus puede cambiar entre la consulta y la acción
(`validarSeleccion()` existe por eso).

### 2.3 Paso 2 — solicitar liberación 🟡

```json
POST /api/guias/liberacion/solicitar
{"motivo": "Corrección de datos del cliente receptor",
 "guias": [{"num_guia": "12345"}, {"num_guia": "12346"}]}
```
Validación mínima: `motivo` no vacío + al menos una guía.

Cadena interna:
```
LiberacionGuiaController::solicitar
  ├─ GuiasModel::validarBloqueoPorFolios($folios)   ← revalidación
  ├─ GuiaOriginPolicyService::registrarAccionSiLegado()  ← auditoría
  ├─ SolicitudLiberacionService  → crea solicitud EN_TRANSITO
  └─ AtlasClient::solicitarLiberacion()
       POST http://host.docker.internal:8097/api/solicitudes-liberacion.php
```

### 2.4 Seguimiento 🟢

```
GET /api/facturacion/reportes/solicitudes           (lista)
GET /api/facturacion/reportes/solicitudes/detalle    (una)
GET /api/facturacion/reportes/solicitudes/exportar
GET /api/facturacion/reportes/guias-liberadas        → ATLAS reporte
```
O bien consultar ATLAS: `consultarEstadosLiberacion(numGuias[])` /
`listarFoliosLiberacionPorEstado('APROBADA', perPage=1000)`.
Eventos en tiempo real por webhook `POST /api/facturacion/eventos-atlas` (HMAC).

### 2.5 Manejo de fallos de ATLAS

| Excepción `AtlasIntegrationException` | Causa |
|---|---|
| `::timeout()` | 5 s agotados |
| `::conexionFallida()` | ATLAS en `:8097` caído |
| `::porHttpStatus($code)` | ATLAS devolvió error |

⚠️ Un 5xx de ATLAS **no** implica que la solicitud no se haya creado. Revisar siempre
`/api/facturacion/reportes/solicitudes` antes de reintentar, para no duplicar.

---

## 3. Timbrado

### 3.1 Timbrado de guía 🟡

| Paso | Endpoint |
|---|---|
| Validar | `POST /api/guias/timbrado/validar` |
| Solicitar | `POST /api/guias/timbrado/solicitar` → ATLAS `/api/solicitudes-timbrado.php` |

Mismo contrato que liberación. Seguimiento con `consultarEstadosTimbrado()`.

### 3.2 Timbrado manual (motor propio) 🔴

```
GET  /api/facturacion/timbrado/captura
POST /api/facturacion/timbrado/captura/guardar    → timbrado_captura (borrador)
POST /api/facturacion/timbrado/captura/emitir     → motor
POST /api/facturacion/timbrado/emitir
```
`snapshot_json` + `yaml_sha256` + `version_snapshot` + `version_motor` permiten reconstruir
exactamente qué se envió. Estados: `EN_TRANSITO` → `CONCLUIDO` | `FALLIDO` (`motivo_fallo`,
`reintento_de`). Lo vigila `motor-watcher`.

### 3.3 Emisión fiscal directa 🔴

| Acción | Endpoint | Irreversibilidad |
|---|---|---|
| Factura normal | `POST /api/facturacion/factura-normal/emitir` | CFDI ante SAT |
| **Carta Porte** | `POST /api/facturacion/carta-porte-manual/emitir` | CFDI + IDCCP |
| Cancelar factura | `POST /api/facturacion/factura/cancelar` | Cancelación |
| Nota de crédito | `POST /api/facturacion/nota-credito/emitir` | CFDI |
| Emitir pago | `POST /api/facturacion/pago/emitir` | Complemento |
| Cancelar pago | `POST /api/facturacion/pago/cancelar` | Cancelación |

Disponibilidad de candidatas: `GET /api/facturacion/{factura-normal,carta-porte-manual}/guias-disponibles`.

⚠️ **El agente no debe ejecutar 🔴 sin confirmación humana explícita y registro de la razón.**

### 3.4 Consulta de CFDI 🟢

`/api/facturacion/cfdi-emitidos`, `/detalle`, `/pdf`, `/xml`, `/rechazos-pendientes`.

---

## 4. Pases de descarga 🟢

### 4.1 Consulta

```python
r = session.get(f"{BASE}/api/facturacion/guias/pase-descarga",
                params={"num_guia": "12345"})
j = r.json()          # {"success":…, "disponible":…, "pase":{…} | None}
```
Permiso: `puedeConsultarPaseDescarga()` → Facturación, Súper Usuario, Tráfico.

### 4.2 Descarga

```
GET /api/facturacion/guias/pase-descarga/descargar?num_guia=…
```
Devuelve el **binario**, no JSON. MIME forzado a la allowlist
`application/pdf | image/jpeg | image/png`. 404 si el registro existe pero el fichero no está.

### 4.3 Ingesta automática

```
worker: correo-pases-cron → bin/correo-pases-watcher-cli.php  (cada 60 s)
IMAP: mail.forsis.com.mx:993 SSL, buzón INBOX, filtro asunto "Tuxpan Ops"
→ INSERT trafico.guia_pases_descarga (origen='correo', usuario_carga='SISTEMA')
```
Idempotente por `hash_sha256`. `activo=0` permite reemplazo lógico sin borrar histórico.

| Campo | Uso |
|---|---|
| `folio_pase`, `contenedor`, `fecha_cita` | Datos operativos extraídos |
| `hash_sha256` | Deduplicación |
| `origen` | `correo` (automático) vs `manual` |
| `remitente_correo` | Trazabilidad del envío |
| `ruta_archivo` | Resolución física por `GuiaPaseDescargaStorageService` |

---

## 5. Planeación y operación 🟡

| Acción | Endpoint |
|---|---|
| Crear despachos (lote) | `POST /api/planeacion/despachos/batch-crear` |
| Pegar/importar | `POST /api/planeacion/despachos/batch-pegar` |
| Acción masiva | `POST /api/planeacion/despachos/batch-accion` |
| Sustitución | `POST /api/planeacion/despacho/sustitucion` |
| Registrar evento | `POST /api/planeacion/despacho/evento` |
| Editar tramo rápido | `POST /api/planeacion/despacho/tramo-quick-edit` |
| Complements de tramo | `POST /api/planeacion/despacho/complementar-tramo` |
| Copiar plantilla | `POST /api/planeacion/despacho/copiar-plantilla` |
| Asignar sellos | `POST /api/planeacion/sellos/asignar` |
| Cambiar estado de sello | `POST /api/planeacion/sellos/cambiar-estado` |
| Registrar lote de sellos | `POST /api/planeacion/sellos/registrar-lote` |
| Guardar peaje | `POST /api/peajes/guardar` |
| Eliminar peaje | `POST /api/peajes/eliminar` |
| Guardar checkpoint unidad | `POST /api/monitoreo/guardar-checkpoint` |

Lectura: `/api/planeacion/despacho`, `/despacho-detalle`, `/resumen-jornada`,
`/api/planeacion/sellos/{stock,disponibles,asignados,asignados-guias,control-sellos,resumen-kpis}`,
`/api/planeacion/contenedores/*`, `/api/planeacion/peaje-desglose`,
`/api/planeacion/reporte-operativo`, `/reporte-samsung`, `/api/viajes`, `/buscar-viajes`.

Configuraciones de viaje: `Sencillo`, `Doble`, `Triple`, `Cuadruple` (columna
`despacho.configuracion_viaje`).

---

## 6. Unidades y proveedores 🟡

**Unidades** (`puedeOperarGuias` o permiso de módulo): CRUD de `tractos`, `remolques`, `dollys`,
`utilitarios`; `documento/{crear,renovar}`; subir/eliminar archivo; historial.

**Proveedores** — Mostly 🟡, con 🔴 en pagos:
```
POST /api/proveedores/facturas/{crear,actualizar,validar,analizar-xml,workflow}
POST /api/proveedores/pagos/{crear-lote,aplicar,...}
POST /api/proveedores/aprobaciones/{aprobar,rechazar}
POST /api/proveedores/programacion-pagos/*
GET  /api/proveedores/action-center | /exceptions | /lifecycle | /bitacora
```

---

## 7. RRHH 🔴 mayoritariamente

| Dominio | Acciones | Riesgo |
|---|---|---|
| Nómina | `nomina/*`: calcular, autorizar, pagar, exportar | 🔴 |
| Finiquitos | `finiquitos/{simular,autorizar,pagar,regenerar}` | 🔴 |
| Aguinaldos | `aguinaldos/*` | 🔴 |
| Vacaciones | `vacaciones/*`: requesting, approving | 🟡 |
| Préstamos | `prestamos/*`: alta,abo,deducción | 🟡 |
| Tarjetas deudor | 17 rutas (cliente y empleado): cargo, abono, cancelar | 🔴 |
| Deducciones | `deducciones-programadas/*` (9) | 🔴 |
| Expediente | `expediente/*`: documentos, riwayat | 🟡 |
| Personal | `personal/*`: alta, baja, gafete, foto | 🟡 |

⚠️ **`pagar` en nómina, finiquitos y deducciones no es reversible.** El agente debe poder
consultar pero no disparar pagos sin un flujo de aprobación de dos pasos en Mattermost.

---

## 8. QHSE, comunicaciones, reseteo

| Módulo | Acciones | Nivel |
|---|---|---|
| **QHSE** | `entregas/*`, `equipos/*`, `revision/*`, conteos, `vale-print` | 🟢🟡 |
| **Comunicaciones** | `conversaciones/*`, `mensajes/{enviar-texto,enviar-media}`, `conversacion/{asignar,vincular}`, `adjunto/*`, `sincronizar` | 🟡 |
| **WhatsApp (integraciones)** | `whatsapp/{crear,eliminar,qr,sincronizar,estado,desconectar,probar}` | 🟡 (requiere `comunicaciones.asignar`) |
| **Reseteo** | `events/{analyze,reprocess,review}`, `cases/{assign,resolve,close,reopen,notes,evidence}`, `run-ingestion` | 🟡🟢 |

---

## 9. Administración 🔴 — sólo SUPER USUARIO

| Acción | Endpoint |
|---|---|
| Ver usuarios | `GET /api/usuarios`, `/api/usuarios/detalle` |
| Crear/editar | `POST /api/usuarios`, `/api/usuarios/editar` |
| Habilitar/deshabilitar | `POST /api/usuarios/{deshabilitar,restablecer}` |
| Acceso FORSIS/SICRET | `POST /api/usuarios/{forsis,sicret}/{habilitar,deshabilitar}` |
| Cambiar contraseña | `POST /api/usuarios/cambiar-password` |
| **Revocar sesiones** | `POST /api/usuarios/sesiones/revocar` |
| Roles | `/api/usuarios/roles*` (6), `/api/usuarios/roles-nativos` |
| Forzar logout | `POST /api/control/users/force-logout` |
| Alternar acceso | `POST /api/control/users/toggle-access` |
| Semáforos del sistema | `GET /api/control/{overview,activity,sessions,pipelines}` |

⚠️ `session_version++` mata todas las sesiones activas del usuario. No usarlo como método de
"castigo": rompe trabajo en curso de forma invisible.

---

## 10. Superficie recomendada para el agente: `/api/control/*`

Existe un precedente valuable: `Guard::protegerControlApi()` implementa autenticación **propia**
(distinta de la sesión de navegador), devolviendo 401 en vez de redirigir a login. Es la app Android
*Forsis Control*.

**Recomendación Fase 2**: replicar ese patrón para el agente —
- Token de servicio con expiración propia, no una sesión de usuario.
- Alcance acotado por *action classes* explícitas (no por "si es admin, todo").
- Auditoría dedicada (`agente_acciones`: timestamp, actor humano, acción, payload, resultado).
- Endpoint de *dry-run* que devuelve el plan sin ejecutar (imprescindible para 🔴).
- Allowlist de operadores en Mattermost como precondición.

---

## 11. Matriz de confirmación

| Acción 🟡/🔴 | Quién confirma | Cómo |
|---|---|---|
| Crear/editar/copiar guía | Supervisor de tráfico | Botón en Mattermost con resumen de campos |
| Solicitar liberación | Supervisor de tráfico | Idem, mostrando folios + motivo |
| Solicitar timbrado | Facturación | Idem |
| Emitir CFDI / Carta Porte / Nota / Pago 🔴 | **Gerente de facturación** | Doble confirmación + razón obligatoria |
| Cancelar CFDI 🔴 | **Gerente de facturación** | Doble confirmación + razón |
| Solicitar timbrado de pago (PAGADA*) | Gerente de facturación | Idem |
| Pago de nómina/finiquito/deducciones 🔴 | **RRHH + Dirección** | Aprobación en dos pasos |
| Crear/edición de usuarios, revocar sesiones 🔴 | **Admin del sistema** | Fuera del canal del bot |
| Modificación de configuración crítica | Admin | Fuera del bot |

---

## 12. Checklist de implementación Fase 1

1. Crear usuario de servicio `agente_ia` con rol y permisos mínimos.
2. Cliente HTTP con: login + reintento en `SESSION_EXPIRED` + cookie persistente + heartbeat.
3. `POST /api/guias/empresa` como primer paso de toda sesión.
4. Módulo de lectura para 🟢: KPIs, listados, detalle, estados, CFDI emitidos, pases.
5. Módulo de escritura 🟡 con wrapper obligatorio:
   ```python
   def guarded(fn, *a, **kw):
       require_allowlisted_operator()
       plan = fn(dry_run=True, *a, **kw)
       await human_confirmation(plan)
       return fn(*a, **kw)
   ```
6. **Nunca** exponer 🔴 en Fase 1.
7. Manejo de errores ATLAS: `timeout`/`conexionFallida`/`porHttpStatus`; verificar duplicados
   antes de reintentar.
8. Normalizar las dos convenciones de respuesta (`ok`/`data` vs `success`).
9. Logging de cada acción: operador, acción, payload, respuesta, duración.
10. Tests de contrato contra la instancia real para cada endpoint usado.

---

## 13. Referencias de archivo

| Acción | Archivo |
|---|---|
| Liberación | `app/modules/guias/controllers/LiberacionGuiaController.php` |
| Timbrado de guía | `app/modules/guias/controllers/TimbradoGuiaController.php` |
| Bloqueo/estados | `app/modules/guias/services/GuiaBloqueoService.php` |
| Modelo de guías | `app/modules/guias/models/GuiasModel.php` |
| Crear/editar | `app/modules/guias/controllers/CrearGuiaController.php` |
| Sellos | `app/modules/guias/controllers/EditarSellosController.php` |
| Pases descarga | `app/modules/facturacion/controllers/GuiaPaseDescargaController.php` |
| Ingesta IMAP | `app/bin/correo-pases-watcher-cli.php` |
| ATLAS | `app/integrations/atlas/AtlasClient.php` |
| Permisos | `app/Auth/CurrentUser.php` |
| Precedente auth bot | `forsis-bot/app/actions.py` (`usuarios_autorizados_agy`) |
