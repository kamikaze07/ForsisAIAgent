# Estrategia de Despliegue — Contenedor `forsis-ai-agent`

**Fecha:** 2026-10-03
**Fase:** 0 — Propuesta arquitectónica (no implementada)
**Base:** `infrastructure-analysis.md` + `resources-inventory.md`

---

## 1. Principios de diseño

Derivados del análisis de los stacks existentes del servidor:

1. **Seguir las convenciones del host, no inventar.** trafico, liquidaciones y
   ATLAS comparten un patrón claro (nginx como único punto publicado, PHP-FPM
   interno, bind-mount del código, redes externas compartidas). El agente lo
   replica.
2. **Un solo puerto publicado.** Todo lo demás vive en redes internas con
   `expose:`, nunca `ports:`.
3. **Límites de recursos obligatorios.** Hoy solo `openwa-api` los declara. El
   agente es el primer stack que los declara correctamente; con 5.7 GB de swap
   ya en uso, no es opcional.
4. **Fail-closed en permisos.** Hereda el patrón de `forsis-bot`
   (`AGY_USUARIOS_AUTORIZADOS: ""` → nadie autorizado por defecto). Las
   acciones de escritura sobre trafico/liquidaciones requieren allowlist
   explícita.
5. **Secretos fuera del compose.** `env_file: .env` (modo 600, en `.gitignore`),
   nunca `environment:` con contraseñas — corrigiendo el antipatrón presente
   en `forsis-bot` y `trafico-system`.
6. **Solo lectura por defecto hacia los sistemas de negocio.** El agente se
   conecta a `trafico-db` y a la BD de liquidaciones con **usuarios dedicados
   de solo lectura**, no con `root` ni `trafico_user`.

---

## 2. Topología de red

### Decisión: tres adhesiones de red, ninguna nueva creada por el agente

| Red | Driver | Por qué el agente la necesita |
|---|---|---|
| **`ai-network`** (external, 172.26.0.0/16) | bridge | Acceso a `forsis-memory` (pgvector, memoria conversacional/RAG) y coordinación con `forsis-bot`. Ya existe y es el hogar natural del stack IA. |
| **`forsis-comunicaciones`** (external, 192.168.16.0/20) | bridge | Resolución DNS directa de `trafico-php`, `trafico-nginx`, `atlas-php`, `atlas-sync-engine`. Es el bus inter-stack ya establecido por el operador. |
| **`forsis-ai-agent_default`** (propia) | bridge | Aísla la BD privada del agente y nginx↔app. Creada por Compose, sin publicar nada. |

### Por qué NO se crea una red nueva compartida

`forsis-comunicaciones` ya resuelve exactamente este problema y está
documentada en `trafico-system/docker-compose.yml` como red creada una vez por
el operador y declarada `external: true` en cada consumidor. Crear una cuarta
red compartida fragmentaría la topología sin beneficio.

### Acceso a `liquidaciones-system`

`liquidaciones-system_default` **no está unida a `forsis-comunicaciones`**. Dos
opciones, en orden de preferencia:

- **(A) Recomendada:** añadir `forsis-comunicaciones` como red externa a los
  servicios `liquidaciones-php` y `liquidaciones-nginx`, replicando lo que ya
  se hizo con trafico. Cambio mínimo, coherente, reversible.
- **(B) Alternativa sin tocar liquidaciones:** el agente consume liquidaciones
  por su endpoint HTTPS publicado (`https://<host>:8096`) y su BD por el
  puerto publicado en el host. Más frágil (depende de TLS y del gateway Docker)
  pero cero intervención en un stack de producción.

> **Pendiente de Fase 1:** confirmar qué motor de BD usa realmente
> liquidaciones. Su compose no declara MariaDB propia — comparte con
> `trafico-db` (3310) o `sicret-pruebas-db` (3307). Hay que leer la cadena de
> conexión en `liquidaciones-system/app` antes de cerrar esta decisión.

### Acceso a Omniroute (modelos IA)

Omniroute vive en `omniroute_default` (172.22.0.3) y publica en el host:

| Puerto | Verificación realizada | Resultado |
|---|---|---|
| 20128 | TCP abierto, bind loopback | dashboard interno |
| 20129 | TCP abierto | API dev |
| **20130** | **HTTP 200/307** | **Endpoint API + Dashboard unificado (activo y verificado)** |
| 20132 | TCP abierto | Live WebSocket |

El contenedor Omniroute corre con `PORT=20130` y `DASHBOARD_PORT=20130`. Expone tanto el dashboard web como la API REST compatible con OpenAI bajo el prefijo `/api/v1`:
- `/api/health` → `200 {"status":"ok"}`
- `/api/v1/chat/completions` → responde exitosamente con modelo `Forsis` o `forsis` (mapeado a `qwen/qwen3.8-27b`)
- `/api/v1/messages` → compatible con llamadas estilo Anthropic
- Autenticación: `REQUIRE_API_KEY=false` para llamadas de inferencia

**Decisión:** el agente alcanza Omniroute por el **gateway del host**
(`host.docker.internal:20130` vía `extra_hosts: ["host.docker.internal:host-gateway"]`).
URL base configurada: `http://host.docker.internal:20130/api/v1`.
Comprobado exitosamente desde contenedor Docker con `curlimages/curl` (HTTP 200).

> **Estado Fase 1: VERIFICADO Y RESUELTO.** Endpoint: `http://host.docker.internal:20130/api/v1/chat/completions`, modelo: `Forsis`. NO ES BLOQUEANTE.

### Acceso a Mattermost

Por host público `https://chatforsis.ddns.net:443` (mismo método que
`forsis-bot`), no por red Docker — `forsis-chat` está aislado en
`chat_forsis-chat-net`.

---

## 3. Puertos

### Puerto publicado: **8099** (HTTPS)

Verificado libre con `ss -ltn sport = :8099` y contra todos los `ports:` de
Docker. Elegido por coherencia con la serie existente:

| Puerto | Sistema |
|---|---|
| 8095 | trafico-system (HTTPS) |
| 8096 | liquidaciones-system (HTTPS) |
| 8097 | ATLAS (HTTP) |
| 8098 | ATLAS WebSocket |
| **8099** | **forsis-ai-agent (HTTPS)** ← propuesto |

### Reservas (verificadas libres)

| Puerto | Uso reservado |
|---|---|
| 8092, 8093, 8094 | WebSocket del agente / streaming SSE si se separa de nginx |
| 8100 | Expansión |
| 3312 | **NO publicar** — reservado solo por si una emergencia exige acceso externo a la BD del agente |

### Puertos internos (expuestos, nunca publicados)

| Servicio | Puerto interno |
|---|---|
| `forsis-ai-agent-php` (PHP-FPM) | 9000 |
| `forsis-ai-agent-db` (PostgreSQL) | 5432 |
| nginx interno plano (webhooks/widget) | 8099 interno |

### Prohibiciones explícitas

- **8000** — ocupado por un `uvicorn` suelto en el host (PID 1203). El
  prototipo `forsis-agent` lo reclamaba: **colisión real**, no reutilizar.
- **5433** — reclamado por el prototipo abandonado. No publicar la BD.

---

## 4. Volúmenes

### Volúmenes nombrados (propiedad del agente)

| Volumen | Montaje | Contenido |
|---|---|---|
| `forsis-ai-agent_db_data` | `/var/lib/postgresql/data` | BD propia del agente (usuarios, permisos, conversaciones, auditoría) |
| `forsis-ai-agent_storage` | `/var/www/html/storage` | Laravel storage: logs, caché, reportes generados |

**Nunca volúmenes anónimos** — el host ya arrastra 13 hashes huérfanos de
imágenes con `VOLUME` en su Dockerfile.

### Bind-mounts

| Origen (host) | Destino | Modo | Razón |
|---|---|---|---|
| `./app` | `/var/www/html` | rw | Deploy sin rebuild (convención de trafico/liquidaciones) |
| `./docker/nginx/default.conf` | `/etc/nginx/conf.d/default.conf` | ro | Config nginx |
| `/etc/letsencrypt` | `/etc/letsencrypt` | **ro** | TLS para 8099 (mismo patrón que trafico/liquidaciones) |
| `./knowledge` | `/var/www/html/knowledge` | ro | Base de conocimiento para RAG |

### Reutilización del volumen huérfano

`forsis-agent_forsis_postgres_data` (del prototipo FastAPI) **no se reutiliza**
— esquema incompatible y credenciales por defecto `postgres/postgres`.
Recomendación: inspeccionar su contenido por si hay datos de valor, y
eliminarlo después (`docker volume rm`). Igual con `adguard_conf` y
`adguard_work`, huérfanos de un servicio retirado.

### Elección de disco

Los volúmenes van en `/` (**NVMe, 1.3 TB libres**), no en
`/mnt/63537E674CF73DC0` (HDD de 5.5 TB) — una BD en disco mecánico penalizaría
las consultas vectoriales y de auditoría. El HDD solo si el agente necesita
archivar adjuntos masivos.

---

## 5. Recursos asignados

Presupuesto total: **≤ 2 GB RAM / 2 vCPU** (≈6.5% de la RAM y 12.5% de la CPU
del host).

| Servicio | CPU límite | CPU reserva | RAM límite | RAM reserva |
|---|---|---|---|---|
| `forsis-ai-agent-php` | 1.5 | 0.25 | 1 GB | 256 MB |
| `forsis-ai-agent-db` | 0.5 | 0.1 | 512 MB | 128 MB |
| `forsis-ai-agent-nginx` | 0.25 | 0.05 | 64 MB | 32 MB |
| **Total** | **2.25** | 0.4 | **~1.6 GB** | 416 MB |

### Justificación

- `liquidaciones-php` consume 334 MB y `trafico-php` 223 MB en producción real
  → 1 GB para el agente es holgado incluso con cargas de IA.
- Los límites son **duros y no negociables**: con 5.7 GB de swap ya en uso,
  un contenedor sin techo puede forzar la paginación de `trafico-db` o
  `atlas-db`.
- Se evita competir con los dos vecinos ruidosos ya identificados:
  `trafico-correo-pases-cron` (163% CPU sostenido) y `omniroute` (66% CPU).

---

## 6. Compose propuesto

```yaml
# /home/servidor/forsis-ai-agent/docker-compose.yml
services:

  nginx:
    image: nginx:alpine
    container_name: forsis-ai-agent-nginx
    restart: unless-stopped
    ports:
      - "8099:443"          # único puerto publicado
    expose:
      - "8099"              # listener interno plano (widget/webhooks), NO publicado
    volumes:
      - ./app:/var/www/html
      - ./docker/nginx/default.conf:/etc/nginx/conf.d/default.conf:ro
      - /etc/letsencrypt:/etc/letsencrypt:ro
    depends_on:
      - php
    networks:
      - default
      - forsis-comunicaciones
    deploy:
      resources:
        limits:   {cpus: "0.25", memory: 64M}
        reservations: {cpus: "0.05", memory: 32M}

  php:
    build:
      context: ./docker/php
    container_name: forsis-ai-agent-php
    restart: unless-stopped
    env_file: .env          # secretos FUERA del compose (modo 600, gitignored)
    environment:
      APP_ENV: production
      OMNIROUTE_BASE_URL: http://host.docker.internal:20130
      MEMORY_DB_HOST: forsis-memory      # pgvector vía ai-network
      AGENT_DB_HOST: db
      MATTERMOST_URL: https://chatforsis.ddns.net
      # Fail-closed: sin usuarios en la allowlist, cero acciones de escritura
      AGENT_WRITE_ALLOWLIST: ""
    extra_hosts:
      - "host.docker.internal:host-gateway"
    volumes:
      - ./app:/var/www/html
      - ./knowledge:/var/www/html/knowledge:ro
      - forsis-ai-agent_storage:/var/www/html/storage
    depends_on:
      db:
        condition: service_healthy
    networks:
      - default
      - ai-network
      - forsis-comunicaciones
    deploy:
      resources:
        limits:   {cpus: "1.5", memory: 1G}
        reservations: {cpus: "0.25", memory: 256M}

  db:
    image: postgres:16-alpine
    container_name: forsis-ai-agent-db
    restart: unless-stopped
    env_file: .env          # POSTGRES_USER / POSTGRES_PASSWORD / POSTGRES_DB
    # Sin `ports:` — la BD NO se publica al host, a propósito
    volumes:
      - forsis-ai-agent_db_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U $${POSTGRES_USER}"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 30s
    networks:
      - default
    deploy:
      resources:
        limits:   {cpus: "0.5", memory: 512M}
        reservations: {cpus: "0.1", memory: 128M}

volumes:
  forsis-ai-agent_db_data:
  forsis-ai-agent_storage:

networks:
  default: {}
  ai-network:
    external: true
  forsis-comunicaciones:
    external: true
```

### Notas sobre el compose

- **`ai-network` y `forsis-comunicaciones` son `external: true`** — ya existen,
  Compose solo se adhiere. Verificado: ambas presentes en `docker network ls`.
- `$${POSTGRES_USER}` con doble `$` escapa la interpolación de Compose para que
  la variable la resuelva el shell del contenedor.
- `deploy.resources` funciona en Compose v2.39.4 (presente en el host) sin
  Swarm.
- La BD del agente **no publica puerto**: acceso para depuración vía
  `docker compose exec db psql`.

---

## 7. Imagen base

### Decisión: `php:8.3-fpm-alpine`, no reutilizar el Dockerfile de trafico

| Opción | Tamaño estimado | Veredicto |
|---|---|---|
| Reutilizar `docker/php` de trafico-system | ~1.5 GB | ❌ Las 10 imágenes de trafico ya ocupan ~14 GB |
| `php:8.3-fpm` (Debian) | ~500 MB | Aceptable |
| **`php:8.3-fpm-alpine` + extensiones** | **~300-400 MB** | ✅ **Recomendado** |

Extensiones necesarias: `pdo_pgsql`, `pdo_mysql` (lectura de trafico/ATLAS),
`redis`, `mbstring`, `bcmath`, `zip`, `gd`, `opcache`, `pcntl`.

**Antes del primer build**, liberar espacio sin riesgo:

```bash
docker image prune            # ~9.8 GB (incluye 2 imágenes <none> de ~3 GB)
docker builder prune          # ~524 MB (278 entradas, 0 activas)
```

---

## 8. Seguridad

| Control | Implementación |
|---|---|
| Secretos | `env_file: .env`, modo 600, en `.gitignore`. Nunca en `environment:`. |
| Acceso a BD de negocio | Usuarios PostgreSQL/MariaDB **dedicados de solo lectura** para trafico y ATLAS. Jamás `root` ni `trafico_user`. |
| Escritura | Fail-closed: `AGENT_WRITE_ALLOWLIST: ""`. Toda acción de escritura pasa por allowlist + auditoría en la BD del agente. |
| TLS | Certificado Let's Encrypt montado RO, igual que trafico/liquidaciones. |
| Superficie expuesta | Un solo puerto (8099). BD y PHP-FPM sin publicar. |
| Auditoría | Tabla de auditoría en la BD propia: usuario, acción, sistema destino, payload, resultado, timestamp. |
| Aislamiento | La BD del agente vive solo en `default`; no es alcanzable desde `forsis-comunicaciones` ni `ai-network`. |

---

## 9. Secuencia de despliegue

```bash
# 0. Pre-requisitos: verificar que las redes externas existen
docker network ls | grep -E "ai-network|forsis-comunicaciones"

# 1. Liberar espacio antes del build
docker image prune -f
docker builder prune -f

# 2. Preparar secretos
cd /home/servidor/forsis-ai-agent
cp .env.example .env && chmod 600 .env   # editar credenciales
echo ".env" >> .gitignore

# 3. Confirmar que 8099 sigue libre
ss -ltn 'sport = :8099' | grep LISTEN || echo "8099 libre"

# 4. Build y arranque
docker compose build
docker compose up -d

# 5. Verificar
docker compose ps
docker compose logs -f --tail=50
curl -sk -o /dev/null -w "%{http_code}\n" https://localhost:8099/health

# 6. Verificar conectividad desde el contenedor
docker compose exec php sh -c 'getent hosts forsis-memory trafico-php atlas-php'
docker compose exec php sh -c 'curl -s -o /dev/null -w "%{http_code}" http://host.docker.internal:20130/'

# 7. Confirmar que los límites se aplicaron
docker stats --no-stream | grep forsis-ai-agent
```

### Rollback

```bash
docker compose down              # conserva volúmenes
docker compose down -v           # destruye datos (solo si se descarta el stack)
```

Las redes externas sobreviven a `down` — ningún otro stack se ve afectado.

---

## 10. Riesgos del despliegue y mitigaciones

| Riesgo | Severidad | Mitigación |
|---|---|---|
| Presión de memoria (swap ya al 34%) | **Alta** | Límites duros de 1.6 GB; monitorear `free -m` tras el arranque |
| Omniroute saturado (66% CPU) atiende también al agente | Media | Timeouts y reintentos con backoff; caché de respuestas en la BD del agente |
| Ruta/auth de la API de Omniroute sin confirmar | Media | **Bloqueante de Fase 1**: validar endpoint y credencial del combo "Forsis" |
| Motor de BD de liquidaciones sin identificar | Media | **Bloqueante de Fase 1**: leer cadena de conexión en `liquidaciones-system/app` |
| Modificar el compose de liquidaciones (opción A) | Media | Cambio aditivo y reversible; o usar opción B sin tocarlo |
| Colisión de puertos a futuro | Baja | 8099 verificado libre; 8092-8094 y 8100 reservados |
| Build de 1.5 GB si se reutiliza la base PHP de trafico | Baja | Usar `php:8.3-fpm-alpine` |

---

## 11. Pendientes para Fase 1

1. **Revisar la documentación del prototipo abandonado** en
   `/home/servidor/forsis-agent/`: `FORSIS_INTELLIGENCE_BLUEPRINT.md` (37 KB),
   `FORSIS_OPERATIONAL_DISCOVERY_CATALOG.md` (48 KB),
   `MULTI_COMPANY_AUDIT_AND_TOOLS_BLUEPRINT.md` (72 KB),
   `MVP_IMPLEMENTATION_PLAN.md` (37 KB). ~194 KB de diseño previo que
   probablemente ya resolvió decisiones de dominio.
2. **Confirmar endpoint y autenticación de Omniroute** (combo "Forsis").
3. **Identificar la BD de liquidaciones-system** y decidir opción A o B.
4. **Definir el esquema de la BD del agente**: usuarios, roles, permisos,
   conversaciones, auditoría, caché de respuestas.
5. **Decidir si reutilizar `forsis-memory` (pgvector)** para RAG o crear una
   instancia propia. Recomendación: reutilizar — ya existe, está en
   `ai-network` y evita duplicar un pgvector de 438 MB.
6. **Crear usuarios de BD de solo lectura** en `trafico-db` y `atlas-db`.
7. **Reportar al operador** el bucle de reinicios de `orion-scheduler-1`
   (`orion-redis-1` caído hace 4 días) — ajeno al proyecto pero consume CPU.

---

## 12. Diagrama de topología propuesta

```
                        HOST (Debian 12, 16 vCPU, 30 GB RAM)
                                       │
  Internet ──► :8099/tcp (HTTPS) ──► forsis-ai-agent-nginx
                                       │
                 ┌─────────────────────┼──────────────────────┐
                 │                     │                      │
          [default]            [forsis-comunicaciones]   [ai-network]
                 │                 192.168.16.0/20        172.26.0.0/16
                 │                     │                      │
      ┌──────────┴─────────┐           │                      │
      │                    │           │                      │
 forsis-ai-agent-php  forsis-ai-agent-db                      │
 (PHP-FPM :9000)      (PostgreSQL :5432)                      │
      │                 sin publicar                          │
      │                                │                      │
      │                    ┌───────────┴──────────┐    ┌──────┴────────┐
      │                    │                      │    │               │
      │              trafico-php            atlas-php  forsis-memory  forsis-bot
      │              trafico-nginx     atlas-sync-engine  (pgvector)
      │                                                  DB forsis_ai
      │
      └──► host.docker.internal:20130 ──► omniroute (172.22.0.3)
      └──► https://chatforsis.ddns.net:443 ──► forsis-chat (Mattermost)
```
