"""
R-3 — Parser con allowlist de sentencias (`tools-design.md` §3.2, `permissions.md` §4.3).

Esta capa NO es la barrera fuerte: la barrera fuerte es `GRANT SELECT` en el
servidor (R-1), verificada en vivo con una prueba de `INSERT` rechazado. R-3
existe para que un bug del agente falle **antes** de llegar a la red, y para
que el rechazo quede auditado con un motivo legible.

Rechaza:
  - toda sentencia cuyo primer token no sea SELECT/SHOW/EXPLAIN/DESCRIBE/DESC/WITH
  - `;` múltiple (apilado de sentencias)
  - comentarios ejecutables de MySQL `/*! ... */` y `/*+ ... */`
  - cualquier token prohibido (DML, DDL, SET, LOAD, INTO OUTFILE, CALL, ...)
"""

from __future__ import annotations

import re
from typing import Final

from app.core.exceptions import SqlNotAllowedError

# Sentencias permitidas como primer token.
_ALLOWED_LEADERS: Final[frozenset[str]] = frozenset(
    {"SELECT", "SHOW", "EXPLAIN", "DESCRIBE", "DESC", "WITH"}
)

# Tokens prohibidos en cualquier posición (fuera de literales/comentarios).
_FORBIDDEN_TOKENS: Final[frozenset[str]] = frozenset(
    {
        "INSERT", "UPDATE", "DELETE", "REPLACE", "MERGE", "UPSERT",
        "TRUNCATE", "DROP", "ALTER", "CREATE", "RENAME",
        "GRANT", "REVOKE", "SET", "RESET",
        "LOAD", "OUTFILE", "DUMPFILE", "INFILE",
        "CALL", "EXEC", "EXECUTE", "DO", "HANDLER",
        "LOCK", "UNLOCK", "FLUSH", "KILL", "SHUTDOWN",
        "START", "COMMIT", "ROLLBACK", "SAVEPOINT", "BEGIN",
        "PREPARE", "DEALLOCATE", "INTO",
    }
)

# Comentarios ejecutables de MySQL: /*!40101 ... */ y hints /*+ ... */
_EXEC_COMMENT = re.compile(r"/\*[!+]")

_LINE_COMMENT = re.compile(r"(--[^\n]*|#[^\n]*)")
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_STRING_LITERAL = re.compile(r"'(?:[^'\\]|\\.|'')*'|\"(?:[^\"\\]|\\.|\"\")*\"")
_WORD = re.compile(r"[A-Za-z_][A-Za-z_0-9]*")

MAX_SQL_LEN: Final[int] = 8000


def _strip_noise(sql: str) -> str:
    """Quita literales y comentarios NO ejecutables para analizar solo código."""
    s = _STRING_LITERAL.sub(" '' ", sql)
    s = _LINE_COMMENT.sub(" ", s)
    s = _BLOCK_COMMENT.sub(" ", s)
    return s


def assert_read_only(sql: str) -> None:
    """
    Valida que `sql` sea una única sentencia de solo lectura.
    Lanza `SqlNotAllowedError` (403 SQL_NOT_ALLOWED) con el motivo exacto.
    """
    if not sql or not sql.strip():
        raise SqlNotAllowedError("SQL vacío.")

    if len(sql) > MAX_SQL_LEN:
        raise SqlNotAllowedError(f"SQL excede {MAX_SQL_LEN} caracteres.")

    # Los comentarios ejecutables se buscan en el SQL CRUDO: /*!...*/ es código
    # para MySQL y quitarlo antes de inspeccionar sería exactamente el bypass.
    if _EXEC_COMMENT.search(sql):
        raise SqlNotAllowedError("Comentario ejecutable de MySQL (/*! o /*+) no permitido.")

    code = _strip_noise(sql)

    # Apilado de sentencias: se tolera un único `;` final.
    if ";" in code.strip().rstrip(";"):
        raise SqlNotAllowedError("Múltiples sentencias SQL no permitidas.")

    words = [w.upper() for w in _WORD.findall(code)]
    if not words:
        raise SqlNotAllowedError("SQL sin sentencia reconocible.")

    if words[0] not in _ALLOWED_LEADERS:
        raise SqlNotAllowedError(
            f"Sentencia '{words[0]}' no permitida. Solo SELECT/SHOW/EXPLAIN/DESCRIBE."
        )

    matched_forbidden = set(words) & _FORBIDDEN_TOKENS
    if "REPLACE" in matched_forbidden:
        # Si todo REPLACE es una llamada a función escalar REPLACE(...), se permite.
        total_replace = len(re.findall(r"\bREPLACE\b", code, re.IGNORECASE))
        func_replace = len(re.findall(r"\bREPLACE\s*\(", code, re.IGNORECASE))
        if total_replace == func_replace:
            matched_forbidden.remove("REPLACE")

    prohibidos = sorted(matched_forbidden)
    if prohibidos:
        raise SqlNotAllowedError(f"Token(s) prohibido(s) en SQL: {', '.join(prohibidos)}")


def is_read_only(sql: str) -> bool:
    try:
        assert_read_only(sql)
        return True
    except SqlNotAllowedError:
        return False
