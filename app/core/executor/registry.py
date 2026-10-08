from typing import Dict, List, Optional, Type
from app.contracts.capability_definition import CapabilityDefinition
from .capability import Capability


class CapabilityRegistry:
    """
    Registro centralizado para Capabilities.
    Separa las definiciones (para el Planner) de las implementaciones (para el Executor).
    """
    def __init__(self):
        self._definitions: Dict[str, CapabilityDefinition] = {}
        self._implementations: Dict[str, Type[Capability]] = {}

    def register(self, definition: CapabilityDefinition, implementation: Type[Capability]) -> None:
        if definition.id in self._definitions:
            raise ValueError(f"Definition with id '{definition.id}' is already registered.")
        
        if any(d.name == definition.name for d in self._definitions.values()):
            raise ValueError(f"Definition with name '{definition.name}' is already registered.")

        self._definitions[definition.id] = definition
        self._implementations[definition.id] = implementation

    def get_definition_by_id(self, capability_id: str) -> Optional[CapabilityDefinition]:
        return self._definitions.get(capability_id)

    def get_definition_by_name(self, name: str) -> Optional[CapabilityDefinition]:
        for definition in self._definitions.values():
            if definition.name == name:
                return definition
        return None

    def list_definitions(self) -> List[CapabilityDefinition]:
        return list(self._definitions.values())

    def sync_with_runtime(self, runtime) -> None:
        """
        Populate definitions in CapabilityRegistry directly from the Operational Registry (ADR-0008/ADR-0010).
        """
        for reg in runtime.list_capabilities():
            cap_id = reg.action_id
            name = reg.action_id.replace("action-", "").replace("-", "_")

            if cap_id in self._definitions or any(d.name == name for d in self._definitions.values()):
                continue

            defn = CapabilityDefinition(
                id=cap_id,
                name=name,
                description=f"{reg.display_name}: {reg.description}",
                category=reg.owning_domain,
                tags=reg.entity_types,
                required_permissions=reg.required_permissions,
                input_schema={inp: {"type": "string"} for inp in reg.inputs},
                output_schema={out: {"type": "string"} for out in reg.outputs}
            )
            self._definitions[cap_id] = defn

    def resolve_implementation(self, capability_id: str) -> Optional[Type[Capability]]:
        """
        Este método sólo debe ser llamado por el Executor.
        Retorna la clase ejecutable de la capability.
        """
        return self._implementations.get(capability_id)
