-- ============================================================================
-- 06-sprint4-password-changed.sql
--
-- Sprint 4 / §6.11: registrar cuándo se cambió la contraseña.
--
-- Por qué una columna y no deducirlo del log: la política de caducidad y el
-- aviso "tu contraseña tiene N meses" necesitan un dato consultable en la
-- misma fila que se lee al autenticar. Derivarlo de los logs obligaría a
-- conservarlos para siempre y a escanearlos en cada login.
--
-- Idempotente: re-ejecutable sin efecto si la columna ya existe.
-- ============================================================================

ALTER TABLE agent_ui_users
    ADD COLUMN IF NOT EXISTS password_changed_at TIMESTAMPTZ;

-- Las cuentas ya existentes se marcan con su fecha de creación: es la mejor
-- aproximación disponible y evita que todas aparezcan como "nunca cambiada",
-- que es indistinguible de "cambiada hoy" en una columna NULL.
UPDATE agent_ui_users
   SET password_changed_at = created_at
 WHERE password_changed_at IS NULL;

COMMENT ON COLUMN agent_ui_users.password_changed_at IS
    'Último cambio de contraseña (§6.11). Se actualiza en change_password().';
