-- ==============================================================================
-- FORSIS AI AGENT — ESQUEMA RELACIONAL COMPLEMENTARIO (02-sprint1-tables.sql)
-- Tablas y vistas para Sprint 1: Idempotencia, Identidad, UI Users, Planes
-- ==============================================================================

-- 1. TABLA agent_ui_users (Cuentas nativas para la UI Standalone)
CREATE TABLE IF NOT EXISTS agent_ui_users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username VARCHAR(64) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    display_name VARCHAR(128) NOT NULL,
    role VARCHAR(32) NOT NULL DEFAULT 'validador', -- 'admin' | 'validador'
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_login_at TIMESTAMPTZ NULL
);

CREATE INDEX IF NOT EXISTS ix_agent_ui_users_username ON agent_ui_users(username);

-- 2. TABLA idempotency_keys (Garantía at-most-once para llamadas de API)
CREATE TABLE IF NOT EXISTS idempotency_keys (
    key VARCHAR(128) NOT NULL,
    scope VARCHAR(128) NOT NULL,
    request_hash VARCHAR(64) NOT NULL,
    state VARCHAR(32) NOT NULL DEFAULT 'in_flight', -- 'in_flight' | 'completed' | 'failed'
    response_body JSONB NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMPTZ NOT NULL DEFAULT (CURRENT_TIMESTAMP + INTERVAL '24 hours'),
    PRIMARY KEY (scope, key)
);

CREATE INDEX IF NOT EXISTS ix_idempotency_expires ON idempotency_keys(expires_at);

-- 3. TABLA channel_identity_map (Mapeo explícito canal externo -> identidad de negocio)
CREATE TABLE IF NOT EXISTS channel_identity_map (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    channel VARCHAR(32) NOT NULL,                    -- 'mattermost' | 'widget'
    external_id VARCHAR(128) NOT NULL,               -- Mattermost user_id, etc.
    subject VARCHAR(64) NOT NULL,                   -- ID de usuario en trafico/liquidaciones
    subject_type VARCHAR(32) NOT NULL,              -- 'trafico_user' | 'liquidaciones_user'
    company VARCHAR(32) NOT NULL DEFAULT 'FORSIS',   -- 'FORSIS' | 'GERO'
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_channel_ext UNIQUE (channel, external_id)
);

CREATE INDEX IF NOT EXISTS ix_channel_identity_lookup ON channel_identity_map(channel, external_id);

-- 4. TABLA plans (Planes de ejecución generados por el Planner)
CREATE TABLE IF NOT EXISTS plans (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
    intent VARCHAR(128) NOT NULL,
    steps JSONB NOT NULL DEFAULT '[]'::jsonb,
    status VARCHAR(32) NOT NULL DEFAULT 'pending', -- 'pending' | 'executing' | 'completed' | 'failed'
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_plans_session ON plans(session_id, created_at DESC);

-- 5. VISTAS DE COMPATIBILIDAD (sessions, messages, audit_log)
CREATE OR REPLACE VIEW sessions AS SELECT * FROM agent_sessions;
CREATE OR REPLACE VIEW messages AS SELECT * FROM agent_messages;
CREATE OR REPLACE VIEW audit_log AS SELECT * FROM audit_records;

-- 6. SEED PILOTO (Exactamente 1 cuenta validadora inicial)
INSERT INTO agent_ui_users (username, password_hash, display_name, role)
VALUES (
    'validador',
    '$2y$12$0b9/3jCCNIDSWs6Fhbd5TOlpSkarDirOtALb91ZFsceTYZeuAop3O',
    'Usuario Validador Piloto',
    'validador'
)
ON CONFLICT (username) DO NOTHING;
