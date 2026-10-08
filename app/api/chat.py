"""
Router del endpoint POST /api/v1/chat (channels.md §1.3, §1.5, §1.6).
Manejo fail-closed de autenticación por canal, idempotencia, contrato Pydantic
y serialización uniforme de errores.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse

from app.contracts.chat_contract import (
    ChatRequest,
    ChatResponse,
    ErrorBody,
)
from app.core.agent_service import agent_service
from app.core.auth import authenticate
from app.core.exceptions import (
    ChannelMismatchError,
    ContractError,
    IdempotencyInFlightError,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["Chat"])


@router.post(
    "/chat",
    response_model=ChatResponse,
    responses={
        200: {"model": ChatResponse, "description": "Turno procesado correctamente"},
        400: {"model": ErrorBody, "description": "Error en contrato o parámetros"},
        401: {"model": ErrorBody, "description": "Credenciales inválidas o ausentes"},
        403: {"model": ErrorBody, "description": "Acceso denegado o discordancia de canal/sesión"},
        409: {"model": ErrorBody, "description": "Turno con la misma clave en vuelo"},
        413: {"model": ErrorBody, "description": "Mensaje excede los 4000 caracteres"},
        422: {"model": ErrorBody, "description": "Error de validación de contrato o clave de idempotencia reutilizada"},
        502: {"model": ErrorBody, "description": "Proveedor OmniRoute inalcanzable o respuesta corrupta"},
        503: {"model": ErrorBody, "description": "Dependencia interna (Base de Datos) no disponible"},
        504: {"model": ErrorBody, "description": "Timeout del turno (>120 s)"},
    },
)
async def chat_endpoint(
    req_body: ChatRequest,
    request: Request,
    authorization: Optional[str] = Header(default=None),
    x_forsis_channel: Optional[str] = Header(default=None, alias="X-Forsis-Channel"),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
) -> ChatResponse:
    # 1. Autenticación multi-token por canal
    auth_channel = authenticate(authorization, x_forsis_channel)

    # 2. Verificar correspondencia del canal en el cuerpo con el autenticado
    if req_body.channel != auth_channel:
        raise ChannelMismatchError(
            f"El canal declarado en el cuerpo ('{req_body.channel.value}') "
            f"no coincide con el autenticado ('{auth_channel.value}')."
        )

    # 3. Datos de red del cliente
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    # 4. Procesamiento orquestado del turno
    return await agent_service.process_turn(
        req=req_body,
        client_ip=client_ip,
        user_agent=user_agent,
        idempotency_key=idempotency_key,
    )
