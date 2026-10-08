"""
Capabilities de ESCRITURA registradas y DENEGADAS (Sprint 3, entregable 7).

Existen en el catálogo a propósito. Son la prueba de que la guarda de riesgo
funciona sobre algo real: si no hubiera ninguna L2/L3 registrada, el criterio
A3 ("un tool L3 es RECHAZADO, no ejecutado") sería vacuo.

Ninguna de las dos tiene implementación de escritura. `execute()` lanza
`CapabilityDeniedError` de forma incondicional: aunque un bug del PlanGuard
las dejara pasar, no hay camino de código que escriba nada. La escritura real
llega en el Sprint 7, con dry-run y confirmación humana.
"""

from __future__ import annotations

from typing import Any, Dict

from app.contracts.capability_definition import CapabilityDefinition
from app.core.exceptions import CapabilityDeniedError
from app.core.executor.capability import Capability
from app.core.risk import RiskClass

# --------------------------------------------------------------------- L2

LIBERAR_GUIA_DEFINITION = CapabilityDefinition(
    id="traf.guia_liberar",
    name="traf_guia_liberar",
    description=(
        "Libera una guía retenida en trafico-system. ESCRITURA reversible (L2): "
        "requiere dry-run y confirmación humana explícita. No disponible en Fase 1."
    ),
    version="0.0.0-registrada-no-ejecutable",
    category="trafico",
    tags=["guias", "escritura", "l2"],
    required_permissions=["trafico.guias.liberar"],
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "num_guia": {"type": "string", "minLength": 2, "maxLength": 15},
            "motivo": {"type": "string", "minLength": 5, "maxLength": 500},
        },
        "required": ["num_guia", "motivo"],
    },
    timeout=30,
    experimental=True,
)


class GuiaLiberarCapability(Capability):
    """L2 — registrada para que PlanGuard la deniegue de forma trazable."""

    definition = LIBERAR_GUIA_DEFINITION
    risk_class = RiskClass.L2

    def execute(self, parameters: Dict[str, Any]) -> Any:
        raise CapabilityDeniedError(
            "La capability 'traf.guia_liberar' es de escritura (L2) y está deshabilitada en Fase 1. "
            "Las escrituras requieren dry-run y confirmación humana (Sprint 7).",
            details={"tool": "traf.guia_liberar", "risk_class": "L2"},
        )


# --------------------------------------------------------------------- L3

CANCELAR_FACTURA_DEFINITION = CapabilityDefinition(
    id="traf.factura_cancelar",
    name="traf_factura_cancelar",
    description=(
        "Cancela un CFDI timbrado ante el SAT. ESCRITURA IRREVERSIBLE (L3): "
        "PROHIBIDA para el agente en cualquier fase. Jamás se ejecuta."
    ),
    version="0.0.0-prohibida",
    category="trafico",
    tags=["facturacion", "escritura", "l3", "irreversible"],
    required_permissions=["trafico.facturas.cancelar"],
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "uuid": {"type": "string", "minLength": 36, "maxLength": 36},
            "motivo_sat": {"type": "string", "enum": ["01", "02", "03", "04"]},
        },
        "required": ["uuid", "motivo_sat"],
    },
    timeout=30,
    experimental=True,
)


class FacturaCancelarCapability(Capability):
    """L3 — nunca ejecutable. Existe para que la denegación sea demostrable."""

    definition = CANCELAR_FACTURA_DEFINITION
    risk_class = RiskClass.L3

    def execute(self, parameters: Dict[str, Any]) -> Any:
        raise CapabilityDeniedError(
            "La capability 'traf.factura_cancelar' es irreversible (L3) y está PROHIBIDA "
            "para el agente. Esta operación solo puede realizarla una persona en el sistema.",
            details={"tool": "traf.factura_cancelar", "risk_class": "L3"},
        )
