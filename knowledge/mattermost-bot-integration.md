# Mattermost — Estrategia de Integración para Forsis Bot

## Estado actual
- Ya existe `forsisbot` (usuario `zgu6x8p5mjdaxdj5qdbynqak4w`, `system_post_all`), corriendo como contenedor `forsis-bot` con `mattermostdriver`.
- Bot token actual en `/home/servidor/forsis-bot/.env` → `BOT_TOKEN=ns5nmg...ym9w`.
- Config: `MATTERMOST_URL=chatforsis.ddns.net`, esquema `https`, puerto 443.

## Opciones de integración recomendadas

### 1) Bot account con API REST v4 (recomendado)
- Crear bot vía `POST /api/v4/bots` con token admin → token bearer persistente.
- Permissions: `system_user` + `system_post_all` (ya tiene). Para acciones administrativas → `system_admin`.
- Endpoints útiles:
  - `POST /api/v4/posts` → publicar en canal.
  - `PUT /api/v4/posts/{postid}/patch` → editar.
  - `GET /api/v4/channels/{id}/posts` → leer historial.
  - `GET /api/v4/users/me` → identidad.
  - `GET /api/v4/teams/{teamid}/channels` → descubrir canales.
  - `GET /api/v4/users/in_team/{teamid}` → lista usuarios.
- SDK oficial: `mattermostdriver` (Node/Python) — ya en uso.

### 2) Incoming Webhooks (solo lectura entrante)
- `POST /hooks/{hook_id}` → postea en canal sin auth bearer.
- 3 webhooks ya activos (Chat General admin, Tráfico-Operación, Anuncios).
- Limitación: solo posts, sin lectura.

### 3) Outgoing Webhooks / Slash Commands
- Callback HTTP por evento de post → permite reaccionar.
- Ninguno configurado actualmente (tabla vacía).

### 4) Local Mode (admin local)
- `MM_LOCALMODETOKEN` + header `X-Local-Mode: true` → bypass OAuth.
- Útil para operaciones de admin desde el mismo host, pero **riesgo**: si el contenedor se compromete, acceso total.
- `EnableLocalMode=true` en esta instancia.

### 5) OAuth2 / OIDC
- `EnableOAuthServiceProvider=true`, `EnableDynamicClientRegistration=false`.
- Flujo: redirigir usuario → consentimiento → token → API como ese usuario.

## Flujo propuesto para Forsis Bot
1. Bot account con token API v4.
2. Escuchar canales vía `websocket` (driver lo soporta) o polling `GET /channels/{id}/posts`.
3. Post respuestas con `POST /posts`.
4. Comando slash `/forsis` vía `EnableCommands=true` para acciones.
5. Autorización por usuario (lista blanca `AGY_USUARIOS_AUTORIZADOS`) → fail-closed.

## Tokens / credenciales existentes
- `BOT_TOKEN` en forsis-bot `.env` (valor truncado: `ns5nmg...ym9w`).
- No hay OAuth apps registradas.
- No hay user access tokens activos (`EnableUserAccessTokens=false`).

## Permisos necesarios según caso
- Solo responder en chat → `system_user` + `system_post_all` (suficiente).
- Administrar canales/usuarios → `system_admin`.
- Gestionar webhooks → `manage_webhooks` scope.
