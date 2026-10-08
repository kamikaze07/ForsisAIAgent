"""
Persistencia del turno: `sessions` (memoria conversacional) e `idempotency_keys`
(channels.md §1.8), sobre la BD PROPIA del agente.

Dos decisiones que parecen sobre-ingeniería y no lo son:

1. **Sin ORM y sin pool en el import.** FastAPI corre async; `asyncpg` abre una
   conexión por operación. El Sprint 2 no necesita alta concurrencia (es la
   etapa de validación con un usuario piloto), y un pool mal configurado en un
   path de error es una fuente clásica de fugas. El Sprint 8 introduce el pool
   junto con la observabilidad.

2. **`company` forma parte de la clave de sesión.** `liquidaciones-system-analysis.md`
   §1.4 la señala como la fuente de error más peligrosa para un agente
   automatizado: el mismo endpoint lee FORSIS o GERO según el estado de sesión.
   Por eso el `session_id` se compone de (channel, company, actor.subject) y
   la validación de pertenencia se hace SIEMPRE, nunca se deduce del estado.
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from app.contracts.chat_contract import ChatRequest, Company, canonicalizar_request_hash
from app.core.exceptions import (
    DependencyUnavailableError,
    IdempotencyInFlightError,
    IdempotencyKeyReusedError,
)

try:
    import asyncpg
except Exception:  # pragma: no cover
    asyncpg = None  # type: ignore

logger = logging.getLogger(__name__)

IDEMPOTENCY_TTL_S = 24 * 3600  # 24 h, misma ventana que el TTL de sesión
TURN_TIMEOUT_S = 120.0


# --------------------------------------------------------------- conexión

def _dsn_kwargs() -> Dict[str, Any]:
    return {
        "user": os.getenv("POSTGRES_USER", "forsis_agent"),
        "password": os.getenv("POSTGRES_PASSWORD", ""),
        "database": os.getenv("POSTGRES_DB", "forsis_agent"),
        "host": os.getenv("DB_HOST", "db"),
        "port": int(os.getenv("DB_PORT", "5432")),
    }


async def _connect():
    if asyncpg is None:
        raise DependencyUnavailableError("Driver asyncpg no disponible.")
    try:
        return await asyncpg.connect(timeout=5.0, **_dsn_kwargs())
    except Exception as e:
        logger.error("No se pudo conectar a PostgreSQL: %s", type(e).__name__)
        raise DependencyUnavailableError("Base de datos propia no disponible.")


# --------------------------------------------------------------- sesiones

def compose_session_id(channel: str, company: str, actor_subject: str) -> str:
    """
    Identidad de sesión opaca y no adivinable.

    Se deriva por HMAC del site secret + tupla (channel, company, subject) para
    que no sea un string concatenado que cualquiera pueda enumerar y para que el
    servidor necesite el secret para validarla. Sin secret (configuración
    rota) se degrada a uuid4 opaco, que sigue siendo seguro pero no
    determinista — el usuario pierde continuidad de sesión, no seguridad.
    """
    secret = os.getenv("FORSIS_SESSION_SECRET", "")
    material = f"{channel}|{company}|{actor_subject}"
    if secret:
        import hashlib
        import hmac as _hmac

        digest = _hmac.new(secret.encode(), material.encode(), hashlib.sha256).hexdigest()[:20]
        return f"{channel}:{company.lower()}:{digest}"
    return f"{channel}:{company.lower()}:{uuid.uuid4().hex[:20]}"


def parse_session_id(session_id: str) -> Tuple[str, str, str]:
    """Descompone `canal:empresa:hash`. Lanza ValueError si no tiene 3 partes."""
    parts = session_id.split(":")
    if len(parts) != 3:
        raise ValueError("session_id mal formado")
    return parts[0], parts[1], parts[2]


class SessionStore:
    """
    Memoria conversacional mínima pero suficiente para el Sprint 2.

    No replica el `ConversationMemory` del prototipo (que trackea entidades
    tipadas con UUIDs). Todavía no hay herramientas que resuelvan referencias
    ("¿y el de la otra?"), así que guardar el historial literal de turnos es la
    representación honesta de lo que el agente realmente puede usar hoy.
    """

    @staticmethod
    async def ensure(req: ChatRequest) -> str:
        """Valida el session_id entrante o crea uno nuevo. Devuelve el válido."""
        if req.session_id:
            try:
                canal, empresa, _hash = parse_session_id(req.session_id)
            except ValueError:
                # Un session_id con otra forma no puede ser nuestro: no adivino,
                # lo trato como nuevo. Un id SessionMismatch sería más estricto
                # pero obligaría al adaptador a conocer el formato opaco.
                return compose_session_id(req.channel.value, req.company.value, req.actor.subject)

            if canal != req.channel.value or empresa != req.company.value.lower():
                from app.core.exceptions import SessionMismatchError

                raise SessionMismatchError("La sesión pertenece a otro canal u otra empresa.")
            return req.session_id

        return compose_session_id(req.channel.value, req.company.value, req.actor.subject)

    @staticmethod
    async def append_turn(
        session_id: str,
        req: ChatRequest,
        answer: str,
        status: str,
        context_state: Dict[str, Any],
    ) -> None:
        """Guarda user + assistant en el mismo turno. Best-effort con alerta."""
        try:
            conn = await _connect()
        except DependencyUnavailableError:
            raise
        try:
            async with conn.transaction():
                await conn.execute(
                    """
                    INSERT INTO chat_sessions (session_id, channel, company, actor_subject,
                                           state, last_seen_at, created_at)
                    VALUES ($1, $2, $3, $4, $5::jsonb, now(), now())
                    ON CONFLICT (session_id) DO UPDATE
                       SET last_seen_at = now(),
                           state = chat_sessions.state || EXCLUDED.state
                    """,
                    session_id,
                    req.channel.value,
                    req.company.value,
                    req.actor.subject,
                    json.dumps(context_state),
                )
                await conn.execute(
                    """
                    INSERT INTO chat_messages (session_id, role, content, created_at)
                    VALUES ($1, 'user', $2, now()),
                           ($1, 'assistant', $3, now())
                    """,
                    session_id,
                    req.message,
                    answer,
                )
        except Exception as e:
            logger.error("append_turn falló (%s): la respuesta NO se pierde, el log sí.",
                         type(e).__name__)
            raise DependencyUnavailableError("No se pudo persistir el turno.")
        finally:
            await conn.close()

    @staticmethod
    async def history(session_id: str, limit: int = 20) -> List[Dict[str, str]]:
        """Últimos `limit` turnos (user+assistant), en orden cronológico."""
        try:
            conn = await _connect()
        except DependencyUnavailableError:
            raise
        try:
            rows = await conn.fetch(
                """
                SELECT role, content FROM (
                    SELECT role, content, created_at, id FROM chat_messages
                    WHERE session_id = $1
                    ORDER BY created_at DESC, id DESC
                    LIMIT $2
                ) t ORDER BY created_at ASC, id ASC
                """,
                session_id,
                limit * 2,
            )
            return [{"role": r["role"], "content": r["content"]} for r in rows]
        except Exception as e:
            logger.error("history falló: %s", type(e).__name__)
            return []
        finally:
            await conn.close()


# ------------------------------------------------------------ idempotencia

class IdempotencyStore:
    """
    Tramo de idempotencia de `channels.md` §1.8.

    Semántica por estado:
      - RESERVED + request_hash DISTINTO  → 422 IDEMPOTENCY_KEY_REUSED (bug del adaptador)
      - RESERVED + mismo hash, en vuelo   → 409 IDEMPOTENCY_IN_FLIGHT + Retry-After 5
      - COMPLETED + mismo hash            → respuesta guardada byte a byte, no se re-ejecuta
      - COMPLETED + hash DISTINTO         → 422 IDEMPOTENCY_KEY_REUSED

    El turno se reserva ANTES de llamar al LLM, no después: si se reservara al
    final, dos peticiones simultáneas con la misma clave pasarían las dos el
    `SELECT` y ejecutarían el turno dos veces — precisamente lo que la clave
    existe para evitar.
    """

    @staticmethod
    def scope(req: ChatRequest, key: str) -> str:
        """Alcance de unicidad: (channel, actor.subject, Idempotency-Key)."""
        return f"{req.channel.value}:{req.actor.subject}:{key}"

    @staticmethod
    async def reserve(req: ChatRequest, key: str) -> Tuple[str, Optional[Dict[str, Any]]]:
        """
        Intenta reservar la clave. Devuelve:
          ("replay", response_body) → turno ya terminado, devuelve esto tal cual
          ("run",    None)            → el llamador ejecuta el turno
        Lanza 409 si hay un turno en vuelo con la misma clave.
        """
        scope = IdempotencyStore.scope(req, key)
        req_hash = canonicalizar_request_hash(req)
        conn = await _connect()
        try:
            # INSERT ... ON CONFLICT DO NOTHING: la unicidad la impone el índice
            # (scope, key), no una comprobación previa — sin carrera.
            inserted = await conn.fetchval(
                """
                INSERT INTO idempotency_keys (key, scope, request_hash, state, created_at)
                VALUES ($1, $2, $3, 'RESERVED', now())
                ON CONFLICT (key, scope) DO NOTHING
                RETURNING 1
                """,
                key,
                scope,
                req_hash,
            )
            if inserted:
                return ("run", None)

            fila = await conn.fetchrow(
                """
                SELECT request_hash, state, response_body, created_at
                FROM idempotency_keys WHERE key = $1 AND scope = $2
                """,
                key,
                scope,
            )
            if fila is None:
                # La fila desapareció entre el INSERT y el SELECT (TTL sweep).
                # Reintentamos una vez con un INSERT normal.
                await conn.execute(
                    """
                    INSERT INTO idempotency_keys (key, scope, request_hash, state, created_at)
                    VALUES ($1, $2, $3, 'RESERVED', now()) ON CONFLICT DO NOTHING
                    """,
                    key, scope, req_hash,
                )
                return ("run", None)

            if fila["request_hash"] != req_hash:
                raise IdempotencyKeyReusedError(
                    "La Idempotency-Key ya se usó con un cuerpo distinto."
                )

            if fila["state"] == "COMPLETED" and fila["response_body"]:
                return ("replay", json.loads(fila["response_body"]))

            # RESERVED: hay un turno en vuelo. Si es más viejo que el TTL, es un
            # proceso que murió a mitad — lo re-orientamos y tomamos el turno.
            if time.time() - fila["created_at"].timestamp() > IDEMPOTENCY_TTL_S:
                await conn.execute(
                    "UPDATE idempotency_keys SET created_at = now() "
                    "WHERE key = $1 AND scope = $2",
                    key, scope,
                )
                return ("run", None)

            raise IdempotencyInFlightError("Un turno con la misma clave sigue en curso.")
        finally:
            await conn.close()

    @staticmethod
    async def complete(key: str, req: ChatRequest, response_body: Dict[str, Any]) -> None:
        """Marca COMPLETED y guarda la respuesta para el replay byte a byte."""
        scope = IdempotencyStore.scope(req, key)
        try:
            conn = await _connect()
        except DependencyUnavailableError:
            return  # best-effort: perder el replay no pierde el turno ya respondido
        try:
            await conn.execute(
                """
                UPDATE idempotency_keys
                   SET state = 'COMPLETED', response_body = $3::jsonb, completed_at = now()
                 WHERE key = $1 AND scope = $2
                """,
                key, scope, json.dumps(response_body),
            )
        except Exception as e:
            logger.error("idempotency complete falló: %s", type(e).__name__)
        finally:
            await conn.close()

    @staticmethod
    async def release(key: str, req: ChatRequest) -> None:
        """
        Libera la reserva cuando el turno falló. Sin esto, un 502 dejaría la
        clave en RESERVED 24 h y el usuario no podría reintentar el mismo
        mensaje — la idempotencia se convertiría en pérdida de disponibilidad.
        """
        scope = IdempotencyStore.scope(req, key)
        try:
            conn = await _connect()
        except DependencyUnavailableError:
            return
        try:
            await conn.execute(
                "DELETE FROM idempotency_keys WHERE key = $1 AND scope = $2 AND state = 'RESERVED'",
                key, scope,
            )
        except Exception as e:
            logger.error("idempotency release falló: %s", type(e).__name__)
        finally:
            await conn.close()