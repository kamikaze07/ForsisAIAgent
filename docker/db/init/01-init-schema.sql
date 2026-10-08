-- ==============================================================================
-- FORSIS AI AGENT — ESQUEMA RELACIONAL (01-init-schema.sql)
-- Motor: PostgreSQL 16 Alpine
-- ==============================================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- 1. SESIONES DE AGENTE
CREATE TABLE IF NOT EXISTS agent_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    channel_type VARCHAR(32) NOT NULL,
    channel_session_id VARCHAR(128) NOT NULL,
    user_id VARCHAR(64) NOT NULL,
    user_role VARCHAR(32) NOT NULL DEFAULT 'operador',
    state VARCHAR(32) NOT NULL DEFAULT 'active',
    context_metadata JSONB DEFAULT '{}'::jsonb,
    total_tokens_consumed INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    closed_at TIMESTAMPTZ NULL
);

CREATE INDEX IF NOT EXISTS ix_sessions_channel ON agent_sessions(channel_type, channel_session_id);
CREATE INDEX IF NOT EXISTS ix_sessions_user ON agent_sessions(user_id, state);
CREATE INDEX IF NOT EXISTS ix_sessions_updated ON agent_sessions(updated_at DESC);

-- 2. MENSAJES Y CONTEXTO
CREATE TABLE IF NOT EXISTS agent_messages (
    id BIGSERIAL PRIMARY KEY,
    session_id UUID NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
    role VARCHAR(16) NOT NULL,
    content TEXT NULL,
    tool_calls JSONB NULL,
    tool_call_id VARCHAR(64) NULL,
    token_count INTEGER NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_messages_session_seq ON agent_messages(session_id, id ASC);
CREATE INDEX IF NOT EXISTS ix_messages_tool_call_id ON agent_messages(tool_call_id) WHERE tool_call_id IS NOT NULL;

-- 3. EJECUCIÓN DE HERRAMIENTAS
CREATE TABLE IF NOT EXISTS tool_executions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
    tool_name VARCHAR(64) NOT NULL,
    category VARCHAR(32) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'proposed',
    requires_approval BOOLEAN NOT NULL DEFAULT FALSE,
    parameters_in JSONB NOT NULL DEFAULT '{}'::jsonb,
    result_out JSONB NULL,
    error_message TEXT NULL,
    execution_time_ms INTEGER NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMPTZ NULL
);

CREATE INDEX IF NOT EXISTS ix_tool_exec_session ON tool_executions(session_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_tool_exec_name_status ON tool_executions(tool_name, status);
CREATE INDEX IF NOT EXISTS ix_tool_exec_pending ON tool_executions(status) WHERE status = 'proposed';

-- 4. COMPUERTAS DE APROBACIÓN HUMANA
CREATE TABLE IF NOT EXISTS approval_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tool_execution_id UUID NOT NULL UNIQUE REFERENCES tool_executions(id) ON DELETE RESTRICT,
    session_id UUID NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
    action_code VARCHAR(64) NOT NULL,
    summary TEXT NOT NULL,
    requested_payload JSONB NOT NULL,
    risk_level VARCHAR(16) NOT NULL DEFAULT 'medium',
    status VARCHAR(16) NOT NULL DEFAULT 'pending',
    approver_user_id VARCHAR(64) NULL,
    approval_channel VARCHAR(32) NULL,
    rejection_reason TEXT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    responded_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_approvals_status_expires ON approval_requests(status, expires_at);
CREATE INDEX IF NOT EXISTS ix_approvals_session ON approval_requests(session_id);

-- 5. AUDITORÍA INMUTABLE
CREATE TABLE IF NOT EXISTS audit_records (
    id BIGSERIAL PRIMARY KEY,
    event_uuid UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    session_id UUID NULL REFERENCES agent_sessions(id) ON DELETE SET NULL,
    tool_execution_id UUID NULL REFERENCES tool_executions(id) ON DELETE SET NULL,
    event_type VARCHAR(64) NOT NULL,
    actor_id VARCHAR(64) NOT NULL,
    target_entity VARCHAR(64) NULL,
    target_id VARCHAR(64) NULL,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    ip_address INET NULL,
    integrity_hash VARCHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_audit_target ON audit_records(target_entity, target_id);
CREATE INDEX IF NOT EXISTS ix_audit_session_time ON audit_records(session_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_audit_type_time ON audit_records(event_type, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_audit_details_gin ON audit_records USING gin (details);

-- 6. DOCUMENTOS Y CHUNKS RAG
CREATE TABLE IF NOT EXISTS rag_documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title VARCHAR(255) NOT NULL,
    source_path VARCHAR(512) NOT NULL UNIQUE,
    doc_hash VARCHAR(64) NOT NULL,
    total_chunks INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS rag_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES rag_documents(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    content TEXT NOT NULL,
    vector_id VARCHAR(128) NULL,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_rag_chunks_doc ON rag_chunks(document_id, chunk_index);
CREATE INDEX IF NOT EXISTS ix_rag_chunks_meta_gin ON rag_chunks USING gin (metadata);

-- 7. CONFIGURACIONES GLOBALES
CREATE TABLE IF NOT EXISTS agent_configs (
    config_key VARCHAR(64) PRIMARY KEY,
    config_value JSONB NOT NULL,
    value_type VARCHAR(16) NOT NULL DEFAULT 'string',
    description VARCHAR(255) NULL,
    is_secret BOOLEAN NOT NULL DEFAULT FALSE,
    updated_by VARCHAR(64) NOT NULL DEFAULT 'system',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
