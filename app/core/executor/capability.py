from abc import ABC, abstractmethod
from typing import Any, ClassVar, Dict, Optional

from app.contracts.capability_definition import CapabilityDefinition


class Capability(ABC):
    """
    Abstracción base de una herramienta ejecutable por el Agente.
    Representa estrictamente el contrato de ejecución.

    `definition` y `risk_class` se declaran como atributos de CLASE para que el
    catálogo y el PlanGuard puedan leerlos SIN instanciar la herramienta:
    decidir si algo está permitido no debe requerir construir el objeto que
    haría el trabajo. Son `Optional` en la base por compatibilidad con las
    capabilities del prototipo que todavía no las declaran.
    """

    definition: ClassVar[Optional[CapabilityDefinition]] = None
    risk_class: ClassVar[Any] = None

    @abstractmethod
    def execute(self, parameters: Dict[str, Any]) -> Any:
        pass
