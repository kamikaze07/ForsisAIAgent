"""
Detección determinista de small talk conversacional (saludos, despedidas,
agradecimientos, preguntas de identidad) -- se resuelve ANTES del Planner,
sin llamar a Ollama ni a ninguna Tool.

Por qué existe: verificado en producción que "Hola" llegaba hasta el
Planner, el modelo de planning no encontraba ninguna capability razonable
para eso (correcto -- no existe una "Tool de saludar"), y el usuario
recibía "No encontré ninguna herramienta capaz de responder esa pregunta"
-- una respuesta técnicamente correcta pero conversacionalmente rota.

Deliberadamente NO es NLP/intención difusa: es un matching de frases
NORMALIZADAS (sin acentos, sin puntuación, en minúsculas) contra listas
curadas, 100% determinista y trivial de testear -- mismo criterio de
simplicidad que ya se usa en guide_knowledge.py/billing_knowledge.py.

Por diseño, solo dispara cuando el mensaje ES small talk de principio a
fin. "hola, cuánto pesa la guía PR226644" NO debe interceptarse aquí --
debe llegar íntegro al Planner. Esto es intencional: un matcher de
palabras sueltas dentro de una frase más larga produciría falsos
positivos constantes.
"""

import re
import unicodedata
from datetime import datetime
from enum import Enum
from typing import Dict, Optional, Set
from zoneinfo import ZoneInfo


class SmalltalkIntent(str, Enum):
    GREETING = "GREETING"
    THANKS = "THANKS"
    FAREWELL = "FAREWELL"
    IDENTITY = "IDENTITY"
    DATETIME = "DATETIME"


_PHRASES: Dict[SmalltalkIntent, Set[str]] = {
    SmalltalkIntent.GREETING: {
        "hola",
        "hola hola",
        "buenas",
        "buenos dias",
        "buenas tardes",
        "buenas noches",
        "hey",
        "que tal",
        "hola que tal",
        "saludos",
        "hi",
        "hello",
    },
    SmalltalkIntent.THANKS: {
        "gracias",
        "muchas gracias",
        "mil gracias",
        "gracias totales",
        "te lo agradezco",
        "muy amable",
        "ok gracias",
    },
    SmalltalkIntent.FAREWELL: {
        "adios",
        "hasta luego",
        "nos vemos",
        "bye",
        "chao",
        "hasta pronto",
        "me despido",
        "hasta la proxima",
    },
    SmalltalkIntent.IDENTITY: {
        "quien eres",
        "que eres",
        "quien eres tu",
        "quien eres tu exactamente",
        "que puedes hacer",
        "que haces",
        "que puedes hacer por mi",
        "en que me puedes ayudar",
    },
    SmalltalkIntent.DATETIME: {
        "que dia es hoy",
        "que dia es",
        "que dia tenemos hoy",
        "en que dia estamos",
        "que fecha es hoy",
        "que fecha es",
        "cual es la fecha de hoy",
        "fecha de hoy",
        "dime la fecha de hoy",
        "dime que dia es hoy",
        "que hora es",
        "que hora tienes",
        "dime la hora",
        "hora actual",
        "que hora es hoy",
    },
}

_DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
_MESES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"
]


def _formatear_fecha_hora() -> str:
    try:
        tz = ZoneInfo("America/Mexico_City")
        ahora = datetime.now(tz)
    except Exception:
        ahora = datetime.now()
    dia_sem = _DIAS[ahora.weekday()]
    mes = _MESES[ahora.month - 1]
    return f"Hoy es {dia_sem} {ahora.day} de {mes} de {ahora.year}, y son las {ahora.strftime('%H:%M')} hrs (hora central de México)."

_RESPONSES: Dict[SmalltalkIntent, str] = {
    SmalltalkIntent.GREETING: "Hola, ¿en qué puedo ayudarte?",
    SmalltalkIntent.THANKS: "Con gusto. ¿Necesitas algo más?",
    SmalltalkIntent.FAREWELL: "Hasta luego.",
    SmalltalkIntent.IDENTITY: (
        "Soy Forsis Intelligence, el asistente conversacional interno de Forsis "
        "(logística y transporte de carga). Puedo ayudarte a consultar guías, "
        "operadores, unidades, remolques, clientes y facturas."
    ),
}


def classify(text: str) -> Optional[SmalltalkIntent]:
    """Devuelve la intención de small talk si el mensaje completo
    (normalizado) coincide con una frase conocida; None en cualquier otro
    caso -- incluida una pregunta real que solo empieza con un saludo."""
    normalized = _normalize(text)
    if not normalized:
        return None
    for intent, phrases in _PHRASES.items():
        if normalized in phrases:
            return intent
    return None


def respond(intent: SmalltalkIntent) -> str:
    if intent == SmalltalkIntent.DATETIME:
        return _formatear_fecha_hora()
    return _RESPONSES[intent]


def detect_response(text: str) -> Optional[str]:
    """Atajo para la capa de interfaz: None si no es small talk, o la
    respuesta canónica lista para devolver al usuario sin tocar
    Planner/Executor/Composer."""
    intent = classify(text)
    return respond(intent) if intent else None


def _normalize(text: str) -> str:
    text = text.strip().lower()
    text = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()
