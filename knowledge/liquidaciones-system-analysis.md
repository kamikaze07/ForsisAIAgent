# liquidaciones-system — Análisis Arquitectónico

**Fecha:** 2026-10-03 · **Fase:** 0 (reconocimiento) · **Proyecto:** Forsis AI Agent
**Ruta en disco:** `/home/servidor/liquidaciones-system`
**Stack Compose:** `liquidaciones-system_default`

---

## 1. Resumen ejecutivo

`liquidaciones-system` es una **reescritura web (PHP 8 + nginx + PHP-FPM) de módulos
del ERP legacy SICRET**, orientada a la liquidación de operadores de transporte,
tarjeta deudor (cuentas por cobrar al operador), caja chica, vales de diésel,
recepción de guías y reportes de ralentí.

Características determinantes para el diseño del agente IA:

1. **No es un framework.** No hay Laravel, Symfony ni router. Son **54 scripts PHP
   sueltos bajo `app/public/api/*.php`**, cada uno un endpoint autónomo. El
   "contrato de API" es el archivo mismo. `composer.json` no declara dependencias
   productivas relevantes.
2. **No tiene base de datos propia.** Se conecta a un **MySQL/MariaDB externo en
   `192.168.1.209:3306`** (fuera de Docker) con las BD legacy `sicrePR` (FORSIS,
   136 tablas) y `sicreGero` (GERO, 124 tablas). El compose no declara contenedor
   de BD — esto corrige la suposición del `infrastructure-analysis.md` previo.
3. **Autenticación por sesión PHP con hash MD5 sin salt.** No existe API de
   tokens. Cualquier integración del agente debe **mantener cookie de sesión**.
4. **Multiempresa por sesión** (`$_SESSION['empresa']`): el mismo endpoint lee
   FORSIS o GERO según el estado de sesión. Es la fuente de error más peligrosa
   para un agente automatizado.
5. **Escritura altamente transaccional con efectos colaterales en cascada.**
   Autorizar una liquidación mueve saldos de tarjeta deudor, salda cargos por FIFO
   e inserta movimientos contables. **No existe endpoint de reversa.**

---

## 2. Stack tecnológico

| Capa | Tecnología | Detalle |
|---|---|---|
| Web server | `nginx:alpine` | contenedor `liquidaciones-nginx` |
| Runtime | PHP-FPM 8.x (`Dockerfile` propio) | contenedor `liquidaciones-php`, FastCGI `:9000` |
| Tiempo real | Node.js 22 alpine + `ws` | contenedor `liquidaciones-ws`, puerto `8083` |
| BD principal | MySQL/MariaDB **externa** | `192.168.1.209:3306` — `sicrePR`, `sicreGero` |
| BD auxiliar | **SQLite** (2 archivos) | workflow de cancelaciones + preferencias UI |
| Acceso a datos | **PDO puro**, sin ORM | prepared statements; `ConnectionManager` singleton |
| PDF | Chromium headless | `pdf_liquidacion.php` vía listener interno `:8081` |
| Parsing PDF | `ReseteoParser.php` (clase propia) | extrae ralentí de reportes de unidad |
| Frontend | PHP server-rendered + DataTables (server-side) | sin SPA, sin build step |
| Cron | loop `sh` en contenedor | ingesta de reseteos cada 180 s |

### 2.1 Contenedores y puertos

| Contenedor | Imagen | Puerto host | Puerto interno |
|---|---|---|---|
| `liquidaciones-nginx` | nginx:alpine | **8096 → 443** (TLS) | `8081` expuesto, **no publicado** |
| `liquidaciones-php` | build local | — | 9000 (FastCGI) |
| `liquidaciones-ws` | node:22-alpine | — | 8083 (WS + HTTP `/broadcast`) |
| `liquidaciones-reseteo-ingestion-cron` | build local | — | — |

- **URL pública:** `https://forsispr1.ddns.net:8096/` (cert Let's Encrypt montado
  read-only desde `/etc/letsencrypt`).
- **Listener interno `:8081`** (HTTP plano, `server_name liquidaciones-nginx`):
  misma aplicación, pensado para consumo intra-Docker. **Es la puerta de entrada
  recomendada para el agente IA** — evita TLS y es inalcanzable desde fuera.
- `location /ws/` → `proxy_pass http://liquidaciones-ws:8083/`.

### 2.2 Volúmenes montados (dependencias externas de filesystem)

| Ruta host | Ruta contenedor | Modo |
|---|---|---|
| `./app` | `/var/www/html` | rw (código en caliente, **sin build**) |
| `/etc/letsencrypt` | `/etc/letsencrypt` | ro |
| `/home/servidor/fotos_sicret@y968jh` | `/var/www/fotos_sicret` | ro |
| `/mnt/63537E674CF73DC0/nextcloud_data/data/luis01/files/Reseteo de Unidades` | `/var/www/nextcloud_luis01_reseteos` | ro |

> **Dependencia crítica no obvia:** la ingesta automática de reseteos depende de un
> **disco externo montado y de una carpeta sincronizada por Nextcloud**. Si el
> montaje `/mnt/63537E674CF73DC0` falla, el cron sigue corriendo en silencio sin
> procesar nada.

---

## 3. Arquitectura de datos

### 3.1 Tres almacenes distintos

```
┌─────────────────────────────────────────────────────────────┐
│ MySQL externo 192.168.1.209:3306   (usuario: kofuz01)       │
│   ├── sicrePR     → empresa 'forsis' (136 tablas)  DEFAULT  │
│   └── sicreGero   → empresa 'gero'   (124 tablas)           │
│   Datos de negocio legacy SICRET. Compartido con otros       │
│   sistemas (trafico-system / ATLAS) — NO es exclusivo.      │
├─────────────────────────────────────────────────────────────┤
│ SQLite  app/config/solicitudes_workflow.sqlite              │
│   └── solicitudes_cancelacion   (workflow de aprobación)    │
├─────────────────────────────────────────────────────────────┤
│ SQLite  app/config/preferencias_usuario.sqlite              │
│   └── usuario_preferencias      (tema/acento UI)            │
└─────────────────────────────────────────────────────────────┘
```

**Decisión de diseño documentada en el código:** las tablas nuevas del workflow se
pusieron en SQLite deliberadamente *"para preservar el aislamiento 100% de las BD
MySQL heredadas de SICRET"*. Consecuencia: **el estado de aprobaciones no es
consultable por SQL junto al dato de negocio** — requiere dos conexiones.

### 3.2 `ConnectionManager` (`app/config/database.php`)

- Credenciales **hardcodeadas como constantes de clase** (`HOST`, `USER`, `PASS`).
  No usa variables de entorno. ⚠️ Riesgo documentado.
- `db()` → PDO de la empresa activa en sesión.
- `db_empresa($key)` → PDO de una empresa específica (`'forsis'` / `'gero'`).
- Pool estático por clave; abre sesión PHP si no existe para resolver la empresa.
- Usuarios `CARLOSD`, `FATIMA`, `RUBISEL01` están **forzados a FORSIS** por código.
- Empresa inválida o ausente → *silenciosamente* `forsis`.

### 3.3 Esquema del núcleo de liquidaciones

#### `liquidaciones` (cabecera — 60,534 filas)
| Columna | Tipo | Nota |
|---|---|---|
| `mov` | int PK AI | id interno |
| `folio_liq` | varchar(10) MUL | **clave de negocio** (`LQ-xxxxx`) |
| `fecha` | datetime MUL | |
| `fechaPrimerViaje` | varchar(15) | |
| `unidad` | varchar(4) | tractor |
| `tarjeta` | int MUL | → `tarjeta_deudor.tarjeta` (operador) |
| `diesel`, `premios`, `autopistas`, `propinas`, `llantas`, `otrosGastos`, `gastosTotal`, `gastosAsig`, `gastosDif`, `viajesForaneos` | **varchar(15)** | ⚠️ importes guardados como texto |
| `impuestos`, `saldoTD`, `abonoTD`, `subtotal`, `total`, `dieselConsum`, `dieselContra` | double | |
| `totalLetra` | varchar(15) | importe en formato `$0.00` |
| `precioLitro` | float | |
| `tipoLiq`, `tipoTractor` | varchar | |
| `estatus` | varchar(50) | ver máquina de estados |
| `motivo` | varchar(90) | razón de cancelación |
| `usuario` | varchar(60) | |

> **Trampa de tipos:** varios importes conviven como `varchar`, `double` y
> `*Letra` (string formateado). El código reconstruye números con
> `(float)str_replace(['$',','],'',$x)`. Cualquier lectura del agente debe
> normalizar igual.

#### Tablas hijas (ligadas por `folio_liq`, **sin FK declarada**)
| Tabla | Filas | Rol |
|---|---|---|
| `detliq` | 399,629 | detalle de viajes (origen/destino, km, litros, tons, autopistas, propinas, llantas); `manual` tinyint marca captura manual |
| `premiosliq` | 9,781 | **bonos a favor** del operador (`concepto`, `total`) |
| `gastosliq` | 88,969 | **cobros/descuentos** al operador (`concepto`, `referencia`, `fecha`, `total`). Ojo: la columna es `folio_Liq` con L mayúscula |
| `liquidacion_td_detalle` | — | puente explícito liquidación ↔ movimiento de tarjeta deudor (`mov_id`, `importe`, `fecha_asignacion`) |

> **Regla de negocio crítica (origen, no texto):** `premiosliq` = BONO (suma),
> `gastosliq` = COBRO (descuenta). El campo `concepto` es texto libre y a veces
> dice "bono" estando en `gastosliq`. **La tabla de origen manda.**

### 3.4 Tarjeta deudor (cuenta corriente del operador)

#### `tarjeta_deudor` (1,506 filas)
`tarjeta` (PK AI), `f_creacion`, `tipo`, `clave_emp`, `num_ope`,
`nombreCompleto`, `usuario_creo`, `estatus`, **`saldo` varchar(20)** (`"$1,234.00"`).

#### `tarjeta_contenido` (335,817 filas) — libro mayor
`mov` PK AI, `fecha`/`fecha1`/`fecha2`, `tipoConcep` int(2), `concepto`,
`referencia`, `importe`+`importeLetra`, `abono`+`abonoLetra`,
**`importeSaldado`**, **`importeRestante`**, `observaciones`, `estatus`, `motivo`,
`tipo` int(2), `folio_vale`, `repuesto`, `saldoFinal`+`saldoFinalLetra`, `tarjeta` MUL.

**Modelo de saldo (lógica SICRET replicada):**
- **Cargo:** inserta fila con `importeRestante = importe`, `estatus '<Por Pagar>'`.
- **Abono:** recorre cargos con `importeRestante > 0` **ordenados por `mov ASC`
  (FIFO)**, bajo `SELECT ... FOR UPDATE`, saldando parcial o totalmente.
  - saldado total → `estatus = '<Pagado:YYYY-MM-DD>'`
  - parcial → `estatus = '<Abono:$X.XX>'`
- **Saldo real = `SUM(importeRestante)` por tarjeta**, no el campo `saldo`.
  `tarjeta_deudor.saldo` es un **denormalizado de conveniencia** que el código
  reescribe tras cada movimiento.

> Para el agente: **nunca** derivar saldo de `tarjeta_deudor.saldo` sin recalcular;
> es cacheado y puede divergir.

### 3.5 Caja chica y vales

| Tabla | Filas | Rol |
|---|---|---|
| `valesgastos` | 132,999 | vale de gasto: `folio_valegastos`, `monto`, `unidad`, `rem1/rem2`, `estatus`, `tarjeta`, `nombre_usu`, `folio_repo` |
| `reposiciones` | — | reposición de caja: `folio_repo` (`PR-00001`), `cheque`, `banco`, `importe`, `cantVales` |
| `vales_diesel` | 91,691 | `folio`, `num_emp`/`num_ope`, `eco`, `num_concep`, `litros`, `precioLitro`, `total`, `folio_Liq`, `estado` |
| `vales_diesel_conceptos` | — | catálogo de conceptos |
| `vales_diesel_guias` | — | N:M vale ↔ guía |
| `vales_diesel_cancel` | — | histórico de cancelados |

### 3.6 Guías y reportes

| Tabla | Filas | Rol |
|---|---|---|
| `guias` | 228,681 | viajes; `folio_imp` único por guía (validado en app, no en BD) |
| `recepcion` | — | bitácora de recepción de documentos; centralizada en **FORSIS** aunque se lea de ambas empresas |
| `reportes_reseteo` | 5,940 | ralentí por unidad; `estado` (ACTIVO/BORRADOR), `requiere_revision`, `archivo_origen` |
| `reportes_categoria_premio` | — | categorías + `patron` (UNIQUE) para clasificar bonos |
| `tracto` | — | catálogo de unidades (match por `no_motor`/`no_chasis`) |
| `usuarios` | 95 | `nombre_usu` PK, `contrasena` (MD5), `priv`, `cajaChica`, `correo`, `num_emp` |

### 3.7 `solicitudes_cancelacion` (SQLite — workflow)

`id`, `empresa`, `modulo`, `referencia_id`, `folio_texto`, `monto`, `solicitante`,
`motivo`, `fecha_solicitud`, `estatus` (`PENDIENTE`/aprobada/rechazada),
`revisado_por`, `fecha_revision`, `motivo_rechazo`, `tipo`.

- **Módulos soportados:** `CAJA_CHICA`, `TARJETA_DEUDOR`, `RECEPCION_GUIAS`.
  Otro valor → excepción `"Módulo desconocido"`.
- **Tipos:** `CANCELACION`, `EDICION`, `CONVERTIR_TD`, `CONVERTIR_DIRECTO`.
- Unicidad lógica: no se admite segunda solicitud `PENDIENTE` para la misma
  tripleta `(empresa, modulo, referencia_id)`.
- La tabla se **autocrea** en el primer uso (`CREATE TABLE IF NOT EXISTS`).

---

## 4. Autenticación

### 4.1 Mecanismo

`app/public/api/login.php` → `POST {username, password}` (JSON body).

```php
$user['contrasena'] === md5($password) || $user['contrasena'] === ''
```

- **Hash MD5 sin salt**, comparación con `===`.
- **Contraseña vacía en BD = acceso concedido sin validar** (compatibilidad
  declarada con SICRET legacy). ⚠️ Hallazgo de seguridad relevante.
- Éxito → `$_SESSION['usuario']`, `$_SESSION['priv']`, `$_SESSION['num_emp']`;
  responde `{ok:true, redirect}`. Admins → `/index.php`, resto → `/vales_diesel.php`.
- `priv` ausente → default `'TRÁFICO'`.

### 4.2 Sesión (`app/public/includes/auth.php`)

| Parámetro | Valor |
|---|---|
| `session.gc_maxlifetime` | 28800 (8 h) |
| cookie lifetime | 28800 |
| `httponly` | true |
| `samesite` | Lax |
| `secure` | **condicional** al esquema real (permite HTTP plano por `:8081`) |

Todo endpoint protegido hace `require_once '../includes/auth.php'` **en la primera
línea**. Sin sesión válida:
- petición API (URI contiene `/api/`, o `Accept: application/json`, o
  `X-Requested-With: XMLHttpRequest`) → **HTTP 401** con payload JSON compatible
  con DataTables (`{ok:false, draw, recordsTotal:0, data:[]}`).
- navegación normal → `Location: /login.php`.

> No hay CSRF token, ni rate limiting, ni bloqueo por intentos fallidos.

### 4.3 Endpoints sin `auth.php` (⚠️ expuestos a sesión-only, sin gate explícito)

`login.php`, `logout.php`, `buscar_operadores.php`, `imprimir_termico_caja.php`,
`imprimir_termico_rsp.php`, `liquidacion_detalle.php`, `liquidaciones.php`,
`next_folio.php`, `nueva_liquidacion_operador.php`, `perfil_foto.php`,
`preferencias.php`, `set_empresa.php`, `tarjeta_deudor.php`.

Destacan por sensibilidad: **`liquidaciones.php`, `liquidacion_detalle.php`,
`tarjeta_deudor.php`, `nueva_liquidacion_operador.php`** — exponen datos
financieros completos sin incluir el guard de autenticación.

---

## 5. Permisos y roles

### 5.1 Fuente de verdad: `usuarios.priv` (texto libre)

Distribución real (95 usuarios):

| `priv` | Usuarios |
|---|---|
| *(vacío)* | **77** |
| SUPER USUARIO | 8 |
| LIQUIDACIONES | 3 |
| FACTURACIÓN | 2 |
| CUENTAS POR PAGAR | 1 |
| RECURSOS HUMANOS | 1 |
| TRÁFICO | 1 |
| SUPERVISOR DE CUENTAS POR PAGAR | 1 |
| ADMINISTRADOR | 1 |

> **81% de los usuarios tiene `priv` vacío** → no son admin global, caen en el
> carril restringido.

### 5.2 `esUsuarioAdminGlobal()`

Admin global si `priv` ∈ {`LIQUIDACIONES`, `SUPER USUARIO`, `ADMINISTRADOR`,
`FACTURACIÓN`, `CUENTAS POR PAGAR`, `SUPERVISOR DE CUENTAS POR PAGAR`,
`JEFE DE TRÁFICO`} **o** contiene los substrings `SUPER` / `LIQUIDAC` / `ADMIN`.

> El match por substring es permisivo por diseño: un `priv` como
> `"AUXILIAR ADMINISTRATIVO"` **concede admin global** (contiene `ADMIN`).
> Hallazgo de seguridad a reportar.

### 5.3 Visibilidad de datos — `obtenerUsuariosVisibles()`

| Caso | Resultado |
|---|---|
| Admin global | `[]` → **ve todo** |
| Grupo operativo (`CARLOSD`, `FATIMA`, `RUBISEL01`) | ve los registros de los tres |
| Resto | solo los propios (`[$_SESSION['usuario']]`) |

`obtenerSqlFiltroUsuario($columna, $pdo)` genera el fragmento
`AND columna = '…'` / `AND columna IN (…)` que los listados concatenan. Los valores
se escapan con `$pdo->quote()`.

> **Grupo operativo hardcodeado en PHP**, no en BD. Cambiar el equipo exige editar
> código y redeploy.

### 5.4 Endpoints con chequeo de rol/visibilidad explícito

`guias_recepciones.php`, `login.php`, `perfil_foto.php`,
`recepcion_documentos.php`, `solicitud_cancelacion.php`,
`vale_diesel_cancelacion.php`, `vales_diesel.php`.

> El resto de los 54 endpoints **solo exige sesión**, sin discriminar rol. En
> particular `autorizar_liquidacion.php` **no valida `priv`** — cualquier sesión
> autenticada puede autorizar. Hallazgo crítico.

---

## 6. Máquinas de estado

### 6.1 `liquidaciones.estatus`

```
            ┌──────────────────┐
  crear ───▶│ <Por Autorizar>  │  (6 registros hoy)
            └────────┬─────────┘
                     │ autorizar_liquidacion.php
          total<-0.1 │ (único transitor)
         ┌───────────┴───────────┐
         ▼                       ▼
    ┌──────────┐          ┌─────────────┐
    │ <Pagada> │          │ <Por Pagar> │  (56,970)
    │  2,940   │          └─────────────┘
    └──────────┘
                     ┌──────────────┐
                     │ <Cancelada>  │  617
                     └──────────────┘
   (<FIX>: 1 registro, estado espurio de corrección manual)
```

- `autorizar_liquidacion.php` **exige** `estatus === '<Por Autorizar>'`.
- Destino: `total < -0.1` → `<Pagada>`; en otro caso `<Por Pagar>`.
- **No hay endpoint de desautorización/reversa.**

### 6.2 Otros estados observados

| Tabla | Estados reales |
|---|---|
| `valesgastos.estatus` | `<Repuesto>` 132,864 · `<Por Reponer>` 124 · `<Cancelada>` 10 · `<Cancelado>` 1 |
| `vales_diesel.estado` | `ACTIVO` 91,205 · `CANCELADO` + ~15 variantes de texto libre (`CANCELADO/ERROR DE DEDO`, `CANCELADO/NO SE USO`, …) |
| `tarjeta_contenido.estatus` | `<Por Pagar>`, `<Pagado:YYYY-MM-DD>`, `<Abono:$X.XX>`, `<Cancelada>` |
| `reportes_reseteo.estado` | `ACTIVO`, `BORRADOR` |

> **Inconsistencias a manejar:** `<Cancelada>`/`<Cancelado>` coexisten; el código
> compara con `stripos($estatus,'Cancelad') !== false` para cubrir ambos. Los
> estados de `vales_diesel` son **texto libre concatenado** — cualquier filtro del
> agente debe usar `LIKE 'CANCELADO%'`, no igualdad.

---

## 7. Capa de tiempo real

`ws/server.js` (Node 22, módulo `ws`):

- Puerto `WS_PORT` (default **8083**), bind `0.0.0.0`.
- Doble función: **servidor WebSocket** + **endpoint HTTP interno `POST /broadcast`**.
- `/broadcast` protegido por header **`X-Internal-Token`** = `WS_INTERNAL_TOKEN`
  (desde `ws/.env`, no versionado). Si la variable está vacía el server **avisa por
  log y deja el endpoint sin protección**.
- Productor desde PHP: `includes/WebSocketNotifier.php`, usado por
  `reportes_reseteo_subir.php` y `reportes_reseteo_actualizar.php`.
- Expuesto al navegador vía `location /ws/` en nginx.

---

## 8. Automatización existente (cron)

`liquidaciones-reseteo-ingestion-cron` ejecuta en bucle:

```sh
while true; do
  php /var/www/html/scripts/importar_reseteos_carpeta.php
  sleep ${RESETEO_INGESTION_INTERVAL_SECONDS:-180}
done
```

Flujo: lee PDFs de la carpeta Nextcloud montada → `ReseteoParser::parseFile()` →
`ReseteoParser::matchUnidad()` contra `tracto` → inserta en `reportes_reseteo`.

**Regla de calidad de dato:** entra como `ACTIVO` solo si el parser reconoce el
formato **y** empareja la unidad; en cualquier otro caso (formato desconocido, PDF
sin capa de texto, unidad no encontrada) entra como **`BORRADOR`** con
`requiere_revision = 1` y no cuenta para reportes hasta confirmación humana.

> Es el precedente arquitectónico más cercano a lo que hará el agente IA:
> **ingesta automática con cola de revisión humana en lugar de confianza ciega.**

Otros scripts en `app/scripts/`: `importar_reseteos_carpeta.php`,
`migracion_liquidacion_td_detalle.php`. Seeds en `deploy/`
(p. ej. `seed_reportes_categoria_premio_v2.php`).

---

## 9. Dependencias críticas

| # | Dependencia | Impacto si falla |
|---|---|---|
| 1 | **MySQL `192.168.1.209:3306`** (host externo, fuera de Docker) | sistema totalmente inoperante |
| 2 | Credenciales **hardcodeadas** en `app/config/database.php` | rotación de password exige editar código |
| 3 | `/mnt/63537E674CF73DC0` (disco externo) + sync Nextcloud | ingesta de reseteos se detiene **en silencio** |
| 4 | `/etc/letsencrypt/live/forsispr1.ddns.net` | caída del listener 443 (`:8096`) |
| 5 | `ws/.env` (`WS_INTERNAL_TOKEN`) no versionado | `/broadcast` queda sin protección |
| 6 | SQLite `app/config/*.sqlite` + permisos uid www-data (33) | workflow de cancelaciones muere; bug histórico de "readonly database" ya parchado con `preferencias_asegurar_escribible()` |
| 7 | `/home/servidor/fotos_sicret@y968jh` | fotos de perfil sin resolver |
| 8 | **BD compartida** con `trafico-system` / ATLAS | escrituras del agente pueden colisionar con otros sistemas |
| 9 | Chromium headless + listener `:8081` | generación de PDF de liquidación |

---

## 10. Hallazgos de seguridad (para reporte)

| Sev | Hallazgo | Ubicación |
|---|---|---|
| **Alta** | Contraseñas en **MD5 sin salt** | `api/login.php:28` |
| **Alta** | `contrasena === ''` → **login sin validar** | `api/login.php:28` |
| **Alta** | `autorizar_liquidacion.php` **no valida `priv`**; cualquier sesión autoriza pagos | `api/autorizar_liquidacion.php` |
| **Alta** | Credenciales de BD hardcodeadas en el repo | `config/database.php:14-16` |
| **Media** | `esUsuarioAdminGlobal()` por **substring**: `"AUXILIAR ADMINISTRATIVO"` → admin | `includes/auth.php:60` |
| **Media** | 13 endpoints sin `require auth.php`, incluidos financieros | §4.3 |
| **Media** | Sin CSRF token, sin rate limiting, sin lockout | global |
| **Baja** | `display_errors=0` solo en rutas `/api/` | `includes/auth.php:6-9` |
| **Baja** | Grupo de visibilidad hardcodeado en PHP | `includes/auth.php:74` |

---

## 11. Implicaciones para el agente IA

### 11.1 Integración recomendada

1. **Entrar por el listener interno `http://liquidaciones-nginx:8081`** uniendo el
   contenedor del agente a la red `liquidaciones-system_default`. Evita TLS y no
   amplía superficie pública.
2. **Mantener cookie de sesión**: `POST /api/login.php` y conservar `PHPSESSID`
   (vida 8 h). No existe otra vía de autenticación.
3. **Fijar empresa explícitamente** con `POST /api/set_empresa.php` al inicio de
   cada sesión. El default silencioso a FORSIS es un riesgo de corrupción cruzada.
4. **Usar un usuario de servicio dedicado** con `priv` controlado — no reutilizar
   credenciales humanas, para que la auditoría por `usuario`/`nombre_usu` sea útil.

### 11.2 Guardarraíles obligatorios

- **Lectura libre / escritura con aprobación.** Las escrituras financieras
  (`autorizar_liquidacion`, `movimiento_tarjeta`, `guardar_liquidacion`,
  `solicitud_cancelacion?action=aprobar`) son **irreversibles y en cascada**.
- Reutilizar el patrón ya existente del sistema: **crear
  `solicitudes_cancelacion` en estado `PENDIENTE`** y dejar que un humano apruebe,
  en lugar de que el agente ejecute `aprobar` directamente.
- Imitar el modelo `BORRADOR`/`requiere_revision` de `reportes_reseteo` para
  cualquier dato que el agente infiera.
- Normalizar importes siempre con `(float)str_replace(['$',','],'',$v)`.
- Calcular saldos con `SUM(importeRestante)`, nunca con `tarjeta_deudor.saldo`.
- Distinguir BONO/COBRO por **tabla de origen**, nunca por el texto del concepto.
- Filtrar estados con `LIKE`/`stripos`, no con `=`, por el texto libre heredado.

### 11.3 Oportunidades de alto valor

| Oportunidad | Base existente |
|---|---|
| Detección de anomalías en liquidaciones (km/lt fuera de rango, conceptos atípicos) | `detliq` 399k filas, `kmlt` precalculado |
| Conciliación automática vale diésel ↔ liquidación ↔ guía | `vales_diesel.folio_Liq`, `vales_diesel_guias` |
| Clasificación de conceptos de bono/cobro por patrón | `reportes_categoria_premio.patron` ya es un motor de patrones |
| Triage de los 5,940 reseteos en `BORRADOR` | `reportes_reseteo.requiere_revision` |
| Auditoría de saldos: `SUM(importeRestante)` vs `tarjeta_deudor.saldo` | detecta divergencias del denormalizado |
| Limpieza de los 112+ estados de cancelación de vales diésel | normalización de texto libre |

---

## 12. Comandos de verificación usados

```bash
# Esquema y volumetría (desde el contenedor, reutiliza ConnectionManager)
docker exec liquidaciones-php php -r 'require "/var/www/html/config/database.php";
  $pdo=db(); foreach($pdo->query("SHOW TABLES")->fetchAll(PDO::FETCH_COLUMN) as $t) echo "$t\n";'

# Distribución de roles y estados
docker exec liquidaciones-php php -r 'require "/var/www/html/config/database.php";
  $pdo=db(); foreach($pdo->query("SELECT priv,COUNT(*) c FROM usuarios GROUP BY priv")->fetchAll() as $r) print_r($r);'

# Inventario de endpoints
ls -1 /home/servidor/liquidaciones-system/app/public/api/*.php
```

---

**Documentos relacionados:**
`liquidaciones-system-api-inventory.md` (54 endpoints detallados) ·
`liquidaciones-system-actions.md` (acciones ejecutables por el agente)
