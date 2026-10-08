"""
Forsis AI Agent — FastAPI Application Entry Point
Stack: Python 3.12 + FastAPI + PostgreSQL 16

Fase 1 (Sprint 2): runtime base + health/readiness + chat API endpoint
con fail-closed contract, multi-token auth, persistencia e idempotencia.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api.chat import router as chat_router
from app.api.health import calcular_firma_planner, check_db, check_llm
from app.api.v1.ui import UnauthenticatedUI
from app.api.v1.ui import router as ui_api_router
from app.web.routes import router as ui_pages_router
from app.contracts.chat_contract import ErrorBody
from app.core.exceptions import (
    ContractError,
    IdempotencyInFlightError,
)
from app.core.metrics import metrics

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Forsis AI Agent",
    description="Agente IA empresarial para ERP Forsis (Tráfico y Liquidaciones)",
    version="1.1.0-sprint2",
    docs_url=None,
    redoc_url=None,
)

# Incluir router de chat (canal estable)
app.include_router(chat_router)

# --------------------------------------------------------------------------
# Sprint 4 — Interfaz web standalone (web-ui-design.md §5.3)
#
# El prefijo /api/v1/ui separa los endpoints de la UI del contrato estable de
# channels.md: la UI puede evolucionar sin tocar lo que ya consumen los
# adaptadores. Las páginas viven bajo /ui y los estáticos bajo /static/ui.
# --------------------------------------------------------------------------

app.include_router(ui_api_router, prefix="/api/v1/ui")
app.include_router(ui_pages_router, prefix="/ui")

_STATIC_DIR = Path(__file__).parent / "web" / "static"
app.mount("/static/ui", StaticFiles(directory=str(_STATIC_DIR)), name="static-ui")


# --------------------------------------------------------------------------
# Exception Handlers fail-closed según channels.md §1.6
# --------------------------------------------------------------------------

@app.exception_handler(ContractError)
async def contract_error_handler(request: Request, exc: ContractError) -> JSONResponse:
    headers = {}
    if isinstance(exc, IdempotencyInFlightError):
        headers["Retry-After"] = "5"

    body = ErrorBody(
        error_code=exc.error_code,
        answer=exc.message,
        retryable=exc.retryable,
        trace_id=None,
        session_id=None,
        details=exc.details,
    )
    return JSONResponse(
        status_code=exc.http_status,
        content=body.model_dump(mode="json"),
        headers=headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = []
    for err in exc.errors():
        loc = " -> ".join(str(l) for l in err.get("loc", []))
        msg = err.get("msg", "valor inválido")
        errors.append(f"{loc}: {msg}")

    body = ErrorBody(
        error_code="VALIDATION_ERROR",
        answer="La solicitud no cumple con el contrato requerido.",
        retryable=False,
        trace_id=None,
        session_id=None,
        details={"validation_errors": errors},
    )
    return JSONResponse(
        status_code=422,
        content=body.model_dump(mode="json"),
    )


@app.exception_handler(UnauthenticatedUI)
async def ui_unauthenticated_handler(request: Request, exc: UnauthenticatedUI) -> JSONResponse:
    """
    Sesión de UI ausente o expirada.

    Se registra explícitamente porque el handler genérico de `Exception`
    capturaría esta excepción y devolvería un 500: un login caducado no es un
    fallo del servidor y el cliente necesita el 401 para redirigir al login.
    """
    return JSONResponse(
        status_code=401,
        content={
            "answer": "Tu sesión expiró. Vuelve a iniciar sesión.",
            "status": "error",
            "error": {
                "code": "UNAUTHENTICATED",
                "message": "Sesión de interfaz web ausente o expirada.",
                "retryable": False,
                "details": {},
            },
        },
    )


@app.exception_handler(Exception)
async def generic_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Error no manejado en la aplicación: %s", exc)
    body = ErrorBody(
        error_code="INTERNAL_ERROR",
        answer="Ocurrió un error inesperado al procesar la solicitud.",
        retryable=True,
        trace_id=None,
        session_id=None,
        details={},
    )
    return JSONResponse(
        status_code=500,
        content=body.model_dump(mode="json"),
    )


# --------------------------------------------------------------------------
# Endpoints de Diagnóstico y Métricas
# --------------------------------------------------------------------------

@app.get("/health", response_class=PlainTextResponse, tags=["Health"])
async def health_check() -> str:
    """Liveness barato para el healthcheck de Docker. No toca dependencias."""
    return "healthy"


@app.get("/", tags=["Root"])
async def root() -> Dict[str, Any]:
    """Información del servicio."""
    return {
        "service": "Forsis AI Agent",
        "version": "1.1.0-sprint2",
        "stack": "Python 3.12 / FastAPI",
        "phase": "Fase 1 — Standalone Validation (Sprint 2)",
        "status": "operational",
    }


@app.get("/api/v1/health", tags=["Health"])
async def api_health() -> Dict[str, Any]:
    """Contrato A1: {\"status\":\"ok\"} — liveness sin dependencias."""
    return {"status": "ok"}


@app.get("/api/v1/ready", tags=["Health"])
async def api_ready() -> Dict[str, Any]:
    """
    Contrato A1/A6: readiness real.
      - db  : SELECT 1 contra PostgreSQL
      - llm : probe a OmniRoute (combo `Forsis`)
      - planner_signature: SHA-256 del código del Planner + sus prompts
    """
    db = await check_db()
    llm = check_llm()
    ready = db.get("status") == "ok" and llm.get("status") == "ok"
    return {
        "status": "ok" if ready else "degraded",
        "db": db.get("status"),
        "llm": llm.get("status"),
        "db_detail": db,
        "llm_detail": llm,
        "planner_signature": calcular_firma_planner(),
        "version": "1.1.0-sprint2",
    }


@app.get("/api/v1/metrics", tags=["Metrics"])
async def api_metrics() -> Dict[str, Any]:
    """Telemetría in-process de capas LLM, caché y turnos (sprint-plan-v2 §Sprint 2)."""
    return metrics.snapshot()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
