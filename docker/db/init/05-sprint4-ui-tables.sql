-- =============================================================================
-- 05-sprint4-ui-tables.sql — Interfaz web standalone (Sprint 4)
--
-- Resuelve los bloqueantes de arranque declarados en web-ui-design.md §10:
--   B-U7  agent_ui_sessions (sesiones revocables) + columnas de lockout
--   B-U3  status/trace_id en los mensajes (historial P2 y criterio A5)
--   B-U1  persistencia de ejecuciones de tool enlazables desde la UI (P3, A13)
--   B-U8  mapeo del usuario de UI al actor del contrato (ROL_NO_MAPEADO)
--   B-U14 cuentas piloto con permisos distintos (estado 6 y aislamiento A6)
--
-- NOTA DE ESQUEMA: el código del Sprint 2/3 persiste en `chat_sessions` /
-- `chat_messages`, cuyo session_id es VARCHAR(128). La tabla preexistente
-- `tool_executions` referencia `agent_sessions(id) UUID` y por tanto NO es
-- utilizable desde el flujo vivo. Para no modificar ni romper nada existente,
-- la UI usa su propia tabla `agent_ui_tool_executions` alineada al tipo real.
-- Idempotente: se puede re-ejecutar sin efecto.
-- =============================================================================

-- ---------------------------------------------------------------------------
-- B-U7 · Control de intentos fallidos y bloqueo temporal (criterio A2)
-- ---------------------------------------------------------------------------
ALTER TABLE agent_ui_users
    ADD COLUMN IF NOT EXISTS failed_attempts  INTEGER      NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS locked_until     TIMESTAMPTZ  NULL,
    -- B-U8: enlace explícito del usuario de UI con las identidades de los ERP.
    -- NULL = sin mapear; las tools de negocio denegarán por D-2 (ROL_NO_MAPEADO),
    -- que es el comportamiento correcto y además nos da el estado 6 reproducible.
    ADD COLUMN IF NOT EXISTS traf_username    VARCHAR(64)  NULL,
    ADD COLUMN IF NOT EXISTS liq_nombre_usu   VARCHAR(64)  NULL,
    -- Roles que se enviarán en ChatRequest.actor.roles
    ADD COLUMN IF NOT EXISTS agent_roles      JSONB        NOT NULL DEFAULT '[]'::jsonb,
    -- D-10: fail-closed. Ninguna cuenta puede escribir salvo decisión explícita.
    ADD COLUMN IF NOT EXISTS write_allowlisted BOOLEAN     NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS must_change_password BOOLEAN  NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN agent_ui_users.agent_roles IS
    'Roles enviados en ChatRequest.actor.roles. Fuente de verdad del RBAC de la UI.';
COMMENT ON COLUMN agent_ui_users.write_allowlisted IS
    'D-10 de permissions.md: sin esto en TRUE ninguna escritura procede.';

-- ---------------------------------------------------------------------------
-- B-U7 · Sesiones de UI revocables (§5.5). Token opaco, nunca JWT:
-- así el admin revoca por SQL y el cambio de contraseña invalida el resto.
-- Se guarda SOLO el hash del token; el valor plano vive únicamente en la cookie.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS agent_ui_sessions (
    id            UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    token_hash    CHAR(64)     NOT NULL UNIQUE,        -- sha256 hex del token
    user_id       UUID         NOT NULL REFERENCES agent_ui_users(id) ON DELETE CASCADE,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen_at  TIMESTAMPTZ  NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at    TIMESTAMPTZ  NOT NULL,
    revoked_at    TIMESTAMPTZ  NULL,
    ip            VARCHAR(64)  NULL,
    user_agent    VARCHAR(255) NULL,
    csrf_token    CHAR(64)     NOT NULL                -- doble envío (A-2 de §6.0)
);

CREATE INDEX IF NOT EXISTS ix_ui_sessions_user    ON agent_ui_sessions (user_id, expires_at DESC);
CREATE INDEX IF NOT EXISTS ix_ui_sessions_live    ON agent_ui_sessions (expires_at)
    WHERE revoked_at IS NULL;

COMMENT ON TABLE  agent_ui_sessions IS 'Sesión de login de la UI standalone (8 h). Distinta de la sesión conversacional.';
COMMENT ON COLUMN agent_ui_sessions.token_hash IS 'sha256 del token de cookie. El token plano NO se persiste.';

-- ---------------------------------------------------------------------------
-- B-U3 · El historial debe poder mostrar el estado que el usuario vio en vivo
-- y permitir el filtro only_errors (§6.3, criterio A5). Aditivo, sin reescritura.
-- ---------------------------------------------------------------------------
ALTER TABLE chat_messages
    ADD COLUMN IF NOT EXISTS status   VARCHAR(32) NULL,
    ADD COLUMN IF NOT EXISTS trace_id VARCHAR(64) NULL;

-- Índice parcial para el filtro only_errors del historial
CREATE INDEX IF NOT EXISTS ix_chat_messages_errors ON chat_messages (session_id, created_at DESC)
    WHERE status IN ('error', 'denied', 'degraded');

-- La UI lista hilos por dueño: el aislamiento (A6) se resuelve en el índice.
ALTER TABLE chat_sessions
    ADD COLUMN IF NOT EXISTS ui_user_id UUID NULL REFERENCES agent_ui_users(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS ix_chat_sessions_ui_user ON chat_sessions (ui_user_id, last_seen_at DESC)
    WHERE ui_user_id IS NOT NULL;

-- ---------------------------------------------------------------------------
-- B-U1 · Ejecuciones de tool enlazables desde la respuesta (§3.4 L3 y P3).
-- Alineada a chat_sessions.session_id VARCHAR(128), a diferencia de la
-- tool_executions preexistente (que apunta a agent_sessions UUID).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS agent_ui_tool_executions (
    id             UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id     VARCHAR(128) NOT NULL REFERENCES chat_sessions(session_id) ON DELETE CASCADE,
    trace_id       VARCHAR(64)  NOT NULL,
    ui_user_id     UUID         NULL REFERENCES agent_ui_users(id) ON DELETE SET NULL,
    tool_name      VARCHAR(64)  NOT NULL,
    risk_class     VARCHAR(8)   NOT NULL,
    status         VARCHAR(32)  NOT NULL,       -- ok | denied | error | degraded
    company        VARCHAR(32)  NOT NULL,
    params_in      JSONB        NOT NULL DEFAULT '{}'::jsonb,
    result_out     JSONB        NULL,           -- B-U15: retención a definir antes del piloto
    row_count      INTEGER      NULL,
    source_ref     JSONB        NULL,           -- {server, database, table} para la citación
    error_code     VARCHAR(64)  NULL,
    error_message  TEXT         NULL,
    duration_ms    INTEGER      NULL,
    created_at     TIMESTAMPTZ  NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_ui_tool_exec_session ON agent_ui_tool_executions (session_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_ui_tool_exec_trace   ON agent_ui_tool_executions (trace_id);
CREATE INDEX IF NOT EXISTS ix_ui_tool_exec_owner   ON agent_ui_tool_executions (ui_user_id, created_at DESC);

COMMENT ON TABLE agent_ui_tool_executions IS
    'ADJ-1 de web-ui-design.md §6.0: da el id opaco que trace.tool_executions[] publica.';

-- ---------------------------------------------------------------------------
-- B-U14 · Cuentas piloto. Tres perfiles, para que el HITO no se evalúe solo
-- con el camino feliz de un superusuario:
--   · forsis_admin : admin, mapeado, ve P5 (depuración)
--   · validador    : rol de tráfico, mapeado  → camino feliz de lectura
--   · val_liq      : SIN rol de tráfico       → provoca el estado 6 (denegado)
-- Las contraseñas NO van aquí. Se siembran con scripts/seed_ui_users.py, que
-- las toma del entorno y las hashea con argon2id. Esta migración solo garantiza
-- la forma y los permisos de cada cuenta.
-- ---------------------------------------------------------------------------
UPDATE agent_ui_users
   SET role              = 'validador',
       agent_roles       = '["trafico"]'::jsonb,
       traf_username     = COALESCE(traf_username, 'validador'),
       write_allowlisted = FALSE
 WHERE username = 'validador';

-- Cuenta deliberadamente sin permiso de tráfico: el estado 6 debe ser
-- reproducible sin tocar permisos en caliente.
INSERT INTO agent_ui_users (username, password_hash, display_name, role, agent_roles, is_active, write_allowlisted)
VALUES ('val_liq', '!', 'Validador Liquidaciones (sin tráfico)', 'validador',
        '["liquidaciones"]'::jsonb, TRUE, FALSE)
ON CONFLICT (username) DO UPDATE
   SET agent_roles = '["liquidaciones"]'::jsonb,
       role        = 'validador';

INSERT INTO agent_ui_users (username, password_hash, display_name, role, agent_roles, is_active, write_allowlisted)
VALUES ('forsis_admin', '!', 'Administrador de Validación', 'admin',
        '["trafico","admin"]'::jsonb, TRUE, FALSE)
ON CONFLICT (username) DO UPDATE
   SET agent_roles = '["trafico","admin"]'::jsonb,
       role        = 'admin';

-- password_hash = '!' es un hash imposible de satisfacer (ningún argon2/bcrypt
-- válido lo iguala): la cuenta existe pero NO puede entrar hasta que el script
-- de siembra le ponga una contraseña real. Fail-closed por defecto.
