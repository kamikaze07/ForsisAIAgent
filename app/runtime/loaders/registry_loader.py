"""
Component 1: Registry Loader
Loads every Registry Entry from operational-registry/ and builds an in-memory catalog.
"""

import os
from typing import Dict, List, Optional, Any
from app.runtime.models import RegistryEntryModel
from app.runtime.loaders.yaml_loader import parse_yaml_string


class RegistryLoader:
    def __init__(self, registry_dir: str = "/home/servidor/forsis-agent/operational-registry"):
        self.registry_dir = registry_dir
        self.entries_dir = os.path.join(registry_dir, "entries")
        self._entries_by_id: Dict[str, RegistryEntryModel] = {}
        self._entries_by_action_id: Dict[str, RegistryEntryModel] = {}
        self._entries_by_capability: Dict[str, List[RegistryEntryModel]] = {}
        self._entries_by_system: Dict[str, List[RegistryEntryModel]] = {}
        self._entries_by_domain: Dict[str, List[RegistryEntryModel]] = {}
        self._entries_by_automation: Dict[str, List[RegistryEntryModel]] = {}
        self._entries_by_entity: Dict[str, List[RegistryEntryModel]] = {}

    def load_all(self) -> Dict[str, RegistryEntryModel]:
        """Load and validate all registry entries from disk."""
        self._entries_by_id.clear()
        self._entries_by_action_id.clear()
        self._entries_by_capability.clear()
        self._entries_by_system.clear()
        self._entries_by_domain.clear()
        self._entries_by_automation.clear()
        self._entries_by_entity.clear()

        if not os.path.exists(self.entries_dir):
            raise FileNotFoundError(f"Registry entries directory not found at: {self.entries_dir}")

        for fname in os.listdir(self.entries_dir):
            if fname.endswith(".yaml") or fname.endswith(".yml"):
                fpath = os.path.join(self.entries_dir, fname)
                entry = self._load_single_entry(fpath)
                if entry:
                    self._index_entry(entry)

        return self._entries_by_id

    def _load_single_entry(self, filepath: str) -> Optional[RegistryEntryModel]:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        raw = parse_yaml_string(content)
        self.validate_schema(raw, filepath)

        entrypoint = raw.get("execution_entrypoint", {})
        if isinstance(entrypoint, str):
            entrypoint = {"type": "internal_method", "ref": entrypoint}

        return RegistryEntryModel(
            registry_id=str(raw["registry_id"]),
            action_id=str(raw["action_id"]),
            display_name=str(raw.get("display_name", "")),
            description=str(raw.get("description", "")),
            owning_system=str(raw.get("owning_system", "")),
            owning_domain=str(raw.get("owning_domain", "")),
            business_capability=str(raw.get("business_capability", "")),
            entity_types=list(raw.get("entity_types", [])),
            execution_type=str(raw.get("execution_type", "http")),
            trigger_type=str(raw.get("trigger_type", "on_demand")),
            automation_level=str(raw.get("automation_level", "ASSISTED")),
            mutates_state=bool(raw.get("mutates_state", False)),
            reversible=bool(raw.get("reversible", False)),
            idempotent=bool(raw.get("idempotent", False)),
            fiscal=bool(raw.get("fiscal", False)),
            financial=bool(raw.get("financial", False)),
            destructive=bool(raw.get("destructive", False)),
            requires_human_approval=bool(raw.get("requires_human_approval", False)),
            required_permissions=list(raw.get("required_permissions", [])),
            execution_entrypoint=dict(entrypoint),
            inputs=list(raw.get("inputs", [])),
            outputs=list(raw.get("outputs", [])),
            emitted_events=list(raw.get("emitted_events", [])),
            consumed_events=list(raw.get("consumed_events", [])),
            dependencies=list(raw.get("dependencies", [])),
            external_integrations=list(raw.get("external_integrations", [])),
            related_playbooks=list(raw.get("related_playbooks", [])),
            related_operational_knowledge=list(raw.get("related_operational_knowledge", [])),
            monitoring_requirements=str(raw.get("monitoring_requirements", "")),
            audit_requirements=str(raw.get("audit_requirements", "")),
            confidence=str(raw.get("confidence", "alta")),
            provenance=dict(raw.get("provenance", {})),
            capability_category=str(raw.get("capability_category", "LOOKUP_SINGLE")),
            required_context=list(raw.get("required_context", [])),
            optional_context=list(raw.get("optional_context", [])),
            context_defaults=dict(raw.get("context_defaults", {})),
            collection_support=bool(raw.get("collection_support", False))
        )

    def validate_schema(self, raw: Dict[str, Any], filepath: str) -> None:
        """Validate required fields in registry entry."""
        required = ["registry_id", "action_id", "owning_system", "automation_level"]
        missing = [f for f in required if f not in raw]
        if missing:
            raise ValueError(f"Malformed registry entry at {filepath}: missing required fields {missing}")

    def _index_entry(self, entry: RegistryEntryModel) -> None:
        self._entries_by_id[entry.registry_id] = entry
        self._entries_by_action_id[entry.action_id] = entry

        cap_key = entry.business_capability.lower()
        self._entries_by_capability.setdefault(cap_key, []).append(entry)

        sys_key = entry.owning_system.lower()
        self._entries_by_system.setdefault(sys_key, []).append(entry)

        dom_key = entry.owning_domain.lower()
        self._entries_by_domain.setdefault(dom_key, []).append(entry)

        aut_key = entry.automation_level.upper()
        self._entries_by_automation.setdefault(aut_key, []).append(entry)

        for ent in entry.entity_types:
            self._entries_by_entity.setdefault(ent.lower(), []).append(entry)

    def get_by_id(self, registry_id: str) -> Optional[RegistryEntryModel]:
        return self._entries_by_id.get(registry_id)

    def get_by_action_id(self, action_id: str) -> Optional[RegistryEntryModel]:
        return self._entries_by_action_id.get(action_id)

    def get_by_capability(self, capability: str) -> List[RegistryEntryModel]:
        return self._entries_by_capability.get(capability.lower(), [])

    def get_by_system(self, system: str) -> List[RegistryEntryModel]:
        return self._entries_by_system.get(system.lower(), [])

    def get_by_domain(self, domain: str) -> List[RegistryEntryModel]:
        return self._entries_by_domain.get(domain.lower(), [])

    def get_by_automation_level(self, level: str) -> List[RegistryEntryModel]:
        return self._entries_by_automation.get(level.upper(), [])

    def get_by_entity(self, entity: str) -> List[RegistryEntryModel]:
        return self._entries_by_entity.get(entity.lower(), [])

    def list_all(self) -> List[RegistryEntryModel]:
        return list(self._entries_by_id.values())
