# ADR-001: Stack Python/FastAPI y secuencia de validación standalone

## Estado
ACEPTADO — 2026-10-05, decisión del usuario (Cesar).

## Contexto
El brief de Fase 1 fijó PHP/Laravel 11 por homogeneidad con trafico-system y
liquidaciones-system. El análisis de `prototype-reusability-analysis.md` y
`llm-provider.md` midió el costo real:

- El núcleo reutilizable del prototipo (`/home/servidor/forsis-agent`) son
  ~2.500 líneas Python ya probadas: Planner, Executor, Registry, Capability,
  contratos Pydantic, PromptBuilder, TemplateComposer.
- En PHP ese núcleo se reescribe desde cero.
- El agente queda detrás de una frontera HTTP (`POST /api/v1/chat`), por lo que
  su lenguaje es invisible para los sistemas que lo consumen.

## Decisión 1 — Stack
**Python 3.12 + FastAPI.**

Consecuencias:
- Se reutiliza el núcleo del prototipo en vez de reescribirlo.
- `OmnirouteProvider` se escribe nuevo (Omniroute es OpenAI-compatible), pero
  reutiliza ~70% de la lógica de aplicación de `OllamaProvider`
  (retry-con-feedback, parseo multi-paso, timeout de pared).
- **Queda obsoleto** el andamiaje PHP ya escrito: `docker/php/Dockerfile`,
  `docker/php/entrypoint.sh`, el servicio `php` del compose y el `fastcgi_pass`
  de nginx. Debe migrarse, no coexistir.
- `architecture.md` debe reescribirse en su capa de runtime. El esquema de
  `db-schema.md` NO cambia: es PostgreSQL y es agnóstico al lenguaje.

## Decisión 2 — Secuencia: validar standalone antes de integrar
El agente se valida mediante una **interfaz web propia** (login propio + UI de
chat) ANTES de integrarlo en las UIs de trafico-system/liquidaciones-system y
antes de cablear Mattermost.

Razones:
- Permite probar el núcleo, el provider y las tools de lectura sin tocar ningún
  sistema en producción.
- El widget embebido y el canal Mattermost son *canales adicionales* sobre un
  contrato (`POST /api/v1/chat`) que ya habrá sido ejercitado de verdad.
- Reduce el riesgo de exponer un agente no validado a 36 canales de Mattermost
  o a las UIs que usan los operadores.

Consecuencias en el plan de sprints:
- La UI standalone sube a sprint temprano, inmediatamente después del endpoint
  `/api/v1/chat` y de la primera tool de lectura.
- El widget embebido, el cableado de `forsis-bot` y el módulo LIQUIDACIONES
  bajan a después del hito de validación con el usuario.
- **El saneo del `BOT_TOKEN` commiteado deja de estar en la ruta crítica**
  (ya no bloquea el sprint 1), pero sigue siendo un incidente de seguridad
  abierto: token en git con `system_post_all` sobre 36 canales. Se mantiene
  como tarea independiente, obligatoria antes de reactivar el canal Mattermost.

## Hito de decisión (go/no-go)
Tras la UI standalone + primera tool de lectura end-to-end, el usuario valida
en persona. Solo con esa validación se habilitan los sprints de integración.

## No decidido aquí
- Fiabilidad del JSON mode (70% crudo / 80% con salvage) sigue mitigada por las
  4 capas de defensa de `agent-core.md`, no resuelta.
- El combo "Forsis" inyecta ~4.000 tokens de prompt propio y no permite fijar
  modelo (402). Valorar combo dedicado al agente.
