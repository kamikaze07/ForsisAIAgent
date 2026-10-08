from datetime import datetime
from typing import List
from zoneinfo import ZoneInfo

from app.contracts.capability_definition import CapabilityDefinition

from .system import (
    MULTI_STEP_INSTRUCTIONS,
    NO_CAPABILITY_MATCH_INSTRUCTIONS,
    RESPONSE_FORMAT_INSTRUCTIONS,
    SYSTEM_PLANNER_PROMPT,
)

_TZ = ZoneInfo("America/Mexico_City")


def _contexto_de_fecha() -> str:
    """
    Ancla temporal para el planificador.

    Sin esto, "este mes" lo resuelve el LLM por su cuenta y acierta o falla
    según su knowledge cutoff: se observó responder con datos de mayo cuando
    el usuario preguntaba por octubre. Va en el **user prompt**, no en el
    system prompt, a propósito: el system prompt está firmado
    (`calcular_firma_planner`), así que incluir la fecha allí haría que la
    firma cambiara cada día y la verificación de deriva no significaría nada.
    """
    ahora = datetime.now(_TZ)
    meses = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
             "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
    return (
        "CONTEXTO TEMPORAL (servidor, zona America/Mexico_City):\n"
        f"- Fecha actual: {ahora:%Y-%m-%d} ({meses[ahora.month - 1]} de {ahora.year}).\n"
        f"- Mes actual: {ahora.month:02d} ({meses[ahora.month - 1]}).\n"
        f"- Año actual: {ahora.year}.\n"
        "- Si el usuario dice 'este mes', 'el mes actual', 'octubre', 'este año' o "
        "similares, NUNCA inventes la fecha: tradúcelo a funciones SQL relativas "
        "(CURDATE(), MONTH(CURDATE()), YEAR(CURDATE())). Si el periodo es "
        "ambiguo, pregunta antes de consultar."
    )


class PromptBuilder:
    """
    Clase responsable de construir los prompts para el LLM.
    Mantiene al Planner libre de la lógica de strings o plantillas.

    El prompt se construye de forma dinámica a partir del catálogo REAL de
    capabilities registradas: el LLM nunca ve más que nombre, parámetros y
    descripción de cada una. No tiene acceso a SQL, nombres de tablas, ni
    ningún detalle de infraestructura.
    """

    @staticmethod
    def contexto_de_fecha() -> str:
        """El ancla temporal del servidor, compartida por ambos prompts."""
        return _contexto_de_fecha()

    @staticmethod
    def build_system_prompt(capabilities: List[CapabilityDefinition]) -> str:
        catalog = PromptBuilder._render_catalog(capabilities)
        return (
            f"{SYSTEM_PLANNER_PROMPT}\n\n"
            f"Capabilities disponibles:\n{catalog}\n\n"
            f"{RESPONSE_FORMAT_INSTRUCTIONS}\n\n"
            f"{NO_CAPABILITY_MATCH_INSTRUCTIONS}\n\n"
            f"{MULTI_STEP_INSTRUCTIONS}"
        )

    @staticmethod
    def build_user_prompt(text: str) -> str:
        """
        User prompt por turno: la pregunta más el contexto temporal del servidor.

        El system prompt va firmado y no puede llevar la fecha (haría que la
        firma variase cada día). El ancla temporal va aquí, donde es por turno.
        """
        return f"{_contexto_de_fecha()}\n\nPregunta del usuario: {text}"

    @staticmethod
    def _render_catalog(capabilities: List[CapabilityDefinition]) -> str:
        if not capabilities:
            return "(ninguna capability disponible todavía)"

        lines = []
        for cap in capabilities:
            properties = (cap.input_schema or {}).get("properties", {})
            params = ", ".join(properties.keys())
            params_part = f"({params})" if params else "()"
            lines.append(f"- {cap.name}{params_part}: {cap.description}")
        return "\n".join(lines)
