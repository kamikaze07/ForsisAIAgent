"""
Component 14: Runtime Startup Validator
Verifies architecture integrity on startup across Registry, Actions, Playbooks, Knowledge.
Fails startup if integrity is compromised.
"""

from typing import List
from app.runtime.loaders.registry_loader import RegistryLoader
from app.runtime.loaders.action_loader import ActionLoader
from app.runtime.loaders.playbook_loader import PlaybookLoader
from app.runtime.loaders.knowledge_loader import KnowledgeLoader


class StartupValidationError(Exception):
    """Raised when architecture startup validation fails."""
    pass


class StartupValidator:
    def __init__(
        self,
        registry_loader: RegistryLoader,
        action_loader: ActionLoader,
        playbook_loader: PlaybookLoader,
        knowledge_loader: KnowledgeLoader
    ):
        self.registry_loader = registry_loader
        self.action_loader = action_loader
        self.playbook_loader = playbook_loader
        self.knowledge_loader = knowledge_loader

    def validate(self) -> List[str]:
        """Perform comprehensive startup integrity checks."""
        errors: List[str] = []

        registry_entries = self.registry_loader.load_all()
        actions = self.action_loader.load_all(registry_entries)
        playbooks = self.playbook_loader.load_all()
        knowledge = self.knowledge_loader.load_all()

        # 1. Verify 1:1 Action <-> Registry Mapping
        for reg_id, reg in registry_entries.items():
            if reg.action_id not in actions:
                errors.append(f"Registry entry {reg_id} references non-existent Action {reg.action_id}")

        for act_id, act in actions.items():
            reg = self.registry_loader.get_by_action_id(act_id)
            if not reg:
                errors.append(f"Action {act_id} has no corresponding Registry Entry")

        # 2. Verify Action Dependencies
        for act_id, act in actions.items():
            for dep in act.depends_on_actions:
                if dep not in actions:
                    errors.append(f"Action {act_id} references missing dependency action {dep}")

        # 3. Verify Playbook Cross-References
        for act_id, act in actions.items():
            for pb_slug in act.used_by_playbooks:
                pb_id = f"pb-{pb_slug}"
                if pb_id not in playbooks and pb_slug not in playbooks:
                    errors.append(f"Action {act_id} references non-existent Playbook {pb_slug}")

        # 4. Verify Enums & Permissions
        valid_automation_levels = {
            "READ_ONLY", "MANUAL", "ASSISTED", "SEMI_AUTOMATED", "FULLY_AUTOMATED", "NEVER_AUTOMATE"
        }
        for reg_id, reg in registry_entries.items():
            if reg.automation_level not in valid_automation_levels:
                errors.append(f"Registry entry {reg_id} has invalid automation_level {reg.automation_level}")

        if errors:
            error_msg = f"Startup architecture validation failed with {len(errors)} errors:\n" + "\n".join(f"- {e}" for e in errors)
            raise StartupValidationError(error_msg)

        return [f"Architecture integrity verified: {len(registry_entries)} registry entries, {len(actions)} actions, {len(playbooks)} playbooks, {len(knowledge)} OKB docs."]
