# Forsis AI Agent — Arquitectura de Runtime Python/FastAPI (Fase 1, estado REAL)

**Fecha:** 2026-10-05
**Estado:** Migración ejecutada y verificada empíricamente (build + `compose config`). **No es un diseño propuesto: es lo que hay en disco.**
**Stack:** Python 3.12-slim (Debian bookworm) + FastAPI 0.111 + uvicorn 0.30.1 + Nginx Alpine + PostgreSQL 16 Alpine
**Reemplaza a:** la capa de runtime de `architecture.md` (PHP 8.3-fpm / Laravel 11), ahora **obsoleta**. Ver §9 para el diff conceptual.
**Autoridad de la decisión:** `ADR-001-stack-y-secuencia.md` (ACEPTADO, decisión del usuario).

> **Alcance de este documento.** Describe la **capa de runtime**. Lo que NO cambia con la migración y por tanto no se repite aquí:
> - `db-schema.md` — el esquema PostgreSQL es agnóstico al lenguaje. Sigue vigente al 100%.
> - `data-access-strategy-analysis.md` — la regla híbrida (lectura=DB read-only / escritura=API REST) es una decisión de arquitectura de datos, no de stack. Sigue vigente al 100%.
> - `llm-provider.md` — el contrato de Omniroute, los timeouts y los bloqueantes B-2/B-3/B-4 siguen vigentes. Este documento sólo añade **cómo** se materializan en uvicorn/httpx.
> - `channels.md` — la decisión de proxy same-origin sigue vigente y es la que permite no publicar el 8099.

---

## 1. Estado verificado de la migración

| Artefacto | Estado | Verificación |
|---|---|---|
| `docker-compose.yml` | Servicios `db`, `app`, `nginx`. El servicio `php` ya no existe | `docker compose config` → **exit 0** |
| `docker/app/Dockerfile` | `python:3.12-slim`, multi-stage (`base` → `builder` → `stage-2`), `USER agentuser` (uid 1000) | `docker compose build app` → **exit 0**, imagen `sha256:d769eea1f62f` (300 MB) |
| `docker/app/entrypoint.sh` | Espera de BD + hook de migraciones + `exec "$@"` | Presente. **Ver BLOQUEANTE B-P3 en §10** |
| `docker/nginx/default.conf` | `proxy_pass` a `upstream fastapi_backend` (`app:8000`). **0 ocurrencias de `fastcgi`** | `grep -c fastcgi` → 0 |
| `docker/db/init/01-init-schema.sql` | DDL inicial, montado `:ro` en `/docker-entrypoint-initdb.d` | Presente |
| `app/main.py` (49 líneas) + `app/__init__.py` | App FastAPI: `/health`, `/`, `POST /api/v1/chat` (stub 501-lógico) | `python -c "import app.main"` dentro de la imagen → **OK** |
| `requirements.txt` | Versiones todas fijadas (`==`) | Instalado en build sin conflictos |
| `docker/php/` | **Retirado** | El directorio no existe |
| `.gitignore` | Python (se eliminaron restos de Laravel `/vendor/`, `/storage/framework/`) | Revisado |
| `.dockerignore` | **Creado en esta revisión** (§8.1) | Build confirma que `knowledge/` no entra |

**Madurez real del código:** `app/` contiene únicamente el esqueleto HTTP. **No existe todavía capa de datos, ni providers, ni Planner/Executor** — `grep` de `asyncpg|sqlalchemy|psycopg|pymysql` sobre `app/` devuelve **cero** ocurrencias. Esto es importante para leer el resto del documento: las secciones §5–§7 describen **el contrato que la implementación debe cumplir**, derivado de las dependencias ya fijadas y de los análisis de Fase 0/1, no código ya existente. Están marcadas con 🔜 donde aplica.

---

## 2. Topología de contenedores y redes (real)

```
                        [ Usuario / Widget / forsis-bot / Webhook ]
                                            │
                              HTTPS :8099 → :443  (ÚNICO puerto publicado)
                                            │
                    ┌───────────────────────▼────────────────────────┐
                    │          forsis-ai-agent-nginx                 │
                    │              (nginx:alpine)                    │
                    │  TLS: /etc/letsencrypt:ro (forsispr1.ddns.net) │
                    │  :443 TLS público  ·  :8080 plano SOLO interno  │
                    │  upstream fastapi_backend { app:8000;           │
                    │                             keepalive 32; }     │
                    │  límites: 0.25 vCPU / 64 MB                     │
                    └───────────────────────┬────────────────────────┘
                                            │
                              HTTP/1.1 proxy_pass  (NO FastCGI)
                              Connection: ""  → keepalive al upstream
                              red: default
                                            │
                    ┌───────────────────────▼────────────────────────┐
                    │           forsis-ai-agent-app                  │
                    │     forsis-ai-agent-app:local (python:3.12)    │
                    │     uvicorn app.main:app --workers 2 :8000     │
                    │     USER agentuser (uid 1000, no-root)         │
                    │     límites: 1.5 vCPU / 1 GB                   │
                    └──┬──────────────┬──────────────┬───────────┬───┘
                       │              │              │           │
      red: default ────┘   ai-network ┘   forsis-comunicaciones ┘   │ extra_hosts
                       │              │              │              │ host-gateway
                       ▼              ▼              ▼              ▼
          ┌──────────────────┐ ┌─────────────┐ ┌──────────────┐ ┌──────────────────┐
          │forsis-ai-agent-db│ │forsis-memory│ │trafico-system│ │ Omniroute :20130 │
          │ postgres:16-alpine│ │  (pgvector) │ │  API REST    │ │ /v1/chat/compl.  │
          │ asyncpg, pool propio│ │   PG 16    │ │ (escrituras) │ │ combo "Forsis"   │
          │ **SIN `ports:`**  │ │            │ │   httpx      │ │     httpx        │
          │ 0.5 vCPU / 512 MB │ └─────────────┘ └──────────────┘ └──────────────────┘
          └──────────────────┘
                                                  │
                        ┌─────────────────────────┘
                        ▼  (lecturas read-only, fuera de Docker)
          ┌──────────────────────────────────────────────────┐
          │   SICRET MariaDB  192.168.1.209:3306             │
          │   sicrePR / sicre2PR / sicreGero / sicre2Gero     │
          │   latin1 · SIN TLS (--ssl=0) · GRANT SELECT only │
          │   PyMySQL + pool read-only                        │
          └──────────────────────────────────────────────────┘
```

### 2.1 Segmentación de redes (sin cambios respecto a `architecture.md`)

La migración de stack **no tocó la topología de red**. Se conserva íntegra porque la decisión era independiente del lenguaje:

| Red | Miembros | Garantía |
|---|---|---|
| `default` (bridge del stack) | `nginx`, `app`, `db` | `db` está **sólo** aquí y **sin directiva `ports:`** → inaccesible desde el host y desde otros contenedores |
| `ai-network` (external) | `app` ↔ `forsis-memory` (pgvector) | Memoria vectorial compartida. Debe existir antes del `up` |
| `forsis-comunicaciones` (external) | `app` ↔ `trafico-system` | Canal de escrituras vía API REST |
| `host.docker.internal` (host-gateway) | `app` → Omniroute `:20130` | `extra_hosts: ["host.docker.internal:host-gateway"]` |

Verificado en el host: `docker network ls` confirma que **`ai-network` y `forsis-comunicaciones` ya existen**.

**Único cambio nominal:** el miembro de las tres redes pasó de `forsis-ai-agent-php` a `forsis-ai-agent-app`. Cualquier documento o `.env` de otro sistema que resuelva el agente por nombre de contenedor **debe actualizarse** (ver §10, B-P4).

### 2.2 Exposición: un solo puerto, y aún así cerrable

- **`8099:443`** es el único puerto publicado. Termina TLS con certificados Let's Encrypt de producción montados `:ro` desde el host.
- **`:8080`** es `expose:` (no `ports:`) — listener HTTP plano **sólo** visible dentro de las redes Docker. Lo consumen `forsis-bot` y los proxies PHP de trafico/liquidaciones, evitando el coste de TLS en tráfico intra-host.
- Por la decisión de **proxy same-origin** de `channels.md` §2.2, el widget llama a `/api/ai/chat` en el origen del anfitrión, no a `:8099`. **Consecuencia: el `8099` se puede cerrar por completo**, que es la mitigación del bloqueante B-C1. Este documento no lo cierra (sigue publicado hoy), sólo registra que nada en el stack Python lo impide.

---

## 3. Flujo HTTP: nginx → uvicorn

```
 1. Cliente        →  TLS handshake contra nginx:443 (TLSv1.2/1.3, HIGH:!aNULL:!MD5)
 2. nginx          →  evalúa `location`:
                        /health          → return 200 "healthy" (NO toca a la app, access_log off)
                        /static/ /assets/→ alias a /var/www/html (bind-mount :ro), expires 1y
                        ~ /\.(?!well-known) → deny all  (bloquea .env, .git)
                        /ws              → proxy + Upgrade, read_timeout 86400
                        /                → proxy_pass http://fastapi_backend
 3. nginx→uvicorn  →  HTTP/1.1, Connection: "" (habilita keepalive al upstream, pool de 32)
                      X-Forwarded-Proto: https (fijo, no $scheme — el upstream siempre es TLS-terminado)
                      X-Real-IP / X-Forwarded-For preservados
 4. uvicorn        →  reparte la conexión entre 2 procesos worker (ASGI)
 5. app (FastAPI)  →  corutina del endpoint sobre el event loop uvloop
 6. Respuesta      →  buffering ON, buffer_size 128k, buffers 4x256k
```

**Diferencia estructural con el stack anterior:** ya no hay FastCGI ni un pool de procesos FPM. nginx deja de ser *el gestor del ciclo de vida de la aplicación* y pasa a ser **un reverse proxy HTTP ordinario**. uvicorn gestiona su propia concurrencia. Esto elimina la clase entera de fallos de `fastcgi_pass`/socket y de agotamiento de `pm.max_children`, y es lo que hace que el servicio sea observable con herramientas HTTP estándar.

**Cabeceras de hardening** (en nginx, no en la app): `X-Frame-Options: SAMEORIGIN`, `X-XSS-Protection`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin`. `client_max_body_size 25M`.

---

## 4. Modelo de concurrencia de uvicorn y su interacción con los timeouts 60 s / 120 s

Esta es la sección donde el cambio de stack tiene **consecuencias operativas reales**, no sólo de sintaxis.

### 4.1 Lo que hay configurado

```
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000",
     "--workers", "2", "--log-level", "info"]
```

- **2 procesos worker**, cada uno con su propio event loop (`uvloop`, vía `uvicorn[standard]`). Son procesos OS independientes: **no comparten memoria, ni pools de conexión, ni caché en proceso.**
- Dentro de cada worker, la concurrencia es **cooperativa**: miles de corutinas en espera de I/O conviven en un hilo. El límite real no son los 2 workers, es que **ninguna corutina bloquee el loop**.
- `--workers 2` encaja con el límite de **1.5 vCPU**: 2 workers pueden saturar ~1.5 núcleos sin que el cgroup los estrangule constantemente. Subirlos competiría por CPU y multiplicaría los pools de conexión (§5.4).

### 4.2 La cadena de timeouts, de fuera hacia dentro

| # | Capa | Valor | Fuente |
|---|---|---|---|
| 1 | nginx `proxy_connect_timeout` | 10 s | `default.conf` |
| 2 | nginx `proxy_read_timeout` / `proxy_send_timeout` | **120 s** | `default.conf` |
| 3 | **Presupuesto de turno del `AgentService`** | **120 s** | `agent-core.md` §4.3 🔜 |
| 4 | **Techo duro por llamada LLM** | **60 s** | `llm-provider.md` §2.2 (máx observado 34.6 s × 1.7) |
| 5 | `httpx` timeout al cliente Omniroute | 60 s | `OMNIROUTE_TIMEOUT_SECONDS` |
| 6 | Reintentos de formato | máx 2 (3 intentos) | `OMNIROUTE_MAX_RETRIES` |

**El conflicto que hay que ver:** 3 intentos × 60 s = **180 s teóricos**, contra un `proxy_read_timeout` de **120 s**. No es un error de configuración — es el diseño de `llm-provider.md`: **el presupuesto de turno (120 s) manda sobre la suma de los techos por llamada**. El `AgentService` debe cortar el turno a 120 s aunque le queden reintentos.

> 🔜 **Requisito de implementación no negociable.** Si el `AgentService` no implementa el corte de turno a 120 s, nginx devolverá **504** al cliente mientras el worker sigue quemando CPU y tokens en un reintento cuya respuesta nadie va a leer. `channels.md` §273 pide además `proxy_read_timeout` **130 s** en el nginx del agente para que la capa de red nunca corte antes que la aplicación. **Hoy está en 120 s = empate con el presupuesto de turno; conviene subirlo a 130 s** para dejar el margen que pide el diseño de canales. Registrado como B-P1 en §10.

### 4.3 El riesgo específico de este stack: bloquear el event loop

En PHP/FPM cada request era un proceso aislado: una llamada bloqueante de 35 s afectaba *a ese worker* y FPM tenía decenas. En uvicorn con 2 workers, **una sola corutina que bloquee el loop congela todas las demás peticiones de ese worker** — es decir, ~50% de la capacidad del servicio.

Dado que las latencias medidas de Omniroute son p50 3.6 s / p95 10.5 s / **máx 34.6 s** (`llm-provider.md` §2.1), esto no es teórico. Reglas derivadas, obligatorias:

1. **Todo I/O en corutinas async.** `httpx.AsyncClient` para Omniroute y para la API REST de trafico. `asyncpg` para PostgreSQL. Nunca `requests`, nunca `psycopg2` síncrono (razón adicional para §8.2).
2. **PyMySQL es síncrono y no tiene alternativa async aquí** → toda consulta a SICRET va en `run_in_executor` / `asyncio.to_thread`, con un threadpool acotado. Es la excepción consciente, y está aislada en hilos precisamente para no tocar el loop (§5.3).
3. **El `ThreadPoolExecutor` + `future.result(timeout=…)` del prototipo se conserva.** `llm-provider.md` §2.2 lo justifica con un incidente real: una petición colgada >50 min sin que `httpx.ReadTimeout` se disparara. El timeout del cliente HTTP **no es suficiente por sí solo**; hace falta el techo de pared.
4. **Sin estado en memoria del worker.** Con 2 workers sin memoria compartida, dos peticiones del mismo usuario pueden caer en workers distintos. Historial de conversación, sesiones y rate-limits viven en PostgreSQL, no en variables de proceso.

### 4.4 Capacidad estimada

El agente es **I/O-bound, no CPU-bound**: un turno es mayoritariamente espera de Omniroute (p50 3.6 s). Con 2 workers y presupuesto de 120 s/turno, el techo lo pone el pool de conexiones y la cola de Omniroute, no la CPU. Cálculo conservador: con p50 de 3.6 s y ~10 corutinas concurrentes por worker sin presión de pool, el stack sostiene del orden de **2–5 turnos/segundo en el caso bueno (caché semántica) y ~0.3–0.5 turnos/segundo en el caso p95**. 🔜 Sin medir end-to-end (no hay núcleo todavía); no tratar como SLO.

---

## 5. Estrategia de conexiones

Tres destinos de datos con tres mecanismos distintos. La frontera lectura/escritura es la de `data-access-strategy-analysis.md` y **no la cambia la migración**.

### 5.1 PostgreSQL propio (`db`) — pool asyncpg vía SQLAlchemy async 🔜

```
DSN:    postgresql+asyncpg://${DB_USERNAME}:***@db:5432/${DB_DATABASE}
Driver: asyncpg 0.29.0  (único driver PG — ver §8.2)
Capa:   SQLAlchemy 2.0.31 [asyncio] → create_async_engine()
```

**Dimensionamiento, derivado del límite real del motor.** `db` arranca con `max_connections=60` (`command:` del compose). Reparto:

| Consumidor | Conexiones |
|---|---|
| 2 workers uvicorn × (`pool_size` 5 + `max_overflow` 5) | hasta **20** |
| Alembic en arranque (puntual, `RUN_MIGRATIONS=true`) | 1–2 |
| `psql` de depuración / healthchecks | ~3 |
| **Techo del agente** | **~25 de 60** → margen amplio |

> **`pool_size` se multiplica por el número de workers, no se reparte.** Cada proceso crea su propio pool. Si alguien sube `--workers` a 4 sin bajar `pool_size`, el consumo salta a 40 y se empieza a competir con todo lo demás. Dejar constancia en el `.env`.

Recomendado: `pool_pre_ping=True` (sobrevive reinicios de `db`) y `pool_recycle=1800`.

### 5.2 `forsis-memory` (pgvector, vía `ai-network`) 🔜

Segundo engine async independiente (`MEMORY_DB_HOST`/`MEMORY_DB_PORT`), pool más pequeño (`pool_size` 2–3): el acceso es esporádico (RAG), no por request. Es una BD ajena al stack — **no se le aplican migraciones de Alembic** (§6).

### 5.3 SICRET MariaDB read-only — el caso delicado

```
Host:     192.168.1.209:3306   (fuera de Docker; ya compartido por trafico y liquidaciones)
Bases:    sicrePR, sicre2PR, sicreGero, sicre2Gero
Driver:   PyMySQL 1.1.1 (+ cryptography, requerida para el handshake de auth)
Permisos: GRANT SELECT únicamente — garantía a nivel de MOTOR, no de código
```

Tres restricciones verificadas en Fase 0 que la implementación debe respetar literalmente:

1. **SIN TLS.** El servidor no lo soporta → conexión explícita con `ssl=None`/`ssl_disabled=True` (equivalente a `--ssl=0`). Variable: `ERP_SICRET_SSL_DISABLED=true`. **No es una preferencia: sin esto la conexión falla.** Mitigante: el tráfico es LAN interna. Registrado como riesgo residual, no resuelto.
2. **`latin1`, con riesgo real de mojibake.** `charset="latin1"` explícito por conexión (`ERP_SICRET_CHARSET=latin1`). Nunca asumir utf8mb4. Toda cadena que salga de SICRET hacia un prompt LLM o hacia JSON se normaliza a UTF-8 en la frontera del repositorio — **una sola vez y en un solo sitio**. Doble decodificación produce `Ã±` silenciosamente, y el LLM lo propagará a la respuesta del usuario sin error visible.
3. **Síncrono → aislado en hilos.** PyMySQL bloquea. Toda query va por `asyncio.to_thread` con un threadpool acotado (sugerido 4–8 hilos **por worker**), para no congelar el event loop (§4.3) ni abrir conexiones sin límite contra un servidor de producción compartido por dos sistemas más.

Además, por diseño: `SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY` al abrir, defensa en profundidad **encima** del `GRANT SELECT`. Nunca las credenciales de servicio de trafico/liquidaciones, nunca `root`: usuario dedicado.

### 5.4 Omniroute y API REST de trafico — `httpx` 🔜

| Destino | Cliente | Config |
|---|---|---|
| Omniroute (LLM) | `httpx.AsyncClient` | `base_url=http://host.docker.internal:20130/v1`, `timeout=60`, `Authorization: Bearer ***` **siempre** (aunque hoy no se valide — B-4) |
| API REST trafico (escrituras) | `httpx.AsyncClient` | login + heartbeat + `set_empresa` explícito; **cookie jar NUNCA compartido** con sesiones humanas |

Dos puntos heredados de los análisis, que siguen siendo obligatorios:
- **Un fallo de transporte contra Omniroute NO se reintenta** (se propaga como `ProviderError`). Omniroute ya hace failover entre proveedores; reintentar desde el agente sólo suma latencia a un fallo definitivo. Los reintentos son **exclusivamente por formato de respuesta inválido**.
- `OMNIROUTE_BASE_URL` en el compose es `.../v1` y la ruta es `/chat/completions`. `architecture.md` §4 documentaba `/api/v1/...`; **la forma verificada en `llm-provider.md` §4.3 es `POST {base}/v1/chat/completions`**. El compose actual ya está correcto; cuidado al concatenar y no duplicar el `/v1`.

### 5.5 Fail-closed de escrituras

`AGENT_WRITE_ALLOWLIST: ""` y `AGENT_DRY_RUN_DEFAULT: "true"` están fijados en el `environment:` del compose (no en `.env`), es decir **en el artefacto versionado**. Con allowlist vacía, **cero acciones de escritura** se ejecutan. Esto es intencional: el estado por defecto del stack recién desplegado es inocuo, y habilitar escrituras exige un cambio explícito y revisable.

---

## 6. Migraciones con Alembic

**Estado real: `alembic` está en `requirements.txt` y el binario existe en la imagen (`/home/agentuser/.local/bin/alembic`), pero NO hay `alembic.ini` ni directorio `alembic/` en el repositorio.** El schema se aplica hoy **únicamente** vía `docker/db/init/01-init-schema.sql`, que `postgres:16-alpine` ejecuta **sólo en la primera inicialización del volumen** (`forsis-ai-agent_db_data` vacío).

Y el entrypoint lo dice explícitamente:

```bash
if [ "$RUN_MIGRATIONS" = "true" ]; then
    # TODO: alembic upgrade head cuando se implemente Alembic
fi
```

### 6.1 Consecuencia operativa que hay que entender ahora

El modelo actual **no tiene ruta de evolución de schema**. Si `db-schema.md` cambia una tabla después del primer arranque:
- `01-init-schema.sql` **no se vuelve a ejecutar** (el volumen ya está inicializado),
- y no hay migración que aplique el delta.

El resultado es deriva silenciosa entre el schema documentado y el real. En Fase 1, con una sola instancia y datos descartables, es tolerable. **Deja de serlo en el momento en que haya datos de auditoría que no se puedan perder** — y `db-schema.md` §1.3 define `audit_records` y `tool_executions` como append-only forense. Registrado como **B-P2** en §10.

### 6.2 Estrategia objetivo 🔜

1. `alembic init -t async alembic` — **plantilla async obligatoria**: con un solo driver `asyncpg` (§8.2), el `env.py` sincrónico por defecto no funciona. La plantilla async usa `connection.run_sync(context.run_migrations)` sobre el engine async.
2. `sqlalchemy.url` **no** se escribe en `alembic.ini`: se lee de entorno en `env.py` (el `.ini` es versionable y no debe contener credenciales).
3. **Migración 0 = el estado actual de `01-init-schema.sql`**, para que una BD creada por el init-script y una creada por Alembic converjan al mismo schema.
4. Tras eso, `01-init-schema.sql` se reduce a lo que Alembic no puede hacer bien: `CREATE EXTENSION`, roles, `GRANT`.
5. `RUN_MIGRATIONS` se mantiene **`false` por defecto** (así está en `.env.example`): ejecutar DDL automáticamente en cada arranque de un contenedor con `restart: unless-stopped` es un riesgo. Migración = paso deliberado de despliegue.

---

## 7. Seguridad del runtime

### 7.1 Usuario no-root — verificado

```
RUN useradd -m -u 1000 -s /bin/bash agentuser     # en el stage `base`
COPY --chown=agentuser:agentuser ./app /app/app
USER agentuser                                     # antes de ENTRYPOINT
```

Verificado dentro de la imagen: `id` → `uid=1000(agentuser) gid=1000(agentuser)`. uvicorn escucha en **:8000** (>1024), por lo que no necesita capacidades para bind. TLS y el puerto privilegiado son problema de nginx, no de la app.

**Nota sobre el multi-stage:** las dependencias se instalan con `pip install --user` en `builder` (quedan en `/root/.local`) y se copian a `/home/agentuser/.local` con `ENV PATH=/home/agentuser/.local/bin:$PATH`. El resultado es que `gcc`, `libpq-dev` y los headers de MySQL **no están en la imagen final** — sólo `libpq5`, el cliente MySQL y `curl`. Menor superficie de ataque y menor tamaño (300 MB).

**Observación menor:** `COPY --from=builder /root/.local /home/agentuser/.local` no lleva `--chown`, por lo que los paquetes quedan propiedad de `root` y `agentuser` sólo puede leerlos/ejecutarlos. **Es la postura correcta** (el runtime no puede modificar sus propias dependencias); se deja así a propósito.

### 7.2 Secretos

- Todos vía `env_file: .env` (modo 600, en `.gitignore`). El `environment:` del compose contiene **sólo** valores no sensibles (hosts, flags, nombres de modelo).
- `.env.example` usa marcadores `[REDACTED_...]`, sin valores reales.
- `.dockerignore` (§8.1) excluye `.env`, `*.pem`, `*.key` del **contexto de build**, de modo que no pueden acabar en una capa ni siquiera por accidente.
- nginx bloquea `location ~ /\.(?!well-known).*` → `.env` y `.git` no son servibles por HTTP.
- Pendiente ajeno a este stack, no resuelto aquí: el `BOT_TOKEN` commiteado (`ADR-001` §Consecuencias) sigue siendo un incidente abierto antes de reactivar el canal Mattermost.

### 7.3 Lo que este stack NO arregla

- **B-4 (Omniroute sin autenticación):** `POST /v1/chat/completions` en `0.0.0.0:20130` responde 200 sin `Authorization` y con Bearer inválido. Es un defecto de Omniroute, no del agente. El provider envía la cabecera siempre para no romperse cuando se cierre el hueco, pero **cualquiera con acceso de red al host puede consumir el presupuesto de tokens del combo**. Reportar al dueño de Omniroute.
- **B-2 / B-3 (JSON mode 70%, prompt inyectado de ~4.000 tokens, modelo no fijable):** propiedades del combo, no del lenguaje. Las 4 capas de defensa de `llm-provider.md` §3.3 siguen siendo obligatorias.

---

## 8. Revisión de los dos defectos detectados (ENTREGABLE 2)

### 8.1 (a) `knowledge/` dentro de la imagen → **ELIMINADO**

**Hallazgo.** El Dockerfile hacía:

```dockerfile
COPY --chown=agentuser:agentuser ./knowledge /app/knowledge   # ← eliminado
```

metiendo **764 KB** (46 ficheros markdown) de documentación interna en la imagen de runtime. El contenido no es inocuo — incluye, entre otros:
- `liquidaciones-security-strategy.md` y `infrastructure-analysis.md`,
- el hallazgo **B-4** (endpoint de inferencia de Omniroute sin autenticar, con puerto y método exactos),
- `llm-provider.md` (credenciales/puertos del gateway, modos de fallo),
- `trafico-system-analysis.md` (que el schema SICRET es `NOT NULL` sin defaults, rutas de API, nombres de tablas y la máquina de estados de guías),
- la contraseña-por-defecto multiempresa de `liquidaciones-system` (`$_SESSION['empresa']` → `'forsis'`).

En conjunto es un **mapa de ataque de los sistemas de producción de la empresa**, dentro de un artefacto que se distribuye, se cachea en registries y se puede extraer con `docker save` sin ejecutar nada.

**¿Lo necesita el runtime?** **No.** Verificado por tres vías independientes:

| Verificación | Resultado |
|---|---|
| `grep -rn "knowledge" app/ docker/app/entrypoint.sh` | **0 ocurrencias** |
| `grep -rniE "rag\|embed\|vector\|chroma\|faiss\|loader\|\.md" app/` | **0 ocurrencias** |
| ¿Existe capa de RAG en `app/`? | No. `app/` son 49 líneas: `/health`, `/`, y un stub de `/api/v1/chat` |

**Y el detalle que lo cierra:** el compose ya monta `./knowledge:/app/knowledge:ro` como bind-mount. Es decir, **en ejecución el bind-mount tapaba (shadow) el contenido copiado en la imagen**. La capa no sólo era peligrosa: era *inerte*. Se pagaba el riesgo sin obtener el beneficio.

**Acción tomada.**
1. Línea `COPY ... ./knowledge ...` **eliminada**, con comentario in-situ explicando por qué, para que nadie la reponga.
2. **`.dockerignore` creado** (no existía). Excluye del contexto de build: `knowledge/`, `*.md`, `.git/`, `.env`/`.env.*` (con `!.env.example`), `*.pem`/`*.key`/`*.crt`, `__pycache__/`, `venv/`, caches de pytest/mypy/ruff, `tests/`, `logs/`, `storage/`, `docker-compose.yml`, `docker/nginx/`, `docker/db/`, y ficheros de editor.

**Decisión para RAG en Fase 2.** Cuando exista capa de RAG, el conocimiento **no vuelve a la imagen**. Razones: (1) el corpus cambia a ritmo distinto que el código — hornearlo obliga a rebuild+redeploy por cada corrección de texto; (2) `db-schema.md` §1.5 ya define `rag_documents`/`rag_chunks` en PostgreSQL con los embeddings en `forsis-memory`, o sea **el destino del conocimiento es la BD, no el filesystem de la imagen**; (3) el corpus debe ser un subconjunto curado y clasificado, no el volcado de las notas de análisis internas. Vía correcta: ingestar desde el bind-mount `:ro` (o desde un volumen dedicado) hacia `rag_documents`/pgvector en un job de indexación.

**Verificado tras el cambio:**
```
docker run --rm --entrypoint sh forsis-ai-agent-app:local -c 'ls -la /app; test -e /app/knowledge && echo PRESENT || echo ABSENT'
  total 12
  drwxr-xr-x 3 agentuser agentuser 4096  app
  --- knowledge? ---
  ABSENT (OK)
```

### 8.2 (b) Redundancia de drivers PostgreSQL → **`psycopg2-binary` ELIMINADO**

**Hallazgo.** `requirements.txt` declaraba **tres** paquetes para PostgreSQL más el ORM:

| Paquete | Rol | ¿Redundante? |
|---|---|---|
| `psycopg2-binary==2.9.9` | Driver DBAPI **síncrono** | **SÍ — eliminado** |
| `asyncpg==0.29.0` | Driver **async** nativo | No — es el único coherente con FastAPI |
| `sqlalchemy==2.0.31` | Core/ORM — **no es un driver** | No |
| `alembic==1.13.2` | Migraciones — **no es un driver** | No |

**Análisis.** `sqlalchemy` y `alembic` no son drivers: son la capa de abstracción y la de migraciones, y ambas necesitan *un* DBAPI por debajo. La redundancia real era **`psycopg2-binary` + `asyncpg`: dos drivers para la misma base de datos**.

El criterio de desempate no es preferencia estética:
- **La aplicación es 100% async.** FastAPI + uvicorn + `uvloop`. Un driver síncrono usado en una corutina **bloquea el event loop** y, con sólo 2 workers, degrada ~50% de la capacidad del servicio (§4.3). `psycopg2` es exactamente ese riesgo, empaquetado y listo para que alguien lo importe sin pensar.
- **Dos drivers = dos DSN = dos pools** para la misma BD (`postgresql+asyncpg://` vs `postgresql+psycopg2://`), consumiendo del mismo `max_connections=60`, con dos sitios donde configurar timeouts y dos comportamientos distintos ante un reinicio de `db`.
- **El argumento habitual a favor de conservarlo —"Alembic necesita un driver síncrono"— es falso.** Alembic soporta engines async desde 1.6 con la plantilla `alembic init -t async`, que ejecuta las migraciones vía `connection.run_sync()`. Con Alembic 1.13.2 esto es territorio maduro, no experimental.
- **Nadie lo usaba.** `grep -rniE "psycopg|asyncpg|sqlalchemy|alembic|pymysql" app/` → **0 ocurrencias**. Eliminarlo ahora no rompe nada; eliminarlo después de que alguien lo importe, sí.

**Acción tomada.**
1. `psycopg2-binary==2.9.9` **eliminado** de `requirements.txt`.
2. `sqlalchemy==2.0.31` → **`sqlalchemy[asyncio]==2.0.31`**, que declara explícitamente el extra `greenlet` del que depende el soporte async. Antes funcionaba por dependencia transitiva; ahora es intencional y no se rompe si cambia el árbol de dependencias.
3. Decisión documentada como comentario en `requirements.txt`, junto a la nota de que Alembic debe inicializarse con `-t async`.

**No se eliminó `libpq5`** del Dockerfile: `asyncpg` trae su propia implementación del protocolo, pero `libpq5` es barato, lo usan utilidades de diagnóstico y retirarlo no aporta. Lo que ya **no** está en la imagen final es `libpq-dev`/`gcc` (viven sólo en el stage `builder`).

**Verificado tras el cambio, dentro de la imagen:**
```
pip list | grep -iE "psycopg|asyncpg|sqlalchemy|alembic|pymysql"
  alembic     1.13.2
  asyncpg     0.29.0
  PyMySQL     1.1.1
  SQLAlchemy  2.0.31

python -c "...":
  asyncpg 0.29.0 | sqlalchemy 2.0.31
  async engine dialect OK: postgresql asyncpg     ← create_async_engine("postgresql+asyncpg://...") construye
  psycopg2 present: False                          ← confirmado ausente
  app.main imports OK
```

### 8.3 Re-verificación tras ambos cambios (salida real)

```
$ docker compose config
config EXIT: 0
diff contra la salida previa a los cambios: IDENTICAL to baseline (no semantic change)

$ docker compose build app
#14 [stage-2 2/4] COPY --chown=agentuser:agentuser ./app /app/app
#14 DONE 0.1s
#15 [stage-2 3/4] COPY docker/app/entrypoint.sh /usr/local/bin/entrypoint.sh
#15 DONE 0.1s
#16 [stage-2 4/4] RUN chmod +x /usr/local/bin/entrypoint.sh
#16 DONE 0.4s
#17 exporting to image
#17 writing image sha256:d769eea1f62f42bdcf49bf9462e7a3841fb9f9567acdc929c00687dc273665f1 done
#17 naming to docker.io/library/forsis-ai-agent-app:local done
 forsis-ai-agent-app:local  Built
build EXIT: 0
```

Nótese que el stage-2 ahora tiene **4 pasos en vez de 5**: la capa de `knowledge` desapareció. Imagen final: **300 MB**, `sha256:d769eea1f62f` (la anterior era `sha256:d6982452b1f5`).

**No se levantó el stack ni se tocó ningún contenedor de otro proyecto.** Sólo `docker compose config`, `docker compose build app` y `docker run --rm` efímeros sobre la imagen propia.

---

## 9. Diff conceptual contra `architecture.md`

### 9.1 Tabla de cambios

| Dimensión | `architecture.md` (PHP, obsoleto) | Este documento (Python, real) | Por qué cambió |
|---|---|---|---|
| **Lenguaje/runtime** | PHP 8.3-fpm-alpine + Laravel 11 | Python 3.12-slim + FastAPI 0.111 | `ADR-001`: el núcleo reutilizable del prototipo son ~2.500 líneas de Python ya probadas (Planner, Executor, Registry, contratos Pydantic). En PHP se reescribía desde cero |
| **Servicio de app** | `php` / `forsis-ai-agent-php` | `app` / `forsis-ai-agent-app` | Renombrado. **Rompe resolución por nombre de contenedor** (§10, B-P4) |
| **Imagen base** | Alpine (musl) | **Debian bookworm slim (glibc)** | Los drivers de BD tienen mejor soporte en glibc; evita el patrón de ruedas musl y los fallos sutiles de locale/charset — relevante con `latin1` de SICRET |
| **Protocolo nginx→app** | `fastcgi_pass :9000` | `proxy_pass http://app:8000` + `keepalive 32` | ASGI habla HTTP. **0 ocurrencias de `fastcgi`** en el conf actual |
| **Modelo de concurrencia** | Pool de procesos FPM, 1 request por proceso, bloqueante | **2 workers uvicorn × event loop async** | Cambia el modo de fallo: ya no se agota `pm.max_children`; ahora el riesgo es **bloquear el event loop** (§4.3). Es el cambio con más consecuencias operativas |
| **Deps de runtime** | Extensiones PHP: `pdo_pgsql`, `pgsql`, `pdo_mysql`, `bcmath`, `opcache`, `pcntl`, `zip` | `requirements.txt`, todo con `==`; multi-stage deja fuera los toolchains | Reproducibilidad por lockfile en vez de por extensiones compiladas |
| **Driver PostgreSQL** | `pdo_pgsql` (síncrono, único) | **`asyncpg` único** (`psycopg2-binary` eliminado, §8.2) | Un driver, async, coherente con el event loop |
| **Driver MySQL** | `pdo_mysql` | `PyMySQL` + `cryptography`, **aislado en hilos** | PyMySQL es síncrono: `asyncio.to_thread` obligatorio |
| **Migraciones** | `php artisan migrate --force` | `alembic upgrade head` 🔜 **no implementado** | El framework ya no las trae de serie. Hoy sólo `01-init-schema.sql` de primer arranque (§6) |
| **Entrypoint** | Permisos de `storage/`+`bootstrap/cache/`, luego `php-fpm` | Espera de BD, hook de migraciones, `exec "$@"` | Python no necesita cache de framework escribible |
| **Cliente HTTP** | Guzzle | `httpx.AsyncClient` | Async nativo |
| **`knowledge/` en imagen** | — | **Excluido** + `.dockerignore` (§8.1) | Documentación interna con hallazgos de seguridad; no usada en runtime; además el bind-mount la tapaba |
| **Usuario no-root** | (implícito en php-fpm) | `agentuser` uid 1000 explícito, verificado | Explícito y comprobado |
| **Timeout del LLM** | 60 s / 3 reintentos exponenciales (§4) | **60 s/llamada + 120 s/turno**, y el **transporte no se reintenta** | `llm-provider.md` §2.2/§4.5 lo corrigió con medición real: reintentar un fallo de transporte sólo suma latencia, porque Omniroute ya hace failover |
| **Ruta de Omniroute** | `/api/v1/chat/completions` (§4) | **`{base}/v1/chat/completions`**, `base=...:20130/v1` en compose | Forma verificada empíricamente en `llm-provider.md` §4.3 |

### 9.2 Lo que **NO** cambió (y es deliberado)

Esto importa tanto como lo que cambió: la migración fue **quirúrgica sobre la capa de runtime**, sin arrastrar decisiones de seguridad ni de datos.

- **Topología de red idéntica:** `default` / `ai-network` / `forsis-comunicaciones`, con `db` aislada en `default` y **sin `ports:`**.
- **Un solo puerto publicado:** `8099:443`. `:8080` sigue siendo `expose:` interno.
- **Límites de recursos idénticos, al miligramo** — ver §9.3.
- **Regla híbrida de acceso a datos intacta:** lecturas por DB read-only con `GRANT SELECT`, escrituras **siempre** por API REST. La garantía sigue siendo del motor de BD, no de la disciplina del código.
- **Esquema PostgreSQL intacto:** `db-schema.md` no se toca (`ADR-001` §Decisión 1).
- **Proxy same-origin de `channels.md`** como estrategia de canal (y por tanto, la opción de cerrar el 8099).
- **Fail-closed:** `AGENT_WRITE_ALLOWLIST=""`, `AGENT_DRY_RUN_DEFAULT=true`.
- **Secretos sólo en `.env`**, nunca en `environment:`.
- **Tuning de PostgreSQL:** `max_connections=60`, `shared_buffers=128MB`, `work_mem=4MB`.

### 9.3 Presupuesto de recursos — sin cambios respecto a `architecture.md` §3.4

| Servicio | vCPU límite | vCPU reserva | RAM límite | RAM reserva |
|---|---|---|---|---|
| `nginx` | 0.25 | 0.05 | 64 MB | 32 MB |
| `app` (antes `php`) | 1.50 | 0.25 | 1024 MB | 256 MB |
| `db` | 0.50 | 0.10 | 512 MB | 128 MB |
| **Total** | **2.25 vCPU** | **0.40 vCPU** | **1.60 GB** | **0.41 GB** |
| **Presupuesto máx.** | **2.25 vCPU** | — | **2.00 GB** | — |
| **Margen libre** | **0.00 vCPU** | — | **+400 MB** | — |

**La cuota de CPU está agotada (margen 0.00 vCPU).** Consecuencia directa: **`--workers 2` no se puede subir sin renegociar el presupuesto** o sin bajar el límite de otro servicio. Es la razón cuantitativa por la que §4.3 (no bloquear el event loop) es crítico: no hay margen para compensar un worker atascado con más workers. En un host con ~78 contenedores, este presupuesto es la frontera que impide que el agente degrade a los sistemas de producción vecinos.

> **Nota:** `deploy.resources.limits` sólo se aplica de verdad en `docker compose up` (v2 lo respeta en modo no-Swarm). No verificado en ejecución en esta sesión, porque levantar el stack estaba fuera del alcance. 🔜

---

## 10. Bloqueantes y pendientes

Marcados como **BLOQUEANTE** los que no se pueden verificar o que romperán algo si no se atienden. No se declara funcionando nada que no se haya ejecutado.

| # | Severidad | Asunto | Detalle y acción |
|---|---|---|---|
| **B-P1** | ⚠️ Media | **`proxy_read_timeout` = presupuesto de turno** | nginx corta a 120 s y el presupuesto del `AgentService` es 120 s: empate. `channels.md` §273 pide **130 s** en nginx para que la red nunca corte antes que la app. **Acción:** subir a 130 s e implementar el corte de turno a 120 s en `AgentService`. Sin el corte, 3×60 s = 180 s produce **504** con el worker aún quemando CPU y tokens |
| **B-P2** | 🔴 Alta | **No hay ruta de evolución de schema** | `alembic` está instalado pero **no hay `alembic.ini` ni `alembic/`**. `01-init-schema.sql` sólo corre en la primera inicialización del volumen. Cualquier cambio posterior de `db-schema.md` **no se aplica** → deriva silenciosa. Tolerable mientras los datos sean descartables; **inaceptable en cuanto `audit_records` tenga datos forenses reales**. **Acción:** `alembic init -t async` + migración 0 equivalente al init-script |
| **B-P3** | ⚠️ Media | **El entrypoint no puede comprobar la BD: `pg_isready` NO existe en la imagen** | Verificado: `command -v pg_isready` → **MISSING** (hay `libpq5`, no `postgresql-client`). El `if` del entrypoint cae al fallback `curl http://$DB_HOST:$DB_PORT`, que contra un puerto PostgreSQL **nunca** indica readiness correctamente. El bucle de 30 intentos **se agota siempre (~60 s) y continúa igual**, sin fallar. Hoy lo salva `depends_on: db: condition: service_healthy`, que es la garantía real. **Acción:** o instalar `postgresql-client` en el stage final, o sustituir la comprobación por un `python -c` con `asyncpg`, o eliminar el bucle y confiar explícitamente en `depends_on` |
| **B-P4** | ⚠️ Media | **Renombrado `forsis-ai-agent-php` → `-app`** | `channels.md` referencia `http://forsis-ai-agent-nginx:8080` (ese **no** cambia), pero cualquier `.env` o doc de `forsis-bot` / proxies PHP que resuelva el contenedor de aplicación por nombre antiguo se rompe. **Acción:** grep de `forsis-ai-agent-php` en los repos consumidores |
| **B-P5** | 🔴 Alta (heredado) | **B-4: Omniroute sin autenticación** | `POST /v1/chat/completions` en `0.0.0.0:20130` responde 200 sin `Authorization`. Ajeno a este stack. **Acción:** reportar al dueño de Omniroute |
| **B-P6** | ⚠️ Media (heredado) | **B-2/B-3: JSON mode 70% / prompt inyectado / modelo no fijable** | Propiedades del combo. Requiere V-1…V-5 de `llm-provider.md` §3.4 y, idealmente, un combo dedicado sin prompt inyectado |
| **B-P7** | ⚠️ Media | **SICRET sin TLS** | `192.168.1.209:3306` no soporta TLS → `--ssl=0` obligatorio. Credenciales de BD viajan en claro por la LAN. No resoluble desde el agente. **Riesgo residual aceptado y registrado**, no mitigado |
| **B-P8** | ℹ️ Info | **`latin1` → mojibake** | Normalización a UTF-8 **una sola vez**, en la frontera del repositorio de SICRET. Doble decodificación produce `Ã±` **sin error visible** y el LLM lo propaga al usuario. Requiere test de contrato con acentos y `ñ` |
| **B-P9** | ℹ️ Info | **Sin verificación en ejecución** | No se levantó el stack (fuera de alcance). **No verificado empíricamente:** aplicación real de `deploy.resources.limits`, conectividad `app`→`db`, `app`→`forsis-memory`, `app`→Omniroute desde dentro del contenedor, healthchecks en verde, y el flujo HTTPS completo por `:8099`. Todo ello **declarado como no verificado**, no como funcionando |
| **B-P10** | ℹ️ Info | **Núcleo del agente inexistente** | `app/` son 49 líneas. No hay Planner/Executor/providers/capa de datos. Las secciones 🔜 son contrato a implementar, no estado actual |

---

## 11. Procedimiento de despliegue (actualizado al stack Python)

```bash
cd /home/servidor/forsis-ai-agent

# 1. Redes externas (ya verificadas presentes en este host)
docker network inspect ai-network >/dev/null 2>&1 || docker network create ai-network
docker network inspect forsis-comunicaciones >/dev/null 2>&1 || docker network create forsis-comunicaciones

# 2. Secretos
cp .env.example .env && chmod 600 .env
#    editar .env con credenciales reales (NUNCA commitear)

# 3. Validar y construir   ← lo único ejecutado en esta sesión
docker compose config          # → exit 0
docker compose build app       # → exit 0, sha256:d769eea1f62f

# 4. Comprobar que la imagen NO lleva documentación interna
docker run --rm --entrypoint sh forsis-ai-agent-app:local \
  -c 'test -e /app/knowledge && echo "FALLO: knowledge en la imagen" || echo OK'

# 5. Levantar (NO ejecutado en esta sesión)
docker compose up -d
docker compose ps
curl -k https://127.0.0.1:8099/health      # → "healthy" (lo sirve nginx, no la app)
curl -k https://127.0.0.1:8099/            # → JSON de la app, atraviesa uvicorn
```

> El paso 4 conviene como check de CI: impide que alguien reponga el `COPY ./knowledge` sin que nadie se dé cuenta.

---

## 12. Resumen

La migración PHP/Laravel → Python/FastAPI **está hecha y el build pasa**. El cambio es real en la capa de runtime (proceso, protocolo, drivers, concurrencia) y **deliberadamente nulo** en topología de red, exposición de puertos, presupuesto de recursos, esquema de BD y regla híbrida de acceso a datos.

Los dos defectos señalados eran reales y están corregidos y re-verificados:
- **`knowledge/` fuera de la imagen** — era un mapa de ataque de los sistemas de producción dentro de un artefacto distribuible, y encima inerte porque el bind-mount lo tapaba. Más `.dockerignore` para que no vuelva.
- **`psycopg2-binary` eliminado** — driver síncrono redundante en una aplicación 100% async, con el riesgo concreto de bloquear el event loop de uno de sólo 2 workers.

El riesgo arquitectónico dominante ya no es el stack: es que **el núcleo del agente no existe todavía** (B-P10) y que **no hay ruta de migración de schema** (B-P2). Lo segundo hay que resolverlo antes de que la BD contenga auditoría que no se pueda perder.

---
**Verificado en esta sesión:** `docker compose config` (exit 0, salida idéntica a la previa), `docker compose build app` (exit 0, `sha256:d769eea1f62f`, 300 MB), ausencia de `/app/knowledge`, `uid=1000(agentuser)`, inventario de drivers, construcción de un engine `postgresql+asyncpg`, `psycopg2` ausente, `import app.main` OK, `pg_isready` ausente (B-P3), redes externas presentes.
**NO verificado (fuera de alcance):** stack levantado, conectividad en ejecución, healthchecks, límites de recursos aplicados.
