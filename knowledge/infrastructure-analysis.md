# Análisis de Infraestructura Docker — Forsis

**Fecha:** 2026-10-03
**Servidor:** Debian GNU/Linux 12 (bookworm), kernel 6.1.0-39-amd64
**Docker:** 28.4.0 · **Compose:** v2.39.4
**Uptime:** 7 días, 20:45 · **Load average:** 2.42 / 2.87 / 2.97 (16 vCPU)

---

## 1. Resumen ejecutivo

El servidor es un host Docker **densamente poblado**: 78 contenedores
(77 en ejecución), 73 imágenes y 40 volúmenes, repartidos en **16 redes bridge**
y al menos 12 stacks de Compose independientes. No es un servidor dedicado al
proyecto: conviven sistemas de negocio críticos (trafico-system,
liquidaciones-system, ATLAS), infraestructura de correo completa (mailcow,
22 contenedores), almacenamiento (Nextcloud, Immich), colaboración
(Mattermost, OnlyOffice), monitoreo (Orion/Grafana/Prometheus) y el gateway de
modelos IA (Omniroute).

Conclusión para Fase 0: **hay recursos suficientes** para el contenedor
`forsis-ai-agent` (≈15 GB RAM y 1.3 TB disco libres, carga de CPU al ~18%),
pero el despliegue debe ser **conservador y explícitamente limitado** —
cualquier fuga de memoria o build pesado compite con mailcow y las bases de
datos de producción. Existe además un **prototipo previo abandonado**
(`/home/servidor/forsis-agent`, FastAPI + Postgres) cuyo volumen sigue en
disco; es la referencia histórica obligada antes de diseñar el nuevo stack.

---

## 2. Inventario de contenedores (`docker ps -a`)

Comando ejecutado:

```bash
docker ps -a --format "table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}"
```

### 2.1 Sistemas objetivo de integración

#### trafico-system (`trafico-system_default` + `forsis-comunicaciones`)

| Contenedor | Imagen | Estado | Puertos |
|---|---|---|---|
| trafico-nginx | nginx:alpine | Up 7 días | `8095->443`, expone 8091 interno |
| trafico-php | trafico-system-php | Up 7 días | 9000/tcp (interno) |
| trafico-db | mariadb:11 | Up 7 días (healthy) | `3310->3306` |
| trafico-redis | redis:alpine | Up 7 días | 6379 (interno) |
| trafico-motor-watcher | trafico-system-motor-watcher | Up 7 días | 9000 |
| trafico-comunicaciones-websocket | …-comunicaciones-websocket | Up 7 días (healthy) | 8090 interno, **sin publicar** |
| trafico-correo-pases-cron | …-correo-pases-cron | Up 7 días | 9000 |
| trafico-comunicaciones-adjuntos-cron | …-adjuntos-cron | Up 7 días | 9000 |
| trafico-perfil-inteligente-cron | …-perfil-inteligente-cron | Up 7 días | 9000 |
| trafico-tipo-cambio-cron | …-tipo-cambio-cron | Up 7 días | 9000 |
| trafico-scheduled-deductions-cron | …-scheduled-deductions-cron | Up 7 días | 9000 |
| trafico-sicret-guide-cleanup-cron | …-sicret-guide-cleanup-cron | Up 7 días | 9000 |
| trafico-reseteo-ingestion-cron | …-reseteo-ingestion-cron | Up 7 días | 9000 |
| trafico-rrhh-nomina-cron | …-rrhh-nomina-cron | Up 7 días | 9000 |

#### liquidaciones-system (`liquidaciones-system_default`)

| Contenedor | Imagen | Estado | Puertos |
|---|---|---|---|
| liquidaciones-nginx | nginx:alpine | Up ~1 h | `8096->443`, expone 8081 interno |
| liquidaciones-php | liquidaciones-system-liquidaciones-php | Up ~1 h | 9000 |
| liquidaciones-ws | node:22-alpine | Up 2 días | interno |
| liquidaciones-reseteo-ingestion-cron | …-reseteo-ingestion-cron | Up 2 días | 9000 |

> **Nota:** liquidaciones no declara su propia MariaDB en el compose — comparte
> base de datos vía red/host con otro stack (`sicret-pruebas-db` en `3307`
> y/o `trafico-db` en `3310`). **Validar la cadena de conexión real en
> `liquidaciones-system/app` antes de diseñar el acceso a datos del agente.**

#### ATLAS / tablero-guias (`tablero-guias_default` + `forsis-comunicaciones`)

| Contenedor | Imagen | Estado | Puertos |
|---|---|---|---|
| atlas-nginx | nginx:alpine | Up 7 días | `8097->80` |
| atlas-php | tablero-guias-php | Up 7 días | 9000 |
| atlas-db | mariadb:11 | Up 7 días (healthy) | `3311->3306` |
| atlas-sync-engine | tablero-guias-sync-engine | Up 7 días | 9000 |
| atlas-websocket | tablero-guias-websocket | Up 7 días | `8098->8098` |
| atlas-daily-cutover | tablero-guias-daily-cutover | Up 7 días | 9000 |
| atlas-monitoring | tablero-guias-monitoring | Up 7 días | 9000 |

### 2.2 Stack IA existente (`ai-network`) — base del nuevo agente

| Contenedor | Imagen | Estado | Rol |
|---|---|---|---|
| forsis-bot | forsis-bot-forsis-bot | Up 22 h | Bot Mattermost + agente CLI (`agy`) |
| forsis-memory | pgvector/pgvector:pg16 | Up 7 días | Memoria vectorial (DB `forsis_ai`) |
| onlyoffice | onlyoffice/documentserver | Up 7 días | Unido también a ai-network |
| forsis-social-bot | forsis-social-bot | Up 7 días | En red `bridge` por defecto |

### 2.3 Gateway de modelos IA

| Contenedor | Imagen | Estado | Puertos |
|---|---|---|---|
| omniroute | omniroute-playwright:local | Up 27 h (healthy) | `20129-20130`, `20132`, 20128 interno |
| omniroute-redis | redis:7-alpine | Up 7 días (healthy) | 6379 interno |

Omniroute vive en `omniroute_default` (**172.22.0.3**) y publica su API en
`20129`. Es el proveedor de modelos designado para el agente (combo "Forsis").

### 2.4 Mattermost (canal conversacional)

| Contenedor | Imagen | Estado | Puertos |
|---|---|---|---|
| forsis-chat | mattermost/mattermost-team-edition | Up 7 días (healthy) | `25080->8065` |
| forsis-chat-db | postgres:15 | Up 7 días | 5432 interno |

Red: `chat_forsis-chat-net`. Host público: `chatforsis.ddns.net:443`.

### 2.5 Resto del parque (no se toca)

- **mailcow** (22 contenedores, red `mailcowdockerized_mailcow-network`):
  postfix, dovecot, rspamd, clamd, sogo, unbound, netfilter, mysql, redis…
  Puertos de correo: 25, 110, 143, 465, 587, 993, 995, 4190, 8086, 8444.
- **Nextcloud**: nextcloud-app (`8090->80`), nextcloud-db, nextcloud-redis.
- **Immich**: immich_server (`2283`), machine_learning, postgres, redis(valkey).
- **Orion** (monitoreo): api, worker, scheduler, frontend, nginx (`18080`),
  grafana (`53000`), prometheus, timescaledb (`55432`).
- **Almacén**: almacen-nginx (`81->80`), almacen-php, almacen-db,
  almacen-phpmyadmin (`8081->80`).
- **Forsis Recovery Dashboard**: forsis-dashboard-nginx (`8501->80`,
  `8500->443`), forsis-dashboard-backend.
- **OpenWA**: openwa-api (red `forsis-comunicaciones`, 2785 interno).
- **RustDesk**: hbbs/hbbr (21115-21119).
- **Otros**: sicret-pruebas-db (`3307->3306`), noip-duc-runner.

---

## 3. Redes (`docker network ls`)

```bash
docker network ls
```

| Red | Driver | Subred conocida | Uso |
|---|---|---|---|
| **ai-network** | bridge | **172.26.0.0/16** (gw .1) | **Stack IA: forsis-bot .2, forsis-memory .3, onlyoffice .4** |
| **forsis-comunicaciones** | bridge | **192.168.16.0/20** | Bus inter-stack: trafico-nginx .2, atlas-sync .3, adjuntos-cron .4, atlas-php .5, trafico-php .6, openwa-api .7, trafico-ws .8, atlas-monitoring .9 |
| trafico-system_default | bridge | — | Interna trafico |
| liquidaciones-system_default | bridge | — | Interna liquidaciones |
| tablero-guias_default | bridge | — | Interna ATLAS |
| omniroute_default | bridge | 172.22.0.0/16 | Omniroute (172.22.0.3) |
| chat_forsis-chat-net | bridge | — | Mattermost |
| forsis-recovery-dashboard_default | bridge | — | Dashboard recovery |
| almacen-app_almacen-network | bridge | — | Almacén |
| mailcowdockerized_mailcow-network | bridge | — | Correo |
| nextcloud_default / immich_default | bridge | — | Archivos/fotos |
| orion_orion_net | bridge | — | Monitoreo |
| rustdesk-server_default | bridge | — | Escritorio remoto |
| bridge / host / none | — | 172.17.0.0/16 | Por defecto Docker |

### Hallazgo arquitectónico clave

Ya existe un **patrón establecido de red externa compartida**:
`forsis-comunicaciones` fue creada manualmente por el operador
(`docker network create forsis-comunicaciones`) y se declara `external: true`
en cada compose que la necesita. El comentario en
`trafico-system/docker-compose.yml` lo documenta explícitamente:

> `forsis-comunicaciones` es EXTERNA a propósito: la crea el operador UNA vez
> y la comparte con el stack independiente de OpenWA — si no fuera `external`,
> cada proyecto de Compose crearía su propia red aislada con un nombre
> distinto (prefijado por proyecto) y nunca se alcanzarían entre sí.

**El agente IA debe seguir este mismo patrón**, no inventar uno nuevo.
`ai-network` es también externa (ver `forsis-bot/docker-compose.yml`).

---

## 4. Volúmenes (`docker volume ls`)

```bash
docker volume ls
```

40 volúmenes, 5.999 GB, de los cuales **217.1 MB reclamables (7 huérfanos)**.

### Volúmenes con nombre relevantes

| Volumen | Stack | Observación |
|---|---|---|
| **forsis-agent_forsis_postgres_data** | prototipo previo | **HUÉRFANO** — del intento FastAPI abandonado |
| **forsis-bot_pgdata** | forsis-bot | Datos de `forsis-memory` (pgvector, DB `forsis_ai`) |
| trafico-system_trafico_mariadb | trafico | BD producción tráfico |
| tablero-guias_atlas-db-data | ATLAS | BD producción ATLAS |
| sicret_pruebas_data | SICRET | BD pruebas |
| almacen-app_mariadb_data | almacén | BD almacén |
| nextcloud_db_data | Nextcloud | BD |
| immich_model-cache | Immich | Caché modelos ML |
| omniroute_redis-data | Omniroute | Cola/caché gateway IA |
| openwa_openwa-data | OpenWA | Sesión WhatsApp |
| orion_orion_db_data / _grafana_data / _prometheus_data / _redis_data | Orion | Monitoreo |
| mailcowdockerized_* (12 vols) | mailcow | vmail, mysql, redis, rspamd, clamd, crypt… |
| adguard_conf / adguard_work | — | **HUÉRFANOS** (AdGuard ya no corre) |

Además hay **13 volúmenes anónimos** (hashes de 64 caracteres) creados por
imágenes con `VOLUME` en su Dockerfile (mariadb, postgres, onlyoffice).
**Lección para el agente: declarar siempre volúmenes nombrados**, nunca
depender de los anónimos.

---

## 5. Imágenes (`docker images`)

73 imágenes, **34.45 GB**, de las cuales **9.819 GB (28%) reclamables**.

### Las más pesadas

| Imagen | Tamaño |
|---|---|
| omniroute-playwright:local | 4.39 GB |
| diegosouzapw/omniroute:latest | 4.14 GB |
| onlyoffice/documentserver | 3.90 GB |
| immich-server:v2 | 2.12 GB |
| timescale/timescaledb:latest-pg16 | 1.61 GB |
| openwa-stack-openwa-api | 1.55 GB |
| trafico-system-php / rrhh-nomina-cron | 1.53 GB cada una |
| liquidaciones-*-cron | 1.46 GB |
| liquidaciones-system-liquidaciones-php | 1.45 GB |
| nextcloud-app | 1.43 GB |
| 8 × trafico-system-*-cron | ~1.41 GB cada una |

### Observaciones para el diseño del agente

1. **Las imágenes PHP de trafico/liquidaciones pesan ~1.4–1.5 GB cada una.**
   Si `forsis-ai-agent` usa el mismo `Dockerfile` base de PHP, añade otro
   ~1.5 GB. Conviene **reutilizar una imagen base común** o construir sobre
   `php:8.x-fpm-alpine` para quedarse en ~300–500 MB.
2. Hay 2 imágenes `<none>:<none>` (1.51 GB + 1.41 GB) = capas dangling de
   rebuilds de trafico. `docker image prune` liberaría ~3 GB sin riesgo.
3. `build cache`: 278 entradas, 523.9 MB, **100% reclamable**.

---

## 6. Análisis de `docker-compose.yml` existentes

### 6.1 Convenciones comunes (a replicar)

Analizados: `trafico-system/`, `liquidaciones-system/`, `forsis-bot/`,
`forsis-agent/`, `omniroute/`.

| Convención | Evidencia |
|---|---|
| `container_name:` explícito | Todos los servicios de producción |
| `restart: unless-stopped` | Todos los de producción (**el prototipo forsis-agent NO lo tiene**) |
| nginx como único punto publicado | trafico `8095:443`, liquidaciones `8096:443`, atlas `8097:80` |
| Servicios internos con `expose:`, nunca `ports:` | trafico-ws (8090), nginx interno (8091/8081) |
| TLS vía Let's Encrypt montado RO | `- /etc/letsencrypt:/etc/letsencrypt:ro` |
| Código montado como bind-mount | `- ./app:/var/www/html` (deploy sin rebuild) |
| Redes compartidas declaradas `external: true` | `forsis-comunicaciones`, `ai-network` |
| Secretos en `environment:` plano | **Antipatrón presente** (ver §7) |
| `healthcheck` + `depends_on: condition: service_healthy` | Solo en forsis-agent (prototipo) y omniroute |

### 6.2 El prototipo abandonado: `/home/servidor/forsis-agent`

```yaml
services:
  api:
    build: .
    ports: ["8000:8000"]
    environment: [FORSIS_ENV=development, POSTGRES_*...]
    depends_on: {postgres: {condition: service_healthy}}
  postgres:
    image: postgres:16-alpine
    ports: ["5433:5432"]
    volumes: [forsis_postgres_data:/var/lib/postgresql/data]
    healthcheck: {test: ["CMD-SHELL","pg_isready -U postgres"], ...}
volumes: {forsis_postgres_data:}
```

Estado: **no desplegado** (ningún contenedor corriendo), pero su volumen
`forsis-agent_forsis_postgres_data` persiste. El directorio contiene
documentación de alto valor que **debe revisarse antes de rediseñar**:

- `FORSIS_INTELLIGENCE_BLUEPRINT.md` (37 KB)
- `FORSIS_OPERATIONAL_DISCOVERY_CATALOG.md` (48 KB)
- `MULTI_COMPANY_AUDIT_AND_TOOLS_BLUEPRINT.md` (72 KB)
- `MVP_IMPLEMENTATION_PLAN.md` (37 KB)
- `AGENT.md`, `knowledge/`, `alembic/`, `frontend/`, `docs/`

Defectos del prototipo a **no repetir**:
- Credenciales `postgres/postgres` por defecto.
- Sin `restart: unless-stopped`.
- Sin `container_name`.
- Publica `8000` y `5433` al host sin necesidad (hoy `8000` lo ocupa un
  uvicorn suelto fuera de Docker, PID 1203 → **colisión real**).
- Sin límites de recursos.
- `FORSIS_ENV=development`.

### 6.3 `forsis-bot/docker-compose.yml` — el modelo más cercano

Es el precedente directo del nuevo agente:
- Se une a `ai-network` (external).
- Usa `forsis-memory` (pgvector) vía DNS interno: `forsis-memory:5432`.
- Habla con Mattermost por host público (`chatforsis.ddns.net:443`).
- Monta binario y credenciales del host en RO.
- Implementa **autorización fail-closed**:
  `AGY_USUARIOS_AUTORIZADOS: ""` → nadie autorizado por defecto.
  **Este patrón debe heredarse en el agente IA** para acciones de escritura.

---

## 7. Riesgos y hallazgos

### Críticos / a resolver antes de desplegar

1. **Colisión de puerto 8000.** Un proceso `uvicorn` (PID 1203) escucha en
   `0.0.0.0:8000` fuera de Docker, y el prototipo `forsis-agent` reclama ese
   mismo puerto. El nuevo agente **no debe usar 8000**.
2. **`orion-redis-1` está caído** (`Exited (1)` hace 4 días) y
   **`orion-scheduler-1` reinicia en bucle** con
   `redis.exceptions.ConnectionError: Error -2 connecting to redis:6379`.
   Es un bucle de reinicios que consume CPU y llena logs — ajeno a este
   proyecto pero conviene reportarlo al operador.
3. **Secretos en texto plano** en los compose: `BOT_TOKEN` de Mattermost y
   `DATABASE_URL` con contraseña en `forsis-bot/docker-compose.yml`;
   `MYSQL_ROOT_PASSWORD: root` en trafico. El agente IA debe usar
   `env_file:` con un `.env` fuera de git (modo 600), no `environment:`.
4. **Sin límites de recursos en ningún contenedor** salvo openwa-api (2 GiB).
   Un contenedor con fuga puede agotar los 15 GB libres y afectar a las BD de
   producción. El agente **debe** declarar `deploy.resources.limits`.

### Medios

5. **Memoria libre real baja**: 646 MB "libre", 15.7 GB "disponible"
   (el resto es caché). Swap ya en uso: **5.7 GB de 16 GB**, señal de presión
   de memoria histórica.
6. **`trafico-correo-pases-cron` consume 163% de CPU** de forma sostenida —
   1.6 núcleos permanentes. Reduce el margen de CPU disponible.
7. **Omniroute al 65.87% de CPU** y 1.26 GB RAM. Es la dependencia de modelos
   del agente: cada petición del agente aumentará esta carga.
8. `/etc/letsencrypt/live` no es legible por el usuario `servidor` (requiere
   root). Los nginx lo montan como root dentro del contenedor. El despliegue
   del agente necesitará el mismo bind-mount RO.

### Bajos

9. ~13.4 GB recuperables sin riesgo: 9.8 GB imágenes + 0.5 GB build cache +
   0.2 GB volúmenes huérfanos (`adguard_*`, `forsis-agent_*`).
10. 13 volúmenes anónimos sin rastrear.
11. `omniroute` tiene dos imágenes de 4+ GB (local y upstream) duplicando ~4 GB.

---

## 8. Comandos de referencia utilizados

```bash
# Contenedores
docker ps -a --format "table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}"
# Imágenes
docker images --format "table {{.Repository}}:{{.Tag}}\t{{.Size}}\t{{.CreatedSince}}"
# Redes
docker network ls
docker network inspect ai-network
docker network inspect forsis-comunicaciones
# Volúmenes
docker volume ls
# Uso de disco Docker
docker system df
# Consumo en vivo
docker stats --no-stream --format "{{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}"
# Red de un contenedor
docker inspect -f '{{range $k,$v := .NetworkSettings.Networks}}{{$k}}={{$v.IPAddress}} {{end}}' <name>
```
