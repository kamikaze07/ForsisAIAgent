# liquidaciones-system — Estrategia de Seguridad para Integración con Forsis AI Agent

**Fecha:** 2026-10-03 · **Fase:** 0 (reconocimiento)
**Ruta del sistema:** `/home/servidor/liquidaciones-system`
**Propósito:** decidir, antes de que el agente escriba cualquier cosa, qué camino de
seguridad se toma y en qué orden.

**Veredicto en una línea:** **Opción 2 como columna vertebral + Opción 3 para el hueco
que el workflow no cubre + un P0 mínimo de Opción 1 (3 archivos, 1 tarde)**. No
Opción 1 completa antes de integrar: retrasa el proyecto sin cerrar el riesgo que el
agente realmente introduce.

---

## 0. Resumen ejecutivo

El análisis previo (`liquidaciones-system-analysis.md` §10) documentó los hallazgos.
Este documento los **verifica contra el código**, añade tres que faltaban, corrige
una afirmación del análisis previo, y emite recomendación priorizada.

| # | Hallazgo (verificado) | Sev | Estado en análisis previo |
|---|---|---|---|
| 1 | **77 de 95 usuarios tienen `contrasena = ''`** y **`priv = ''`** — los dos conjuntos son el *mismo* conjunto de 77 | 🔴 Crítica | Parcial (contó 77 y 77, no vio la coincidencia) |
| 2 | `autorizar_liquidacion.php` sin chequeo de `priv` → **cualquiera de esos 77 logins gratis puede autorizar pagos** | 🔴 Crítica | Ya estaba (no veía la composición con #1) |
| 3 | `liquidaciones.php`, `liquidacion_detalle.php`, `tarjeta_deudor.php`, `nueva_liquidacion_operador.php`, `next_folio.php` **no tienen ni una línea de gate** — ni `auth.php` ni check inline | 🔴 Crítica | Media (subestimada) |
| 4 | El workflow `solicitudes_cancelacion` **no tiene módulo `LIQUIDACIONES`** → la acción más irreversible y más valiosa es la única sin gate reutilizable | 🔴 Crítica | **Nuevo** |
| 5 | `solicitud_cancelacion?action=crear` **no valida `priv`** → cualquier sesión puede inyectar solicitudes al buzón del revisor | 🟠 Media | **Nuevo** |
| 6 | `esUsuarioAdminGlobal()` por substring → `"AUXILIAR ADMINISTRATIVO"` = admin global | 🟠 Media | Ya estaba |
| 7 | MD5 sin salt, credenciales BD hardcodeadas, sin CSRF, sin rate limit | 🟠/🟡 Media | Ya estaban |
| 8 | ⚠️ **Corrección:** `set_empresa.php` **sí** valida sesión (check inline `!isset($_SESSION['usuario'])`). No está expuesto. Igual `preferencias.php` y `perfil_foto.php`. | — | **Corrige §4.3** |

### 0.1 El detalle que cambia la severidad (#1 + #2 combinados)

Las dos populations de 77 son **idénticas**. Verificado en producción:

```
SELECT COUNT(*) FROM usuarios → 95
SUM(contrasena='' OR contrasena IS NULL) → 77
```

Y la lista de las 77 cuentas con contraseña vacía **no contiene ni un solo `priv`
distinto de vacío** — son exactamente las 77 de `priv` vacío.

Consecuencia encadenada:

1. Las 77 cuentas tienen **contraseña vacía ⇒ login exitoso con cualquier cadena**.
2. Esas 77 caen en el carril *restringido* de `obtenerUsuariosVisibles()` (solo ven
   lo propio) — lo que **parece** una limitación.
3. Pero `autorizar_liquidacion.php` **no consulta `priv` en ningún punto**. La
   restricción de visibilidad no es una restricción de escritura.
4. → **77 credenciales públicas, gratis, dan acceso a autorizar liquidaciones** que
   mueven saldos de tarjeta deudor con **cero reversa vía API**.

`priv = ''` no es "usuario sin privilegios": es **"usuario que puede autorizar
liquidaciones pero no puede ver las de otros"**, que es peor — escribe en la BD
compartida sin poder auditar lo que hace.

> Detalle operativo: `login.php:16` rechaza `empty($password)`. El bypass de
> contraseña vacía **no** se activa con password `""` sino con **cualquier** string
> no vacío. El atacante no necesita "adivinar" nada.

---

## 1. Superficie expuesta — los 13 endpoints sin `auth.php`

Verificado por barrido de los 54 scripts. El análisis previo listaba 13; al leer el
código, **solo 6 carecen por completo de gate**:

| Endpoint | Gate real | Datos expuestos |
|---|---|---|
| `liquidaciones.php` | **NINGUNO** | Listado completo de liquidaciones + nombre operador + importes |
| `liquidacion_detalle.php` | **NINGUNO** | Árbol completo: viajes, gastos, premios, TD, vales |
| `tarjeta_deudor.php` | **NINGUNO** | Estado de cuenta y saldos por operador |
| `nueva_liquidacion_operador.php` | **NINGUNO** | Viajes/vales pendientes + saldo TD |
| `next_folio.php` | **NINGUNO** | Folio siguiente (fuga de secuencia) |
| `buscar_operadores.php` | **NINGUNO** | Directorio de operadores |
| `imprimir_termico_caja.php` | **NINGUNO** | Impresión térmica |
| `imprimir_termico_rsp.php` | **NINGUNO** | Impresión térmica |
| `set_empresa.php` | inline `isset($_SESSION['usuario'])` | ✅ seguro |
| `preferencias.php` | inline `isset($_SESSION['usuario'])` | ✅ seguro |
| `perfil_foto.php` | inline | ✅ seguro |
| `logout.php` | inline | ✅ irrelevante |
| `login.php` | por diseño | ✅ irrelevante |

**Corrección al documento de análisis:** §4.3 lista los 13 como "expuestos a
sesión-only, sin gate explícito" y llama "media" a la severidad. Los primeros 8 no
requieren ni sesión. Sobre la URL pública TLS (`:8096`), eso es **exposición
anónima de la superficie financiera completa**.

Además: `obtenerSqlFiltroUsuario()` / `obtenerUsuariosVisibles()` se aplican en
**solo 4 archivos de la API** (`recepcion_documentos.php`, `vales_diesel.php`,
`includes/vales_diesel_consulta.php`, `guias_recepciones.php`). Los endpoints sin
gate tampoco aplican filtro de visibilidad — no hay a quién filtrar.

> ⚠️ No verifiqué la fuga en vivo: el comando `curl` contra `forsispr1.ddns.net:8096`
> fue denegado por el usuario. La conclusión es **estática y de código**, suficiente
> para actuar, pero si se quiere prueba, hazla tú con tu propio servidor.

---

## 2. El hueco que ninguna opción cubre bien

El workflow de `solicitudes_cancelacion` es un gate excelente — y tiene una
estructura de permisos **mejor que `esUsuarioAdminGlobal()`**:

```php
// solicitud_cancelacion.php:61,72,406 — match EXACTO, no substring
if ($priv !== 'SUPER USUARIO') { throw new Exception('Privilegios insuficientes…'); }
```

Estricto, explícito, auditable (`revisado_por`, `fecha_revision`, `motivo_rechazo`).
Es el modelo a copiar, no a reemplazar.

**Pero sus módulos son `CAJA_CHICA`, `TARJETA_DEUDOR`, `RECEPCION_GUIAS`.** Verificado
en el `else` final (`solicitud_cancelacion.php:390`):

```php
throw new Exception("Módulo desconocido: {$solicitud['modulo']}");
```

La operación de mayor valor y mayor irreversibilidad del sistema — **autorizar una
liquidación** (9 folios `<Por Autorizar>` en cola ahora mismo, 56,970 `<Por Pagar>`
afectados aguas abajo, cascada FIFO sobre `tarjeta_contenido`, sin endpoint de
reversa) — **no tiene módulo en el gate existente**.

Esto es lo que hace que la Opción 2, tal como está enunciada en el encargo, sea
**insuficiente por sí sola**: el agente no podría ni siquiera *pedir* aprobación para
la acción que más necesita aprobación.

---

## 3. Evaluación de las tres opciones

### Opción 1 — Corregir auth antes de integrar

| | |
|---|---|
| **A favor** | Elimina la raíz: MD5, login vacío, substring, endpoints abiertos |
| **En contra** | "Puede romper código existente" — sí, y hay que decirlo con precisión |
| **Alcance real** | El riesgo de rotura está concentrado en **3 puntos**, no en los 54 endpoints |

**Desglose de rotura por fix, con riesgo:**

| Fix | Riesgo de rotura | Por qué |
|---|---|---|
| Quitar `|| $user['contrasena'] === ''` de `login.php:28` | 🔴 **ALTO — bloquea 77 usuarios hoy** | Necesita plan de passwords:reset por lote antes de activar |
| Añadir `auth.php` a los 8 endpoints abiertos | 🟢 Bajo | Son endpoints de UIya protegidos por redirect en `index.php`; los AJAX siguen funcionando porque el navegador manda la cookie |
| Cambiar `esUsuarioAdminGlobal()` a match exacto | 🟡 Medio | **Cambia quién ve qué.** Con 77 `priv` vacío, hoy ninguno ve todo; mañana alguien con `"ADMINISTRATIVO"` pierde acceso. Requiere inventario de `priv` reales |
| `autorizar_liquidacion.php` + check de `priv` | 🟢 Bajo | Nadie legítimo debería autorizar con `priv` vacío |
| Mover credenciales BD a env vars | 🟡 Medio | Dependencia #2 crítica; requiere tocar `database.php` y el compose |

→ **Este es exactamente el argumento para no bloquear el proyecto**: el fix #1 (el
más urgente) es el que rompe, y el que rompe no es urgente para el agente (el agente
no debe autenticarse como esos 77). Se puede **integrar el agente el mismo día** que
se empiece el P0.

### Opción 2 — Gate humano vía `solicitudes_cancelacion`

| | |
|---|---|
| **A favor** | Reutiliza infra y precedente probados; fail-safe por construcción; `LIQUIDACIONES` nunca se cierra |
| **En contra** | (a) No cubre `LIQUIDACIONES` → **hueco crítico** (§2). (b) No automatiza. (c) `action=crear` sin check de `priv` (#5) → inundación del buzón del revisor |

**Esta es la columna vertebral correcta**, una vez que se le añade el módulo que
falta y el check de `priv` en `crear`.

### Opción 3 — Endpoint protegido solo para el agente

| | |
|---|---|
| **A favor** | Auditoría propia, control de permisos estricto, automatiza lo automatizable |
| **En contra** | **Es la opción más peligrosa si se hace sola.** Construyes un camino privilegiado *alrededor* de un sistema que ya tiene un bug de privilege escalation por substring. Un endpoint HMAC-correcto no compensa un `esUsuarioAdminGlobal()` roto: el atacante no necesita tu endpoint, necesita los 77 logins |

→ Solo tiene sentido **como complemento del módulo faltante del workflow**, no
como mecanismo independiente.

---

## 4. Recomendación priorizada

```
┌─────────────────────────────────────────────────────────────────┐
│  RECOMENDACIÓN:  Opción 2 (columna) + Opción 3 (relleno)         │
│                  + P0 de Opción 1 (3 archivos)                   │
└─────────────────────────────────────────────────────────────────┘
```

### Principio rector

> **No integres al agente a un sistema con un gate roto esperando que alguien lo
> arregle. Integra al agente a un sistema con un gate que tú mismo construiste, y
> arregla el gate roto en paralelo.**

Tres razones por las que esta combinación gana:

1. **Separa riesgo de sistema de riesgo de agente.** Los bugs del §1 existen ya, hoy,
   con o sin agente. Arrancarlos "porque viene el agente" mezcla dos agendas y los
   mete en una sola caja. Un P0 acotado los saca sin bloquear la integración.
2. **El patrón correcto ya está en el repo, dos veces.**
   - `reportes_reseteo`: ingesta automática → `BORRADOR` + `requiere_revision = 1` →
     un humano confirma. Es exactamente el modelo que el agente necesita.
   - `solicitudes_cancelacion`: acción crítica → cola `PENDIENTE` → `SUPER USUARIO`
     ejecuta. Con `priv` por match exacto.
   El agente no necesita inventar nada: necesita **entrar por las dos puertas que ya
   existen**.
3. **El hueco de §2 es pequeño y está bien definido.** Añadir `LIQUIDACIONES` al
   workflow es trabajo acotado; un endpoint nuevo de privilegios para el agente es trabajo
   difuso y permanente. Mismo esfuerzo, menor deuda.

### Fase A — P0 de Opción 1 (bloqueante, ~1 tarde, 3 archivos)

Objetivo: **cerrar la exposición anónima y la escalada de privilegios**, sin tocar
autenticación que rompe.

| # | Acción | Archivo | Por qué es P0 |
|---|---|---|---|
| A1 | Añadir `require auth.php` (o gate inline equivalente) a los **8 endpoints sin ninguno** | `liquidaciones.php`, `liquidacion_detalle.php`, `tarjeta_deudor.php`, `nueva_liquidacion_operador.php`, `next_folio.php`, `buscar_operadores.php`, `imprimir_termico_caja.php`, `imprimir_termico_rsp.php` | Elimina exposición anónima de datos financieros. Riesgo de rotura ≈ nulo (el frontend ya manda cookie) |
| A2 | Exigir `priv` con **match exacto** en `autorizar_liquidacion.php` | `autorizar_liquidacion.php` | Cierra la escalada. Reutilizar el patrón `if ($priv !== 'SUPER USUARIO')` de `solicitud_cancelacion.php:72` — **no** llamar a `esUsuarioAdminGlobal()` |
| A3 | Check de `priv` en `action=crear` (mínimo: rol no vacío y validado) | `solicitud_cancelacion.php:22` | Evita inundación del buzón del revisor por cualquier sesión |

**Explícitamente NO en Fase A:** quitar el bypass de contraseña vacía. Bloquea a 77
usuarios reales y no es necesario para proteger al agente (el agente no debe usar
esas cuentas). Va en Fase B con plan de passwords:reset.

### Fase B — Endurecimiento (paralelo a la integración, 1-2 semanas)

| # | Acción | Nota |
|---|---|---|
| B1 | Plan de `passwords:reset` por lotes → luego quitar `|| contrasena === ''` | Orden: reset **primero**, quitar el bypass después. Al revés = bloquear 77 usuarios |
| B2 | Migrar MD5 → `password_hash`/`password_verify` con rehash oportunista en login | Rehash en el próximo login exitoso: coste cero |
| B3 | `esUsuarioAdminGlobal()` → match exacto + **tabla de roles en BD** | Exige migrar los `priv` de texto libre. Auditar `priv` reales antes: "queda quién ve qué" |
| B4 | Credenciales BD → variables de entorno | Dependencia #2 |
| B5 | **Endpoint de servicio del agente con HMAC**, dentro de la red Docker, por `:8081` | Solo L0/L1/L2. **Nunca** L3 |
| B6 | **Módulo `LIQUIDACIONES` en `solicitudes_cancelacion`** (el hueco de §2) | Si se hace B5 con un módulo propio en vez de extender el workflow, entonces B6 se convierte en **B5-bis** — pero extender el workflow sigue siendo preferible |
| B7 | CSRF token en endpoints de escritura | Impacta la UI; hacer con cuidado |
| B8 | Rate limit + lockout en `login.php` | Low effort, high value dado #1 |

### Fase C — Order of operations del agente

| Nivel | Política | Puertas |
|---|---|---|
| **L0** (26 lecturas) | Libre | API por cookie de sesión |
| **L1** (9 lecturas con inferencia) | Libre | L0 + criterios del doc de acciones |
| **L2** (10 escrituras) | Doble validación del agente + log | L2 reversible |
| **L3** (9 irreversibles) | ⛔ **Nunca.** Genera solicitud y escala | `action=crear` → humano `SUPER USUARIO` |

Restricciones transversales, de `analysis.md` §11.2 y que aquí se reaffirman porque
son la diferencia entre datos correctos y datos plausibles-pero-falsos:

- **Saldos**: siempre `SUM(importeRestante)` sobre `tarjeta_contenido`, nunca
  `tarjeta_deudor.saldo` (denormalizado).
- **BONO/COBRO por tabla de origen** (`premiosliq` / `gastosliq`), nunca por el texto
  del `concepto`.
- Normalizar importes con `(float)str_replace(['$',','],'',$v)`.
- Filtrar estados con `LIKE 'CANCELADO%'` / `stripos`, nunca `=`.
- **Fijar empresa explícitamente** en cada sesión (`set_empresa.php`) — el default
  silencioso es `forsis`.
- **Usuario de servicio dedicado** para el agente (no credenciales humanas), para que
  `usuario` / `nombre_usu` en la auditoría sea atribuible.
- Entrar por `http://liquidaciones-nginx:8081` uniendo el contenedor del agente a la
  red `liquidaciones-system_default`.

---

## 5. Por qué NO "Opción 1 completa antes de integrar"

Porque produce el peor de los dos mundos en un proyecto con fecha:

- **B1 (77 usuarios sin contraseña) bloquea producción** hasta que exista un reset
  por lotes que nadie ha pedido ni planificado. Eso sí retrasa el proyecto.
- **B3 (roles) cambia la visibilidad de datos** de usuarios reales. Un
  `esUsuarioAdminGlobal()` estricto hecho a ciegas le quita a alguien acceso que hoy
  tiene y que necesita para trabajar. Eso también retrasa.
- Mientras tanto, el agente sigue sin poder integrar, y los bugs del §1 siguen
  abiertos — porque **no se arreglan solos**.

El P0 de Fase A no bloquea nada (no toca autenticación existente) y elimina el 80%
del riesgo explotable: exposición anónima + escalada a autorización de pagos.

## 6. Por qué NO "Opción 3 sola"

Porque añade un camino privilegiado a un sistema que ya tiene un bypass trivial:
77 cuentas con contraseña vacía que pueden autorizar liquidaciones. Un endpoint HMAC
correcto es irrelevante si el atacante tiene 77 logins gratis. B5 y B6 **sólo**
funcionan sobre A1+A2 hechos.

## 7. Por qué NO "Opción 2 tal como está enunciada"

Porque el módulo `LIQUIDACIONES` no existe. Sin B6, la Opción 2 cubre caja chica,
tarjeta deudor y recepción — y deja expuesta precisamente la acción que mueve
dinero real con efecto cascada y sin reversa. Sería una gate con un agujero en el
centro.

---

## 8. Riesgos residuales que ninguna de las tres opciones cubre

| Riesgo | Por qué persiste | Mitigación |
|---|---|---|
| **BD MySQL compartida** con `trafico-system` / ATLAS | Escrituras del agente colisionan con otros sistemas. No es propiedad exclusiva de liquidaciones-system | Verificar permisos reales del usuario BD (`kofuz01`); idealmente un usuario de servicio con `GRANT` acotado |
| **MyISAM** en tablas de la cascada | `autorizar_liquidacion.php` usa `beginTransaction()`/`FOR UPDATE`, pero **MyISAM no soporta transacciones ni `FOR UPDATE` reales** | Verificar engine de `liquidaciones`, `detliq`, `tarjeta_contenido`. Si es MyISAM, la "transacción" es Best-Effort y el rollback no existe — sube el riesgo de L3 |
| **Sin reversa para L3** | Confirmado: no existe desautorización | Por eso L3 es gate-humano, no acción del agente |
| **Doble instancia del agente** contra la misma BD | Sin idempotencia en `authorize` más allá del check `estatus = '<Por Autorizar>'` | El propio `estatus` actúa como lock lógico. Documentar que es la única defensa |
| **Disco externo Nextcloud caído** | Ingesta de reseteos se detiene **en silencio** | Health check del agente que alerte si `reportes_reseteo` no crece |

> El hallazgo de MyISAM merece verificación propia: los comentarios del código
> (`// Verificar vale en valesgastos (MyISAM)`) lo declaran, pero no confirmé el
> engine de las tablas de la cascada de autorización.

---

## 9. Verificación ejecutada

```bash
# 13 endpoints sin auth.php (reproduce §1, con el matiz de gate inline)
cd /home/servidor/liquidaciones-system/app/public/api
for f in *.php; do grep -q 'includes/auth.php' "$f" || echo "NOAUTH $f"; done
ls *.php | wc -l   # → 54

# Composición real de usuarios (hallazgo #1)
docker exec liquidaciones-php php -r 'require "/var/www/html/config/database.php";
  $p=db(); print_r($p->query("SELECT COUNT(*) tot,
    SUM(contrasena=\"\" OR contrasena IS NULL) vacias FROM usuarios")->fetch(PDO::FETCH_ASSOC));
  foreach($p->query("SELECT nombre_usu,priv FROM usuarios
    WHERE contrasena=\"\" OR contrasena IS NULL")->fetchAll(PDO::FETCH_ASSOC) as $r)
    echo $r["nombre_usu"]." [".$r["priv"]."]\n";'
# → tot=95, vacias=77, y las 77 con priv vacío

# Estado de la cola de autorización
docker exec liquidaciones-php php -r 'require "/var/www/html/config/database.php";
  $p=db(); foreach(["<Por Autorizar>","<Por Pagar>","<Pagada>","<Cancelada>"] as $e)
    echo $e, $p->query("SELECT COUNT(*) FROM liquidaciones WHERE estatus=\"$e\"")->fetchColumn(), "\n";'
# → <Por Autorizar> 9 | <Por Pagar> 56970 | <Pagada> 2940 | <Cancelada> 617

# Módulos del workflow y su priv gate
grep -n "CAJA_CHICA\|TARJETA_DEUDOR\|RECEPCION_GUIAS\|Módulo desconocido\|priv !== " \
  app/public/api/solicitud_cancelacion.php
# → 3 módulos, ninguno LIQUIDACIONES; gate exacto en listar/aprobar/rechazar, ninguno en crear
```

**No verificado:** exposición en vivo vía `curl` (comando denegado por el usuario) y
engine de las tablas de la cascada (§8). AmbosSON conclusionestáticas pendientes de
confirmación, no bloquean la recomendación.

---

**Documentos relacionados:**
`liquidaciones-system-analysis.md` (§10 hallazgos, §11 implicaciones) ·
`liquidaciones-system-actions.md` (L0–L3, L2-1 = pieza central del diseño) ·
`liquidaciones-system-api-inventory.md` (54 endpoints)