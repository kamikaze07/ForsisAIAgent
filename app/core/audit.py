"""
AuditStore asíncrono sobre agent_audit_log (sprint-plan-v2.md D-2).
Cumple con channels.md §1.8.2.

Append-only con política fail-open hacia el usuario:
Un fallo de logging a la BD emite una alerta en logs pero NO interrumpe la respuesta.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional
import asyncpg

logger = logging.getLogger(__name__)


class AuditStore:
    def __init__(self, dsn: Optional[str] = None):
        user = os.getenv("POSTGRES_USER", "forsis_agent")
        password = os.getenv("POSTGRES_PASSWORD", "forsis_agent_secure_pass")
        host = os.getenv("POSTGRES_HOST", "db")
        port = os.getenv("POSTGRES_PORT", "5432")
        database = os.getenv("POSTGRES_DB", "forsis_agent")
        self.dsn = dsn or f"postgresql://{user}:{password}@{host}:{port}/{database}"

    async def _get_conn(self) -> asyncpg.Connection:
        return await asyncpg.connect(self.dsn)

    async def record_turn(
        self,
        turn_id: str,
        session_id: str,
        channel: str,
        company: str,
        actor_subject: str,
        actor_roles: List[str],
        ip: Optional[str] = None,
        user_agent: Optional[str] = None,
        status: str = "ok",
        duration_ms: int = 0,
        error_code: Optional[str] = None,
        plan_id: Optional[str] = None,
        tasks_count: int = 0,
        tools_called: Optional[List[str]] = None,
        sql_statements_count: int = 0,
        write_calls_count: int = 0,
    ) -> bool:
        """
        Inserta un registro append-only de auditoría.
        Fail-open: captura excepciones internas para no fallar el turno del usuario.
        """
        tools_json = json.dumps(tools_called or [])
        roles_json = json.dumps(actor_roles or [])

        query = """
            INSERT INTO agent_audit_log (
                turn_id, session_id, channel, company, actor_subject, actor_roles,
                ip, user_agent, status, duration_ms, error_code, plan_id,
                tasks_count, tools_called, sql_statements_count, write_calls_count
            ) VALUES (
                $1, $2, $3, $4, $5, $6::jsonb,
                $7, $8, $9, $10, $11, $12,
                $13, $14::jsonb, $15, $16
            );
        """
        try:
            conn = await self._get_conn()
            try:
                await conn.execute(
                    query,
                    turn_id,
                    session_id,
                    channel,
                    company,
                    actor_subject,
                    roles_json,
                    ip,
                    user_agent,
                    status,
                    duration_ms,
                    error_code,
                    plan_id,
                    tasks_count,
                    tools_json,
                    sql_statements_count,
                    write_calls_count,
                )
                return True
            finally:
                await conn.close()
        except Exception as exc:
            # FAIL-OPEN: Alertar en logs, nunca romper la interacción del usuario
            logger.error(
                "CRITICAL: Fallo al escribir en agent_audit_log para turn_id=%s: %s",
                turn_id,
                exc,
                exc_info=True,
            )
            return False


# Singleton global
audit_store = AuditStore()
