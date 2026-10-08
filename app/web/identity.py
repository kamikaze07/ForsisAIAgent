"""
Identidad desde `trafico-system` (sprint5-identity-design.md §2, §5.2).

Qué cambia respecto al Sprint 4: la credencial del agente deja de ser propia.
El login verifica contra `trafico.usuarios` en vivo, por el canal de solo
lectura que ya existe (`readonly_pool`, destino `trafico`), y el hash de tráfico
se lee, se verifica y se descarta. Nunca se persiste.

Cuatro decisiones que conviene no revertir sin leer el diseño:

1. **Proyección explícita de columnas, nunca `SELECT *`.** `sql_guard` filtra
   verbos, no columnas. `usuarios` tiene `session_version`, `last_login_at` y
   `created_by`, que no tienen nada que ver con autenticar a alguien; con `*`
   filtrarían solos a la respuesta. La lista se declara abajo como constante.

2. **Gate doble antes de verificar.** `access_forsis = 1` y
   `deactivated_at IS NULL`. No es solo higiene: significa que el equipo de
   tráfico revoca el acceso de alguien al agente desde tráfico, sin tocar el
   agente.

3. **Anti-enumeración.** Usuario inexistente, contraseña incorrecta,
   `access_forsis = 0` y `deactivated_at` relleno devuelven el mismo error y el
   mismo código. El trabajo de hash se paga en todos los caminos —incluido el
   de usuario inexistente— para que la latencia no delate qué usuarios son
   reales. Es el mismo criterio que tráfico (`AuthenticationService.php:48`).

4. **Fail closed en el algoritmo.** `password_algorithm` es un ENUM; cualquier
   valor fuera de `argon2id`/`md5_legacy`/`bcrypt` rechaza el login en vez de
   probar una verificación improvisada. Una fila con un algoritmo desconocido
   tiene una credencial que este módulo no sabe evaluar.

El módulo no decide quién puede ver qué datos de tráfico: eso es la matriz
rol -> capacidades (Sprint 6). Aquí sólo se autentica y se deriva el rol de
UI. `trafico.usuarios.role` (8 privilegios de tráfico) y `agent_ui_users.role`
(admin/validador) son escalas distintas y no se acoplan más allá de la
traducción de abajo.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
from dataclasses import dataclass
from typing import Any, Dict, Optional

from app.infrastructure.db.readonly_pool import ro_pool

logger = logging.getLogger(__name__)

# --------------------------------------------------------------- parámetros

#: Roles de `trafico.usuarios.role` que obtienen `admin` en la UI.
#:
#: Sólo `SUPER USUARIO`. `ADMINISTRADOR` es el rol real de QHSE -administra
#: Unidades, no Guías- y tráfico lo tiene excluido de operar Guías
#: (`AuthorizationService.php:96-102`), así que no puede ser admin del agente.
#: Editable por entorno para no tocar Python si tráfico cambia su catálogo.
UI_ADMIN_ROLES = frozenset(
    r.strip().upper()
    for r in os.getenv("UI_ADMIN_ROLES", "SUPER USUARIO").split("|")
    if r.strip()
)

#: ¿Se crea la fila local al primer login de un usuario de tráfico?
#: Encendido por defecto: cualquier usuario de tráfico con `access_forsis = 1`
#: debe poder entrar. Apagarlo deja fuera a usuarios legítimos.
AUTO_PROVISION = os.getenv("AGENT_UI_AUTO_PROVISION", "1") != "0"

#: Timeout de la consulta de identidad. Es un login: si `trafico-db` no
#: responde, se falla rapido con DependencyUnavailable, no se cuelga.
IDENTITY_TIMEOUT_MS = int(os.getenv("AGENT_UI_IDENTITY_TIMEOUT_MS", "5000"))

#: Columnas de `trafico.usuarios` que este modulo puede leer. Cerrado y explicito.
IDENTITY_COLUMNS = (
    "username",           # login
    "password_hash",      # verificacion, nunca persistido
    "password_algorithm", # selecciona el verificador
    "access_forsis",      # gate
    "deactivated_at",     # gate
    "role",               # deriva del rol de UI
    "email",              # contacto, opcional
)


# --------------------------------------------------------------- modelo

@dataclass(frozen=True)
class IdentityResult:
    """Resultado de autenticar a alguien contra trafico."""

    ok: bool
    code: str                          # INVALID_CREDENTIALS | DEPENDENCY_UNAVAILABLE
    traf_username: Optional[str] = None
    traf_role: str = ""                # `role` de trafico, verbatim
    email: Optional[str] = None
    role_ui: str = "validador"         # admin | validador


# --------------------------------------------------------------- roles

def derivar_rol_ui(role_trafico: Optional[str]) -> str:
    """
    Traduce el rol de trafico al rol de UI. Fail closed: lo que no este
    explicitamente listado como admin es `validador`.

    La lista se lee del entorno (`UI_ADMIN_ROLES`) para que un cambio de
    catalogo en trafico no obligue a editar Python. El coste de que sea
    configurable es que tambien se puede equivocar; por eso el diseno pone
    la lista blanca en un solo sitio y todo lo demas cae a `validador`.
    """
    if not role_trafico:
        return "validador"
    return "admin" if role_trafico.strip().upper() in UI_ADMIN_ROLES else "validador"


# --------------------------------------------------------------- hash

def _verify_argon2id(stored: str, plain: str) -> bool:
    try:
        from argon2 import PasswordHasher
        from argon2.exceptions import InvalidHashError, VerifyMismatchError
    except Exception:  # pragma: no cover
        logger.error("argon2-cffi ausente: no se puede verificar argon2id.")
        return False
    try:
        return bool(PasswordHasher().verify(stored, plain))
    except (VerifyMismatchError, InvalidHashError):
        return False
    except Exception as exc:
        logger.warning("Hash argon2id no verificable: %s", type(exc).__name__)
        return False


def _verify_bcrypt(stored: str, plain: str) -> bool:
    try:
        import bcrypt
    except Exception:  # pragma: no cover
        logger.error("bcrypt ausente: no se puede verificar bcrypt.")
        return False
    try:
        return bool(bcrypt.checkpw(plain.encode("utf-8"), stored.encode("utf-8")))
    except Exception as exc:
        logger.warning("Hash bcrypt no verificable: %s", type(exc).__name__)
        return False


def _verify_md5_legacy(stored: str, plain: str) -> bool:
    """
    MD5 sin sal, tal como lo usa trafico (`AuthenticationService.php:119-147`).

    Solo se acepta para lectura de esas 22 filas heredadas. Se anota el riesgo:
    el agente NO puede disparar la migracion perezosa a argon2id que trafico
    hace en login, porque escribir en trafico esta prohibido. Corresponde al
    equipo de trafico.
    """
    return hmac.compare_digest(stored.strip().lower(), hashlib.md5(
        plain.encode("utf-8")).hexdigest())


#: Verificadores por valor del ENUM `password_algorithm`. Un valor fuera de
#: este mapa NO tiene verificador y por tanto falla cerrado.
_VERIFICADORES = {
    "argon2id": _verify_argon2id,
    "bcrypt": _verify_bcrypt,
    "md5_legacy": _verify_md5_legacy,
}

#: Hash de referencia para el camino "usuario inexistente": argon2id valido de
#: una contrasena aleatoria. Verificarlo cuesta lo mismo que uno real, lo que
#: iguala la latencia de ambos caminos (anti-enumeracion por canal lateral).
_DUMMY_HASH: Optional[str] = None


def _coste_de_referencia() -> None:
    """
    Genera una vez el hash de referencia para igualar la latencia del camino
    "usuario inexistente". Se hace con argon2 directamente, sin las credenciales
    de nadie.
    """
    global _DUMMY_HASH
    if _DUMMY_HASH is not None:
        return
    try:
        from argon2 import PasswordHasher
        _DUMMY_HASH = str(PasswordHasher().hash(secrets.token_urlsafe(32)))
    except Exception as exc:  # pragma: no cover
        logger.error("No se pudo generar el hash de referencia: %s", type(exc).__name__)
        _DUMMY_HASH = ""


def _verificar_password(algoritmo: Optional[str], stored: Optional[str], plain: str) -> bool:
    """Despacha al verificador del ENUM. Fail closed si el algoritmo no existe."""
    if not algoritmo or not stored:
        return False
    verificador = _VERIFICADORES.get(algoritmo.strip().lower())
    if verificador is None:
        logger.warning(
            "password_algorithm desconocido (%r): login rechazado (fail closed).", algoritmo)
        return False
    return verificador(stored, plain)


# --------------------------------------------------------------- consulta

def _buscar_en_trafico(username: str) -> Optional[Dict[str, Any]]:
    """
    Lee UNA fila de `trafico.usuarios` por username. Devuelve None si no existe.

    Proyeccion explicita (IDENTITY_COLUMNS). Nunca `SELECT *`: `sql_guard`
    filtra verbos, no columnas, y el resto de la tabla no tiene que ver con
    autenticar a alguien. El WHERE va con parametro vinculado: el username
    entra del usuario y jamas se concatena en el SQL.
    """
    columnas = ", ".join(IDENTITY_COLUMNS)
    sql = f"SELECT {columnas} FROM usuarios WHERE username = %s"
    filas, _meta = ro_pool.query(
        "trafico", sql, params=[username], max_rows=1, timeout_ms=IDENTITY_TIMEOUT_MS,
    )
    return filas[0] if filas else None


# --------------------------------------------------------------- API

def verificar_credenciales(username: str, password: str) -> IdentityResult:
    """
    Autentica contra `trafico.usuarios`. NO escribe nada y NO persiste el hash.

    Todos los rechazos devuelven `INVALID_CREDENTIALS` con el mismo mensaje,
    incluidos usuario inexistente, `access_forsis = 0` y `deactivated_at`
    relleno: el usuario no debe poder distinguir "no existe" de "existe pero
    no le sirve".

    `DEPENDENCY_UNAVAILABLE` es el unico caso que se propaga como error, y es
    deliberado: si `trafico-db` esta caido el problema no es la contrasena y
    ocultarlo dejaria al usuario probando passwords que nunca van a funcionar.
    """
    _coste_de_referencia()

    if not username or not password:
        return IdentityResult(ok=False, code="INVALID_CREDENTIALS")

    try:
        fila = _buscar_en_trafico(username)
    except Exception as exc:
        # Dependencia caida, no credencial invalida. Se loguea sin el username
        # del usuario final para no ensuciar el log con identificadores.
        logger.error("Fallo consultando trafico.usuarios: %s", type(exc).__name__)
        return IdentityResult(ok=False, code="DEPENDENCY_UNAVAILABLE")

    if fila is None:
        # Se paga el coste de un hash real para no delatar por latencia.
        _verificar_password("argon2id", _DUMMY_HASH, password)
        return IdentityResult(ok=False, code="INVALID_CREDENTIALS")

    algoritmo = fila.get("password_algorithm")
    almacenado = fila.get("password_hash")

    # Gate ANTES de verificar la contrasena: un usuario sin `access_forsis` o
    # desactivado no autenticara aunque la contrasena sea correcta.
    if not fila.get("access_forsis") or fila.get("deactivated_at"):
        _verificar_password(algoritmo, almacenado, password)
        return IdentityResult(ok=False, code="INVALID_CREDENTIALS")

    if not _verificar_password(algoritmo, almacenado, password):
        return IdentityResult(ok=False, code="INVALID_CREDENTIALS")

    traf_username = fila.get("username")
    traf_role = fila.get("role") or ""
    return IdentityResult(
        ok=True,
        code="OK",
        traf_username=traf_username,
        traf_role=traf_role,
        email=fila.get("email"),
        role_ui=derivar_rol_ui(traf_role),
    )


def describe_origen() -> Dict[str, Any]:
    """Para `/api/v1/ui/me` y diagnostico: de donde salio esta identidad."""
    return {
        "origen": "trafico-system",
        "tabla": "trafico.usuarios",
        "auto_provision": AUTO_PROVISION,
        "admin_roles": sorted(UI_ADMIN_ROLES),
    }