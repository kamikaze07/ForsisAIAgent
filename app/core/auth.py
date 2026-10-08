"""
Autenticación por token de servicio, uno POR CANAL (channels.md §1.4).

Por qué no un token global: un token filtrado se revoca sin tirar los otros dos
canales, y el log dice de inmediato qué adaptador se comprometió. Es la
mitigación directa de la lección de `BOT_TOKEN` en `mattermost-integration-strategy.md` §5.

Por qué el token autentica al ADAPTADOR y no al usuario: la identidad del humano
viaja en `actor` (Mattermost) o en `X-Forsis-Identity` (widget). Confundir las
dos cosas es exactamente el error que anticipa §5 S7.

Fail-closed: sin token configurado, el módulo registra el canal como
inaccesible y TODAS las peticiones → 401. Nunca "si no hay token, pasa": eso
convertiría un despliegue mal configurado en un endpoint abierto.
"""

from __future__ import annotations

import hmac
import logging
import os
from typing import Dict, Optional, Tuple

from app.contracts.chat_contract import Channel
from app.core.exceptions import ChannelMismatchError, UnauthenticatedError

logger = logging.getLogger(__name__)

# Token por canal. Soporta dos tokens simultáneos por canal (`..._TOKEN` y
# `..._TOKEN_NEXT`) para rotar sin ventana de caída (§1.4 decisión 5).
ENV_TOKEN_BY_CHANNEL: Dict[Channel, list[str]] = {
    Channel.MATTERMOST: [
        "FORSIS_AGENT_TOKEN_MATTERMOST",
        "FORSIS_CHANNEL_TOKEN_MATTERMOST",
        "FORSIS_AGENT_TOKEN_MATTERMOST_NEXT",
        "FORSIS_CHANNEL_TOKEN_MATTERMOST_PREV",
    ],
    Channel.WIDGET_TRAFICO: [
        "FORSIS_AGENT_TOKEN_TRAFICO",
        "FORSIS_CHANNEL_TOKEN_WIDGET_TRAFICO",
        "FORSIS_AGENT_TOKEN_TRAFICO_NEXT",
        "FORSIS_CHANNEL_TOKEN_WIDGET_TRAFICO_PREV",
    ],
    Channel.WIDGET_LIQUIDACIONES: [
        "FORSIS_AGENT_TOKEN_LIQUIDACIONES",
        "FORSIS_CHANNEL_TOKEN_WIDGET_LIQUIDACIONES",
        "FORSIS_AGENT_TOKEN_LIQUIDACIONES_NEXT",
        "FORSIS_CHANNEL_TOKEN_WIDGET_LIQUIDACIONES_PREV",
    ],
    # ADJ-2 (web-ui-design.md §6.0): la UI standalone tiene token propio.
    # No reutiliza el del widget: el token identifica al adaptador, y mentir
    # en X-Forsis-Channel debe seguir produciendo 403 CHANNEL_MISMATCH.
    Channel.UI_STANDALONE: [
        "FORSIS_AGENT_TOKEN_UI_STANDALONE",
        "FORSIS_CHANNEL_TOKEN_UI_STANDALONE",
        "FORSIS_AGENT_TOKEN_UI_STANDALONE_NEXT",
        "FORSIS_CHANNEL_TOKEN_UI_STANDALONE_PREV",
    ],
    Channel.API: [
        "FORSIS_AGENT_TOKEN_API",
        "FORSIS_CHANNEL_TOKEN_API",
        "FORSIS_AGENT_TOKEN_API_NEXT",
        "FORSIS_CHANNEL_TOKEN_API_PREV",
    ],
}


def _tokens_for(channel: Channel) -> list[str]:
    names = ENV_TOKEN_BY_CHANNEL.get(channel, [])
    tokens: list[str] = []
    for var in names:
        val = os.getenv(var)
        if val and val.strip():
            tokens.append(val.strip())
    return tokens


def configured_channels() -> list[str]:
    """Canales con al menos un token válido configurado. Para diagnóstico."""
    return sorted(c.value for c in Channel if _tokens_for(c))


def extract_bearer(authorization: Optional[str]) -> str:
    """
    Saca el token del header `Authorization: Bearer ...`.

    Si el header falta, tiene otro esquema, o el token es demasiado corto
    (mínimo 32 bytes aleatorios, §1.4 decisión 5), la respuesta es la misma:
    401 sin pistas sobre el motivo. Un `401 "formato inválido"` vs `401 "token
    equivocado"` es un oráculo gratis para fuerza bruta.
    """
    if not authorization:
        raise UnauthenticatedError("Credenciales ausentes.")
    parts = authorization.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise UnauthenticatedError("Credenciales ausentes.")
    token = parts[1].strip()
    if len(token) < 32:
        raise UnauthenticatedError("Credenciales ausentes.")
    return token


def authenticate(
    authorization: Optional[str],
    declared_channel: Optional[str],
) -> Channel:
    """
    Valida el bearer y lo liga a su canal. Devuelve el canal AUTENTICADO.

    Reglas:
      - token ausente/inválido           → 401 UNAUTHENTICATED
      - canal del header ausente         → 403 CHANNEL_MISMATCH
      - canal no corresponde al token    → 403 CHANNEL_MISMATCH

    La comparación es en tiempo constante (`hmac.compare_digest`) sobre TODOS
    los tokens configurados: no se sale del bucle en el primer match, para no
    filtrar por temporización cuál canal es.
    """
    token = extract_bearer(authorization)

    if not declared_channel:
        raise ChannelMismatchError("El header X-Forsis-Channel es obligatorio.")

    try:
        channel = Channel(declared_channel)
    except ValueError:
        raise ChannelMismatchError("Canal desconocido.")

    candidates = _tokens_for(channel)
    if not candidates:
        logger.error(
            "Canal %s sin token configurado: se rechaza todo (fail-closed).", channel.value
        )
        raise UnauthenticatedError("Credenciales ausentes.")

    if not any(hmac.compare_digest(token, c) for c in candidates):
        raise UnauthenticatedError("Credenciales ausentes.")

    return channel