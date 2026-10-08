# Mattermost REST API v4 — Endpoints para Mensajería

> Base: `https://chatforsis.ddns.net/api/v4` (o `http://localhost:25080/api/v4` desde el host).
> Auth: `Authorization: Bearer <bot_token>` (26 chars, token de bot account).

## Estado / info
| Endpoint | Método | Notas |
|---|---|---|
| `/system/ping` | GET | Health check, sin auth. `{"status":"OK"}` |
| `/config/client?format=old` | GET | Config pública (Version, SiteURL, flags). Sin auth. |
| `/config/client` | GET | Config pública completa. |
| `/users/me` | GET | Identidad del token. |

## Enviar mensajes
| Endpoint | Método | Body mínimo | Permiso |
|---|---|---|---|
| `/posts` | POST | `{channel_id, message}` | `create_post` |
| `/posts` | PATCH | `{id, message}` (edita) | `edit_post` |
| `/posts/{post_id}/patch` | PUT | `{message}` | `edit_post` |
| `/posts/{post_id}/reactions/{emoji}` | POST | — | `add_reaction` |
| `/posts/{post_id}` | DELETE | — | `delete_post` (admin) |

Ejemplo envío:
```bash
curl -X POST https://chatforsis.ddns.net/api/v4/posts \
  -H "Authorization: Bearer $BOT_TOKEN" -H 'Content-Type: application/json' \
  -d '{"channel_id":"tc8yzf8ckpd7mxyo3p41uwx5ea","message":"Hola"}'
```

## Recibir mensajes
| Endpoint | Método | Notas |
|---|---|---|
| `/channels/{channel_id}/posts` | GET | `?page=0&per_page=60` — historial. |
| `/channels/{channel_id}/posts?since=<ms>` | GET | Solo nuevos desde timestamp. |
| `/users/{user_id}/posts/flag` | GET | Posts marcados. |
| `/channels/{channel_id}/members` | GET | Miembros del canal. |

**Tiempo real**: WebSocket `wss://chatforsis.ddns.net/api/v4/websocket` con `{token}` como query. Eventos `posted`, `new_websocket_event`. Es lo que usa `forsisbot` vía `mattermostdriver`.

## Comandos slash
| Endpoint | Método | Notas |
|---|---|---|
| `/commands` | POST | Crear slash command (`/forsis`). |
| `/commands` | GET | Listar (admin). |

## Webhooks
| Endpoint | Método | Notas |
|---|---|---|
| `/hooks/{incoming_webhook_id}` | POST | Sin bearer; body `{text, username}`. |
| `/webhooks/incoming` | GET/POST | Listar/crear incoming (admin). |
| `/webhooks/outgoing/{id}` | POST | Disparar outgoing manualmente. |

## Canales y equipos
| Endpoint | Método | Notas |
|---|---|---|
| `/teams` | GET | Equipos del usuario. |
| `/teams/{team_id}/channels` | GET | Canales del equipo. |
| `/channels/{channel_id}` | GET | Metadatos. |
| `/channels/members/{user_id}/{team_id}` | GET | Canales del usuario en un equipo. |
| `/users/in_team/{team_id}` | GET | Usuarios de un equipo. |

## IDs útiles de esta instancia
- **Equipo Forsis PR**: `pc64qx8zxpdrdpudjfatnts9ro`
  - Chat General: `tc8yzf8ckpd7mxyo3p41uwx5ea`
  - Anuncios: `3qi4bu56niyb88iy6yb3s9wane`
  - Tráfico: `1ufg418kb7npicdyompu9qniwy`
  - Liquidaciones-TI: `d5iasrubhir8bkm4h1dqnqeiqo`
  - Facturación: `s55sa548e3nybf951jah8rfy7y`
- **Equipo Forsis Cadereyta**: `bin5an9b47dpfjw9oyiw6cwetc` (Chat General `ak9upmot4idybyoz14khzq7zeh`)
- **Equipo Forsis Cacalilao**: `t47nftgf43rubbdkinc3oamy8a` (Chat General `wshhjx4rzpdxux5rxgbqzeia5w`)
- **Equipo Gero Ragar**: `63m5k8btub89j8ec7crdk84w6o` (Chat General `6mb8pa3aatypbngfzwcpou9pwc`)
- **Equipo Laura**: `w1n3j5pwji8otctzdwt4qdsfhh`

## IDs de bots
- `forsisbot`: `zgu6x8p5mjdaxdj5qdbynqak4w` (`system_post_all`, activo)
- `calls`: `y3pfoz8rhfgbdcrb4t14b1ncth`
- `system-bot`: `wje1bujjmbd83cf6wq8uwu6a5y`
- `stickerbot`: `ojab7tuxyfy4tj1xwr9dr7ae7y` (desactivado)

## Notas de versión
- v11.6.0. Endpoints legacy v3 siguen disponibles pero **no usar** (`/api/v3` deprecado).
- `EnableUserAccessTokens=false` → para tokens de usuario individual requiere admin que lo habilite.
- `EnableBotAccountCreation=false` → bots nuevos requieren POST `/bots` con token admin.