from typing import Type
from app.core.executor.capability import Capability


class CapabilityFactory:
    """
    Fábrica encargada de instanciar las Capabilities.
    A futuro, centralizará la inyección de dependencias (repositorios, APIs).
    """
    def create(self, capability_class: Type[Capability]) -> Capability:
        return capability_class()
