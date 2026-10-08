from typing import Any, Dict


class AgentException(Exception):
    """Excepción base para todos los errores del Agente."""
    pass

class CapabilityNotFound(AgentException):
    """La capability solicitada no existe en el registro."""
    pass

class CapabilityExecutionError(AgentException):
    """Error interno durante la ejecución de la capability."""
    pass

class PlanningError(AgentException):
    """Error al generar el plan de ejecución."""
    pass

class ProviderError(AgentException):
    """Error devuelto por el LLM Gateway."""
    pass

class AmbiguousResultError(AgentException):
    """
    Una búsqueda por texto (nombre de operador, nombre de cliente...)
    encontró más de una coincidencia real. No es un error de sistema --
    es una ambigüedad genuina de negocio que ningún Domain Service debe
    resolver adivinando; el Tool la traduce a un ExecutionResult de
    error con los candidatos, igual que un "no encontrado".
    """
    pass

class PlanValidationError(AgentException):
    """
    Un ExecutionPlan multi-task es estructuralmente inválido: referencia
    un task_id que no existe, tiene una dependencia circular, o un
    `depends_on` cuyo `source_task_id` no está declarado en
    `dependencies`. Se detecta ANTES de ejecutar nada -- nunca se ejecuta
    parcialmente un plan mal formado (bloque Multi-Step Agent, sección
    12: "validar el plan" es el primer paso del Executor).
    """
    pass


# --------------------------------------------------------------------------
# Taxonomía de errores del contrato HTTP (channels.md §1.6).
# Cada excepción lleva SU error_code y SU status HTTP para que el handler
# sea un `except AgentException -> JSONResponse` y no un if/elif por sitio.
# --------------------------------------------------------------------------

class ContractError(AgentException):
    """Base de los errores que se traducen 1:1 a una respuesta HTTP."""

    error_code = "INTERNAL_ERROR"
    http_status = 500
    retryable = True

    def __init__(self, message: str, details: Dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class UnauthenticatedError(ContractError):
    """401 — Bearer ausente o inválido. Nunca se dice cuál de los dos falló."""

    error_code = "UNAUTHENTICATED"
    http_status = 401
    retryable = False


class ForbiddenError(ContractError):
    """403 — actor no autorizado, permisos insuficientes o L3."""

    error_code = "FORBIDDEN"
    http_status = 403
    retryable = False


class ChannelMismatchError(ForbiddenError):
    """403 — X-Forsis-Channel no corresponde al token presentado."""

    error_code = "CHANNEL_MISMATCH"


class SessionMismatchError(ForbiddenError):
    """403 — session_id de otro (channel, company, actor.subject)."""

    error_code = "SESSION_MISMATCH"


class MessageTooLongError(ContractError):
    """413 — message > 4000 caracteres."""

    error_code = "MESSAGE_TOO_LONG"
    http_status = 413
    retryable = False


class ValidationFailedError(ContractError):
    """
    422 — campo extra, company ausente, enum inválido. Distingue
    IDEMPOTENCY_KEY_REUSED, que es un bug del adaptador y no del usuario.
    """

    error_code = "VALIDATION_ERROR"
    http_status = 422
    retryable = False


class IdempotencyKeyReusedError(ValidationFailedError):
    """422 — misma Idempotency-Key con request_hash distinto."""

    error_code = "IDEMPOTENCY_KEY_REUSED"


class IdempotencyInFlightError(ContractError):
    """409 — misma clave, turno todavía corriendo. Retry-After: 5."""

    error_code = "IDEMPOTENCY_IN_FLIGHT"
    http_status = 409
    retryable = True


class LlmUnavailableError(ContractError):
    """
    502 — Omniroute inalcanzable o error HTTP.

    retryable=False en el contrato (channels.md §1.6.1): el combo enruta a
    proveedores distintos y un reintento del cliente puede caer en otro
    proveedor con la misma respuesta. NO se traduce a 500 ni a silencio.
    """

    error_code = "LLM_UNAVAILABLE"
    http_status = 502
    retryable = False


class DependencyUnavailableError(ContractError):
    """503 — BD propia o sistema de negocio caído. Retryable con backoff."""

    error_code = "DEPENDENCY_UNAVAILABLE"
    http_status = 503
    retryable = True


class TurnTimeoutError(ContractError):
    """504 — el turno superó el techo de 120 s (channels.md §1.7)."""

    error_code = "TURN_TIMEOUT"
    http_status = 504
    retryable = False


class LlmJsonInvalidError(ContractError):
    """
    Fail-closed del formato (sprint-plan-v2 §Sprint 2, entregable 1):
    tras los intentos permitidos no hubo JSON válido. NUNCA se degrada a
    un dict vacío — un plan vacío parece "no sé hacerlo" y es indistinguible
    de un fallo del proveedor.

    Se materializa como 502 LLM_UNAVAILABLE porque desde el adaptador es un
    fallo del proveedor, no una petición mal formada.
    """

    error_code = "LLM_UNAVAILABLE"
    http_status = 502
    retryable = False


class RateLimitedError(ContractError):
    """429 — cuota por actor o canal excedida."""

    error_code = "RATE_LIMITED"
    http_status = 429
    retryable = True


# --------------------------------------------------------------------------
# Sprint 3 — acceso a datos de solo lectura y guardas de plan.
# --------------------------------------------------------------------------

class SqlNotAllowedError(ForbiddenError):
    """
    403 — el parser con allowlist (R-3) rechazó la sentencia antes de que
    saliera a la red. La barrera fuerte sigue siendo `GRANT SELECT` en el
    servidor; esto es defensa en profundidad con motivo auditable.
    """

    error_code = "SQL_NOT_ALLOWED"


class SqlLimitExceededError(ForbiddenError):
    """403 — la consulta pide más filas que el techo duro de la capability."""

    error_code = "SQL_LIMIT_EXCEEDED"


class QueryTimeoutError(ContractError):
    """
    504 — la consulta SQL superó su techo (`MAX_EXECUTION_TIME`). Se distingue
    de TURN_TIMEOUT: aquí lo que se agotó es una sola query, no el turno.
    """

    error_code = "QUERY_TIMEOUT"
    http_status = 504
    retryable = False


class CapabilityDeniedError(ForbiddenError):
    """
    403 — PlanGuard denegó la capability: risk_class no ejecutable (L3),
    permiso faltante del actor, o empresa fuera de su alcance.
    """

    error_code = "CAPABILITY_DENIED"
