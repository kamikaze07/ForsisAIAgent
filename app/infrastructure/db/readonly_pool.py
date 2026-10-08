"""
Sandbox SQL de solo lectura contra las bases de negocio (`tools-design.md` §3).

Cinco controles independientes, por orden de fuerza:

  R-1  Credenciales: usuario `forsis_agent_ro` con GRANT SELECT y nada más.
       Es la ÚNICA barrera que no depende de código del agente. Verificada
       en vivo: un INSERT devuelve 1142 INSERT command denied.
  R-2  Sesión read-only: `SET SESSION TRANSACTION READ ONLY` al conectar.
  R-3  Parser con allowlist (`sql_guard.assert_read_only`) antes de la red.
  R-4  Techo de filas: LIMIT obligatorio, nunca superior a `max_rows`.
  R-5  Techo de tiempo: `MAX_EXECUTION_TIME` por consulta + connect_timeout.

Las credenciales se leen SIEMPRE del entorno. Nada de valores por defecto
para la contraseña: sin `AGENT_RO_PASSWORD` el pool se niega a arrancar, en
vez de intentar una conexión anónima que confundiría el diagnóstico.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

import pymysql
import pymysql.charset
from pymysql.cursors import DictCursor

from app.core.exceptions import (
    DependencyUnavailableError,
    QueryTimeoutError,
    SqlLimitExceededError,
)
from app.infrastructure.db.sql_guard import assert_read_only

logger = logging.getLogger(__name__)

# Techos duros del Sprint 3. Una capability puede pedir MENOS, nunca más.
DEFAULT_MAX_ROWS = 200
HARD_MAX_ROWS = 1000
DEFAULT_TIMEOUT_MS = 8000
HARD_TIMEOUT_MS = 20000

_LIMIT_RE = re.compile(r"\bLIMIT\s+(\d+)\s*(?:,\s*(\d+))?\s*;?\s*$", re.IGNORECASE)

# Códigos de error de MySQL que significan "el servidor cortó la consulta".
_MYSQL_TIMEOUT_CODES = frozenset({3024, 1969, 2013, 1317})
# 1142/1143 = command denied → el GRANT hizo su trabajo (R-1).
_MYSQL_DENIED_CODES = frozenset({1142, 1143})


@dataclass(frozen=True)
class DbTarget:
    """Un destino de lectura. `key` es lo que declara la capability."""

    key: str
    host: str
    port: int
    database: str
    charset: Optional[str]
    description: str


def _targets() -> Dict[str, DbTarget]:
    """
    Destinos de lectura. Host y puerto vienen del entorno porque el agente
    corre en un contenedor distinto al de cada sistema: `sicrePR` es el MySQL
    del host (vía host.docker.internal) y `trafico` es el MariaDB del compose
    de trafico-system, alcanzable sólo si el agente está unido a su red.
    """
    sicret_host = os.getenv("SICRET_DB_HOST", "host.docker.internal")
    sicret_port = int(os.getenv("SICRET_DB_PORT", "3306"))
    traf_host = os.getenv("TRAFICO_DB_HOST", "trafico-db")
    traf_port = int(os.getenv("TRAFICO_DB_PORT", "3306"))
    atlas_host = os.getenv("ATLAS_DB_HOST", "host.docker.internal")
    atlas_port = int(os.getenv("ATLAS_DB_PORT", "3311"))

    # `guias.nombre` y `facturas33.cliente` guardan texto UTF-8 (verificado:
    # HEX(nombre) = 4E454654414CC38D = "NEFTALÍ") en columnas declaradas
    # latin1_swedish_ci. El charset de la conexión declara latin1 -- el
    # correcto para MySQL -- y `_arreglar_cp1252()` neutraliza el único
    # defecto real: pymysql decodifica latin1 con el codec **cp1252**, donde
    # 0x8D no está asignado. Corregido, latin1 decodifica byte a byte, los
    # bytes UTF-8 sobreviven intactos y `redecodificar()` los pasa a texto.
    #
    # `atlas` NO es un destino más de SICRET: es el sistema externo al que
    # trafico-system ENVÍA las solicitudes de liberación y de timbrado
    # (AtlasClient::solicitarLiberacion -> POST /api/solicitudes-liberacion.php,
    # con 'solicitante' en el payload). Es la ÚNICA fuente de "quién pidió una
    # liberación" y "quién la aceptó": en SICRET no queda rastro de la
    # aprobación, que es enteramente interna de ATLAS.
    #
    # Se accede por el puerto publicado del host (3311) en lugar de unir el
    # contenedor a la red de atlas-db: no amplía la superficie de red del
    # agente y funciona aunque ATLAS se levante en otro host. Requiere que el
    # usuario `forsis_agent_ro` exista en atlas-db con SOLO `GRANT SELECT`.
    return {
        "sicret_pr": DbTarget("sicret_pr", sicret_host, sicret_port, "sicrePR", "latin1",
                              "SICRET Forsis PR -- guías, operadores, facturación"),
        "sicret_gero": DbTarget("sicret_gero", sicret_host, sicret_port, "sicreGero", "latin1",
                                "SICRET GERO -- guías, operadores, facturación"),
        "trafico": DbTarget("trafico", traf_host, traf_port, "trafico", "utf8mb4",
                            "trafico-system -- pases de descarga, despachos"),
        "atlas": DbTarget("atlas", atlas_host, atlas_port, "atlas", "utf8mb4",
                          "ATLAS -- solicitudes de liberación y timbrado de guías"),
    }


_cp1252_arreglado = False


def _arreglar_cp1252() -> None:
    """
    pymysql decodifica el charset MySQL `latin1` con el codec **cp1252**.

    cp1252 es un superconjunto de latin-1 que define los bytes 0x80-0x9F pero
    deja 0x8D, 0x8F, 0x90 y 0x9D sin asignar. Los acentos codificados en UTF-8
    usan justo 0x8D ("Í" = C3 8D), así que cualquier "NEFTALÍ" en una columna
    latin1 tumba el turno con `UnicodeDecodeError` y el usuario recibe un
    "no pude completar la consulta" sin ver datos.

    Salvo esos 32 bytes de control, cp1252 es idéntico byte a byte a latin-1,
    así que redirigirlo no cambia ninguna decodificación válida. Se sobreescribe
    la property de la clase (no su instancia: es read-only) y sólo para latin1;
    el resto de charsets —utf8mb4 incluido— quedan intactos.
    """
    global _cp1252_arreglado
    if _cp1252_arreglado:
        return
    _encoding_original = pymysql.charset.Charset.encoding.fget

    if _encoding_original(pymysql.charset.charset_by_name("latin1")) == "latin-1":
        _cp1252_arreglado = True  # pymysql ya lo hace bien; no se toca.
        return

    def encoding(self):
        """latin1 -> latin-1 real; el resto de charsets sin tocar."""
        if self.name == "latin1":
            return "latin-1"
        return _encoding_original(self)

    # Se reasigna la property con el MISMO nombre: pymysql lee
    # `charset_by_name(...).encoding`, así que cualquier otro nombre no se
    # aplicaría (y colisionaría con `self.encoding` de Connection).
    pymysql.charset.Charset.encoding = property(encoding)
    _cp1252_arreglado = True


# Destinos cuyo texto llega como latin1 pero guarda UTF-8: la decodificación
# correcta se decide en Python, no en el servidor.
_CHARSET_UTF8_EN_LATIN1 = {"sicret_pr", "sicret_gero"}


def redecodificar(valor: Any, target_key: str) -> Any:
    """latin1 o bytes -> texto UTF-8. Cae a latin1 si no es UTF-8 válido."""
    if target_key not in _CHARSET_UTF8_EN_LATIN1:
        return valor
    if isinstance(valor, (bytes, bytearray)):
        bruto = bytes(valor)
        try:
            return bruto.decode("utf-8")
        except UnicodeDecodeError:
            return bruto.decode("latin1", errors="replace")
    if isinstance(valor, str):
        try:
            return valor.encode("latin1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            return valor
    return valor


class ReadOnlyPool:
    """
    Pool mínimo y explícito: una conexión por destino, reconectada bajo demanda.
    No se usa un pool asíncrono a propósito — el volumen del Sprint 3 es de
    unidades de consulta por turno y un pool complejo añade modos de fallo
    (conexiones zombi con transacción abierta) que aquí no se pueden depurar.
    """

    def __init__(self) -> None:
        # Antes de cualquier conexión: pymysql resuelve su codec al importar el
        # charset, así que el registro debe existir antes del primer query().
        _arreglar_cp1252()
        self._lock = threading.Lock()
        self._conns: Dict[str, Any] = {}
        self._targets = _targets()

    # ---------------------------------------------------------------- config

    @property
    def targets(self) -> Dict[str, DbTarget]:
        return dict(self._targets)

    def _credentials(self, target_key: str) -> Tuple[str, str]:
        """Credenciales de solo lectura del destino.

        ATLAS vive en OTRO motor (MariaDB, `atlas-db`) con su propia instancia
        del usuario homónimo, así que declara su par propio. El resto de
        destinos comparten el par genérico `AGENT_RO_*`: un mismo motor puede
        alojar varias bases (SICRET PR y GERO son la misma instancia) y duplicar
        la contraseña por base sólo agrega superficie de configuración que
        rotar. Se resuelve el par específico primero y se cae al genérico, de
        modo que añadir un destino nuevo no rompe los existentes.
        """
        especificas = (
            f"AGENT_RO_PASSWORD_{target_key.upper()}", f"AGENT_RO_USER_{target_key.upper()}"
        )
        if self._tiene_par_especifico(target_key):
            user = os.getenv(f"AGENT_RO_USER_{target_key.upper()}", "forsis_agent_ro")
            password = os.getenv(f"AGENT_RO_PASSWORD_{target_key.upper()}", "")
        else:
            user = os.getenv("AGENT_RO_USER", "forsis_agent_ro")
            password = os.getenv("AGENT_RO_PASSWORD", "")

        if not password:
            raise DependencyUnavailableError(
                f"Contraseña de solo lectura no configurada ("
                f"{' o '.join(especificas)} o AGENT_RO_PASSWORD): el sandbox no "
                f"puede abrir conexión a '{target_key}'."
            )
        return user, password

    @staticmethod
    def _tiene_par_especifico(target_key: str) -> bool:
        """¿El destino declara un par de credenciales propio?"""
        return bool(
            os.getenv(f"AGENT_RO_PASSWORD_{target_key.upper()}", "")
            or os.getenv(f"AGENT_RO_USER_{target_key.upper()}", "")
        )

    # ------------------------------------------------------------ conexiones

    def _connect(self, target: DbTarget) -> Any:
        user, password = self._credentials(target.key)
        try:
            conn = pymysql.connect(
                host=target.host,
                port=target.port,
                user=user,
                password=password,
                database=target.database,
                charset=target.charset,
                cursorclass=DictCursor,
                connect_timeout=int(os.getenv("AGENT_RO_CONNECT_TIMEOUT", "5")),
                read_timeout=int(os.getenv("AGENT_RO_READ_TIMEOUT", "25")),
                write_timeout=10,
                autocommit=True,
            )
        except pymysql.err.MySQLError as exc:
            raise DependencyUnavailableError(
                f"No se pudo conectar a '{target.key}' ({target.database}): {exc.args[0] if exc.args else exc}"
            ) from exc

        # R-2: la sesión entera queda marcada de solo lectura. Si un bug
        # colara una escritura pese a R-3, el servidor la rechaza igualmente.
        with conn.cursor() as cur:
            cur.execute("SET SESSION TRANSACTION READ ONLY")
        return conn

    @contextmanager
    def _cursor(self, target_key: str) -> Iterator[Any]:
        target = self._targets.get(target_key)
        if target is None:
            raise DependencyUnavailableError(f"Destino de lectura desconocido: '{target_key}'.")

        with self._lock:
            conn = self._conns.get(target_key)
            if conn is None:
                conn = self._connect(target)
                self._conns[target_key] = conn
            else:
                try:
                    conn.ping(reconnect=True)
                    with conn.cursor() as c:
                        c.execute("SET SESSION TRANSACTION READ ONLY")
                except pymysql.err.MySQLError:
                    try:
                        conn.close()
                    except Exception:
                        pass
                    conn = self._connect(target)
                    self._conns[target_key] = conn

            cur = conn.cursor()
            try:
                yield cur
            finally:
                try:
                    cur.close()
                except Exception:
                    pass

    # --------------------------------------------------------------- consulta

    @staticmethod
    def _enforce_limit(sql: str, max_rows: int) -> str:
        """
        R-4. Si la consulta ya trae LIMIT, se comprueba que no exceda el techo
        (y se rechaza si lo hace, en vez de recortarlo en silencio: una
        capability que pide 10.000 filas tiene un bug que hay que ver). Si no
        trae LIMIT, se añade.
        """
        m = _LIMIT_RE.search(sql.rstrip().rstrip(";"))
        if m:
            pedido = int(m.group(2) or m.group(1))
            if pedido > max_rows:
                raise SqlLimitExceededError(
                    f"La consulta pide {pedido} filas; el techo de la capability es {max_rows}."
                )
            return sql
        return f"{sql.rstrip().rstrip(';')} LIMIT {max_rows}"

    def query(
        self,
        target_key: str,
        sql: str,
        params: Optional[Sequence[Any]] = None,
        max_rows: int = DEFAULT_MAX_ROWS,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        Ejecuta una consulta de lectura. Devuelve `(filas, meta)`; `meta` lleva
        lo que la auditoría necesita (destino, ms, nº de filas, truncado).

        Toda excepción se traduce a `ContractError`: una capability nunca ve
        un `pymysql.err.*` crudo, que acabaría como 500 opaco.
        """
        max_rows = max(1, min(int(max_rows), HARD_MAX_ROWS))
        timeout_ms = max(100, min(int(timeout_ms), HARD_TIMEOUT_MS))

        assert_read_only(sql)                      # R-3
        sql_final = self._enforce_limit(sql, max_rows)  # R-4

        started = time.perf_counter()
        try:
            with self._cursor(target_key) as cur:
                # R-5: techo de tiempo pedido al propio servidor.
                try:
                    cur.execute(f"SET SESSION MAX_EXECUTION_TIME={timeout_ms}")
                except pymysql.err.MySQLError:
                    # MariaDB no tiene MAX_EXECUTION_TIME; usa max_statement_time (segundos).
                    try:
                        cur.execute(f"SET SESSION max_statement_time={timeout_ms / 1000.0}")
                    except pymysql.err.MySQLError:
                        logger.warning("Destino '%s' no soporta techo de tiempo por sentencia.", target_key)

                cur.execute(sql_final, tuple(params) if params else None)
                rows = cur.fetchmany(max_rows) or []
        except pymysql.err.MySQLError as exc:
            code = exc.args[0] if exc.args else 0
            msg = str(exc.args[1]) if len(exc.args) > 1 else str(exc)
            if code in _MYSQL_TIMEOUT_CODES:
                raise QueryTimeoutError(f"La consulta superó el techo de {timeout_ms} ms.") from exc
            if code in _MYSQL_DENIED_CODES:
                # No debería ocurrir: R-3 filtra antes. Si ocurre, el GRANT
                # salvó la situación y eso merece un WARNING explícito.
                logger.warning("R-1 bloqueó una sentencia que R-3 dejó pasar (code=%s).", code)
                raise SqlLimitExceededError(f"Operación denegada por el servidor: {msg}") from exc
            raise DependencyUnavailableError(f"Error de lectura en '{target_key}': [{code}] {msg}") from exc

        duration_ms = int((time.perf_counter() - started) * 1000)
        # Los acentos se recuperan aquí, antes de que la fila salga del pool:
        # `_serializar()` de las capabilities ya recibe texto UTF-8 bueno.
        rows = [
            {k: redecodificar(v, target_key) for k, v in r.items()} for r in rows
        ]
        meta = {
            "target": target_key,
            "database": self._targets[target_key].database,
            "row_count": len(rows),
            "truncated": len(rows) >= max_rows,
            "max_rows": max_rows,
            "duration_ms": duration_ms,
            "timeout_ms": timeout_ms,
        }
        return list(rows), meta

    # ------------------------------------------------------------ diagnóstico

    def health(self) -> Dict[str, Any]:
        """Estado por destino, para `/api/v1/ready`. Nunca lanza."""
        out: Dict[str, Any] = {}
        for key, target in self._targets.items():
            try:
                rows, meta = self.query(key, "SELECT 1 AS ok", max_rows=1, timeout_ms=3000)
                out[key] = {
                    "status": "up",
                    "database": target.database,
                    "duration_ms": meta["duration_ms"],
                }
            except Exception as exc:
                out[key] = {
                    "status": "down",
                    "database": target.database,
                    "error": type(exc).__name__,
                    "detail": str(exc)[:160],
                }
        return out

    def verify_read_only(self, target_key: str) -> Dict[str, Any]:
        """
        Prueba viva de R-1: intenta una escritura trivial y EXIGE que el
        servidor la rechace. `enforced=True` sólo si el rechazo ocurrió.
        No pasa por `query()` a propósito — aquí se salta R-3 justamente
        para comprobar la barrera que no depende del agente.
        """
        target = self._targets.get(target_key)
        if target is None:
            return {"target": target_key, "enforced": False, "detail": "destino desconocido"}
        try:
            with self._cursor(target_key) as cur:
                cur.execute("CREATE TEMPORARY TABLE __forsis_ro_probe (id INT)")
            return {"target": target_key, "enforced": False,
                    "detail": "el servidor PERMITIÓ crear una tabla: el GRANT no es de solo lectura"}
        except pymysql.err.MySQLError as exc:
            code = exc.args[0] if exc.args else 0
            return {"target": target_key, "enforced": True, "mysql_error": code,
                    "detail": str(exc.args[1])[:160] if len(exc.args) > 1 else str(exc)[:160]}
        except Exception as exc:
            return {"target": target_key, "enforced": False, "detail": f"{type(exc).__name__}: {exc}"[:160]}


ro_pool = ReadOnlyPool()
