# liquidaciones-system — Inventario de APIs y Endpoints

**Fecha:** 2026-10-03 · **Total de endpoints:** 54 archivos PHP en `app/public/api/`
**Base URL interna (recomendada para el agente):** `http://liquidaciones-nginx:8081`
**Base URL pública:** `https://forsispr1.ddns.net:8096`

---

## 0. Cómo leer este inventario

- **No hay router.** Cada archivo `*.php` ES el endpoint:
  `/api/<archivo>.php`. No existe versionado ni prefijo `/v1`.
- **Método:** cuando la columna dice `POST`, el script rechaza explícitamente
  cualquier otro método. Cuando dice `GET`, no hay validación de método — acepta
  lo que llegue y solo lee `$_GET`.
- **Body:** los endpoints POST leen **JSON crudo**
  (`json_decode(file_get_contents('php://input'))`). Algunos caen a `$_POST` como
  fallback. `Content-Type: application/json` es lo correcto.
- **Auth:** `sesión` = incluye `includes/auth.php` (401 JSON si no hay sesión).
  `NINGUNA` = **no incluye el guard** (⚠️).
- **Rol:** `admin-check` = usa `esUsuarioAdminGlobal()` / `obtenerUsuariosVisibles()`.
  `—` = cualquier sesión autenticada pasa.
- Respuesta estándar: `{"ok": true|false, "message": "...", ...}`.
  Listados server-side DataTables: `{draw, recordsTotal, recordsFiltered, data[]}`.

---

## 1. Autenticación y sesión

| Endpoint | Método | Auth | Rol | Parámetros | Efecto |
|---|---|---|---|---|---|
| `/api/login.php` | **POST** | NINGUNA | admin-check | body: `username`, `password` | Valida MD5 contra `usuarios`; set `$_SESSION[usuario,priv,num_emp]`; devuelve `{ok, redirect}` |
| `/api/logout.php` | GET | NINGUNA | — | — | Destruye sesión (7 líneas) |
| `/api/set_empresa.php` | POST | NINGUNA | — | body: `empresa` (`forsis`\|`gero`) | **Cambia la BD activa de toda la sesión.** Único punto que modifica `$_SESSION['empresa']` |
| `/api/preferencias.php` | GET/POST | NINGUNA | — | body: `tema`, `acento`, `color_acento_personalizado` | Preferencias UI en SQLite `preferencias_usuario.sqlite` |
| `/api/perfil_foto.php` | GET | NINGUNA | admin-check | — | Sirve foto desde `/var/www/fotos_sicret` (tabla `usuarios`) |

> ⚠️ `set_empresa.php` sin guard de sesión y sin validación de rol: cambia el
> contexto de datos entre empresas. **Para el agente: llamarlo explícitamente al
> inicio de cada sesión y nunca confiar en el default.**

---

## 2. Liquidaciones (núcleo)

| Endpoint | Método | Auth | Rol | Parámetros | Tablas |
|---|---|---|---|---|---|
| `/api/liquidaciones.php` | GET | **NINGUNA** ⚠️ | — | `page`, `length`, `search`, `estatus`, `order_col`, `order_dir` | `liquidaciones`, `tarjeta_deudor` |
| `/api/liquidacion_detalle.php` | GET | **NINGUNA** ⚠️ | — | `folio` | `liquidaciones`, `detliq`, `premiosliq`, `gastosliq`, `liquidacion_td_detalle`, `tarjeta_contenido`, `tarjeta_deudor`, `vales`, `vales_diesel`, `guias` |
| `/api/nueva_liquidacion_operador.php` | GET | **NINGUNA** ⚠️ | — | `tarjeta` | Precarga viajes/vales pendientes del operador (`guias`, `llamadas_historicas`, `vales`, `vales_diesel`, `tarjeta_contenido`) |
| `/api/guardar_liquidacion.php` (843 L) | POST | sesión | — | ver §2.1 | **ESCRITURA MASIVA** en 8 tablas |
| `/api/autorizar_liquidacion.php` (320 L) | **POST** | sesión | **— ⚠️** | body: `folio` | `liquidaciones`, `tarjeta_contenido`, `tarjeta_deudor` |
| `/api/reportes_operador_listado.php` | GET | sesión | — | `desde`, `hasta`, `page`, `length`, `search` | `liquidaciones`, `tarjeta_deudor` |
| `/api/ultima_unidad.php` | GET | sesión | — | `tarjeta_id` | `liquidaciones` |
| `/api/next_folio.php` | GET | NINGUNA | — | — | Siguiente folio desde `tarjeta_contenido` |

### 2.1 `guardar_liquidacion.php` — contrato del body

El endpoint más complejo del sistema. Body JSON:

| Clave | Tipo | Descripción |
|---|---|---|
| `operador` | int | id de tarjeta deudor |
| `unidad` | string | eco del tractor |
| `fecha_primer_viaje` | string | fecha |
| `precio_diesel` | float | precio por litro |
| `viajes` | array | filas de `detliq` (origen, destino, km, litros, tons, autopistas, propinas, llantas, tipoPago…) |
| `diesel` | array | vales de diésel asociados |
| `gastos` | array | filas de `gastosliq` (cobros) |
| `premios` | array | filas de `premiosliq` (bonos) |
| `gastosTD` | array | cargos de tarjeta deudor a incluir |
| `abonoTD` | float | abono a aplicar a la tarjeta |
| `resumen` | object | totales calculados por el cliente |
| `folio_liq_edit` | string\|null | **si viene, EDITA en lugar de crear** |

Escribe en: `liquidaciones`, `detliq`, `gastosliq`, `premiosliq`,
`liquidacion_td_detalle`, `tarjeta_contenido`, `vales`, `vales_diesel`.

> ⚠️ Los totales se envían **calculados desde el cliente** (`resumen`). El agente
> debe replicar la aritmética exacta o se producen descuadres silenciosos.
> `folio_liq_edit` convierte la llamada en UPDATE destructivo.

### 2.2 `autorizar_liquidacion.php` — secuencia de 8 pasos

Body: `{"folio": "LQ-xxxxx"}`. Transacción única:

1. Lee la liquidación y **exige `estatus === '<Por Autorizar>'`** (si no, excepción).
2. Calcula `$totalLiq`; destino `<Pagada>` si `total < -0.1`, si no `<Por Pagar>`.
3. Cambia estatus de los **Gastos TD asignados a ese folio** en `tarjeta_contenido`.
4-7. Inserta movimientos de cargo/abono; aplica **abono FIFO** (`ORDER BY mov ASC`)
   marcando `<Pagado:fecha>` o `<Abono:$X.XX>`.
8. `UPDATE liquidaciones SET estatus, usuario` + recalcula `tarjeta_deudor.saldo`.

Respuesta: `{ok, nuevo_estatus, ...}`.

> 🔴 **No valida `priv`.** Cualquier sesión autenticada puede autorizar pagos.
> 🔴 **No existe endpoint inverso.** Autorizar es irreversible vía API.

---

## 3. Tarjeta deudor

| Endpoint | Método | Auth | Rol | Parámetros | Notas |
|---|---|---|---|---|---|
| `/api/tarjeta_deudor.php` | GET | **NINGUNA** ⚠️ | — | `tarjeta`, `filter`, `page` | Estado de cuenta completo |
| `/api/lista_tarjetas.php` | GET | sesión | — | — | Catálogo con saldo agregado |
| `/api/buscar_operadores.php` | GET | **NINGUNA** ⚠️ | — | `nombre` | Autocomplete sobre `tarjeta_deudor` |
| `/api/movimiento_tarjeta.php` (187 L) | **POST** | sesión | — | ver §3.1 | **Cargo o abono real** |
| `/api/vale_gasto.php` | GET | sesión | — | `mov` | Detalle de un movimiento |

### 3.1 `movimiento_tarjeta.php` — contrato

| Clave | Tipo | Obligatorio | Default |
|---|---|---|---|
| `tarjeta` | int | **sí** (>0) | — |
| `tipo` | `'cargo'` \| `'abono'` | **sí** | — |
| `monto` | float | **sí** (>0) | — |
| `concepto` | string | **sí** (no vacío) | — |
| `referencia` | string | no | `''` |
| `observaciones` | string | no | `''` |
| `folio` | string | no | `''` |
| `fechaDesde` / `fechaHasta` | date | no | hoy |
| `tipo_concep` | int | no | `1` (solo acepta 1 o 2; otro valor → 1) |

Validación: `tarjeta<=0 || monto<=0 || concepto vacío` → `{ok:false}`.

**Cargo:** `SELECT ... FOR UPDATE` sobre `tarjeta_deudor`; inserta en
`tarjeta_contenido` con `importeRestante = importe`, `estatus '<Por Pagar>'`,
`tipo = 2`; actualiza `saldo` denormalizado. Textos pasan a MAYÚSCULAS
(`mb_strtoupper`).

**Abono:** recorre cargos con `importeRestante > 0` `ORDER BY mov ASC` **(FIFO)**
bajo `FOR UPDATE`; saldado total → `<Pagado:YYYY-MM-DD>`, parcial →
`<Abono:$X.XX>`; recalcula saldo como `SUM(importeRestante)`.

> El saldo verdadero es `SUM(importeRestante)`; `tarjeta_deudor.saldo` es caché.

---

## 4. Caja chica y vales de gasto

| Endpoint | Método | Auth | Rol | Parámetros | Notas |
|---|---|---|---|---|---|
| `/api/caja_chica.php` | GET | sesión | — | `page`, `length`, `search`, `estatus` | Listado |
| `/api/caja_chica_detalle.php` | GET | sesión | — | `folio` | Devuelve además `es_cancelable`, `titular`, `solicitante_usu` |
| `/api/guardar_vale.php` (189 L) | **POST** | sesión | — | `tarjeta_id`, `concepto`, `monto`, `unidad`, `rem1`, `rem2`, `tipo_cargo`, `tipo_concep`, `observaciones` | Crea vale + cargo en `tarjeta_contenido` |
| `/api/reponer_vales.php` | **POST** | sesión | — | `cheque` (def. `EFECTIVO`), `banco` (def. `CAJA`), `fecha_cheque` (def. hoy) | **Reposición en lote** |
| `/api/vale_caja_cancelacion.php` | **POST** | sesión | — | `folio`, `motivo` | Cancela vale y revierte cargo |

### 4.1 `reponer_vales.php` — comportamiento en lote

**No recibe lista de folios.** Toma **todos** los vales
`estatus = '<Por Reponer>' AND nombre_usu = $_SESSION['usuario']` con `FOR UPDATE`,
suma el importe, genera folio `PR-%05d` (`MAX(num)+1` de `reposiciones`), inserta
la reposición con `estatus '<Repuesta>'` y marca los vales.

- Si no hay vales pendientes: `{ok:false, message:"No hay vales pendientes..."}`.
- **Alcance determinado por la sesión**, no por parámetros.

> ⚠️ Para el agente: esta llamada es **todo-o-nada sobre el usuario de la sesión**.
> Imposible reponer un subconjunto. El folio se genera con `MAX(num)+1` — hay
> riesgo de colisión bajo concurrencia.

---

## 5. Vales de diésel

| Endpoint | Método | Auth | Rol | Parámetros |
|---|---|---|---|---|
| `/api/vales_diesel.php` | GET | sesión | **admin-check** | `page`, `length` |
| `/api/vale_diesel_detalle.php` | GET | sesión | — | `folio` |
| `/api/guardar_vale_diesel.php` | **POST** | sesión | — | `titular_id`, `tipo`, `unidad_id`, `unidad_eco`, `concepto`, `litros`, `cantidad`, `guias_seleccionadas`, `guia_libre`, `observacion` |
| `/api/vale_diesel_complementar.php` | **POST** | sesión | — | `folio`, `num`, `tipo`, `num_emp`, `num_ope`, `eco`, `eco_letra`, `num_concep`, `litros`, `guias`, `guias_seleccionadas` |
| `/api/vale_diesel_cancelacion.php` | **POST** | sesión | **admin-check** | `folio`, `accion` |
| `/api/vale_diesel_preview.php` | **POST** | sesión | — | `titular`, `tipo`, `unidad`, `concepto`, `litros` |
| `/api/catalogo_vale_diesel.php` | GET | sesión | — | `tipo`, `q` → `empleados`, `operadores`, `utilitarios` |
| `/api/vales_diesel_export.php` (290 L) | GET | sesión | — | `fecha_inicio`, `fecha_fin`, `estatus`, `tipo`, `concepto`, `empresa`, `search`, `formato` |

> `vales_diesel.estado` es **texto libre concatenado** (`CANCELADO/ERROR DE DEDO`,
> `CANCELADO/NO SE USO`, …+15 variantes). Filtrar con `LIKE 'CANCELADO%'`.

---

## 6. Guías y recepción

| Endpoint | Método | Auth | Rol | Parámetros |
|---|---|---|---|---|
| `/api/guias_listado.php` | GET | sesión | — | `draw`, `page`, `length`, `search`, `fecha_inicio`, `fecha_fin` |
| `/api/guias_detalle.php` | GET | sesión | — | `num_guia` |
| `/api/guias_pendientes_operador.php` | GET | sesión | — | `num_ope` |
| `/api/guias_recepciones.php` | GET | sesión | **admin-check** | `draw`, `page`, `length`, `search`, `fecha_inicio`, `fecha_fin` |
| `/api/buscar_guia_recepcion.php` (245 L) | GET | sesión | — | `action` ∈ {`buscar_guia`, `catalogos`, `check_folio_imp`, `ultima_tarifa`} + `q`, `tipo`, `origen`, `num_pozo`, `clave_desti`, `folio_imp`, `current_guia` |
| `/api/buscar_viaje.php` | GET | sesión | — | `q` |
| `/api/guardar_recepcion_guia.php` (269 L) | **POST** | sesión | — | ver §6.1 |
| `/api/recepcion_documentos.php` (322 L) | GET/POST | sesión | **admin-check** | `action` ∈ {`listar`, `guardar`, `cambiar_estatus`, `buscar_guias`} |

### 6.1 `guardar_recepcion_guia.php` — campos

Obligatorio: `num_guia` (PR). Opcionales con default:
`tipo` (`SENCILLO`), `ope_carga`, `ope_tira`, `completa` (1), `clave1`, `clave2`,
`clave_desti`, `num_pozo`, `ticket` (sanitizado a dígitos), `folio_imp`,
`manifiesto`, `km`, `do`, `lid`, `peso`, `rsp`, `estadias`, `mov`,
`f_llegada`/`f_cargada`/`f_salida` (hoy).

Validaciones: `folio_imp` duplicado en otra guía → excepción; resuelve `clave1`
desde `ope_carga` si no viene. Usuario de sesión en MAYÚSCULAS, fallback literal
`'LIQUIDACIONES'`.

### 6.2 `recepcion_documentos.php` — multi-empresa

Su bitácora se **centraliza en FORSIS** (`db_empresa('forsis')`) pero **itera
`ConnectionManager::listar()`** para leer `recepcion` de cada empresa. Filtros:
`q`, `estatus` (`pendientes`/`aceptados`/`cancelados`), `desde`+`hasta`, `empresa`
(o `todas`). Aplica `obtenerUsuariosVisibles()` sobre `usuario_recibe`/`usuario_entrega`.
Tabla `recepcion`: `num`, `folio`, `fecha`, `usuario_entrega`, `usuario_recibe`,
`documentos`, `titulo`, `asunto`, `comentario`, `estatus`.

---

## 7. Workflow de cancelaciones (SQLite)

### `/api/solicitud_cancelacion.php` (436 L) — **POST**, auth: sesión, **admin-check**

Despacha por `?action=`:

| `action` | Body | Efecto |
|---|---|---|
| `crear` | `modulo`, `referencia_id`, `folio_texto`, `monto`, `motivo`, `tipo` | Inserta `PENDIENTE`. Rechaza duplicado `(empresa, modulo, referencia_id)` ya pendiente. `motivo` obligatorio |
| `listar_pendientes` | — | Todas las `PENDIENTE` ordenadas por `fecha_solicitud DESC` |
| `conteo_pendientes` | — | Contador para el badge de UI |
| `aprobar` | `id` | **Ejecuta la cancelación real en MySQL** |
| `rechazar` | `id`, `motivo_rechazo` | Marca rechazada |

**Módulos** (`modulo`): `CAJA_CHICA`, `TARJETA_DEUDOR`, `RECEPCION_GUIAS`.
Otro valor → `"Módulo desconocido: X"`.

**Tipos** (`tipo`): `CANCELACION` (default), `EDICION`, `CONVERTIR_TD`,
`CONVERTIR_DIRECTO`.

**Lógica de `aprobar` por módulo:**

- `CAJA_CHICA`: valida que el vale no esté ya `Cancelad*` ni `Repuest*`.
  - `CONVERTIR_TD` → convierte el gasto en cargo a tarjeta deudor
    (`estatus '<Por Pagar>'`, inserta en `tarjeta_contenido`, recalcula saldo).
  - `CONVERTIR_DIRECTO` / `CANCELACION` → `estatus '<Cancelada>'`, `monto = 0`,
    `montoletra = '$0.00'`; anula el movimiento en `tarjeta_contenido`; recalcula saldo.
- `TARJETA_DEUDOR`: valida movimiento no cancelado; mismas variantes
  `CONVERTIR_TD` / `CONVERTIR_DIRECTO` / cancelación; propaga a `valesgastos`.
- `RECEPCION_GUIAS`: soporta `EDICION` (desbloquea la guía para corrección).

Finalmente actualiza el registro SQLite con `revisado_por`, `fecha_revision`.

Si `workflow_db()` devuelve `null` (SQLite inaccesible), `listar_pendientes` y
`conteo_pendientes` degradan con respuesta vacía en lugar de error 500.

> ✅ **Este es el patrón de aprobación que el agente debe reutilizar**: el agente
> llama `crear`, un humano llama `aprobar`.

---

## 8. Reportes

| Endpoint | Método | Auth | Parámetros |
|---|---|---|---|
| `/api/reportes_premios_listado.php` | GET | sesión | `desde`, `hasta`, `tipo`, `agrupar`, `page`, `length`, `search` |
| `/api/reportes_premios_detalle.php` | GET | sesión | `desde`, `hasta`, `categoria`, `operador`, `tipo`, `agrupar` |
| `/api/reportes_premios_categorias.php` | GET/POST | sesión | **GET:** lista categorías activas. **POST:** `id` (null=crear), `categoria`, `patron`, `activo` → upsert en `reportes_categoria_premio` |
| `/api/reportes_ralenti_cobros_listado.php` | GET | sesión | `desde`, `hasta`, `tipo` (`''`\|`BONO`\|`COBRO`), `page`, `length` (max **250**), `search` |
| `/api/reportes_ralenti_detalle.php` | GET | sesión | `desde`, `hasta`, `operador`, `unidad`, `tipo` |
| `/api/reportes_unidad_buscar.php` | GET | sesión | `q` → `tracto` |

### 8.1 Regla BONO vs COBRO (documentada en el código)

```
premiosliq → BONO  (SUMA a favor del operador)
gastosliq  → COBRO (DESCUENTA en la liquidación)
```

La distinción se basa en **la tabla de origen, NO en el texto del concepto** —
`concepto` a veces dice "bono" por error de captura estando en `gastosliq`.
Los reportes de ralentí filtran `UPPER(concepto) LIKE '%RELENTI%'`
(**nótese la grafía legacy "RELENTI"**, no "RALENTI") y agrupan por
operador + unidad + tipo mediante `UNION ALL` sobre ambas tablas.

---

## 9. Reportes de reseteo (ralentí por unidad)

| Endpoint | Método | Auth | Parámetros | Notas |
|---|---|---|---|---|
| `/api/reportes_reseteo_listado.php` | GET | sesión | `desde`, `hasta`, `estado`, `page`, `length`, `search` | join con `tracto` |
| `/api/reportes_reseteo_subir.php` | **POST** | sesión | `multipart/form-data`, campo **`archivo`** (solo `.pdf`) | ver §9.1 — **emite WebSocket** |
| `/api/reportes_reseteo_actualizar.php` | **POST** | sesión | `id`, `num_tracto`, `fecha_reseteo`, `periodo_desde`, `periodo_hasta`, `km_total`, `horas_total`, `litros_total`, `horas_ralenti`, `litros_ralenti`, `porcentaje_ralenti` | Confirma/corrige borrador — **emite WebSocket** |
| `/api/reportes_reseteo_eliminar.php` | **POST** | sesión | `id` | Borra registro |
| `/api/reportes_reseteo_archivo.php` | GET | sesión | `id` | Descarga el PDF original |

### 9.1 `reportes_reseteo_subir.php` — pipeline

1. Exige POST y `$_FILES['archivo']` con extensión `.pdf`.
2. `ReseteoParser::parseFile()` → extrae unidad, motor, chasis, periodo, km,
   horas/litros totales y de ralentí.
3. `ReseteoParser::matchUnidad($pdo, unidad_raw, no_motor)` contra `tracto`.
4. Guarda el PDF en `storage/reseteos/<empresa>/<Ymd_His>_<rand>.pdf`.
5. Inserta en `reportes_reseteo` con:
   - `estado = ACTIVO` **solo si** el parser reconoció el formato **y** emparejó la unidad;
   - en cualquier otro caso `estado = BORRADOR`, `requiere_revision = 1`.
6. Notifica por WebSocket (`WebSocketNotifier`).

> Este es el **precedente de diseño** para el agente: ingesta automática con cola
> de revisión humana explícita en lugar de confianza ciega.

---

## 10. Impresión y PDF

| Endpoint | Método | Auth | Parámetros |
|---|---|---|---|
| `/api/imprimir_termico.php` | GET | sesión | `folio` o `folios` (lote) — vales de diésel |
| `/api/imprimir_termico_rsp.php` | GET | **NINGUNA** ⚠️ | `folio`, `folios`, `pdf` |
| `/api/imprimir_termico_caja.php` | GET | NINGUNA | *stub de 3 líneas* |

Páginas (no API) relacionadas: `/pdf_liquidacion.php` (Chromium headless vía
listener interno `:8081`), `/imprimir.php`, `/impresion_lote.php`,
`/imprimir_cargo.php`, `/imprimir_recepcion_documentos.php`,
`/vale_documento.php`.

---

## 11. Páginas de validación pública (QR)

Bajo `app/public/` (no `/api/`), sirven para verificar documentos impresos:
`validar.php`, `validar_caja_chica.php`, `validar_cargo_td.php`,
`validar_recepcion.php`, `validar_rsp.php`.

---

## 12. WebSocket

| Recurso | Detalle |
|---|---|
| Endpoint navegador | `wss://forsispr1.ddns.net:8096/ws/` → `proxy_pass http://liquidaciones-ws:8083/` |
| Broadcast interno | `POST http://liquidaciones-ws:8083/broadcast` |
| Autenticación broadcast | header **`X-Internal-Token`** = `WS_INTERNAL_TOKEN` (`ws/.env`) |
| Si el token está vacío | el servidor **loguea aviso y deja `/broadcast` sin protección** |
| Productor PHP | `includes/WebSocketNotifier.php` |
| Emisores actuales | `reportes_reseteo_subir.php`, `reportes_reseteo_actualizar.php` |

---

## 13. Resumen de cobertura de seguridad

### 13.1 Endpoints **sin** `require auth.php` (13)

`login.php`, `logout.php`, `set_empresa.php`, `preferencias.php`,
`perfil_foto.php`, `next_folio.php`, `buscar_operadores.php`,
**`liquidaciones.php`**, **`liquidacion_detalle.php`**,
**`nueva_liquidacion_operador.php`**, **`tarjeta_deudor.php`**,
`imprimir_termico_rsp.php`, `imprimir_termico_caja.php`.

> Los cuatro en negrita exponen información financiera completa.

### 13.2 Endpoints con chequeo de rol (7)

`login.php`, `perfil_foto.php`, `guias_recepciones.php`,
`recepcion_documentos.php`, `solicitud_cancelacion.php`,
`vale_diesel_cancelacion.php`, `vales_diesel.php`.

### 13.3 Escrituras **sin** chequeo de rol

| Endpoint | Riesgo |
|---|---|
| `autorizar_liquidacion.php` | 🔴 autoriza pagos, irreversible |
| `guardar_liquidacion.php` | 🔴 crea/edita liquidación completa |
| `movimiento_tarjeta.php` | 🔴 cargo/abono a cuenta del operador |
| `guardar_vale.php` | 🟠 crea vale + cargo |
| `reponer_vales.php` | 🟠 reposición en lote |
| `vale_caja_cancelacion.php` | 🟠 cancela vale |
| `guardar_vale_diesel.php` | 🟠 crea vale de diésel |
| `vale_diesel_complementar.php` | 🟠 modifica vale |
| `guardar_recepcion_guia.php` | 🟠 escribe guía |
| `reportes_reseteo_*.php` | 🟡 datos de reporte |
| `reportes_premios_categorias.php` | 🟡 reglas de clasificación |

---

## 14. Plantilla de invocación para el agente

```bash
BASE=http://liquidaciones-nginx:8081
JAR=/tmp/liq_session.txt

# 1) Login (mantiene cookie)
curl -s -c "$JAR" -X POST "$BASE/api/login.php" \
  -H 'Content-Type: application/json' \
  -d '{"username":"<SERVICE_USER>","password":"<REDACTED>"}'

# 2) Fijar empresa SIEMPRE y de forma explícita
curl -s -b "$JAR" -c "$JAR" -X POST "$BASE/api/set_empresa.php" \
  -H 'Content-Type: application/json' -d '{"empresa":"forsis"}'

# 3) Lectura
curl -s -b "$JAR" "$BASE/api/liquidaciones.php?page=1&length=25&estatus=%3CPor%20Autorizar%3E"
curl -s -b "$JAR" "$BASE/api/liquidacion_detalle.php?folio=LQ-00001"

# 4) Escritura segura: solicitar, NO aprobar
curl -s -b "$JAR" -X POST "$BASE/api/solicitud_cancelacion.php?action=crear" \
  -H 'Content-Type: application/json' \
  -d '{"modulo":"CAJA_CHICA","referencia_id":"123","folio_texto":"VG-00123",
       "monto":450.00,"motivo":"Detectado duplicado por el agente","tipo":"CANCELACION"}'
```

**Notas de invocación:**
- Los estatus llevan `<` `>` literales → **URL-encode** (`%3C`, `%3E`).
- `length` tope 250 en los listados de ralentí; los demás no documentan límite.
- Un 401 devuelve JSON (no redirect) si la URI contiene `/api/` → re-login y repetir.
- Sesión válida 8 h; renovar proactivamente en procesos largos.

---

**Documentos relacionados:**
`liquidaciones-system-analysis.md` (arquitectura) ·
`liquidaciones-system-actions.md` (acciones ejecutables)
