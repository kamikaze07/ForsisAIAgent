-- ============================================================================
-- SPRINT 2: TABLA DE AUDITORÍA EMPRESARIAL (agent_audit_log)
-- Cumple con sprint-plan-v2.md D-2 y channels.md §1.8.2
-- Append-only para trazabilidad forense
-- ============================================================================

CREATE TABLE IF NOT EXISTS agent_audit_log (
    id BIGSERIAL PRIMARY KEY,
    turn_id VARCHAR(64) NOT NULL UNIQUE,
    session_id VARCHAR(128) NOT NULL,
    channel VARCHAR(32) NOT NULL,
    company VARCHAR(32) NOT NULL,
    actor_subject VARCHAR(128) NOT NULL,
    actor_roles JSONB NOT NULL DEFAULT '[]'::jsonb,
    ip VARCHAR(64),
    user_agent TEXT,
    status VARCHAR(32) NOT NULL,
    duration_ms INTEGER NOT NULL DEFAULT 0,
    error_code VARCHAR(64),
    plan_id VARCHAR(64),
    tasks_count INTEGER NOT NULL DEFAULT 0,
    tools_called JSONB NOT NULL DEFAULT '[]'::jsonb,
    sql_statements_count INTEGER NOT NULL DEFAULT 0,
    write_calls_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_agent_audit_log_session ON agent_audit_log(session_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_agent_audit_log_actor ON agent_audit_log(actor_subject, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_agent_audit_log_channel ON agent_audit_log(channel, created_at DESC);

-- Columna completed_at para idempotencia
ALTER TABLE idempotency_keys ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ;
