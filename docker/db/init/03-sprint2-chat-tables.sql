-- ==============================================================================
-- FORSIS AI AGENT — ESQUEMA COMPLEMENTARIO SPRINT 2 (03-sprint2-chat-tables.sql)
-- Tablas de sesión y mensajes optimizadas para el contrato POST /api/v1/chat
-- ==============================================================================

-- 1. TABLA chat_sessions: clave de sesión compuesta string (canal:empresa:hash)
CREATE TABLE IF NOT EXISTS chat_sessions (
    session_id VARCHAR(128) PRIMARY KEY,
    channel VARCHAR(32) NOT NULL,
    company VARCHAR(32) NOT NULL,
    actor_subject VARCHAR(128) NOT NULL,
    state JSONB NOT NULL DEFAULT '{}'::jsonb,
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_chat_sessions_actor ON chat_sessions(channel, company, actor_subject);
CREATE INDEX IF NOT EXISTS ix_chat_sessions_seen ON chat_sessions(last_seen_at DESC);

-- 2. TABLA chat_messages: historial ordenado de turnos de conversación
CREATE TABLE IF NOT EXISTS chat_messages (
    id BIGSERIAL PRIMARY KEY,
    session_id VARCHAR(128) NOT NULL REFERENCES chat_sessions(session_id) ON DELETE CASCADE,
    role VARCHAR(16) NOT NULL, -- 'user' | 'assistant'
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_chat_messages_session ON chat_messages(session_id, created_at ASC, id ASC);
