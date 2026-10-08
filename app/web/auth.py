"""
Autenticación de la interfaz web standalone (web-ui-design.md §5.5, §6.1-6.2).

Tres decisiones que conviene no revertir sin leer el diseño:

1. **Token opaco en BD, no JWT.** Un JWT no se puede revocar sin una lista de
   revocación, que es exactamente la tabla que el JWT pretendía evitar. Con
   `agent_ui_sessions` el admin corta una sesión con un UPDATE y el cambio de
   contraseña invalida las demás. La cookie lleva el token plano; la BD solo
   su sha256, de modo que un volcado de la tabla no permite suplantar a nadie.

2. **CSRF por doble envío.** `SameSite=Lax` no cubre POST de formulario
   cross-site en todos los flujos; el header `X-Forsis-CSRF` comparado contra
   el valor de la sesión sí. Obligatorio en todo método mutante (A-2 de §6.0).

3. **Lockout contado en la BD, no en memoria.** Con varios workers de uvicorn
   un contador en proceso es un contador que no cuenta: cada worker lleva el
   suyo y 5 intentos se vuelven 5*N. La columna vive en `agent_ui_users`.

El mensaje de credenciales inválidas es siempre el mismo y el trabajo de hash
se hace incluso cuando el usuario no existe: si no, la diferencia de latencia
delata qué usuarios son reales (enumeración por canal lateral).
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app.core.store import _connect  # mismo patrón de conexión que el Sprint 2
from app.web import identity

logger = logging.getLogger(__name__)

# --------------------------------------------------------------- parámetros

COOKIE_SESSION = "forsis_agent_ui_session"
COOKIE_CSRF = "forsis_csrf"
HEADER_CSRF = "X-Forsis-CSRF"

SESSION_TTL_H = int(os.getenv("AGENT_UI_SESSION_TTL_H", "8"))      # §5.5: 8 h
MAX_FAILED_ATTEMPTS = int(os.getenv("AGENT_UI_MAX_ATTEMPTS", "5"))  # §6.1 A2
LOCKOUT_MINUTES = int(os.getenv("AGENT_UI_LOCKOUT_MIN", "15"))      # §6.1 A2

# Hash de referencia para el camino "usuario inexistente": un argon2id válido
# de una contraseña aleatoria. Verificarlo cuesta lo mismo que uno real, lo
# que iguala la latencia de ambos caminos.
_DUMMY_HASH: Optional[str] = None

try:
    from argon2 import PasswordHasher
    from argon2.exceptions import InvalidHashError, VerifyMismatchError

    _ph: Any = PasswordHasher()
except Exception:  # pragma: no cover — la imagen sin argon2 falla al arrancar
    _ph = None
    PasswordHasher = None  # type: ignore
    InvalidHashError = VerifyMismatchError = Exception  # type: ignore


def _hasher() -> Any:
    if _ph is None:
        raise RuntimeError(
            "argon2-cffi no está instalado: la UI no puede verificar contraseñas. "
            "Revisa requirements.txt (argon2-cffi==23.1.0)."
        )
    return _ph


def hash_password(plain: str) -> str:
    """Hash argon2id. Usado por el script de siembra, nunca por un endpoint."""
    return _hasher().hash(plain)


def _dummy_hash() -> str:
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = str(_hasher().hash(secrets.token_urlsafe(32)))
    return _DUMMY_HASH


def _verify(stored_hash: str, plain: str) -> bool:
    """
    Verificación en tiempo constante respecto al resultado.

    Un `stored_hash` que no es un hash válido (p. ej. el '!' con el que la
    migración crea cuentas sin contraseña) devuelve False sin excepción: la
    cuenta existe pero es inaccesible hasta sembrarla. Fail-closed.
    """
    try:
        return _hasher().verify(stored_hash, plain)
    except (VerifyMismatchError, InvalidHashError):
        return False
    except Exception as e:  # hash corrupto, parámetros desconocidos, etc.
        logger.warning("Hash no verificable para una cuenta de UI: %s", type(e).__name__)
        return False


def _token_hash(token: str) -> str:
    """sha256 del token de sesión. Lo único que se persiste."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------- modelo

@dataclass(frozen=True)
class UIUser:
    """Usuario autenticado de la UI. Inmutable: se reconstruye por petición."""

    id: str
    username: str
    display_name: str
    role: str                      # admin | validador | auditor
    agent_roles: List[str]         # se envían en ChatRequest.actor.roles
    traf_username: Optional[str]
    liq_nombre_usu: Optional[str]
    write_allowlisted: bool
    must_change_password: bool

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    def actor_subject(self) -> str:
        """
        Identidad que se declara al agente.

        B-U8: si la cuenta no está mapeada a una identidad del ERP, se envía el
        username de la UI. Las capabilities de negocio denegarán por D-2
        (ROL_NO_MAPEADO) — que es el comportamiento correcto, y además hace el
        estado 6 (denegado) reproducible sin tocar permisos en caliente.
        """
        return self.traf_username or self.liq_nombre_usu or self.username


@dataclass(frozen=True)
class UISession:
    id: str
    user: UIUser
    csrf_token: str
    expires_at: datetime


def _row_to_user(row: Any) -> UIUser:
    raw_roles = row["agent_roles"]
    if isinstance(raw_roles, str):
        import json

        raw_roles = json.loads(raw_roles or "[]")
    return UIUser(
        id=str(row["id"]),
        username=row["username"],
        display_name=row["display_name"],
        role=row["role"],
        agent_roles=list(raw_roles or []),
        traf_username=row["traf_username"],
        liq_nombre_usu=row["liq_nombre_usu"],
        write_allowlisted=bool(row["write_allowlisted"]),
        must_change_password=bool(row["must_change_password"]),
    )


_USER_COLS = """
    u.id, u.username, u.password_hash, u.display_name, u.role, u.is_active,
    u.failed_attempts, u.locked_until, u.traf_username, u.liq_nombre_usu,
    u.agent_roles, u.write_allowlisted, u.must_change_password
"""


# --------------------------------------------------------------- errores

class LoginFailed(Exception):
    """Credenciales inválidas. Mensaje deliberadamente genérico (§6.1)."""

    code = "INVALID_CREDENTIALS"
    http_status = 401
    answer = "Usuario o contraseña incorrectos."


class LoginLockedOut(Exception):
    """Demasiados intentos fallidos (§6.1 A2)."""

    code = "LOCKED_OUT"
    http_status = 429

    def __init__(self, locked_until: datetime) -> None:
        self.locked_until = locked_until
        self.retry_after = max(1, int((locked_until - _now()).total_seconds()))
        super().__init__("locked out")

    @property
    def answer(self) -> str:
        minutos = max(1, round(self.retry_after / 60))
        return (
            f"Tu cuenta quedó bloqueada temporalmente por intentos fallidos. "
            f"Vuelve a intentar en {minutos} minuto(s)."
        )


class IdentityUnavailable(Exception):
    """
    `trafico-db` no respondió y no se pudo verificar la identidad.

    Distinto de `LoginFailed` a propósito: desde el Sprint 5 la credencial vive
    en `trafico.usuarios`, así que si la base está caída el problema no es la
    contraseña. Responder "usuario o contraseña incorrectos" haría que el
    usuario probase contraseñas que nunca podrían funcionar, y además
    quemaría sus intentos de lockout por una caída de infraestructura ajena.
    """

    code = "IDENTITY_UNAVAILABLE"
    http_status = 503
    answer = (
        "No se pudo verificar tu identidad porque el sistema de tráfico no "
        "responde. Inténtalo de nuevo en unos minutos."
    )


# --------------------------------------------------------------- aprovisionamiento

async def _aprovisionar(conn: Any, ident: "identity.IdentityResult", username: str) -> Any:
    """
    Crea la fila local de un usuario que autenticó correctamente en tráfico y
    no tenía fila propia.

    Qué NO se copia aquí: el `password_hash` de tráfico. Jamás. La fila local
    guarda el mapeo (`traf_username`) y el rol derivado, y `password_hash`
    queda NULL — que es lo que la migración 07 documenta en el comentario de
    la columna.

    `role` sale de `derivar_rol_ui`, nunca del rol que el cliente envíe: un
    usuario no se auto-asigna admin.
    """
    display = ident.email or ident.traf_username or username
    import json
    roles_lista = ["admin", "trafico", "liquidaciones"] if ident.role_ui == "admin" else ["trafico", "liquidaciones"]
    roles_json = json.dumps(roles_lista)
    nuevo = await conn.fetchrow(
        f"""INSERT INTO agent_ui_users
                   (username, password_hash, display_name, role, traf_username, agent_roles)
               VALUES ($1, NULL, $2, $3, $4, $5::jsonb)
               ON CONFLICT (username) DO UPDATE
                   SET last_login_at = CURRENT_TIMESTAMP,
                       role = EXCLUDED.role,
                       agent_roles = EXCLUDED.agent_roles,
                       traf_username = EXCLUDED.traf_username
               RETURNING {_USER_COLS.replace('u.', '')}""",
        username, display, ident.role_ui, ident.traf_username, roles_json,
    )
    logger.info(
        "Aprovisionada cuenta de UI desde tráfico: usuario=%s rol_ui=%s rol_trafico=%s",
        username, ident.role_ui, ident.traf_role,
    )
    return nuevo


# --------------------------------------------------------------- login

async def login(username: str, password: str, ip: str = "", user_agent: str = "") -> tuple[str, UISession]:
    """
    Valida credenciales y abre una sesión de UI.

    Desde el Sprint 5 la credencial se verifica contra `trafico.usuarios`
    (`identity.py`), no contra `agent_ui_users`. Este archivo conserva lo que
    es política del AGENTE y por tanto sigue siendo local: el bloqueo por
    intentos fallidos, la escala de UI (admin/validador), el token opaco de
    sesión y el CSRF.

    Devuelve `(token_plano, UISession)`. El token plano solo viaja a la cookie;
    quien llama no debe registrarlo ni devolverlo en el cuerpo de la respuesta.
    """
    conn = await _connect()
    try:
        # 1. Fila local, si existe. Se lee PRIMERO para respetar un bloqueo
        #    activo: un bloqueo no se puede saltar acertando la contraseña.
        row = await conn.fetchrow(
            f"SELECT {_USER_COLS} FROM agent_ui_users u WHERE u.username = $1", username
        )

        if row is not None and row["locked_until"] is not None:
            if row["locked_until"] > _now():
                raise LoginLockedOut(row["locked_until"])

        # 2. Verificación de la credencial contra tráfico.
        try:
            ident = await asyncio.to_thread(
                identity.verificar_credenciales, username, password
            )
        except Exception as exc:  #pragma: no cover — red/DB caída
            logger.error("Fallo verificando identidad en tráfico: %s", type(exc).__name__)
            raise LoginFailed()

        if not ident.ok:
            if ident.code == "DEPENDENCY_UNAVAILABLE":
                # `trafico-db` caído no es una contraseña incorrecta. Decirlo
                # como "contraseña incorrecta" haría perder tiempo al usuario
                # probando contraseñas que nunca van a funcionar.
                raise IdentityUnavailable()
            # Contador de intentos: sólo existe si hay fila local. Un usuario
            # nuevo que falla no seProvisiona — aprovisionar al primer fallo
            # crearía filas por fuerza bruta.
            if row is not None:
                intentos = int(row["failed_attempts"] or 0) + 1
                if intentos >= MAX_FAILED_ATTEMPTS:
                    hasta = _now() + timedelta(minutes=LOCKOUT_MINUTES)
                    await conn.execute(
                        "UPDATE agent_ui_users SET failed_attempts = $2, locked_until = $3 WHERE id = $1",
                        row["id"], intentos, hasta,
                    )
                    logger.warning("Cuenta de UI bloqueada por intentos fallidos: %s", username)
                    raise LoginLockedOut(hasta)
                await conn.execute(
                    "UPDATE agent_ui_users SET failed_attempts = $2 WHERE id = $1",
                    row["id"], intentos,
                )
            raise LoginFailed()

        # 3. Éxito: resolver la fila local, aprovisionando si hace falta.
        if row is None:
            if not identity.AUTO_PROVISION:
                logger.warning(
                    "Login de usuario de tráfico sin fila local y auto-provisión "
                    "apagada: %s", username,
                )
                raise LoginFailed()
            row = await _aprovisionar(conn, ident, username)
        else:
            # Refresco del mapeo: si tráfico cambió el rol o se revocó el
            # acceso, la sesión local no debe quedar con datos rancios.
            nuevo_rol = identity.derivar_rol_ui(ident.traf_role)
            if nuevo_rol != row["role"] or row["traf_username"] != ident.traf_username:
                row = await conn.fetchrow(
                    f"""UPDATE agent_ui_users
                           SET role = $2, traf_username = COALESCE($3, traf_username)
                         WHERE id = $1
                     RETURNING {_USER_COLS.replace('u.', '')}""",
                    row["id"], nuevo_rol, ident.traf_username,
                )

        # 4. Se limpian los contadores y se registra el acceso.
        await conn.execute(
            """UPDATE agent_ui_users
                  SET failed_attempts = 0, locked_until = NULL, last_login_at = CURRENT_TIMESTAMP
                WHERE id = $1""",
            row["id"],
        )

        # §6.1: "sesión anterior destruida al hacer login nuevo".
        await conn.execute(
            """UPDATE agent_ui_sessions SET revoked_at = CURRENT_TIMESTAMP
                WHERE user_id = $1 AND revoked_at IS NULL""",
            row["id"],
        )

        token = secrets.token_urlsafe(32)
        csrf = secrets.token_hex(32)
        expires = _now() + timedelta(hours=SESSION_TTL_H)

        sess_id = await conn.fetchval(
            """INSERT INTO agent_ui_sessions
                   (token_hash, user_id, expires_at, ip, user_agent, csrf_token)
               VALUES ($1, $2, $3, $4, $5, $6)
               RETURNING id""",
            _token_hash(token), row["id"], expires, ip[:64], user_agent[:255], csrf,
        )

        user = _row_to_user(row)
        logger.info(
            "Login de UI correcto: usuario=%s rol=%s origen=trafico rol_trafico=%s",
            user.username, user.role, ident.traf_role,
        )
        return token, UISession(id=str(sess_id), user=user, csrf_token=csrf, expires_at=expires)
    finally:
        await conn.close()


async def resolve_session(token: Optional[str]) -> Optional[UISession]:
    """
    Resuelve la cookie a una sesión viva y renueva `last_seen_at` (§5.5: TTL
    renovado por actividad). Devuelve None si no hay sesión válida: quien
    llama decide si eso es una redirección a login (páginas) o un 401 (API).
    """
    if not token:
        return None

    conn = await _connect()
    try:
        row = await conn.fetchrow(
            f"""SELECT s.id AS sid, s.csrf_token, s.expires_at, {_USER_COLS}
                  FROM agent_ui_sessions s
                  JOIN agent_ui_users u ON u.id = s.user_id
                 WHERE s.token_hash = $1
                   AND s.revoked_at IS NULL
                   AND s.expires_at > CURRENT_TIMESTAMP
                   AND u.is_active""",
            _token_hash(token),
        )
        if row is None:
            return None

        # Renovación deslizante: mantiene viva la sesión de quien trabaja.
        nuevo_exp = _now() + timedelta(hours=SESSION_TTL_H)
        await conn.execute(
            """UPDATE agent_ui_sessions
                  SET last_seen_at = CURRENT_TIMESTAMP, expires_at = $2
                WHERE id = $1""",
            row["sid"], nuevo_exp,
        )
        return UISession(
            id=str(row["sid"]),
            user=_row_to_user(row),
            csrf_token=row["csrf_token"].strip() if row["csrf_token"] else "",
            expires_at=nuevo_exp,
        )
    finally:
        await conn.close()


async def logout(token: Optional[str]) -> None:
    """Idempotente (§6.2): cerrar sesión sin sesión es un 200."""
    if not token:
        return
    conn = await _connect()
    try:
        await conn.execute(
            """UPDATE agent_ui_sessions SET revoked_at = CURRENT_TIMESTAMP
                WHERE token_hash = $1 AND revoked_at IS NULL""",
            _token_hash(token),
        )
    finally:
        await conn.close()


def csrf_ok(session: UISession, header_value: Optional[str], cookie_value: Optional[str]) -> bool:
    """
    Doble envío: el header debe coincidir con el token de la sesión en BD.

    Se compara con `compare_digest` para no filtrar el prefijo coincidente por
    tiempo. La cookie se exige presente e igual porque es la mitad del patrón:
    sin ella, un atacante que logre fijar solo el header seguiría bloqueado.
    """
    if not header_value or not cookie_value:
        return False
    return (
        hmac.compare_digest(header_value, session.csrf_token)
        and hmac.compare_digest(cookie_value, session.csrf_token)
    )


def cookie_kwargs(secure: Optional[bool] = None) -> Dict[str, Any]:
    """
    Atributos de la cookie de sesión (§5.5).

    `Secure` se puede desactivar SOLO para pruebas locales por HTTP mediante
    AGENT_UI_COOKIE_INSECURE=1; en el stack real todo entra por HTTPS :8099.
    """
    if secure is None:
        secure = os.getenv("AGENT_UI_COOKIE_INSECURE", "0") != "1"
    return {
        "httponly": True,
        "secure": secure,
        "samesite": "lax",
        "path": "/",
        "max_age": SESSION_TTL_H * 3600,
    }


async def change_password(user_id: str, actual: str, nueva: str,
                          keep_session_id: Optional[str] = None) -> bool:
    """
    Cambia la contraseña verificando primero la actual.

    `keep_session_id` evita el efecto absurdo de expulsar al usuario que acaba
    de cambiar su propia contraseña: se revoca todo lo demás. Devuelve False si
    la contraseña actual no coincide (quien llama responde 401 genérico).
    """
    conn = await _connect()
    try:
        row = await conn.fetchrow(
            "SELECT password_hash FROM agent_ui_users WHERE id = $1 AND is_active", user_id
        )
        if row is None or not _verify(row["password_hash"], actual):
            return False

        await conn.execute(
            """UPDATE agent_ui_users
                  SET password_hash = $2,
                      must_change_password = FALSE,
                      password_changed_at = CURRENT_TIMESTAMP,
                      failed_attempts = 0,
                      locked_until = NULL
                WHERE id = $1""",
            user_id, hash_password(nueva),
        )

        if keep_session_id:
            await conn.execute(
                """UPDATE agent_ui_sessions SET revoked_at = CURRENT_TIMESTAMP
                    WHERE user_id = $1 AND id <> $2::uuid AND revoked_at IS NULL""",
                user_id, keep_session_id,
            )
        else:
            await conn.execute(
                """UPDATE agent_ui_sessions SET revoked_at = CURRENT_TIMESTAMP
                    WHERE user_id = $1 AND revoked_at IS NULL""",
                user_id,
            )
        return True
    finally:
        await conn.close()
