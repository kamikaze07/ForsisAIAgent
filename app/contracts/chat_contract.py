"""
Contrato HTTP de `POST /api/v1/chat` (channels.md §1.3 y §1.5).

Todo es fail-closed: `extra="forbid"` en todos los modelos. Un campo no
declarado es un `422 VALIDATION_ERROR`, nunca un valor ignorado en silencio
(channels.md §1.3 regla 1).

Decisión de diseño: `ChatRequest` NO hereda del `UserRequest` interno del
prototipo. Son contratos distintos con consumidores distintos — `UserRequest`
es la entrada del núcleo (text/context) y `ChatRequest` es el cable de red con
`company`, `actor`, `channel` y validaciones de seguridad. Fusionarlos obliga a
la capa de red a conocer campos internos y al núcleo a conocer el canal, que es
precisamente lo que el diseño prohíbe (`channels.md` §0: "el agente no tiene
lógica de canal").
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


# --------------------------------------------------------------------- enums

class Channel(str, Enum):
    """Canales del sistema (channels.md §1.1)."""

    WIDGET_TRAFICO = "widget-trafico"
    WIDGET_LIQUIDACIONES = "widget-liquidaciones"
    MATTERMOST = "mattermost"
    API = "api"
    # ADJ-2 (web-ui-design.md §6.0): la UI standalone declara su propio canal.
    # Mandarlo como "widget-trafico" sería mentir en el contrato y el token por
    # canal ligado a X-Forsis-Channel haría correcto un 403 CHANNEL_MISMATCH.
    UI_STANDALONE = "ui-standalone"

    @classmethod
    def _missing_(cls, value: object):
        if isinstance(value, str):
            normalized = value.strip().lower().replace("_", "-")
            for member in cls:
                if member.value == normalized:
                    return member
        return None


class Company(str, Enum):
    """
    Empresa. SIN DEFAULT y a propósito: `liquidaciones-system-analysis.md` §1.4
    identifica "el mismo endpoint lee FORSIS o GERO según el estado de sesión"
    como la fuente de error más peligrosa para un agente automatizado. Si falta,
    es 422 — nunca se asume.
    """

    FORSIS = "FORSIS"
    GERO = "GERO"


class SubjectType(str, Enum):
    TRAFICO_USER = "trafico_user"
    LIQUIDACIONES_USER = "liquidaciones_user"
    MATTERMOST_USER = "mattermost_user"
    API_USER = "api_user"

    @classmethod
    def _missing_(cls, value: object):
        if isinstance(value, str):
            normalized = value.strip().lower()
            for member in cls:
                if member.value == normalized:
                    return member
        return None


class Mode(str, Enum):
    CHAT = "chat"
    CONFIRM = "confirm"


class ResponseStatus(str, Enum):
    """
    Enum de `status` (channels.md §1.5.2).

    `clarification_needed` y `confirmation_required` son 200, NO 4xx: son
    estados normales de una conversación. Devolverlos como error obligaría a
    `forsis-bot` — que hoy hace `raise_for_status()` — a tratar el camino feliz
    como excepción.
    """

    OK = "ok"
    CLARIFICATION_NEEDED = "clarification_needed"
    CONFIRMATION_REQUIRED = "confirmation_required"
    NO_CAPABILITY = "no_capability"
    DENIED = "denied"
    DEGRADED = "degraded"
    ERROR = "error"


# ------------------------------------------------------------------ requests

class Actor(BaseModel):
    """
    Identidad del humano, resuelta por el adaptador (channels.md §1.2).

    El token autentica al ADAPTADOR, no al usuario: por eso `authorized` viaja
    aquí y la evaluación de la allowlist ocurre UNA sola vez, en el adaptador
    (channels.md §1.4 decisión 3). El agente puede ser MÁS restrictivo
    (PlanGuard filtra por required_permissions), nunca más permisivo.
    """

    model_config = ConfigDict(extra="forbid")

    subject: str = Field(min_length=1, max_length=128)
    subject_type: SubjectType
    display_name: Optional[str] = Field(default=None, max_length=255)
    roles: List[str] = Field(default_factory=list)
    authorized: bool = True


class ThreadMeta(BaseModel):
    """Metadatos de hilo del canal. Solo informativos: nunca lógica."""

    model_config = ConfigDict(extra="forbid")

    root_id: Optional[str] = None
    reply_count: int = Field(default=0, ge=0)


class ClientMeta(BaseModel):
    """Telemetría del adaptador. Nunca influye en la lógica."""

    model_config = ConfigDict(extra="forbid")

    adapter: Optional[str] = Field(default=None, max_length=64)
    locale: str = Field(default="es-MX", max_length=16)


class ChatRequest(BaseModel):
    """Body de `POST /api/v1/chat`. Ver `channels.md` §1.3."""

    model_config = ConfigDict(extra="forbid")

    message: str
    session_id: Optional[str] = Field(default=None, max_length=128)
    channel: Channel
    company: Company
    actor: Actor
    inputs: Optional[Dict[str, Any]] = None
    mode: Mode = Mode.CHAT
    thread: Optional[ThreadMeta] = None
    client: Optional[ClientMeta] = None
    debug: bool = False

    # -- reglas de validación (fail-closed) ---------------------------

    @field_validator("message")
    @classmethod
    def _message_presente(cls, v: str) -> str:
        # Vacío o solo whitespace: 422. El techo de 4000 chars NO se comprueba
        # aquí a propósito — debe dar 413 MESSAGE_TOO_LONG, no 422, y eso lo
        # decide el handler para no perder el código correcto (channels.md §1.6).
        if not v or not v.strip():
            raise ValueError("message no puede estar vacío ni ser solo whitespace")
        return v

    @field_validator("debug")
    @classmethod
    def _debug_requiere_soporte(cls, v: bool, info: Any) -> bool:
        # `debug: true` se acepta sintácticamente; la autorización de rol de
        # soporte se evalúa en el servicio, donde ya se conoce el actor. Aquí
        # solo se normaliza.
        return bool(v)

    def nuevo_trace_id(self) -> str:
        return str(uuid.uuid4())


# ----------------------------------------------------------------- responses

class ComponentField(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    value: str


class ComponentColumn(BaseModel):
    """Columna de un componente `table`.

    `align` existe para que el canal no tenga que adivinar la alineación a
    partir del contenido: una cifra mal alineada a la izquierda es ilegible en
    una tabla de importes, y el backend ya sabe cuáles columnas son numéricas.
    """

    model_config = ConfigDict(extra="forbid")

    key: str
    label: str
    align: str = "left"  # left | right


class UIComponent(BaseModel):
    """Componente renderizable por el adaptador (cards, tablas, chips).

    Dos formas conviven:
      - `type="card"`  -> usa `fields` (pares label/value).
      - `type="table"` -> usa `columns` + `rows`.
    `columns`/`rows` son aditivos y con default vacío, de modo que los canales
    que solo entienden cards siguen funcionando sin cambios.
    """

    model_config = ConfigDict(extra="forbid")

    type: str
    title: Optional[str] = None
    fields: List[ComponentField] = Field(default_factory=list)
    columns: List[ComponentColumn] = Field(default_factory=list)
    rows: List[Dict[str, str]] = Field(default_factory=list)
    caption: Optional[str] = None
    actions: List[Dict[str, Any]] = Field(default_factory=list)


class ClarificationOption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    value: str


class Clarification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str
    missing: List[str] = Field(default_factory=list)
    options: List[ClarificationOption] = Field(default_factory=list)


class DryRunResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    valid: bool
    warnings: List[str] = Field(default_factory=list)


class Confirmation(BaseModel):
    """Propuesta L2 pendiente de humano (channels.md §1.9). Sprint 2 solo lo
    modela: sin Executor no se generan, pero el contrato debe existir ya para
    que el adaptador no cambie al añadir herramientas."""

    model_config = ConfigDict(extra="forbid")

    confirmation_id: str
    summary: str
    tool: str
    risk_class: str
    dry_run_result: DryRunResult
    expires_at: datetime


class TraceLatency(BaseModel):
    model_config = ConfigDict(extra="forbid")

    llm: int = 0
    tools: int = 0
    total: int = 0


class ToolExecutionRef(BaseModel):
    """
    ADJ-1 (web-ui-design.md §6.0). Referencia opaca a una ejecución de tool.

    Sin el `id` la citación de fuente (§3.4) y el enlace a la vista de
    ejecución son imposibles: `tools_executed` solo trae nombres, y dos
    llamadas a la misma tool en un turno serían indistinguibles.
    No contiene datos de negocio, por lo que no amplía la superficie de fuga.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    tool: str
    risk_class: str = "L0"
    status: str = "ok"
    rows: Optional[int] = None
    ms: int = 0


class Trace(BaseModel):
    """
    SIEMPRE presente (channels.md §1.5.3).

    `llm_model_real` no es telemetría opcional: el combo "Forsis" enruta cada
    llamada a un proveedor distinto, y sin el modelo real que respondió un
    fallo intermitente de formato es imposible de diagnosticar.
    """

    model_config = ConfigDict(extra="forbid")

    trace_id: str
    plan_id: Optional[str] = None
    llm_model_real: str
    llm_attempts: int = 0
    latency_ms: TraceLatency
    tools_executed: List[str] = Field(default_factory=list)
    # ADJ-1: aditivo y retrocompatible — los canales existentes lo ignoran.
    tool_executions: List[ToolExecutionRef] = Field(default_factory=list)


class ChatResponse(BaseModel):
    """
    Respuesta de `POST /api/v1/chat` (channels.md §1.5).

    Invariante que el adaptador depende: `answer` NUNCA es null, ni siquiera en
    fallo. Es lo que permite que el canal sea trivial — imprime `answer`,
    siempre — en vez de replicar lógica de decisión de error en dos lugares.
    """

    model_config = ConfigDict(extra="forbid")

    answer: str
    session_id: str
    status: ResponseStatus
    components: List[UIComponent] = Field(default_factory=list)
    clarification: Optional[Clarification] = None
    confirmation: Optional[Confirmation] = None
    context_updated: bool = False
    updated_context: Dict[str, Any] = Field(default_factory=dict)
    trace: Trace
    debug: Optional[Dict[str, Any]] = None


class ErrorBody(BaseModel):
    """
    Body de error (channels.md §1.6). Mismo shape SIEMPRE, y con `answer`
    legible: el canal tiene algo que mostrarle al usuario también cuando la
    petición falla.
    """

    model_config = ConfigDict(extra="forbid")

    error_code: str
    answer: str
    retryable: bool
    trace_id: Optional[str] = None
    session_id: Optional[str] = None
    details: Dict[str, Any] = Field(default_factory=dict)


# -------------------------------------------------------------- utilidades

MAX_MESSAGE_LEN = 4000


def canonicalizar_request_hash(req: ChatRequest) -> str:
    """
    SHA-256 de (message, company, actor.subject, session_id, mode, inputs)
    canonicalizados — el `request_hash` de `channels.md` §1.8.

    Es lo que distingue "reintento de red" (mismo hash → respuesta guardada) de
    "clave reutilizada por error del adaptador" (hash distinto → 422).
    """
    import hashlib
    import json

    payload = {
        "message": req.message,
        "company": req.company.value,
        "channel": req.channel.value,
        "actor_subject": req.actor.subject,
        "session_id": req.session_id,
        "mode": req.mode.value,
        "inputs": req.inputs or {},
    }
    canonico = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonico.encode("utf-8")).hexdigest()