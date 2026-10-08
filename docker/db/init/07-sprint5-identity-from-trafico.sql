-- ============================================================================
-- 07-sprint5-identity-from-trafico.sql
--
-- Sprint 5 / sprint5-identity-design.md §5.1: la credencial del agente deja de
-- ser propia. El login verifica contra `trafico.usuarios` en vivo y este
-- agente deja de almacenar contraseñas propias.
--
-- Por qué `password_hash` pasa a NULL en vez de borrarse:
--   * La tabla ya tiene `NOT NULL`; borrarla sería una migración destructiva
--     sobre una tabla con sesiones y auditoría referenciándola.
--   * Conservar la columna permite volver atrás con un INSERT si el diseño
--     se revisa (y hace visible el estado: NULL significa "la credencial vive
--     en tráfico", que es exactamente lo que quiere decir).
--   * `NULL` es fail-closed por construcción: cualquier ruta de código que
--     aún intente verificar localmente obtiene None y rechaza.
--
-- Lo que NO se borra, y por qué: `role`, `is_active`, `failed_attempts`,
-- `locked_until`, `agent_roles` y `write_allowlisted` son política DEL AGENTE,
-- no de tráfico. El bloqueo por intentos fallidos y la escala de UI
-- (admin/validador) no tienen equivalente en `trafico.usuarios`, así que
-- seguirían siendo locales aunque la credencial ya no lo sea.
--
-- Idempotente: re-ejecutable sin efecto.
-- ============================================================================

ALTER TABLE agent_ui_users
    ALTER COLUMN password_hash DROP NOT NULL;

COMMENT ON COLUMN agent_ui_users.password_hash IS
    'SIEMPRE NULL desde el Sprint 5. La credencial vive en trafico.usuarios y '
    'se verifica en vivo contra trafico-db por el canal de solo lectura. '
    'Nunca se persiste un hash de trafico aqui.';

-- Las cuentas que existían con hash argon2id propio lo pierden. A partir de
-- aquí la verificación ocurre contra tráfico.
UPDATE agent_ui_users
   SET password_hash = NULL
 WHERE password_hash IS NOT NULL;

-- `must_change_password` no tiene sentido ya: no hay contraseña local que
-- cambiar. dejarla en TRUE bloquearía la UI de esas cuentas sin motivo.
UPDATE agent_ui_users
   SET must_change_password = FALSE
 WHERE must_change_password = TRUE;

-- El origen de la identidad se hace explícito para diagnóstico: una cuenta
-- con estas dos columnas vacías es una cuenta local pura (no mapeada), y una
-- con `traf_username` es una identidad de tráfico provisionada.
COMMENT ON COLUMN agent_ui_users.traf_username IS
    'Username en trafico.usuarios. Se rellena solo en el login (sprint5 §5.2). '
    'NULL = identidad no vinculada, y las consultas de negocio se deniegan '
    '(web-ui-design.md §B-U8).';

-- Prueba de que la migración corrió: si esto no vale 0, el UPDATE de arriba
-- no encontró lo que esperaba.
DO $$
DECLARE
    restantes INTEGER;
BEGIN
    SELECT count(*) INTO restantes
      FROM agent_ui_users
     WHERE password_hash IS NOT NULL;
    IF restantes > 0 THEN
        RAISE EXCEPTION
            'Sprint 5: quedan % filas con password_hash no NULL.', restantes;
    END IF;
END $$;