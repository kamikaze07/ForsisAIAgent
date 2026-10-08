# Fase 1: Brief de Diseño Arquitectónico

## Fecha
2026-10-03 (inicio Fase 1)

## Decisiones ya tomadas (Fase 0 → Fase 1)
1. **Acceso a datos:** Híbrido — lecturas via DB read-only (GRANT SELECT), escrituras solo via API REST
2. **Stack:** PHP/Laravel 11 + PHP 8.3 (consistencia con trafico-system / liquidaciones-system)
3. **Mattermost:** forsis-bot se mantiene como gateway; delega a `POST /api/v1/chat` del agente
4. **Liquidaciones:** el agente crea solicitudes (gate humano) en MVP; módulo LIQUIDACIONES en workflow
5. **LLM:** Omniroute OpenAI-compatible, combo "Forsis" — provider propio reutilizando lógica del prototipo

## Correcciones obligatorias de Fase 0
- `deployment-strategy.md` usa puerto 20130 (dashboard) — debe corregirse
- `BOT_TOKEN` commiteado en git de forsis-bot — sanear antes de integrar
- `omniroute-config.md` fue corregido por agente 2 (verificar)

## Agentes de Fase 1
| # | Objetivo | Entregable en knowledge/phase1/ |
|---|---|---|
| 1 | Arquitectura de contenedor + esquema BD propia del agente | `architecture.md`, `db-schema.md` |
| 2 | Diseño del núcleo del agente (Planner/Executor/Registry, OmnirouteProvider, prompts) | `agent-core.md`, `llm-provider.md` |
| 3 | Diseño de herramientas (tools/actions) para trafico-system y liquidaciones-system | `tools-design.md`, `permissions.md` |
| 4 | Canales (chat embebido widget + Mattermost) + plan de implementación por sprints | `channels.md`, `sprint-plan.md` |

## Reglas para todos los agentes
- Documentar en `knowledge/phase1/`, NO modificar código de sistemas existentes
- Toda propuesta debe citar el documento de Fase 0 que la sustenta
- Si algo no se puede verificar, marcarlo como BLOQUEANTE, no asumir
- Respetar: fail-closed, allowlist explícita, dry-run obligatorio en acciones de escritura
- No incluir credenciales reales; usar [REDACTED] o referencias a variables de entorno

---
