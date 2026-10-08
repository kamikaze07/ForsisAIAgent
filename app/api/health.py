"""
Forsis AI Agent — Health & Readiness + firma del Planner.

- `/api/v1/health` : liveness barato (no toca dependencias).
- `/api/v1/ready`  : readiness real: verifica PostgreSQL y OmniRoute, y
  expone la firma SHA-256 del Planner (código + system prompt) para detectar
  deriva entre la versión probada en el HITO GO/NO-GO y producción
  (llm-provider.md V-4/§3.4).

Contrato exacto esperado por los criterios A1/A6 del Sprint 1:
    {"status":"ok"}                en /api/v1/health
    {"db":"ok","llm":"ok",...}      en /api/v1/ready
"""

import hashlib
import os
import time
from typing import Any, Dict, Optional

import httpx

try:  # PostgreSQL async (asyncpg)
    import asyncpg
except Exception:  # pragma: no cover
    asyncpg = None  # type: ignore

try:
    from app.infrastructure.llm_gateway.omniroute_provider import OmnirouteProvider
except Exception:  # pragma: no cover
    OmnirouteProvider = None  # type: ignore


# ---------------------------------------------------------------- firma planner

def _iter_planner_source_files() -> list[str]:
    """Archivos que forman el 'cerebro' del Planner (código + prompts)."""
    import app.core.planner as planner_pkg
    import app.core.prompts as prompts_pkg

    base_dirs = [
        os.path.dirname(os.path.abspath(planner_pkg.__file__)),
        os.path.dirname(os.path.abspath(prompts_pkg.__file__)),
    ]
    files: list[str] = []
    for base in base_dirs:
        for root, _dirs, names in os.walk(base):
            for name in sorted(names):
                if name.endswith(".py"):
                    files.append(os.path.join(root, name))
    return sorted(files)


def calcular_firma_planner() -> str:
    """
    SHA-256 determinista del Planner: hash acumulativo del contenido de sus
    archivos .py (código del planner + prompts del sistema). Cambia si cambia
    una línea del planner o de su prompt — exactamente lo que se necesita para
    detectar deriva entre HITO y producción.
    """
    h = hashlib.sha256()
    for path in _iter_planner_source_files():
        rel = os.path.relpath(path, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        h.update(rel.encode("utf-8"))
        try:
            with open(path, "rb") as f:
                h.update(f.read())
        except OSError:
            # Si un archivo desaparece, la firma DEBE cambiar: mezclamos un
            # marcador determinista en vez de omitirlo en silencio.
            h.update(b"<unreadable>")
    return h.hexdigest()


# ------------------------------------------------------------------ readiness

async def check_db() -> Dict[str, Any]:
    if asyncpg is None:
        return {"status": "error", "detail": "asyncpg no disponible"}
    host = os.getenv("DB_HOST", "db")
    port = int(os.getenv("DB_PORT", "5432"))
    user = os.getenv("POSTGRES_USER", "forsis_agent")
    password = os.getenv("POSTGRES_PASSWORD", "")
    database = os.getenv("POSTGRES_DB", "forsis_agent")
    t0 = time.time()
    try:
        conn = await asyncpg.connect(
            user=user, password=password, database=database, host=host, port=port, timeout=4.0
        )
        try:
            await conn.fetchval("SELECT 1")
        finally:
            await conn.close()
        return {"status": "ok", "latency_ms": round((time.time() - t0) * 1000, 1)}
    except Exception as e:
        return {"status": "error", "detail": type(e).__name__}


def check_llm() -> Dict[str, Any]:
    if OmnirouteProvider is None:
        return {"status": "error", "detail": "OmnirouteProvider no importable"}
    t0 = time.time()
    try:
        provider = OmnirouteProvider()
        ok = provider.ping()
        return {
            "status": "ok" if ok else "error",
            "latency_ms": round((time.time() - t0) * 1000, 1),
        }
    except Exception as e:
        return {"status": "error", "detail": type(e).__name__}