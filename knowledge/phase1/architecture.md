# Forsis AI Agent — Arquitectura de Contenedores y Topología de Red (Fase 1)

**Fecha:** 2026-10-05  
**Estado:** Aprobado / Validado empíricamente  
**Stack Base:** PHP 8.3-fpm-alpine + Nginx Alpine + PostgreSQL 16 Alpine  
**Framework:** Laravel 11  

---

## 1. Visión General de la Arquitectura

Forsis AI Agent es un servicio autónomo contenerizado responsable del procesamiento de lenguaje natural, orquestación de herramientas operacionales y ejecución de tareas guiadas para el ERP Forsis. Opera bajo el principio estricto de **mínimo privilegio y desacoplamiento**:
- **Aislamiento de mutación**: Las consultas operacionales a los sistemas de producción (`trafico-system` y `liquidaciones-system`) se realizan mediante conexiones de base de datos de solo lectura (`ReadOnlySession`). Cualquier acción de modificación de estado se realiza exclusivamente vía APIs REST autenticadas (`POST/PUT/PATCH`) tras superar la compuerta de aprobación (`ApprovalGateway`).
- **Persistencia propia e independiente**: Toda sesión de diálogo, traza de ejecución de herramientas, registro inmutable de auditoría y base de conocimiento RAG reside en su propia base de datos PostgreSQL 16 (y vector store en `forsis-memory`), sin compartir esquemas ni tablas con el ERP.

---

## 2. Topología de Red Docker y Flujos de Comunicación

```
                     [ Usuario / Webhook / Mattermost ]
                                     │
                                     │ HTTPS :8099
                                     ▼
                ┌─────────────────────────────────────────┐
                │        forsis-ai-agent-nginx            │
                │        (image: nginx:alpine)            │
                │  TLS /etc/letsencrypt (read-only)       │
                └───────────────────┬─────────────────────┘
                                    │ FastCGI :9000
                                    │ (Red interna: default)
                                    ▼
                ┌─────────────────────────────────────────┐
                │          forsis-ai-agent-php            │
                │    (image: php:8.3-fpm-alpine)          │
                │         Laravel 11 App Engine           │
                └───┬───────────────┬─────────────────┬───┘
                    │               │                 │
    (Red interna:   │               │ (Red externa:   │ (Red externa:
     default)       │               │  ai-network)    │  forsis-comunicaciones)
                    ▼               ▼                 ▼
          ┌────────────────┐ ┌──────────────┐ ┌────────────────┐
          │forsis-ai-agent │ │forsis-memory │ │trafico-system  │
          │      -db       │ │  (pgvector)  │ │   -nginx       │
          │ (PostgreSQL 16)│ │   (PG 16)    │ │ (API REST :443)│
          │ [NO PUBLICADO] │ └──────────────┘ └────────────────┘
          └────────────────┘
                    │
                    │ host.docker.internal:20130
                    │ (extra_hosts via host-gateway)
                    ▼
          ┌──────────────────────────────────────────┐
          │            Omniroute Gateway             │
          │       http://127.0.0.1:20130/api/v1      │
          │      (Modelo 'Forsis' / Qwen 3.8-27B)    │
          └──────────────────────────────────────────┘
```

### 2.1 Segmentación de Redes

1. **`default` (Red bridge interna del stack):**
   - Ámbito exclusivo para `forsis-ai-agent-nginx`, `forsis-ai-agent-php` y `forsis-ai-agent-db`.
   - **Garantía de seguridad:** La base de datos relacional interna (`db`) solo está conectada a esta red y NO tiene directiva `ports:` expuesta al host. Queda inaccesible para otros contenedores y para la red externa.

2. **`ai-network` (Red bridge externa compartida):**
   - Conecta a `forsis-ai-agent-php` con el servicio `forsis-memory` (contenedor `pgvector/pgvector:pg16`, IP de red `172.26.0.3`) para búsquedas semánticas y embeddings de alta dimensión.

3. **`forsis-comunicaciones` (Red bridge externa compartida):**
   - Permite a `forsis-ai-agent-php` comunicarse de forma segura con los servicios del ERP `trafico-system` (incluyendo su proxy Nginx y webhooks internos).

4. **`host.docker.internal` (Resolución de Gateway del Host):**
   - Conexión hacia el proxy LLM local Omniroute ejecutándose en el puerto del host `20130`.
   - Implementado en `docker-compose.yml` vía:
     ```yaml
     extra_hosts:
       - "host.docker.internal:host-gateway"
     ```
   - **Verificación empírica realizada:** `curl http://host.docker.internal:20130/api/health` retorna `200 OK` desde un contenedor Docker.

---

## 3. Especificación de Servicios Contenedorizados

### 3.1 `nginx` (`forsis-ai-agent-nginx`)
- **Imagen:** `nginx:alpine`
- **Puertos publicados:**
  - `8099:443` (Único puerto expuesto en el host; termina SSL con certificados de producción Let's Encrypt de `forsispr1.ddns.net`).
- **Puertos internos (expose):**
  - `8080`: Listener HTTP plano interno (para healthcheck y posibles llamadas internas sin sobrecarga TLS).
- **Límites de recursos:**
  - `cpus: "0.25"`, `memory: 64M`
- **Volúmenes:**
  - `./app:/var/www/html:ro` (Solo lectura para servir estáticos)
  - `./docker/nginx/default.conf:/etc/nginx/conf.d/default.conf:ro`
  - `/etc/letsencrypt:/etc/letsencrypt:ro` (Certificados del host compartidos)
  - `forsis-ai-agent_storage:/var/www/html/storage`

### 3.2 `php` (`forsis-ai-agent-php`)
- **Imagen:** `forsis-ai-agent-php:local` construida a partir de `php:8.3-fpm-alpine`.
- **Extensiones requeridas:**
  - `pdo`, `pdo_pgsql`, `pgsql` (BD interna y memoria)
  - `pdo_mysql` (Lecturas de solo lectura hacia SICRET MySQL 192.168.1.209)
  - `bcmath`, `opcache`, `pcntl`, `zip`
- **Punto de Entrada (`entrypoint.sh`):**
  - Asegura permisos en `storage/` y `bootstrap/cache/`.
  - Ejecuta migraciones de base de datos propia (`php artisan migrate --force`) solo si `RUN_MIGRATIONS=true`.
  - Inicia `php-fpm` o el worker supervisor según el comando invocado.
- **Límites de recursos:**
  - `cpus: "1.5"`, `memory: 1G` (Reserva: `0.25 vCPU`, `256M`)
- **Variables de Entorno y Secretos:**
  - Inyectadas mediante directiva `env_file: .env`. Ningún secreto vive en el `docker-compose.yml`.

### 3.3 `db` (`forsis-ai-agent-db`)
- **Imagen:** `postgres:16-alpine`
- **Aislamiento de Red:** Red `default` únicamente. Cero exposición externa.
- **Volúmenes:**
  - `forsis-ai-agent_db_data:/var/lib/postgresql/data` (Persistencia nombrada Docker).
  - `./docker/db/init:/docker-entrypoint-initdb.d:ro` (Scripts de inicialización DDL).
- **Parámetros de Tuning PostgreSQL (bajo perfil):**
  - `max_connections=60`
  - `shared_buffers=128MB`
  - `work_mem=4MB`
- **Límites de recursos:**
  - `cpus: "0.5"`, `memory: 512M` (Reserva: `0.1 vCPU`, `128M`)

### 3.4 Resumen de Consumo de Recursos vs. Cuotas Asignadas

| Servicio | vCPU Límite | vCPU Reserva | RAM Límite | RAM Reserva |
|---|---|---|---|---|
| `nginx` | 0.25 | 0.05 | 64 MB | 32 MB |
| `php` | 1.50 | 0.25 | 1024 MB | 256 MB |
| `db` | 0.50 | 0.10 | 512 MB | 128 MB |
| **Total Stack** | **2.25 vCPU** | **0.40 vCPU** | **1.60 GB** | **0.41 GB** |
| **Presupuesto Máximo** | **2.25 vCPU** | — | **2.00 GB** | — |
| **Margen Libre** | **0.00 vCPU** | — | **+400 MB** | — |

---

## 4. Estrategia de Inferencia LLM (Omniroute)

Durante la Fase 1 se resolvió y validó la conectividad con el gateway Omniroute:
- **Puerto:** `20130`
- **URL Base:** `http://host.docker.internal:20130/api/v1`
- **Ruta de Inferencia Chat:** `POST /api/v1/chat/completions`
- **Modelo:** `Forsis` (Combo mapeado dinámicamente a `qwen/qwen3.8-27b`).
- **Autenticación:** Omniroute opera con `REQUIRE_API_KEY=false` permitiendo llamadas internas directas de baja latencia.
- **Timeout y Reintentos:** Timeout cliente de 60 segundos con hasta 3 reintentos exponenciales.

---

## 5. Estrategia de Conexión Híbrida con el ERP (Read-Only DB vs. Mutation API)

1. **Lecturas (Queries analíticas y contextuales de alta velocidad):**
   - Conexión directa desde `forsis-ai-agent-php` a:
     - PostgreSQL `trafico` (172.17.0.1:5432 o red Docker) mediante usuario restringido con `GRANT SELECT` únicamente.
     - MySQL `sicret` (192.168.1.209:3306) mediante usuario restringido de lectura.
   - Forzado de transacción de solo lectura a nivel PDO (`SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY;`).
2. **Escrituras (Acciones operacionales del catálogo `operational-actions`):**
   - El agente tiene estrictamente prohibido emitir sentencias `INSERT`, `UPDATE` o `DELETE` directas sobre las bases de datos de producción.
   - Toda mutación debe invocarse mediante cliente HTTP contra el API REST (`TRAFICO_API_BASE_URL` en `https://forsispr1.ddns.net:8443/api`).
   - El payload y la intención deben registrarse primero en `approval_requests` y `audit_records`. Si la acción requiere aprobación humana (e.g. `requires_approval=true` en `INDEX.yaml`), el agente se suspende y envía una tarjeta interactiva a Mattermost esperando la confirmación de un supervisor.

---

## 6. Procedimiento de Despliegue y Validación

```bash
# 1. Verificar redes externas
docker network inspect ai-network >/dev/null 2>&1 || docker network create ai-network
docker network inspect forsis-comunicaciones >/dev/null 2>&1 || docker network create forsis-comunicaciones

# 2. Configurar entorno y secretos (permisos 600)
cd /home/servidor/forsis-ai-agent
cp .env.example .env
chmod 600 .env
# [Editar .env con contraseñas seguras]

# 3. Validar sintaxis de compose
docker compose config

# 4. Construir y levantar
docker compose build
docker compose up -d

# 5. Verificar salud de los servicios
docker compose ps
curl -k https://127.0.0.1:8099/health
```
