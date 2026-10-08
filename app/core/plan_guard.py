"""
PlanGuard — los 7 gates que un plan debe pasar antes de ejecutarse
(`tools-design.md` §4, Sprint 3 entregable 5).

Alcance declarado del Sprint 3: **gate 5 (permisos) operativo**; los demás son
stubs que PASAN, pero con `assert` ruidoso si un gate falta de la secuencia.
Eso es deliberado y está escrito aquí para que nadie lo confunda con un
descuido: un gate que todavía no decide nada debe ser visible, no invisible.

Gate 1  existencia de la capability en el catálogo
Gate 2  validación de parámetros contra params_schema
Gate 3  coherencia de empresa (FORSIS/GERO)
Gate 4  límites de alcance (rangos de fecha, nº de filas)
Gate 5  PERMISOS del actor + clase de riesgo    ← operativo
Gate 6  dry-run obligatorio para L2             ← stub (Sprint 7)
Gate 7  confirmación humana para L2             ← stub (Sprint 7)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from app.capabilities.catalog import RISK_BY_CAPABILITY
from app.core.exceptions import CapabilityDeniedError, CapabilityNotFound
from app.core.risk import SPRINT3_ALLOWED, RiskClass

logger = logging.getLogger(__name__)

GATES = ("existencia", "params", "empresa", "alcance", "permisos", "dry_run", "confirmacion")

# Permisos implícitos por rol (`permissions.md` §4). Mapa cerrado: un rol
# desconocido no concede nada — fail-closed.
ROLE_PERMISSIONS: Dict[str, Set[str]] = {
    "admin": {"trafico.guias.read", "trafico.guias.liberar", "liq.liquidaciones.read", "analitica.consultar"},
    "trafico": {"trafico.guias.read", "analitica.consultar"},
    "trafico_consulta": {"trafico.guias.read", "analitica.consultar"},
    "operaciones": {"trafico.guias.read", "analitica.consultar"},
    "facturacion": {"trafico.guias.read", "analitica.consultar"},
    "liquidaciones": {"liq.liquidaciones.read", "trafico.guias.read", "analitica.consultar"},
    "soporte": {"trafico.guias.read", "analitica.consultar"},
    "consulta": {"trafico.guias.read", "analitica.consultar"},
}


@dataclass
class GuardDecision:
    """Resultado de pasar un plan por los gates. `allowed=False` ⇒ denegado."""

    allowed: bool
    capability_id: str
    risk_class: Optional[RiskClass] = None
    reason: Optional[str] = None
    failed_gate: Optional[str] = None
    gates_passed: List[str] = field(default_factory=list)
    missing_permissions: List[str] = field(default_factory=list)

    def as_audit(self) -> Dict[str, Any]:
        return {
            "capability": self.capability_id,
            "risk_class": self.risk_class.value if self.risk_class else None,
            "allowed": self.allowed,
            "failed_gate": self.failed_gate,
            "reason": self.reason,
            "gates_passed": list(self.gates_passed),
            "missing_permissions": list(self.missing_permissions),
        }


def _write_allowlist() -> Set[str]:
    """
    `AGENT_WRITE_ALLOWLIST` vacía en Fase 1 = ninguna escritura permitida.
    Se lee del entorno en cada llamada a propósito: así el criterio de
    reversión no exige reconstruir la imagen.
    """
    raw = os.getenv("AGENT_WRITE_ALLOWLIST", "").strip()
    return {x.strip() for x in raw.split(",") if x.strip()}


def resolve_permissions(roles: List[str]) -> Set[str]:
    """Permisos efectivos del actor. Rol no reconocido ⇒ no aporta permisos."""
    efectivos: Set[str] = set()
    for rol in roles or []:
        clave = str(rol).strip().lower()
        concedidos = ROLE_PERMISSIONS.get(clave)
        if concedidos is None:
            logger.info("PlanGuard: rol no reconocido '%s' (no concede permisos).", rol)
            continue
        efectivos |= concedidos
    return efectivos


class PlanGuard:
    """Evalúa los 7 gates en orden fijo y se detiene en el primero que falla."""

    def __init__(self, registry) -> None:
        self.registry = registry
        # Si alguien añade un gate al enum sin implementar su método, esto
        # revienta al arrancar, no en producción a mitad de un turno.
        for gate in GATES:
            assert hasattr(self, f"_gate_{gate}"), f"PlanGuard: falta el gate '{gate}'"

    # ------------------------------------------------------------------ gates

    def _gate_existencia(self, d: GuardDecision, ctx: Dict[str, Any]) -> Optional[str]:
        if self.registry.get_definition_by_id(d.capability_id) is None:
            return f"La capability '{d.capability_id}' no existe en el catálogo."
        return None

    def _gate_params(self, d: GuardDecision, ctx: Dict[str, Any]) -> Optional[str]:
        # STUB Sprint 3: la validación estricta contra params_schema la hace el
        # Executor con jsonschema antes de invocar. Aquí se comprueba sólo la
        # forma para que un plan con `parameters: "texto"` no llegue más lejos.
        params = ctx.get("parameters")
        if params is not None and not isinstance(params, dict):
            return "El campo 'parameters' debe ser un objeto."
        return None

    def _gate_empresa(self, d: GuardDecision, ctx: Dict[str, Any]) -> Optional[str]:
        company = ctx.get("company")
        if not company:
            return "Falta la empresa (company) en el contexto del turno."
        if str(company).upper() not in {"FORSIS", "GERO"}:
            return f"Empresa no reconocida: '{company}'."
        return None

    def _gate_alcance(self, d: GuardDecision, ctx: Dict[str, Any]) -> Optional[str]:
        # STUB Sprint 3 que ya hace una comprobación útil: el techo de filas.
        params = ctx.get("parameters") or {}
        limite = params.get("limit")
        if isinstance(limite, int) and limite > 1000:
            return f"El plan pide {limite} filas; el techo de alcance es 1000."
        return None

    def _gate_permisos(self, d: GuardDecision, ctx: Dict[str, Any]) -> Optional[str]:
        """GATE OPERATIVO del Sprint 3: riesgo + RBAC real."""
        risk = RISK_BY_CAPABILITY.get(d.capability_id)
        if risk is None:
            return f"La capability '{d.capability_id}' no declara risk_class."
        d.risk_class = risk

        # L3: prohibida siempre, sin excepción configurable.
        if risk is RiskClass.L3:
            return (
                f"'{d.capability_id}' es una operación irreversible (L3) y está prohibida "
                "para el agente."
            )

        # L2: sólo si está explícitamente en la allowlist de escritura (vacía en Fase 1).
        if risk not in SPRINT3_ALLOWED:
            if d.capability_id not in _write_allowlist():
                return (
                    f"'{d.capability_id}' es una operación de escritura ({risk.value}) y las "
                    "escrituras están deshabilitadas en esta fase."
                )

        # RBAC: el actor debe tener TODOS los permisos requeridos.
        definicion = self.registry.get_definition_by_id(d.capability_id)
        requeridos = set(definicion.required_permissions or []) if definicion else set()
        if requeridos:
            efectivos = resolve_permissions(ctx.get("roles") or [])
            faltantes = sorted(requeridos - efectivos)
            if faltantes:
                d.missing_permissions = faltantes
                return (
                    f"El actor no tiene permiso para '{d.capability_id}'. "
                    f"Requiere: {', '.join(faltantes)}."
                )
        return None

    def _gate_dry_run(self, d: GuardDecision, ctx: Dict[str, Any]) -> Optional[str]:
        # STUB Sprint 3: sólo alcanzable por L2, que el gate 5 ya denegó.
        if d.risk_class and d.risk_class.requires_dry_run:
            logger.warning(
                "PlanGuard gate 'dry_run' es un stub y se alcanzó con %s (%s). "
                "El dry-run real llega en el Sprint 7.",
                d.capability_id, d.risk_class.value,
            )
        return None

    def _gate_confirmacion(self, d: GuardDecision, ctx: Dict[str, Any]) -> Optional[str]:
        # STUB Sprint 3.
        if d.risk_class and d.risk_class.requires_human_confirmation:
            logger.warning(
                "PlanGuard gate 'confirmacion' es un stub y se alcanzó con %s. "
                "La confirmación humana llega en el Sprint 7.",
                d.capability_id,
            )
        return None

    # ------------------------------------------------------------- evaluación

    def evaluate(
        self,
        capability_id: str,
        parameters: Optional[Dict[str, Any]] = None,
        company: Optional[str] = None,
        roles: Optional[List[str]] = None,
    ) -> GuardDecision:
        d = GuardDecision(allowed=False, capability_id=capability_id)
        ctx = {"parameters": parameters or {}, "company": company, "roles": roles or []}

        for gate in GATES:
            motivo = getattr(self, f"_gate_{gate}")(d, ctx)
            if motivo:
                d.failed_gate = gate
                d.reason = motivo
                d.allowed = False
                return d
            d.gates_passed.append(gate)

        d.allowed = True
        return d

    def assert_allowed(self, *args, **kwargs) -> GuardDecision:
        """Igual que `evaluate`, pero lanza la excepción de contrato si deniega."""
        d = self.evaluate(*args, **kwargs)
        if not d.allowed:
            if d.failed_gate == "existencia":
                raise CapabilityNotFound(d.reason or "capability inexistente")
            raise CapabilityDeniedError(d.reason or "denegado", details=d.as_audit())
        return d
