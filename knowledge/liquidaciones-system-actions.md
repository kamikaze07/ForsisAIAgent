# liquidaciones-system — Acciones Ejecutables por el Agente IA

**Fecha:** 2026-10-03 · **Fase:** 0 (reconocimiento)
**Alcance:** catálogo de acciones derivadas de los 54 endpoints, clasificadas por
nivel de riesgo, con los contratos exactos verificados en el código.

---

## 0. Resumen ejecutivo

| Nivel | Definición | Acciones |
|---|---|---|
| 🟢 **L0 — Lectura segura** | Sin efecto lateral, reintentable | 26 |
| 🟡 **L1 — Lectura con inferencia** | Lee pero requiere criterio del agente | 9 |
| 🟠 **L2 — Escritura reversible** | Se puede corregir sin remediation | 10 |
| 🔴 **L3 — Escritura irreversible** | Sin reversa vía API, efecto cascada | 9 |

> **Política recomendada:** el agente ejecuta L0 y L1 libremente; L2 con doble
> validación; **L3 solo generando solicitudes de aprobación en SQLite, nunca
> ejecutando la acción final.**

---

## 1. Preflight — obligatorio antes de cualquier sesión

| # | Paso | Endpoint | Fallo |
|---|---|---|---|
| 1 | Login | `POST /api/login.php` | sin sesión no hay nada |
| 2 | **Fijar empresa explícitamente** | `POST /api/set_empresa.php` `{"empresa":"forsis"\|"gero"}` | ⚠️ default silencioso = `forsis` |
| 3 | Verificar rol efectivo | inspeccionar `$_SESSION['priv']` vía UI de permisos | rol inesperado → abortar |
| 4 | Confirmar vida de sesión | 8 h desde login | re-login en procesos largos |

> **El paso 2 es el guardarraíl más importante.** `ConnectionManager` resuelve una
> empresa inválida a `forsis` sin error. Un agente que olvide fijarla opera sobre
> la base equivocada sin ningún síntoma visible.

---

## 2. 🟢 L0 — Lectura segura (26 acciones)

### 2.1 Contexto y sesión

| Acción | Endpoint | Entrada | Devuelve |
|---|---|---|---|
| Autenticarse | `POST /api/login.php` | `username`, `password` | `{ok, redirect}` |
| Cerrar sesión | `GET /api/logout.php` | — | — |
| Cambiar empresa | `POST /api/set_empresa.php` | `empresa` | `{ok, empresa}` |
| Listar tarjetas (operadores) | `GET /api/lista_tarjetas.php` | — | catálogo con saldo |
| Buscar operador | `GET /api/buscar_operadores.php` | `nombre` | coincidencias |
| Catálogos maestros | `GET /api/catalogo_vale_diesel.php` | `tipo`, `q` | empleados / operadores / utilitarios |
| Buscar unidad | `GET /api/reportes_unidad_buscar.php` | `q` | coincidencias de `tracto` |
| Preferencias UI | `GET /api/preferencias.php` | — | tema/acento |

### 2.2 Liquidaciones

| Acción | Endpoint | Entrada | Notas |
|---|---|---|---|
| Listar liquidaciones | `GET /api/liquidaciones.php` | `page`, `length`, `search`, `estatus`, `order_col`, `order_dir` | DataTables server-side |
| Detalle de liquidación | `GET /api/liquidacion_detalle.php` | `folio` | árbol completo: viajes, gastos, premios, TD, vales |
| Precarga de operador | `GET /api/nueva_liquidacion_operador.php` | `tarjeta` | viajes/vales pendientes + saldo TD |
| Última unidad liquidada | `GET /api/ultima_unidad.php` | `tarjeta_id` | — |
| Reporte por operador | `GET /api/reportes_operador_listado.php` | `desde`, `hasta`, `page`, `length`, `search` | — |
| Siguiente folio | `GET /api/next_folio.php` | — | — |

### 2.3 Tarjeta deudor

| Acción | Endpoint | Entrada |
|---|---|---|
| Estado de cuenta | `GET /api/tarjeta_deudor.php` | `tarjeta`, `filter`, `page` |
| Detalle de movimiento | `GET /api/vale_gasto.php` | `mov` |

### 2.4 Caja chica

| Acción | Endpoint | Entrada |
|---|---|---|
| Listar vales | `GET /api/caja_chica.php` | `page`, `length`, `search`, `estatus` |
| Detalle de vale | `GET /api/caja_chica_detalle.php` | `folio` (incluye `es_cancelable`, `titular`) |

### 2.5 Diésel

| Acción | Endpoint | Entrada |
|---|---|---|
| Listar vales diésel | `GET /api/vales_diesel.php` | `page`, `length` |
| Detalle de vale | `GET /api/vale_diesel_detalle.php` | `folio` |

### 2.6 Guías y recepción

| Acción | Endpoint | Entrada |
|---|---|---|
| Listar guías | `GET /api/guias_listado.php` | `draw`, `page`, `length`, `search`, `fecha_inicio`, `fecha_fin` |
| Detalle de guía | `GET /api/guias_detalle.php` | `num_guia` |
| Guías pendientes por operador | `GET /api/guias_pendientes_operador.php` | `num_ope` |
| Listar recepciones | `GET /api/guias_recepciones.php` | `draw`, `page`, `length`, `search`, `fecha_inicio`, `fecha_fin` |
| Buscar/consultar en recepción | `GET /api/buscar_guia_recepcion.php` | `action` ∈ `buscar_guia`\|`catalogos`\|`check_folio_imp`\|`ultima_tarifa` |
| Buscar viaje | `GET /api/buscar_viaje.php` | `q` |

### 2.7 Workflow e impresión

| Acción | Endpoint | Entrada |
|---|---|---|
| Listar solicitudes pendientes | `POST /api/solicitud_cancelacion.php?action=listar_pendientes` | — |
| Contar pendientes | `POST /api/solicitud_cancelacion.php?action=conteo_pendientes` | — |
| Descargar PDF de reseteo | `GET /api/reportes_reseteo_archivo.php` | `id` |

---

## 3. 🟡 L1 — Lectura con inferencia (9 acciones)

Estas acciones **no escriben**, pero el agente debe aplicar criterio explícito.

| # | Acción | Endpoint | Criterio requerido |
|---|---|---|---|
| L1-1 | Clasificar concepto como BONO o COBRO | `GET /api/liquidacion_detalle.php` | **Por tabla de origen:** `premiosliq` = BONO, `gastosliq` = COBRO. **Nunca por el texto** |
| L1-2 | Clasificar cancelado | cualquier listado de estados | `LIKE 'CANCELADO%'` o `stripos(...,'Cancelad')` — hay `<Cancelada>` y `<Cancelado>` y 112+ variantes de texto libre en `vales_diesel` |
| L1-3 | Calcular saldo real del operador | `GET /api/tarjeta_deudor.php` | `SUM(importeRestante)` sobre `tarjeta_contenido`. **Nunca** `tarjeta_deudor.saldo` (denormalizado) |
| L1-4 | Detectar.xml de importes malformados | detalle de liquidación | normalizar `(float)str_replace(['$',','],'',$v)` — importes conviven como varchar/double/`*Letra` |
| L1-5 | Evaluar sensibilidad de viaje | `GET /api/liquidacion_detalle.php` | revisar `detliq.kmlt` (km/litro precalculado) y `manual` (tinyint: captura manual vs importada) |
| L1-6 | Validar pendiente de aprobación | `?action=listar_pendientes` | tripleta `(empresa, modulo, referencia_id)` sin `PENDIENTE` duplicada |
| L1-7 | Clasificar reseteo pendiente | `GET /api/reportes_reseteo_listado.php` | `estado = BORRADOR` **o** `requiere_revision = 1` → no usar para reportes |
| L1-8 | Verificar rol/visibilidad efectiva | endpoint con `admin-check` | admin global ve todo; grupo operativo (3 usuarios hardcodeados) ve 3 usuarios; resto solo lo propio |
| L1-9 | Confirmar empresa activa | `GET /api/listar_tarjetas.php` + contexto | si el catálogo no corresponde a la empresa esperada → abortar |

---

## 4. 🟠 L2 — Escritura reversible o de bajo impacto (10 acciones)

| # | Acción | Endpoint | Reversa disponible | Precauciones |
|---|---|---|---|---|
| L2-1 | **Crear solicitud de cancelación/edición** | `POST /api/solicitud_cancelacion.php?action=crear` | `?action=rechazar` con motivo | ✅ **Acción preferida del agente.** No toca MySQL; solo escribe `PENDIENTE` en SQLite |
| L2-2 | Actualizar datos de reseteo | `POST /api/reportes_reseteo_actualizar.php` | re-editar | Confirmar contra el PDF original; emite WebSocket |
| L2-3 | Eliminar registro de reseteo | `POST /api/reportes_reseteo_eliminar.php` | ⚠️ **no recuperable** | Verificar `estado` y que no esté en reporte publicado |
| L2-4 | Descargar PDF de reseteo | `GET /api/reportes_reseteo_archivo.php` | n/a | — |
| L2-5 | Guardar recepción de guía | `POST /api/guardar_recepcion_guia.php` | re-edición | `folio_imp` es único lógico: colisión lanza excepción. `tipo` default `SENCILLO`, `completa` default 1 |
| L2-6 | Guardar documento de recepción | `POST /api/recepcion_documentos.php?action=guardar` | re-edición | Aplica visibilidad por `usuario_recibe`/`usuario_entrega`; bitácora centralizada en FORSIS |
| L2-7 | Cambiar estatus de recepción | `POST /api/recepcion_documentos.php?action=cambiar_estatus` | ⚠️ irreversible el avance | Admin-check |
| L2-8 | Buscar guías para recepción | `POST /api/recepcion_documentos.php?action=buscar_guias` | n/a (lectura) | Multi-empresa: itera `ConnectionManager::listar()` |
| L2-9 | Guardar categoría de premio | `POST /api/reportes_premios_categorias.php` | re-upsert | `id` null = crear; `patron` es UNIQUE |
| L2-10 | Listar categorías de premio | `GET /api/reportes_premios_categorias.php` | n/a | — |

> **L2-1 es la pieza central del diseño de seguridad del agente.** El sistema ya
> tiene un workflow de aprobación con tabla de solicitudes, análisis de módulos y
> auditoría de revisor. Reutilizarlo es más seguro que inventar un gate propio.

---

## 5. 🔴 L3 — Escritura irreversible (9 acciones)

> ⛔ **El agente NO debe ejecutar estas directamente en producción.**
> Debe generar la solicitud correspondiente y escalar a un humano.

| # | Acción | Endpoint | Cascada de efectos | Reversa |
|---|---|---|---|---|
| L3-1 | **Autorizar liquidación** | `POST /api/autorizar_liquidacion.php` `{"folio":"LQ-xxxxx"}` | Cambia estatus; aplica abono FIFO sobre `tarjeta_contenido`; marca `<Pagado:fecha>`/`<Abono:$X>`; recalcula `tarjeta_deudor.saldo` | ❌ **ninguna** |
| L3-2 | **Crear/editar liquidación** | `POST /api/guardar_liquidacion.php` | 8 tablas; totales enviados por el cliente (riesgo de descuadre); `folio_liq_edit` → UPDATE destructivo | ❌ |
| L3-3 | **Cargo/abono a tarjeta deudor** | `POST /api/movimiento_tarjeta.php` | Bloquea con `FOR UPDATE`; inserta movimiento; recalcula saldo | ⚠️ solo vía cancelación |
| L3-4 | **Aprobar cancelación** | `POST /api/solicitud_cancelacion.php?action=aprobar` | Ejecuta la cancelación real en MySQL según módulo/tipo | ❌ |
| L3-5 | **Crear vale de gasto** | `POST /api/guardar_vale.php` | Vale + cargo en `tarjeta_contenido` | ⚠️ |
| L3-6 | **Reposición de caja** | `POST /api/reponer_vales.php` | Toma **TODOS** los `<Por Reponer>` del usuario de sesión; folio `PR-%05d` vía `MAX(num)+1` | ❌ |
| L3-7 | **Cancelar vale de caja** | `POST /api/vale_caja_cancelacion.php` `{"folio","motivo"}` | Anula vale y revierte cargo | ❌ |
| L3-8 | **Crear vale de diésel** | `POST /api/guardar_vale_diesel.php` | Vale + asociación de guías | ⚠️ |
| L3-9 | **Complementar vale de diésel** | `POST /api/vale_diesel_complementar.php` | Modifica vale existente y sus guías | ⚠️ |
| L3-10 | **Cancelar vale de diésel** | `POST /api/vale_diesel_cancelacion.php` `{"folio","accion"}` | Admin-check; estado queda como texto libre `CANCELADO/<motivo>` | ❌ |

---

## 6. Catálogo de contratos de escritura (c bodies exactos)

### 6.1 `guardar_liquidacion.php`

| Clave | Tipo | Regla |
|---|---|---|
| `operador` | int | id de tarjeta deudor |
| `unidad` | string | eco del tractor |
| `fecha_primer_viaje` | string | — |
| `precio_diesel` | float | — |
| `viajes[]` | array | filas `detliq` |
| `diesel[]` | array | vales de diésel asociados |
| `gastos[]` | array | filas `gastosliq` (cobros) |
| `premios[]` | array | filas `premiosliq` (bonos) |
| `gastosTD[]` | array | cargos de TD incluidos |
| `abonoTD` | float | abono aplicado a la tarjeta |
| `resumen` | object | **totales calculados por el cliente** |
| `folio_liq_edit` | string\|null | presente ⇒ modo edición |

### 6.2 `movimiento_tarjeta.php`

```json
{"tipo":"cargo","tarjeta":123,"monto":1500.50,
 "concepto":"PRESTamo","referencia":"REF-01","observaciones":"",
 "folio":"","fechaDesde":"2026-09-01","fechaHasta":"2026-09-30","tipo_concep":1}
```

Validación: `tarjeta<=0 || monto<=0 || concepto==''` → `{ok:false}`.
`tipo_concep` solo acepta 1 o 2 (otro → 1). `tipo` debe ser `cargo` o `abono`.
Texto → MAYÚSCULAS vía `mb_strtoupper`.

### 6.3 `guardar_vale.php`

`tarjeta_id`, `concepto`, `monto`, `unidad`, `rem1`, `rem2`, `tipo_cargo`,
`tipo_concep`, `observaciones`.

### 6.4 `reponer_vales.php`

`cheque` (default `EFECTIVO`), `banco` (default `CAJA`), `fecha_cheque` (default hoy).
**No acepta lista de folios** — el alcance lo define la sesión.

### 6.5 `guardar_vale_diesel.php`

`titular_id`, `tipo`, `unidad_id`, `unidad_eco`, `concepto`, `litros`, `cantidad`,
`guias_seleccionadas`, `guia_libre`, `observacion`.

### 6.6 `vale_diesel_complementar.php`

`folio`, `num`, `tipo`, `num_emp`, `num_ope`, `eco`, `eco_letra`, `num_concep`,
`litros`, `guias`, `guias_seleccionadas`.

### 6.7 `vale_diesel_cancelacion.php`

`folio`, `accion` — admin-check.

### 6.8 `guardar_recepcion_guia.php`

Obligatorio `num_guia`. Defaults: `tipo=SENCILLO`, `completa=1`, fechas = hoy,
campos opcionales `ope_carga`, `ope_tira`, `clave1`, `clave2`, `clave_desti`,
`num_pozo`, `ticket` (sanitizado a dígitos), `folio_imp`, `manifiesto`, `km`, `do`,
`lid`, `peso`, `rsp`, `estadias`, `mov`.

### 6.9 `recepcion_documentos.php`

`action` ∈ `listar` \| `guardar` \| `cambiar_estatus` \| `buscar_guias`.

### 6.10 `reportes_reseteo_subir.php`

`multipart/form-data`, campo **`archivo`**, solo `.pdf`.

### 6.11 `reportes_reseteo_actualizar.php`

`id`, `num_tracto`, `fecha_reseteo`, `periodo_desde`, `periodo_hasta`, `km_total`,
`horas_total`, `litros_total`, `horas_ralenti`, `litros_ralenti`,
`porcentaje_ralenti`.

### 6.12 `solicitud_cancelacion.php`

| `action` | Body |
|---|---|
| `crear` | `modulo`, `referencia_id`, `folio_texto`, `monto`, `motivo` (oblig.), `tipo` |
| `aprobar` | `id` |
| `rechazar` | `id`, `motivo_rechazo` |

`modulo` ∈ `CAJA_CHICA` \| `TARJETA_DEUDOR` \| `RECEPCION_GUIAS`.
`tipo` ∈ `CANCELACION` \| `EDICION` \| `CONVERTIR_TD` \| `CONVERTIR_DIRECTO`.

---

## 7. Flujos de reconciliación ejecutables

### 7.1 Conciliación vale diésel ↔ liquidación ↔ guía

```
1. GET /api/nueva_liquidacion_operador.php?tarjeta={id}
     → viajes pendientes (guias) + vales de diésel no liquidados + saldo TD
2. GET /api/vale_diesel_detalle.php?folio={F}          → detalle del vale
3. Correlacionar por guía:  vales_diesel.folio_Liq  +  vales_diesel_guias
4. POST /api/guardar_liquidacion.php   ← 🔴 L3, requiere aprobación
```

**Puntos de control:** un vale de diésel con guías ya liquidadas en otra
liquidación = inconsistencia. Litros de vale vs `detliq.litros` vs
`liquidaciones.dieselConsum` deben cuadrar. `detliq.kmlt` (km/litro) fuera de
rango_band = anomalía.

### 7.2 Conciliación de premios y cobros

```
1. GET /api/liquidacion_detalle.php?folio={F}
     → premiosliq (BONOS, suman) y gastosliq (COBROS, restan)
2. NO confiar en el texto del concepto: la tabla manda
3. Verificar que totalLetra concuerda con el cálculo del agente
   (diesel, premios, autopistas, propinas, llantas, gastosTotal,
    gastosAsig, gastosDif, viajesForaneos → subtotal → total)
```

### 7.3 Conciliación de cuenta corriente del operador

```
1. GET /api/tarjeta_deudor.php?tarjeta={id}
2. Recalcular  SUM(importeRestante)  agrupado por tarjeta
3. Comparar contra tarjeta_deudor.saldo  → divergencia = bug de denormalización
4. Detectar cargos <Por Pagar> más antiguos que N días (aging)
5. POST /api/movimiento_tarjeta.php  ← 🔴 L3 (abono/cargo), requiere aprobación
```

### 7.4 Ciclo de cancelación (con gate humano)

```
Agente:  POST ?action=crear  {modulo, referencia_id, folio_texto, monto, motivo, tipo}
             ↓ escribe solicitudes_cancelacion(PENDIENTE) en SQLite — MySQL intacto
Humano:  GET  ?action=listar_pendientes   → revisa
         POST ?action=aprobar  {id}        → ejecuta la cancelación real en MySQL
         o POST ?action=rechazar {id, motivo_rechazo}
```

---

## 8. Reglas de negocio que el agente DEBE respetar

| # | Regla | Origen |
|---|---|---|
| R1 | `premiosliq` = BONO (suma); `gastosliq` = COBRO (descuenta). **Por tabla, no por texto** | tablas del esquema |
| R2 | Saldo real = `SUM(importeRestante)`. `tarjeta_deudor.saldo` es caché | lógica de abono FIFO |
| R3 | Los abonos saldan cargos en **orden FIFO por `mov ASC`** bajo `FOR UPDATE` | `movimiento_tarjeta.php`, `autorizar_liquidacion.php` |
| R4 | Autorizar exige `estatus === '<Por Autorizar>'`; destino `<Pagada>` si `total < -0.1` | `autorizar_liquidacion.php:38,60` |
| R5 | Importes conviven como varchar, double y `*Letra`; normalizar siempre | esquema |
| R6 | Estados son texto libre heredado; usar `LIKE`/`stripos`, nunca `=` | `vales_diesel`, `valesgastos` |
| R7 | Ralentí se detecta con `UPPER(concepto) LIKE '%RELENTI%'` (**grafía legacy**) | `reportes_ralenti_*` |
| R8 | Multi-empresa por sesión; default silencioso `forsis` | `ConnectionManager` |
| R9 | Visibilidad de datos por usuario: admin ve todo, grupo operativo ve 3, resto solo lo propio | `obtenerUsuariosVisibles()` |
| R10 | `f_creacion` de `tarjeta_deudor` = fecha; `num_ope`/`clave_emp` desambiguan al operador | esquema |
| R11 | `folio_imp` es único lógico entre guías (validado en app, no en BD) | `guardar_recepcion_guia.php` |
| R12 | Los totales de `guardar_liquidacion.php` llegan calculados del cliente → el agente debe replicar la aritmética | contrato del endpoint |

---

## 13. Hallazgos que condicionan el diseño del agente

1. **Autorizar no es reversible** y no valida rol → el agente jamás debe llamar
   `autorizar_liquidacion.php` en producción. Puede **detectar** liquidaciones en
   `<Por Autorizar>` y **priorizarlas**, que es el valor real.
2. **No hay API de reversión.** Cualquier error del agente en L3 requiere
   intervención humana con acceso a SQL.
3. **`guardar_liquidacion.php` recibe totales del cliente.** Un agente que construya
   el body sin replicar la aritmética producirá descuadres que los usuarios
   detectarán tarde.
4. **Riesgo de contaminación cruzada entre empresas.** `set_empresa.php` es un
   endpoint sin guard; un bug del agente cambia el contexto de datos de una sesión
   humana si comparte cookie jar.
5. **Un artefacto del sistema no es de este sistema:** las BD `sicrePR`/`sicreGero`
   son compartidas con `trafico-system`/ATLAS. Escrituras concurrentes sobre las
   mismas tablas pueden colisionar. Verificar si hay bloqueos antes de automatizar.

---

**Documentos relacionados:**
`liquidaciones-system-analysis.md` (arquitectura) ·
`liquidaciones-system-api-inventory.md` (54 endpoints)
