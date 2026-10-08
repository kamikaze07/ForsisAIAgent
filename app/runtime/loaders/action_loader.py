"""
Component 2: Action Loader
Loads Operational Actions from operational-actions/ and builds executable capability definitions.
Cross-validates against RegistryLoader.
"""

import os
from typing import Dict, List, Optional
from app.runtime.models import ActionModel, RegistryEntryModel
from app.runtime.loaders.yaml_loader import parse_yaml_string


class ActionLoader:
    def __init__(self, actions_dir: str = "/home/servidor/forsis-agent/operational-actions"):
        self.actions_dir = actions_dir
        self._actions_by_id: Dict[str, ActionModel] = {}
        self._actions_by_slug: Dict[str, ActionModel] = {}

    def load_all(self, registry_entries: Optional[Dict[str, RegistryEntryModel]] = None) -> Dict[str, ActionModel]:
        """Load and validate all actions from operational-actions/."""
        self._actions_by_id.clear()
        self._actions_by_slug.clear()

        if not os.path.exists(self.actions_dir):
            raise FileNotFoundError(f"Actions directory not found at: {self.actions_dir}")

        for fname in os.listdir(self.actions_dir):
            action_folder = os.path.join(self.actions_dir, fname)
            if os.path.isdir(action_folder) and not fname.startswith("_") and not fname.startswith("."):
                action_yaml_path = os.path.join(action_folder, "action.yaml")
                if os.path.exists(action_yaml_path):
                    action = self._load_action_folder(fname, action_folder)
                    if action:
                        self._actions_by_id[action.action_id] = action
                        self._actions_by_slug[action.slug] = action

        if registry_entries:
            self.cross_validate_with_registry(registry_entries)

        return self._actions_by_id

    def _load_action_folder(self, slug: str, folder_path: str) -> Optional[ActionModel]:
        action_yaml_path = os.path.join(folder_path, "action.yaml")
        with open(action_yaml_path, "r", encoding="utf-8") as f:
            raw = parse_yaml_string(f.read())

        entrypoint = raw.get("entrypoint", {})
        if isinstance(entrypoint, dict):
            ep_type = str(entrypoint.get("type", "http"))
            ep_ref = str(entrypoint.get("ref", ""))
        elif isinstance(entrypoint, list) and len(entrypoint) > 0:
            ep_type = "internal_method"
            ep_ref = str(entrypoint[0])
        else:
            ep_type = "http"
            ep_ref = str(entrypoint) if entrypoint else ""

        retry_sem = raw.get("retry_semantics", {})
        idempotent = bool(retry_sem.get("idempotent", False)) if isinstance(retry_sem, dict) else False

        # Read auxiliary markdown files if present
        inputs_md = self._read_file_if_exists(os.path.join(folder_path, "inputs.md"))
        execution_md = self._read_file_if_exists(os.path.join(folder_path, "execution.md"))
        verification_md = self._read_file_if_exists(os.path.join(folder_path, "verification.md"))
        rollback_md = self._read_file_if_exists(os.path.join(folder_path, "rollback.md"))
        examples_md = self._read_file_if_exists(os.path.join(folder_path, "examples.md"))

        # Extract required and optional input names
        req_inputs = []
        for inp in raw.get("required_inputs", []):
            val = inp.get("name", "") if isinstance(inp, dict) else str(inp)
            if "name:" in val:
                val = val.split("name:", 1)[1].split("\n")[0].replace('"', '').replace("'", "").strip()
            val = val.strip("{}'\" ")
            if val and not val.startswith("type:") and val not in ["type", "string", "int", "boolean"]:
                req_inputs.append(val)

        opt_inputs = []
        for inp in raw.get("optional_inputs", []):
            val = inp.get("name", "") if isinstance(inp, dict) else str(inp)
            if "name:" in val:
                val = val.split("name:", 1)[1].split("\n")[0].replace('"', '').replace("'", "").strip()
            val = val.strip("{}'\" ")
            if val and not val.startswith("type:") and val not in ["type", "string", "int", "boolean"]:
                opt_inputs.append(val)

        outputs = []
        for out in raw.get("outputs", []):
            if isinstance(out, dict):
                outputs.append(out.get("name", ""))
            else:
                outputs.append(str(out))

        return ActionModel(
            action_id=str(raw["id"]),
            slug=slug,
            name=str(raw.get("name", slug)),
            description=str(raw.get("description", "")),
            system=str(raw.get("system", "")),
            entrypoint_type=ep_type,
            entrypoint_ref=ep_ref,
            execution_type=str(raw.get("execution_type", "http")),
            trigger=str(raw.get("trigger", "on_demand")),
            mutates_state=bool(raw.get("mutates_state", False)),
            reversible=bool(raw.get("reversible", False)),
            idempotent=idempotent,
            required_permissions=list(raw.get("required_permissions", [])),
            required_inputs=req_inputs,
            optional_inputs=opt_inputs,
            outputs=outputs,
            verification_type=str(raw.get("verification_type", "automatic_conservative")),
            verification_ref=str(raw.get("verification_ref", "self")),
            depends_on_actions=list(raw.get("depends_on_actions", [])),
            used_by_playbooks=list(raw.get("used_by_playbooks", [])),
            related_operational_knowledge=list(raw.get("related_operational_knowledge", [])),
            automation_level=str(raw.get("automation_level", "ASSISTED")),
            confidence=str(raw.get("confidence", "alta")),
            status=str(raw.get("status", "validated")),
            capability_category=str(raw.get("capability_category", "LOOKUP_SINGLE")),
            required_context=list(raw.get("required_context", [])),
            optional_context=list(raw.get("optional_context", [])),
            context_defaults=dict(raw.get("context_defaults", {})),
            collection_support=bool(raw.get("collection_support", False)),
            inputs_md_content=inputs_md,
            execution_md_content=execution_md,
            verification_md_content=verification_md,
            rollback_md_content=rollback_md,
            examples_md_content=examples_md
        )

    def _read_file_if_exists(self, filepath: str) -> str:
        if os.path.exists(filepath):
            with open(filepath, "r", encoding="utf-8") as f:
                return f.read()
        return ""

    def cross_validate_with_registry(self, registry_entries: Dict[str, RegistryEntryModel]) -> List[str]:
        """Cross-validate actions against registry entries."""
        warnings = []
        for action_id, action in self._actions_by_id.items():
            matching_reg = None
            for reg in registry_entries.values():
                if reg.action_id == action_id:
                    matching_reg = reg
                    break

            if not matching_reg:
                msg = f"Orphan Action found: {action_id} has no matching Registry entry."
                warnings.append(msg)
                continue

            if action.automation_level != matching_reg.automation_level:
                warnings.append(
                    f"Mismatch in automation level for {action_id}: "
                    f"Action={action.automation_level} vs Registry={matching_reg.automation_level}"
                )

        return warnings

    def get_by_id(self, action_id: str) -> Optional[ActionModel]:
        return self._actions_by_id.get(action_id)

    def get_by_slug(self, slug: str) -> Optional[ActionModel]:
        return self._actions_by_slug.get(slug)

    def list_all(self) -> List[ActionModel]:
        return list(self._actions_by_id.values())
