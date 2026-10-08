"""
ToolRunner — invocación de una capability con todas las guardas aplicadas
(Sprint 3, entregables 4 y 5; criterios A3, A4, A5, A6).

Responsabilidades, en orden:
  1. PlanGuard: 7 gates. Denegación ⇒ `status: denied`, nunca ejecución.
  2. Validación de parámetros contra `params_schema` (JSON Schema estricto).
  3. Ejecución con techo de 30 s por tool (`definition.timeout`).
  4. Traducción de CUALQUIER fallo a un resultado, no a una excepción que
     tumbe el turno: criterio A5 ("una tool que devuelve 500 NO tumba el
     turno → status degraded").
  5. Métricas por capability y risk_class.

El timeout usa un hilo con `concurrent.futures`: pymysql es bloqueante y
`asyncio.wait_for` sobre una corrutina no interrumpe una llamada bloqueante.
Si el hilo no termina, la consulta la corta igualmente el servidor por
`MAX_EXECUTION_TIME` (R-5) — el techo no depende sólo del cliente.
"""

from __future__ import annotations

import concurrent.futures
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.core.exceptions import (
    AgentException,
    CapabilityDeniedError,
    CapabilityNotFound,
    ContractError,
    QueryTimeoutError,
)
from app.core.metrics import metrics
from app.core.plan_guard import GuardDecision, PlanGuard
from app.core.risk import RiskClass

logger = logging.getLogger(__name__)

try:
    import jsonschema
    _HAS_JSONSCHEMA = True
except ImportError:  # pragma: no cover
    _HAS_JSONSCHEMA = False
    logger.warning("jsonschema no instalado: la validación de params será estructural.")


@dataclass
class ToolOutcome:
    """Resultado de invocar una tool. Nunca lanza hacia el AgentService."""

    capability_id: str
    status: str                       # "ok" | "denied" | "degraded"
    data: Optional[Dict[str, Any]] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    risk_class: Optional[str] = None
    duration_ms: int = 0
    guard: Optional[Dict[str, Any]] = None
    warnings: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    def as_audit(self) -> Dict[str, Any]:
        return {
            "tool": self.capability_id,
            "status": self.status,
            "risk_class": self.risk_class,
            "duration_ms": self.duration_ms,
            "error_code": self.error_code,
            "row_count": (self.data or {}).get("row_count"),
            "guard": self.guard,
        }


class ToolRunner:
    def __init__(self, registry, guard: Optional[PlanGuard] = None) -> None:
        self.registry = registry
        self.guard = guard or PlanGuard(registry)
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=4, thread_name_prefix="tool"
        )

    # ------------------------------------------------------------ validación

    def _validate_params(self, schema: Dict[str, Any], params: Dict[str, Any]) -> List[str]:
        """Devuelve la lista de errores de validación (vacía si es válido)."""
        if not schema:
            return []
        if not _HAS_JSONSCHEMA:
            # Degradación honesta: sin jsonschema se comprueba al menos que no
            # haya propiedades no declaradas, que es la regla fail-closed clave.
            permitidas = set((schema.get("properties") or {}).keys())
            if schema.get("additionalProperties") is False and permitidas:
                extras = sorted(set(params) - permitidas)
                return [f"parámetro no declarado: '{e}'" for e in extras]
            return []
        validator = jsonschema.Draft202012Validator(schema)
        return [
            f"{'.'.join(str(p) for p in e.absolute_path) or '(raíz)'}: {e.message}"
            for e in sorted(validator.iter_errors(params), key=lambda e: list(e.absolute_path))
        ]

    # ------------------------------------------------------------- ejecución

    def run(
        self,
        capability_id: str,
        parameters: Optional[Dict[str, Any]] = None,
        company: Optional[str] = None,
        roles: Optional[List[str]] = None,
    ) -> ToolOutcome:
        params = dict(parameters or {})
        started = time.perf_counter()

        # 1. PlanGuard -------------------------------------------------------
        decision: GuardDecision = self.guard.evaluate(
            capability_id=capability_id, parameters=params, company=company, roles=roles
        )
        risk_txt = decision.risk_class.value if decision.risk_class else "L0"

        if not decision.allowed:
            duration_ms = int((time.perf_counter() - started) * 1000)
            code = "CAPABILITY_NOT_FOUND" if decision.failed_gate == "existencia" else "CAPABILITY_DENIED"
            metrics.observe_tool(capability_id, duration_ms, risk_txt, "denied")
            logger.info(
                "PlanGuard DENEGÓ %s en gate '%s': %s",
                capability_id, decision.failed_gate, decision.reason,
            )
            return ToolOutcome(
                capability_id=capability_id,
                status="denied",
                error_code=code,
                error_message=decision.reason,
                risk_class=risk_txt,
                duration_ms=duration_ms,
                guard=decision.as_audit(),
            )

        definicion = self.registry.get_definition_by_id(capability_id)
        impl_cls = self.registry.resolve_implementation(capability_id)
        if definicion is None or impl_cls is None:
            duration_ms = int((time.perf_counter() - started) * 1000)
            metrics.observe_tool(capability_id, duration_ms, risk_txt, "error")
            return ToolOutcome(
                capability_id=capability_id, status="degraded",
                error_code="CAPABILITY_NOT_FOUND",
                error_message=f"No hay implementación registrada para '{capability_id}'.",
                risk_class=risk_txt, duration_ms=duration_ms, guard=decision.as_audit(),
            )

        # 2. Validación de parámetros ---------------------------------------
        errores = self._validate_params(definicion.input_schema or {}, params)
        if errores:
            duration_ms = int((time.perf_counter() - started) * 1000)
            metrics.observe_tool(capability_id, duration_ms, risk_txt, "error")
            return ToolOutcome(
                capability_id=capability_id, status="degraded",
                error_code="TOOL_PARAMS_INVALID",
                error_message="Parámetros inválidos: " + "; ".join(errores[:5]),
                risk_class=risk_txt, duration_ms=duration_ms, guard=decision.as_audit(),
            )

        # La empresa se inyecta DESPUÉS de validar: es contexto del turno, no
        # un parámetro que el LLM pueda elegir (evita cruce FORSIS/GERO).
        if company:
            params["company"] = str(company).upper()

        # 3. Ejecución con techo de tiempo ----------------------------------
        timeout_s = float(definicion.timeout or 30)
        future: Optional[concurrent.futures.Future] = None
        try:
            instancia = impl_cls()
            future = self._executor.submit(instancia.execute, params)
            data = future.result(timeout=timeout_s)
            duration_ms = int((time.perf_counter() - started) * 1000)
            metrics.observe_tool(capability_id, duration_ms, risk_txt, "ok")
            if isinstance(data, dict) and data.get("row_count") is not None:
                metrics.incr("sql_queries")
            return ToolOutcome(
                capability_id=capability_id, status="ok",
                data=data if isinstance(data, dict) else {"result": data},
                risk_class=risk_txt, duration_ms=duration_ms, guard=decision.as_audit(),
                warnings=["resultado truncado al límite de filas"]
                if isinstance(data, dict) and data.get("truncated") else [],
            )

        except concurrent.futures.TimeoutError:
            duration_ms = int((time.perf_counter() - started) * 1000)
            if future is not None:
                future.cancel()
            metrics.observe_tool(capability_id, duration_ms, risk_txt, "timeout")
            logger.warning("Tool %s superó su techo de %ss.", capability_id, timeout_s)
            return ToolOutcome(
                capability_id=capability_id, status="degraded",
                error_code="TOOL_TIMEOUT",
                error_message=f"La herramienta superó su límite de {int(timeout_s)} s.",
                risk_class=risk_txt, duration_ms=duration_ms, guard=decision.as_audit(),
            )

        except CapabilityDeniedError as exc:
            # Una L2/L3 cuyo execute() se niega por sí mismo (defensa en
            # profundidad): se reporta como denegación, no como avería.
            duration_ms = int((time.perf_counter() - started) * 1000)
            metrics.observe_tool(capability_id, duration_ms, risk_txt, "denied")
            return ToolOutcome(
                capability_id=capability_id, status="denied",
                error_code=exc.error_code, error_message=str(exc),
                risk_class=risk_txt, duration_ms=duration_ms, guard=decision.as_audit(),
            )

        except (QueryTimeoutError, ContractError) as exc:
            duration_ms = int((time.perf_counter() - started) * 1000)
            metrics.observe_tool(capability_id, duration_ms, risk_txt, "error")
            if getattr(exc, "error_code", "") in ("SQL_NOT_ALLOWED", "SQL_LIMIT_EXCEEDED"):
                metrics.incr("sql_rejected")
            logger.warning("Tool %s falló (%s): %s", capability_id, exc.error_code, exc)
            return ToolOutcome(
                capability_id=capability_id, status="degraded",
                error_code=exc.error_code, error_message=str(exc),
                risk_class=risk_txt, duration_ms=duration_ms, guard=decision.as_audit(),
            )

        except AgentException as exc:
            duration_ms = int((time.perf_counter() - started) * 1000)
            metrics.observe_tool(capability_id, duration_ms, risk_txt, "error")
            logger.warning("Tool %s falló: %s", capability_id, exc)
            return ToolOutcome(
                capability_id=capability_id, status="degraded",
                error_code="TOOL_EXECUTION_ERROR", error_message=str(exc),
                risk_class=risk_txt, duration_ms=duration_ms, guard=decision.as_audit(),
            )

        except Exception as exc:
            # A5: un fallo no previsto de la tool NO tumba el turno.
            duration_ms = int((time.perf_counter() - started) * 1000)
            metrics.observe_tool(capability_id, duration_ms, risk_txt, "error")
            logger.exception("Tool %s lanzó una excepción no contemplada.", capability_id)
            return ToolOutcome(
                capability_id=capability_id, status="degraded",
                error_code="TOOL_EXECUTION_ERROR",
                error_message=f"{type(exc).__name__}: {exc}"[:300],
                risk_class=risk_txt, duration_ms=duration_ms, guard=decision.as_audit(),
            )
