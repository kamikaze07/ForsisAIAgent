# Estrategia de Acceso a Datos — Forsis AI Agent

**Fecha:** 2026-10-03 · **Fase:** 0 (decisión arquitectónica) · **Autor:** Hermes Agent (subagente de análisis)
**Fuentes:** `trafico-system-analysis.md`, `trafico-system-api-inventory.md`, `trafico-system-actions.md`,
`liquidaciones-system-analysis.md`, `liquidaciones-system-api-inventory.md`, `liquidaciones-system-actions.md`,
`prototype-review.md`, `deployment-strategy.md`, inspección en vivo de `docker ps` / `docker network ls`.

---

## 1. Resumen ejecutivo

**Recomendación: Opción C — Híbrido**, con una regla de corte explícita:

> **Lecturas → DB read-only directa contra SICRET (`sicrePR`/`sicreGero`) y contra `trafico` (MariaDB propia).**
> **Escrituras/acciones → siempre vía API REST de `trafico-system` y `liquidaciones-system`, nunca SQL directo.**

Esta no es una posición intermedia tibia: es la única opción consistente con los hechos ya
verificados en las tres bases de evidencia disponibles (el prototipo abandonado, el inventario de
endpoints de ambos sistemas, y la topología Docker real). Las secciones 2–6 justifican cada mitad
de la regla por separado porque **las dos mitades fallan por razones distintas** si se invierten.

| Opción | Veredicto |
|---|---|
| A — API-only | ❌ Inviable como estrategia única: no todas las lecturas analíticas tienen endpoint, y la sesión PHP compartida no escala a un agente con muchas consultas concurrentes |
| B — DB-direct read-only para todo | ❌ Inviable como estrategia única: las escrituras de ambos sistemas tienen lógica de negocio no trivial (FIFO, auditoría, estados ATLAS asíncronos) que un INSERT directo no puede replicar sin reimplementar media aplicación |
| **C — Híbrido (lectura=DB, escritura=API)** | ✅ Recomendado — ver sección 7 para la matriz de decisión completa |

---

## 2. Qué ya sabemos por evidencia directa (no hipótesis)

### 2.1 El precedente ya probó B para lecturas, y colisionó consigo mismo

El prototipo `forsis-agent` (287 MB, Sprint 2 completado, revisado en `prototype-review.md`) es el
dato más valioso disponible porque **ya se construyó y se validó empíricamente**:

- Su `ADR-0001`/`DECISIONS.md` declaran API-only y prohíben "estrictamente" el acceso directo a
  MariaDB.
- Su código real (`readonly_session.py`, 15 módulos core, ~40 tests en verde) está construido
  **100% sobre acceso directo a MariaDB read-only** contra `sicrePR`/`sicre2PR`/`sicreGero`.
- La contradicción no es un descuido: `MVP_IMPLEMENTATION_PLAN.md` documenta una **excepción
  explícita y razonada** ("API de Forsis no expone agregaciones, solo CRUD") que nunca se formalizó
  en el ADR.
- La validación empírica del esquema encontró un hallazgo que API-only no habría permitido
  descubrir: `operadores.num_tracto` (catálogo) y la última fila de `llamadas_historicas`
  (actividad real) **no coinciden**. Ninguna ruta `/api/` expone esa comparación; sólo fue visible
  leyendo las dos tablas directamente.

**Lectura correcta del precedente:** no es "DB-direct funcionó, repetirlo tal cual". Es "DB-direct
para lectura es la única forma de responder preguntas analíticas reales, y el error del prototipo
fue no formalizar la excepción ni separarla de la capa de escritura". Este documento corrige eso.

### 2.2 El inventario de endpoints confirma el hueco de lectura analítica

- `trafico-system`: ~450 rutas registradas (~370 bajo `/api/`), en su mayoría **CRUD por
  pantalla**, no agregaciones de negocio. `trafico-system-actions.md` cataloga decenas de
  endpoints 🟢 de listado/detalle, pero ninguno resuelve preguntas cruzadas tipo "¿qué guías de
  este cliente llevan más de 5 días sin pase de descarga?" sin paginar manualmente N listados y
  cruzarlos en el cliente.
- `liquidaciones-system`: 54 scripts PHP sueltos (`app/public/api/*.php`), documentados en
  `liquidaciones-system-api-inventory.md`. Varios endpoints de lectura ya devuelven datos
  **denormalizados/cacheados que el propio código no confía** (`tarjeta_deudor.saldo` es un caché
  que diverge; la fuente de verdad es `SUM(tarjeta_contenido.importeRestante)`, una agregación que
  **no existe como endpoint**).
- Ambos inventarios de acciones (`trafico-system-actions.md`, `liquidaciones-system-actions.md`)
  fueron construidos explícitamente clasificando por nivel de riesgo de escritura (🟢/🟡/🔴 y
  L0–L3), lo que ya asume — correctamente — que lectura y escritura tienen requisitos de
  gobernanza distintos.

### 2.3 La topología Docker real hace viable el acceso DB sin tocar producción

Verificado en vivo (`docker ps`, `docker network ls`):

- `trafico-db` (MariaDB 11, contenedor dedicado) y `sicret-pruebas-db` ya corren en el host.
- SICRET (`sicrePR`/`sicreGero`) vive en `192.168.1.209:3306`, **fuera de Docker**, compartido ya
  hoy por `trafico-system` y `liquidaciones-system` simultáneamente — el agente sería un tercer
  lector concurrente, no un patrón nuevo.
- `forsis-comunicaciones` (red bridge 192.168.16.0/20) ya conecta `trafico-php`/`trafico-nginx`;
  `deployment-strategy.md` ya planeó unir el agente a esa red.
- `liquidaciones-system_default` **no** está en `forsis-comunicaciones` todavía — union aditiva y
  reversible (opción A de `deployment-strategy.md §2`), o alternativamente el agente llega al MySQL
  externo directamente por IP, igual que hacen hoy trafico y liquidaciones.

Esto significa que la ruta de lectura DB-direct **no requiere abrir ningún puerto nuevo ni crear
infraestructura**: la conectividad ya existe porque dos sistemas de producción ya la usan.

### 2.4 Ambos sistemas usan autenticación de sesión, no tokens — el problema real de Opción A

- `trafico-system`: `Guard::proteger()` valida `trafico_session` + `session_version` en **cada
  request**; vida 8h/12h. No hay JWT ni API key para flujos de servidor-a-servidor humano (sólo
  HMAC para webhooks puntuales: `/webhook/openwa`, `/eventos-atlas`).
- `liquidaciones-system`: sesión PHP con hash MD5 heredado, sin tokens, con una trampa adicional
  **específica de multiempresa**: `$_SESSION['empresa']` resuelve en silencio a `'forsis'` si no se
  fija explícitamente (`liquidaciones-system-actions.md §1`, paso 2: *"el guardarraíl más
  importante"*).

Un agente que haga **decenas de consultas de lectura por turno de conversación** (listar guías +
detalle + KPIs + cruzar con pases de descarga, por ejemplo) sobre esta base de sesión:
- Satura el pool de sesiones PHP compartido con usuarios humanos reales.
- Arriesga pisar el estado de empresa activa si cualquier parte del pipeline reutiliza la cookie
  jar de forma concurrente (riesgo ya señalado en `liquidaciones-system-actions.md §13.4`: *"un bug
  del agente cambia el contexto de datos de una sesión humana si comparte cookie jar"*).
- Añade 1 round-trip HTTP + parseo JSON por cada subconsulta que en SQL sería un único `JOIN`.

Esto no descalifica la API para escritura (ahí la sesión es la fuente correcta de auditoría), pero
sí la descalifica como **único** canal de lectura a volumen de agente conversacional.

---

## 3. Por qué B (DB-direct para todo) también falla, específicamente en escritura

Esto no es simétrico al punto anterior — el argumento contra DB-direct en escritura es más fuerte
que "inconveniente", es **imposibilidad práctica de replicar invariantes sin duplicar lógica**:

### 3.1 `liquidaciones-system`: la escritura es transaccional con FIFO bajo lock

`liquidaciones-system-analysis.md §3.4` y `liquidaciones-system-actions.md §5` documentan:
- Un abono recorre `tarjeta_contenido` con cargos pendientes **ordenados por `mov ASC` (FIFO) bajo
  `SELECT ... FOR UPDATE`**, saldando parcial o totalmente y reescribiendo tres columnas de
  estado/caché por fila tocada.
- `autorizar_liquidacion.php` dispara una cascada sobre 8 tablas, marca estados con texto libre
  (`<Pagado:fecha>`, `<Abono:$X>`), recalcula `tarjeta_deudor.saldo` — **y no tiene endpoint de
  reversión**. Un `UPDATE` directo que se equivoque en el orden FIFO es indetectable hasta que un
  humano audita manualmente.
- `guardar_liquidacion.php` recibe **totales ya calculados por el cliente** (`resumen` en el body);
  replicar esto en SQL directo obliga al agente a reimplementar la aritmética completa de
  diesel/premios/autopistas/propinas/llantas/gastos — exactamente el tipo de lógica que el
  documento de acciones ya marca como "el agente debe replicar la aritmética" (riesgo documentado,
  no inventado aquí).

### 3.2 `trafico-system`: la escritura tiene máquina de estados + integración asíncrona externa

`trafico-system-analysis.md §7` y `trafico-system-actions.md §2`:
- El estado gobernante de una guía (`sicrePR.guias.estatus`) es **texto libre con una máquina de
  estados implementada en código** (`GuiaBloqueoService`), no en constraints de BD. Un INSERT/UPDATE
  directo no sabe qué transiciones son válidas.
- La liberación de guías **no se resuelve en la BD de trafico-system**: `LiberacionGuiaController`
  valida contra SICRET y delega a ATLAS (sistema externo, HTTP, asíncrono). No existe tabla alguna
  que, escrita directamente, produzca el mismo efecto — el estado final depende de un sistema que
  vive fuera de cualquier MariaDB a la que el agente tendría acceso.
- Toda guía creada por la app registra procedencia en `guia_origen` y
  `forsis_guia_creation_registry`; un `INSERT` directo en `sicrePR.guias` rompe esa auditoría y
  probablemente **falla** de todas formas porque el esquema SICRET es `NOT NULL` sin default en
  todas las columnas (`trafico-system-analysis.md §4.3`).

### 3.3 Conclusión de la sección

DB-direct para escritura no es "más rápido pero arriesgado": es **funcionalmente incompleto**. Para
igualar lo que ya hace la capa de aplicación (FIFO con locks, máquina de estados, integración
ATLAS, registro de auditoría), el agente tendría que reimplementar esa capa en Python — momento en
el que ya no se está evitando acoplamiento, se está duplicando la aplicación entera con el riesgo
añadido de que las dos implementaciones diverjan con el tiempo.

---

## 4. Comparación por los cuatro criterios pedidos

### 4.1 Latencia

| | API-only | DB-direct | Híbrido (recomendado) |
|---|---|---|---|
| Lectura simple (1 entidad) | 1 HTTP round-trip + parseo JSON + overhead de sesión PHP | 1 query SQL, pool persistente, sin HTTP | Igual que DB-direct |
| Lectura cruzada/analítica (N entidades) | N round-trips secuenciales (o `curl_multi` si el cliente lo implementa, como ya hace `AtlasClient::getMany()`) | 1 query con `JOIN`/agregación | Igual que DB-direct — **la ventaja de latencia es la razón primaria para elegir DB en lectura** |
| Escritura con invariantes de negocio | Latencia de la app (ya optimizada por el equipo que la mantiene) + validación server-side | Latencia mínima de SQL, pero **incorrecta** si no replica FIFO/estados/ATLAS | Igual que API-only — aceptable porque las escrituras son por-acción, no por-lote |

Veredicto: la latencia favorece DB-direct únicamente en lectura, y lo hace de forma decisiva para
los casos que motivaron la excepción del propio prototipo (analítica, agregaciones, cruces).

### 4.2 Complejidad

| | API-only | DB-direct | Híbrido |
|---|---|---|---|
| Cliente a construir | Cliente HTTP con sesión persistente, reintento en `SESSION_EXPIRED`, manejo de dos convenciones de respuesta (`ok/data` vs `success`) — ya anticipado en `trafico-system-actions.md §12` | Pool read-only (`readonly_session.py` ya existe y es reutilizable al 100% según `prototype-review.md §11.1`), sin manejo de sesión | Los dos clientes, pero cada uno acotado a su propósito: el cliente HTTP sólo maneja ~20 acciones de escritura, no las ~450 rutas |
| Mantenimiento ante cambios de schema | Cero impacto — la API es el contrato estable | Alto — requiere "validación de schema" como ya hizo el prototipo; el propio catálogo de Query Objects obsoletos (`search_by_name`, `active_customers`, etc. contra tablas que no existen) es evidencia de este costo real | El costo de schema-drift se paga **solo en lectura**, que es más tolerante a fallos (un query roto degrada una consulta, no corrompe un movimiento de tarjeta deudor) |
| Cobertura de casos de uso | Incompleta — faltan agregaciones, cruces multi-tabla, varias definiciones de "fuente de verdad" no expuestas (saldo real, unidad actual) | Completa para lectura; incompleta/peligrosa para escritura (sección 3) | Completa para ambos, cada ruta usando su fortaleza |

### 4.3 Mantenibilidad

- **API-only** es más mantenible a largo plazo *si* la API cubriera todos los casos — no lo hace
  hoy, y el costo real sería pedir al equipo de trafico/liquidaciones que añada decenas de
  endpoints de agregación sólo para el agente, inflando la superficie de ambos sistemas.
- **DB-direct puro** es frágil ante cambios de schema **en escritura** (un cambio de columna rompe
  silenciosamente un INSERT crítico), pero razonablemente estable en lectura si se practica lo que
  el propio prototipo recomienda y no formalizó: una capa de **Query Objects versionados +
  validación de schema en el arranque** (el prototipo ya construyó el patrón, sólo falta
  endurecerlo con tests de contrato contra el schema real, como recomienda
  `trafico-system-actions.md §12.10`).
- **Híbrido** acota el área frágil (escritura, baja frecuencia, alto impacto) al canal estable
  (API), y deja el área de alto volumen pero bajo impacto por error (lectura) al canal rápido. Esto
  es, además, exactamente el patrón de riesgo que ambos inventarios de acciones ya codifican
  (L0/L1 de lectura vs. L2/L3 de escritura, 🟢/🟡 vs 🔴).

### 4.4 Seguridad

| Vector | API-only | DB-direct | Híbrido |
|---|---|---|---|
| Superficie de credenciales | Una cookie de sesión por usuario de servicio, revocable (`session_version++`) | Usuario MariaDB dedicado read-only — revocable a nivel de grant, sin sesión que expire sola | Union de ambos, pero cada canal con el control nativo adecuado |
| Auditoría | Nativa: `guia_origen`, `forsis_guia_creation_registry`, bitácora de solicitudes de cancelación en `liquidaciones-system` | Ninguna automática — un `SELECT` directo no deja rastro de negocio, sólo lo que capture el propio agente | Las escrituras (que requieren auditoría) van por API; las lecturas (que no necesitan auditoría de negocio) van por DB — sin pérdida de trazabilidad donde importa |
| Riesgo de escalamiento de daño | Acotado: la API ya valida permisos por rol en cada escritura | **Alto si se usa para escritura**: un usuario MariaDB con permiso de `INSERT/UPDATE` puede saltarse toda la lógica de negocio, incluida la máquina de estados y el registro de auditoría | El usuario DB del agente es **estrictamente read-only** a nivel de grant MySQL (`GRANT SELECT ON sicrePR.* TO 'agente_ia_ro'@...`) — cero superficie de escritura accidental, con o sin bug en el código del agente |
| Exposición de red | Ninguna nueva — reutiliza el login HTTP existente | Ninguna nueva — reutiliza conectividad ya existente entre `forsis-comunicaciones` y `192.168.1.209:3306` (sección 2.3) | Igual, cero infraestructura nueva requerida |
| Fail-closed ya planeado | `AGENT_WRITE_ALLOWLIST: ""` en `deployment-strategy.md §8` — coherente con el patrón de `forsis-bot` (`AGY_USUARIOS_AUTORIZADOS`) | N/A (si fuera solo lectura) | El patrón fail-closed aplica naturalmente a la mitad de escritura (API); la mitad de lectura no necesita allowlist porque no tiene efecto lateral |

**El argumento de seguridad decisivo:** otorgar `GRANT SELECT` (sin `INSERT`/`UPDATE`/`DELETE`) a un
usuario de MariaDB dedicado es una garantía **a nivel de motor de base de datos**, no de disciplina
de código de aplicación. Es estrictamente más fuerte que confiar en que el agente "nunca escriba
directo" por convención (que es, literalmente, lo que el ADR-0001 del prototipo intentó y el código
real no respetó). El híbrido convierte esa garantía en la frontera arquitectónica real.

---

## 5. Lo que el híbrido NO es (para evitar reinterpretaciones laxas)

1. **No es "lectura por donde sea más conveniente caso a caso".** La regla es binaria y por tipo de
   operación: toda escritura/acción pasa por HTTP con sesión de usuario de servicio; toda lectura
   analítica o de alto volumen va por SQL read-only. No hay zona gris de "esta lectura es tan
   simple que mejor la hago por API" — hacerlo así reintroduce el problema de latencia/sesión de la
   sección 4.1 sin necesidad.
2. **No es acceso DB sin cuentas.** Requiere usuarios MariaDB dedicados, `GRANT SELECT` explícito,
   sin `root` ni las credenciales de servicio de trafico/liquidaciones (ya recomendado en
   `deployment-strategy.md §8`, pendiente de creación como ítem de Fase 1 en
   `deployment-strategy.md §11.6`).
3. **No elimina la necesidad del cliente HTTP con sesión.** Ese cliente sigue siendo obligatorio
   para el conjunto acotado de ~20-30 acciones de escritura catalogadas en
   `trafico-system-actions.md` y `liquidaciones-system-actions.md`, con su propio manejo de
   `SESSION_EXPIRED`, `set_empresa` explícito y allowlist de operadores.
4. **No resuelve por sí solo el gating de riesgo 🟡/🔴 — L2/L3.** Esa es una capa ortogonal
   (confirmación humana, dry-run, aprobación en dos pasos) que debe existir **encima** de la capa
   de acceso a datos, no en vez de ella.

---

## 6. Qué cambia respecto al prototipo abandonado (reconciliación formal)

| Punto | Prototipo (`forsis-agent`) | Este proyecto |
|---|---|---|
| Documento declarado | ADR-0001: API-only, "estrictamente prohibido" DB-direct | Este documento: Híbrido, DB-direct **permitido y recomendado** para lectura, **prohibido** para escritura |
| Código real | 100% DB-direct, incluida la (inexistente) escritura — nunca llegó a implementar acciones de escritura reales | DB-direct read-only por grant de motor (no por convención) + cliente HTTP real para las ~20-30 acciones de escritura catalogadas |
| Formalización | Excepción documentada en un blueprint operativo, nunca llevada al ADR | Este documento **es** el ADR explícito que el prototipo nunca completó |
| Reutilización | `readonly_session.py`, pool config, Query Object pattern: reutilizables al 100% según `prototype-review.md §11.1` | Se reutilizan directamente, extendiendo el pool a `trafico` (MariaDB 11 propia) además de SICRET |

---

## 7. Matriz de decisión operativa (para implementación)

| Tipo de operación | Canal | Ejemplos concretos |
|---|---|---|
| Listados, detalles, KPIs, catálogos | **DB read-only** | `SELECT` sobre `guias`, `liquidaciones`, `tarjeta_contenido`, `detliq`, `guia_pases_descarga` |
| Agregaciones y cruces multi-tabla | **DB read-only** | Saldo real (`SUM(importeRestante)`), reconciliación vale-diésel↔liquidación↔guía, detección de guías sin pase de descarga > N días |
| Clasificaciones que dependen de tabla de origen, no de texto | **DB read-only** | BONO vs COBRO (`premiosliq` vs `gastosliq`), estado de reseteo (`estado`/`requiere_revision`) |
| Crear/editar/copiar guía, sellos, planeación | **API REST** (`trafico-system`) | `POST /api/guias/crear`, `/api/guias/editar`, `/api/guias/sellos/actualizar` |
| Liberación SICRET→ATLAS, timbrado | **API REST** (`trafico-system` → ATLAS) | `POST /api/guias/liberacion/solicitar`, `/api/guias/timbrado/solicitar` |
| Emisión/cancelación fiscal (CFDI, pagos, nómina) | **API REST**, siempre 🔴 con confirmación humana | `POST /api/facturacion/factura-normal/emitir`, nunca ejecutado sin aprobación explícita |
| Crear solicitud de cancelación/edición (liquidaciones) | **API REST** — ruta preferida, es el único gate de aprobación existente | `POST /api/solicitud_cancelacion.php?action=crear` |
| Autorizar liquidación, movimiento de tarjeta, aprobar cancelación | **API REST**, nunca ejecutado por el agente sin aprobación humana — ❌ irreversible | `autorizar_liquidacion.php`, `movimiento_tarjeta.php` |

---

## 8. Requisitos de implementación derivados (Fase 1)

1. **Crear usuarios MariaDB dedicados de solo lectura** para `sicrePR`, `sicreGero` y `trafico`
   (ya identificado como pendiente en `deployment-strategy.md §11.6`). Verificar `--ssl=0` por la
   falta de TLS en `192.168.1.209` (`trafico-system-analysis.md §4.1`).
2. **Reutilizar `readonly_session.py`** del prototipo (pool, multiempresa, charset dual
   latin1/utf8mb4) extendiéndolo con una tercera conexión a `trafico` (MariaDB 11 propia, 114
   tablas).
3. **Construir Query Objects nuevos contra el esquema ya validado** en
   `trafico-system-analysis.md §4.2` y `liquidaciones-system-analysis.md §3`, **no** reutilizar los
   4 Query Objects obsoletos del prototipo que consultan tablas inexistentes (`cat_clientes`,
   `fac_facturas`, `ope_viajes`).
4. **Construir el cliente HTTP de escritura** siguiendo exactamente el checklist de
   `trafico-system-actions.md §12`: login + heartbeat + `set_empresa` explícito en cada sesión +
   wrapper `guarded()` con dry-run y confirmación humana para 🟡/🔴.
5. **Nunca compartir cookie jar** entre el canal de escritura del agente y cualquier sesión humana
   — contenedores/procesos de sesión aislados por diseño.
6. **Allowlist fail-closed** (`AGENT_WRITE_ALLOWLIST: ""` por defecto, ya en
   `deployment-strategy.md`) aplica únicamente al canal de escritura; el canal de lectura no
   requiere allowlist porque el grant `SELECT` ya es la barrera de seguridad.
7. **Tabla de auditoría propia** en la BD PostgreSQL del agente para registrar toda acción de
   escritura ejecutada vía API (actor humano, acción, payload, resultado) — complementa, no
   sustituye, la auditoría nativa de `guia_origen`/`forsis_guia_creation_registry`.

---

## 9. Riesgos residuales del híbrido (y mitigación)

| Riesgo | Mitigación |
|---|---|
| Schema drift en lectura (columna renombrada/eliminada rompe una Query Object) | Tests de contrato contra el schema real en CI, igual que recomienda `trafico-system-actions.md §12.10`; fallo degrada esa consulta, no corrompe datos |
| El agente lee un dato en transición de estado (ventana de carrera entre SELECT y un POST posterior) | Re-validar siempre contra la API antes de actuar (`validarBloqueoPorFolios`, `/api/guias/liberacion/validar`) — ya es el patrón que exige la propia aplicación para sus usuarios humanos |
| Dos fuentes de verdad percibidas (DB para leer, API para escribir) confunden a quien audite el código | Este documento + comentario de cabecera en el cliente de datos del agente señalando la frontera explícita |
| Carga adicional de `SELECT`s de agente sobre SICRET compartido | Usuario dedicado permite *throttling*/monitoreo por conexión a nivel de MySQL; pool con límites conservadores (`pool_size`, `max_overflow` ya configurados en el prototipo) |

---

## 10. Conclusión

La evidencia ya recolectada —no una preferencia de diseño abstracta— apunta a una frontera clara:
**las garantías de un motor SQL (`GRANT SELECT`) son más fuertes y más baratas que una API para
lectura de alto volumen; las garantías de una aplicación con máquina de estados y FIFO bajo lock
son irremplazables para escritura.** El híbrido no es una transigencia entre A y B: es reconocer
que ambos sistemas ya operan así internamente (sesión HTTP para mutar estado de negocio, acceso SQL
compartido para todo lo demás) y alinear al agente con esa misma frontera, formalizándola donde el
prototipo anterior la dejó implícita y a medio documentar.
