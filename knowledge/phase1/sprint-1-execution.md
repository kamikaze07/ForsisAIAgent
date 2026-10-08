# Forsis AI Agent — Sprint 1: Contenedor Python/FastAPI + BD

## Estado
COMPLETADO — 2026-10-05. Verificación automática 13/13 PASS en `verify-sprint1.sh`.

## Entregables Reales Implementados y Verificados

1. **Stack de Contenedores en Ejecución**:
   - `forsis-ai-agent-app`: Python 3.12.15 + FastAPI en uvicorn (puerto interno 8000). Healthy.
   - `forsis-ai-agent-db`: PostgreSQL 16 Alpine privado sin `ports:` al host (no colisiona con el PG del host). Healthy.
   - `forsis-ai-agent-nginx`: Reverse Proxy TLS en `0.0.0.0:8099` (HTTPS). Healthy. Timeout 130s.

2. **Endpoints de Health y Readiness**:
   - `GET /api/v1/health`: Retorna `{"status":"ok"}`.
   - `GET /api/v1/ready`: Verifica DB (`SELECT 1`), LLM OmniRoute (combo `Forsis`), y expone `planner_signature`.

3. **Esquema Relacional**:
   - 7 tablas/vistas verificadas (`sessions`, `messages`, `plans`, `audit_log`, `idempotency_keys`, `channel_identity_map`, `agent_ui_users`).
   - 1 cuenta de UI sembrada (`validador`) con hash bcrypt `$2y$12$...`.

4. **Núcleo del Prototipo Reutilizado**:
   - Contratos Pydantic, Planner, Executor, CapabilityRegistry, Prompts y Domain Types importados a `app/`.
   - Bug de constructor duplicado en `executor.py` (`__init__`) resuelto.
   - `OmnirouteProvider` implementado con parseo multicapa (Capa 1 json, Capa 2 markdown fences, Capa 3 substring regex).

5. **Firma del Planner**:
   - SHA-256 acumulativo de código y prompts: `4eb2b30d7dd7fe5b59dc077512a19a87edbad9fb5743554239d6bed85fd8736e`.
   - Guardada en `.firma-esperada` y validada por `verify-firma.sh --esperado`.

6. **Scripts Operativos**:
   - `up.sh`: Arranque con preflight de .env y redes externas.
   - `down.sh`: Parada segura; `--purge` interactivo para destrucción de volúmenes.
   - `logs.sh`: Monitoreo por servicio o global.
   - `migrate.sh`: Ejecución idempotente de scripts SQL en `docker/db/init/`.
   - `verify-firma.sh`: Verificación de deriva de código/prompts del planner.
   - `verify-sprint1.sh`: Suite de validación de criterios A1-A7.

7. **Redes y Seguridad**:
   - Red externa `forsis-agent_net` creada y conectada a los servicios del agente.
   - Bind mount `./knowledge` retirado de producción en runtime.
   - Swagger / ReDoc (`/docs`, `/redoc`) deshabilitados en producción.
