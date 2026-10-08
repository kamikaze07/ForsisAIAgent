# Mattermost — Análisis de la Instancia

## Resumen
- **Instancia**: Mattermost Team Edition v11.6.0 (build 24038116943), sin licencia Enterprise (`BuildEnterpriseReady: false`).
- **Dockerizado**: `mattermost/mattermost-team-edition:latest` → contenedor `forsis-chat` (project `chat`, compose en `/opt/forsis/chat/docker-compose.yml`).
- **Acceso público**: `https://chatforsis.ddns.net` (443), mapeado a puerto host `25080` → contenedor 8065.
- **Base datos**: PostgreSQL 15 (`forsis-chat-db`), usuario `mmuser`, BD `mattermost`.
- **Estado**: healthy, 7 días up.

## Entorno/Config del contenedor
```
MM_SERVICESETTINGS_SITEURL=https://chatforsis.ddns.net
MM_SERVICESETTINGS_ALLOWCORSFROM=*
MM_SQLSETTINGS_DRIVERNAME=postgres
MM_SQLSETTINGS_DATASOURCE=postgres://mmuser:<pass>@postgres:5432/mattermost?sslmode=disable
MM_SERVICESETTINGS_ENABLELOCALMODE=true
MM_INSTALL_TYPE=docker
```
- `EnableLocalMode=true` → permite acceso local por `MM_LOCALMODETOKEN` (útil para operaciones de admin sin OAuth).
- Configuración persistida en bind: `/opt/forsis/chat/mattermost_config:/mattermost/config`.
- Plugins/Client plugins: `/opt/forsis/chat/mattermost_plugins` y `mattermost_client_plugins` (playbooks, mattermost-ai, com.mattermost.calls).
- Logs/datos: bind mounts en `/opt/forsis/chat/mattermost_logs`, `mattermost_data`.

## Usuarios (activos relevantes)
- `cesarkun07` — system_admin (dueño del equipo).
- `forsisbot` — `system_user + system_post_all`, activo (bot propio, ya existente).
- `stickerbot` — system_admin system_user, **inactivo** (`deleteat≠0`).
- `donserver` — `system_user + system_post_all`, inactivo.
- Usuarios activos restantes: `yuliet01`, `neftali01` (Nefta), `sarai01`, `olaf01`, `martin01`, `rick01`, `shiomara01`, `sonia01`, `aulises01`, `lcarlos01`, `pilar01`, `karla01`, `josue01`, `ruben01`, `juan01`, `victor01`, `lenrique01`, `lesie01`, `uzziel`, `test01`, `qegzf8n3hpbd9g84bco7gwzdph`, `wygysks7ypgmdxxe6ab66hwnry`, `rempla01`, `perla01`, `mera01`, `flor01` (inactiva), `walter`, `eduardocad01`, `keniacad01`, `betycad01`, `mariocad01`, `laura01`, `cdelangel`, `jmrocha`, `eunice01`, `gustavo01`, `Vigilancia` (Caseta).

## Equipos y canales principales
- **Forsis PR** (`pc64qx8zxpdrdpudjfatnts9ro`, 36 miembros): Chat General, Anuncios, Tráfico, Estadías/Reparaciones, Monitoreo, Historial Unidades, Liquidaciones-TI, Facturación, Almacen, Matenimientos, QHSE, Trafico-Operación, Admin-RRHH, Vigilancia PR.
- **Forsis Cadereyta** (`bin5an9b47dpfjw9oyiw6cwetc`, 5 miembros): Chat General, Anuncios, Off-Topic.
- **Forsis Cacalilao** (`t47nftgf43rubbdkinc3oamy8a`, 2 miembros): Chat General, Anuncios.
- **Gero - Ragar Cadereyta** (`63m5k8btub89j8ec7crdk84w6o`, 4 miembros): Chat General, Anuncios.
- **Laura** (`w1n3j5pwji8otctzdwt4qdsfhh`, 1 miembro).

## Integraciones existentes
- **Bots**: `calls` (MM Calls), `system-bot`, `forsisbot` ("Bot de Forsis"), `stickerbot` (inactivo), `donserver` (bot interno, inactivo).
- **Incoming webhooks activos**: 3 (en `Chat General` admin, `Tráfico-Operación`, `Anuncios`).
- **Outgoing webhooks / OAuth apps / Commands**: ninguno detectado (tablas vacías o esquemas distintos).
- **Plugins**: `playbooks`, `mattermost-ai`, `com.mattermost.calls`.

## Observaciones de seguridad
- `EnableBotAccountCreation=false` → crear bots requiere token de admin vía API.
- `EnableUserAccessTokens=false`.
- `EnableMultifactorAuthentication=false`.
- `EnableLocalMode=true` → local-mode token en riesgo si el contenedor se compromete.
- `AllowCorsFrom=*` y `EnableIncomingWebhooks/OutgoingWebhooks=true`.
- `AGY_USUARIOS_AUTORIZADOS` vacío en forsis-bot → fail-closed (nadie autorizado a disparar acciones reales).
