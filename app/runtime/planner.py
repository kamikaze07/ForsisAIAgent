"""
Component 5: Deterministic Planner
Resolves user request into a CapabilityPlan using Registry metadata and Action contracts.
"""

import uuid
import re
from typing import Dict, Any, Optional
from app.runtime.models import (
    UserContext, CapabilityPlan, RegistryEntryModel, ActionModel, PlaybookModel
)
from app.runtime.loaders.registry_loader import RegistryLoader
from app.runtime.loaders.action_loader import ActionLoader
from app.runtime.loaders.playbook_loader import PlaybookLoader
from app.runtime.security.permission_engine import PermissionEngine


class Planner:
    def __init__(
        self,
        registry_loader: RegistryLoader,
        action_loader: ActionLoader,
        playbook_loader: PlaybookLoader,
        permission_engine: PermissionEngine
    ):
        self.registry_loader = registry_loader
        self.action_loader = action_loader
        self.playbook_loader = playbook_loader
        self.permission_engine = permission_engine

    def plan(
        self,
        user: UserContext,
        intent_query: str,
        provided_inputs: Optional[Dict[str, Any]] = None
    ) -> CapabilityPlan:
        """Determine registry entry, action, and playbook from user request."""
        provided_inputs = provided_inputs or {}
        query_clean = intent_query.strip()

        # 1. Resolve matching Registry Entry
        registry_entry = self._resolve_registry_entry(query_clean)
        if not registry_entry:
            raise ValueError(f"Could not resolve any registered capability for query: '{intent_query}'")

        # 2. Resolve matching Action
        action = self.action_loader.get_by_id(registry_entry.action_id)
        if not action:
            raise ValueError(f"Action '{registry_entry.action_id}' not found for registry entry '{registry_entry.registry_id}'")

        # 3. Resolve matching Playbook (if any)
        playbook = None
        if registry_entry.related_playbooks:
            pb_slug = registry_entry.related_playbooks[0]
            playbook = self.playbook_loader.get_by_slug(pb_slug) or self.playbook_loader.get_by_id(f"pb-{pb_slug}")

        # 4. Evaluate Permissions
        allowed, missing, explanation = self.permission_engine.evaluate(
            user, registry_entry.required_permissions
        )

        requires_approval = (
            registry_entry.automation_level == "NEVER_AUTOMATE"
            or registry_entry.requires_human_approval
        )

        plan_id = f"plan-{uuid.uuid4().hex[:8]}"

        return CapabilityPlan(
            plan_id=plan_id,
            user_request=intent_query,
            registry_entry=registry_entry,
            action=action,
            playbook=playbook,
            resolved_inputs=provided_inputs,
            required_permissions=registry_entry.required_permissions,
            automation_level=registry_entry.automation_level,
            requires_approval=requires_approval,
            is_executable=allowed,
            rejection_reason=None if allowed else explanation
        )

    def _resolve_registry_entry(self, query: str) -> Optional[RegistryEntryModel]:
        query_lower = query.lower()

        # Exact ID match
        direct_reg = self.registry_loader.get_by_id(query) or self.registry_loader.get_by_action_id(query)
        if direct_reg:
            return direct_reg

        # Direct slug match (e.g., "generate-guide", "emit-cfdi")
        action_match = self.action_loader.get_by_slug(query_lower)
        if action_match:
            return self.registry_loader.get_by_action_id(action_match.action_id)

        # Keyword matching across all registry entries
        all_entries = self.registry_loader.list_all()
        best_match = None
        best_score = 0

        for reg in all_entries:
            score = 0
            target_text = f"{reg.registry_id} {reg.action_id} {reg.display_name} {reg.description} {reg.business_capability}".lower()

            words = re.findall(r"\w{3,}", query_lower)
            for w in words:
                if w in target_text:
                    score += 1

            if score > best_score:
                best_score = score
                best_match = reg

        if best_score > 0:
            return best_match

        # Fallback to first capability as default if ambiguous
        return all_entries[0] if all_entries else None
