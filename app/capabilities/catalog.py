"""
Catálogo de capabilities del Sprint 3.

Un único punto donde se declara QUÉ existe. El Registry no descubre clases por
reflexión a propósito: un catálogo explícito es auditable de un vistazo y el
criterio de reversión del sprint ("quitar la tool del catálogo versionado") es
literalmente borrar una línea de aquí.
"""

from __future__ import annotations

from typing import Any, Dict, List, Type

from app.capabilities.analitica.consulta_sql import (
    EXAMPLES as CONSULTA_SQL_EXAMPLES,
    ConsultaSqlCapability,
)
from app.capabilities.analitica.explorar_esquema import (
    EXAMPLES as ESQUEMA_EXAMPLES,
    ExplorarEsquemaCapability,
)
from app.capabilities.trafico.escrituras_denegadas import (
    FacturaCancelarCapability,
    GuiaLiberarCapability,
)
from app.capabilities.trafico.guias_listar import EXAMPLES as GUIAS_EXAMPLES
from app.capabilities.trafico.guias_listar import GuiasListarCapability
from app.core.executor.capability import Capability
from app.core.executor.registry import CapabilityRegistry
from app.core.risk import RiskClass

CATALOG_VERSION = "2026.10.05-sprint3"

# (clase, risk_class, ejemplos para el prompt del Planner)
_CATALOG: List[tuple[Type[Capability], RiskClass, List[Dict[str, Any]]]] = [
    (GuiasListarCapability, RiskClass.L0, GUIAS_EXAMPLES),
    (ConsultaSqlCapability, RiskClass.L0, CONSULTA_SQL_EXAMPLES),
    (ExplorarEsquemaCapability, RiskClass.L0, ESQUEMA_EXAMPLES),
    (GuiaLiberarCapability, RiskClass.L2, []),          # registrada, denegada
    (FacturaCancelarCapability, RiskClass.L3, []),      # registrada, prohibida
]

# risk_class por id de capability: lo consulta PlanGuard sin instanciar nada.
RISK_BY_CAPABILITY: Dict[str, RiskClass] = {
    cls.definition.id: risk for cls, risk, _ in _CATALOG
}

EXAMPLES_BY_CAPABILITY: Dict[str, List[Dict[str, Any]]] = {
    cls.definition.id: ex for cls, _, ex in _CATALOG
}


def build_registry() -> CapabilityRegistry:
    """Construye el Registry del proceso con el catálogo completo."""
    registry = CapabilityRegistry()
    for cls, _risk, _ex in _CATALOG:
        registry.register(cls.definition, cls)
    return registry


def planner_catalog() -> List[Dict[str, Any]]:
    """
    Vista del catálogo para el prompt del Planner. **Solo L0/L1**: las de
    escritura no se le ofrecen al modelo en Fase 1 — no se le pide que elija
    bien algo que de todas formas sería denegado, porque eso sólo produce
    turnos fallidos y ruido en las métricas.
    """
    salida: List[Dict[str, Any]] = []
    for cls, risk, ejemplos in _CATALOG:
        if not risk.is_read_only:
            continue
        d = cls.definition
        salida.append({
            "tool": d.id,
            "description": d.description,
            "risk_class": risk.value,
            "params_schema": d.input_schema,
            "examples": ejemplos,
        })
    return salida


def catalog_summary() -> Dict[str, Any]:
    """Resumen para `/api/v1/capabilities` y para la verificación del sprint."""
    return {
        "catalog_version": CATALOG_VERSION,
        "total": len(_CATALOG),
        "by_risk_class": {
            rc.value: sum(1 for _, r, _ in _CATALOG if r is rc) for rc in RiskClass
        },
        "executable": sorted(cid for cid, r in RISK_BY_CAPABILITY.items() if r.is_read_only),
        "registered_denied": sorted(
            cid for cid, r in RISK_BY_CAPABILITY.items() if not r.is_read_only
        ),
        "capabilities": [
            {
                "tool": cls.definition.id,
                "name": cls.definition.name,
                "risk_class": risk.value,
                "category": cls.definition.category,
                "required_permissions": cls.definition.required_permissions,
                "executable": risk.is_read_only,
                "description": cls.definition.description,
            }
            for cls, risk, _ in _CATALOG
        ],
    }
