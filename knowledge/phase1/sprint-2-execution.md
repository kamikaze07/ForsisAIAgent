# Sprint 2 — Ejecución y Verificación

**Estado:** COMPLETADO (37/37 checks superados en `verify-sprint2.sh`, 13/13 en `verify-sprint1.sh`)  
**Fecha:** Lunes 5 de octubre de 2026  
**Objetivo:** Un turno completo de extremo a extremo: mensaje de texto → respuesta de texto vía `POST /api/v1/chat` con persistencia, idempotencia, auth multi-token por canal, proveedor OmniRoute (combo `Forsis`) y auditoría inmutable en PostgreSQL.

---

## 1. Entregables Implementados

1. **`OmnirouteProvider` (`app/infrastructure/llm_gateway/omniroute_provider.py`)**:
   - Integrado con OmniRoute en `http://host.docker.internal:20130/v1` usando el combo `Forsis`.
   - Techo duro de 60s implementado mediante `ThreadPoolExecutor` + `future.result()`.
   - Parseo estructurado en múltiples niveles: JSON directo, `_salvage_json` (strip de fences + extracción de `{...}`), feedback interactivo.
   - Fail-closed: falla elevando `LlmJsonInvalidError` (HTTP 502), nunca un diccionario vacío.
   - Captura del modelo real devuelto (`last_model_real`) para traza (`deepseek-v4-pro-0813`, `gemini-3.8-flash-tiered`, `qwen/qwen3.8-27b`, etc.).
   - Métricas in-process: `llm_json_ok`, `llm_salvage`, `llm_failclosed`, `cache_hit`, `cache_miss`.

2. **Auditoría inmutable (`app/core/audit.py` y `docker/db/init/04-sprint2-audit-log.sql`)**:
   - Tabla física `agent_audit_log` con índices sobre sesión, actor y canal.
   - `AuditStore` asíncrono sobre asyncpg con política fail-open hacia el usuario.

3. **Autenticación multi-token por canal (`app/core/auth.py`)**:
   - Tokens generados para `MATTERMOST`, `TRAFICO`, `LIQUIDACIONES` y `API`.
   - Comparación en tiempo constante con `hmac.compare_digest`.
   - Soporte para rotación con sufijos `_NEXT` y `_PREV`.

4. **Persistencia e Idempotencia (`app/core/store.py` y `docker/db/init/03-sprint2-chat-tables.sql`)**:
   - Tablas `chat_sessions`, `chat_messages` e `idempotency_keys` en PostgreSQL.
   - Sesiones particionadas por `{channel}:{company}:{sha256(actor.subject)[:20]}`.
   - Reserva atómica de idempotencia con bloqueo de 120s; detección de clave reutilizada con cuerpo distinto (HTTP 422 `IDEMPOTENCY_KEY_REUSED`) y replay exacto byte a byte (HTTP 200).

5. **`TemplateComposer` determinista (`app/core/response/template_composer.py`)**:
   - Integración con módulo de `smalltalk` para saludos y despedidas sin invocar al LLM.
   - Respuestas deterministas para cada estado de respuesta (`NO_CAPABILITY`, `CLARIFICATION_NEEDED`, `DEGRADED`, etc.).

6. **`AgentService` (`app/core/agent_service.py`)**:
   - Orquestador del ciclo de vida del turno respetando el techo de 120s (`TURN_TIMEOUT_SECONDS = 120.0`).
   - Flujo: Validación fail-closed → Idempotencia → Sesión multi-empresa → Smalltalk → Planner OmniRoute → Composer → Auditoría → Persistencia.

7. **Router `POST /api/v1/chat` (`app/api/chat.py` y `app/main.py`)**:
   - Validación de contrato Pydantic con `extra="forbid"`.
   - Headers: `Authorization: Bearer ***`, `X-Forsis-Channel`, `Idempotency-Key`.
   - Mapeo estricto de errores a códigos HTTP (200, 400, 401, 403, 409 con `Retry-After: 5`, 413, 422, 502, 504).
   - Endpoint de telemetría `/api/v1/metrics`.

8. **Suite de Verificación `verify-sprint2.sh`**:
   - 37 verificaciones automáticas de contratos, seguridad, idempotencia, fail-closed, tiempos, telemetría y base de datos.

---

## 2. Evidencia de Verificación

```
PRECONDICIONES
  PASS  A0 liveness /api/v1/health → 200 {"status":"ok"}
  PASS  A0 readiness /api/v1/ready → status ok (db + llm)

A1 — TURNO COMPLETO (forma exacta de channels.md §1.5)
  PASS  A1.1 HTTP 200 en turno válido
  PASS  A1.2 status == ok
  PASS  A1.3 answer no vacío
  PASS  A1.4 session_id no vacío (mattermost:forsis:735670d75b8d44a8b5dc)
  PASS  A1.5 trace.llm_model_real no vacío (gemini-3.8-flash-tiered)
  PASS  A1.6 los 9 campos de ChatResponse presentes

A2 — VALIDACIONES FAIL-CLOSED (6 + idempotencia)
  PASS  A2.1 company ausente → 422 VALIDATION_ERROR
  PASS  A2.2 campo extra → 422 (extra=forbid)
  PASS  A2.3 >4000 chars → 413 MESSAGE_TOO_LONG
  PASS  A2.4 token inválido → 401 UNAUTHENTICATED
  PASS  A2.4b Authorization ausente → 401
  PASS  A2.5 authorized=false → 403 FORBIDDEN
  PASS  A2.6 canal del body ≠ canal autenticado → 403 CHANNEL_MISMATCH
  PASS  A2.7 misma key + cuerpo distinto → 422 IDEMPOTENCY_KEY_REUSED

A3 — IDEMPOTENCIA (replay idéntico)
  PASS  A3.1 dos POST idénticos → 200 / 200
  PASS  A3.2 replay devuelve cuerpo byte-idéntico (mismo trace_id y session_id)
  PASS  A3.3 mismo trace_id (6a2c9b55-6516-4463-9973-35bcc38552a0)

A4 — FAIL-CLOSED DE PROVEEDOR (Omniroute caído → 502)
  PASS  A4.1 OmniRoute inalcanzable → LlmUnavailableError(502, LLM_UNAVAILABLE, retryable=False)
  PASS  A4.2 el camino infeliz no degenera en HTTP 500 (con LLM arriba: 200)

A5 — TECHO DE TURNO
  PASS  A5.1 TURN_TIMEOUT_SECONDS == 120.0 s en AgentService
  PASS  A5.2 techo duro por llamada LLM == 60.0 s (ThreadPoolExecutor)
  PASS  A5.3 latencia real del turno 33 ms < 125000 ms
  PASS  A5.4 timeouts de nginx ≥ 130 s (proxy_read_timeout 130s; proxy_read_timeout 130s; proxy_send_timeout 130s; proxy_read_timeout 86400; )

A6 — MÉTRICAS POR CAPA DE PARSEO LLM
  PASS  A6.llm_json_ok métrica presente (valor=2)
  PASS  A6.llm_salvage métrica presente (valor=0)
  PASS  A6.llm_failclosed métrica presente (valor=0)
  PASS  A6.cache métricas cache_hit/cache_miss presentes

A7 — PERSISTENCIA REAL EN POSTGRESQL
  PASS  A7.1 agent_audit_log poblado (8 registro(s) para verify_s2)
  PASS  A7.2 chat_sessions persistido (6 sesión(es))
  PASS  A7.3 chat_messages con pares user/assistant (12 mensajes)
  PASS  A7.4 idempotency_keys COMPLETED con completed_at (6)
  PASS  A7.5 toda fila de auditoría tiene status y duration_ms

A8 — AISLAMIENTO DEL RUNTIME (invariantes Sprint 1)
  PASS  A8.1 knowledge/ NO está montado en producción
  PASS  A8.2 uvicorn en ejecución (PID 1203)
  PASS  A8.3 firma del Planner sin cambios (4eb2b30d7dd7fe5b59dc077512a19a87edbad9fb5743554239d6bed85fd8736e)

═══ RESULTADO SPRINT 2 ═══
  PASS: 37
  FAIL: 0
```
