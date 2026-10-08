"""
Component 8: Human Approval Gateway
Intercepts execution of NEVER_AUTOMATE or human-gated Actions.
Creates and manages pending Approval Requests.
"""

import uuid
from typing import Dict, List, Optional
from app.runtime.models import CapabilityPlan, ApprovalRequest, UserContext


class ApprovalGateway:
    def __init__(self):
        self._pending_approvals: Dict[str, ApprovalRequest] = {}

    def intercept_if_required(self, plan: CapabilityPlan, user: UserContext) -> Optional[ApprovalRequest]:
        """Check if plan requires human approval and intercept if needed."""
        reg = plan.registry_entry

        if not plan.requires_approval:
            return None

        approval_id = f"appr-{uuid.uuid4().hex[:8]}"

        risk_level = "CRITICAL" if (reg.financial or reg.fiscal or not reg.reversible) else "HIGH"
        reason = f"Action '{reg.display_name}' ({reg.action_id}) has automation_level '{reg.automation_level}' and requires explicit human approval."

        appr = ApprovalRequest(
            approval_id=approval_id,
            plan_id=plan.plan_id,
            registry_id=reg.registry_id,
            action_id=reg.action_id,
            user_id=user.user_id,
            reason=reason,
            risk_level=risk_level,
            affected_entities=reg.entity_types,
            irreversible=not reg.reversible,
            status="PENDING",
            inputs=plan.resolved_inputs
        )

        self._pending_approvals[approval_id] = appr
        return appr

    def list_pending_approvals(self) -> List[ApprovalRequest]:
        return [a for a in self._pending_approvals.values() if a.status == "PENDING"]

    def get_approval(self, approval_id: str) -> Optional[ApprovalRequest]:
        return self._pending_approvals.get(approval_id)

    def approve(self, approval_id: str, approver_user_id: str) -> ApprovalRequest:
        appr = self._pending_approvals.get(approval_id)
        if not appr:
            raise KeyError(f"Approval request '{approval_id}' not found.")

        appr.status = "APPROVED"
        appr.decided_by = approver_user_id
        return appr

    def reject(self, approval_id: str, approver_user_id: str) -> ApprovalRequest:
        appr = self._pending_approvals.get(approval_id)
        if not appr:
            raise KeyError(f"Approval request '{approval_id}' not found.")

        appr.status = "REJECTED"
        appr.decided_by = approver_user_id
        return appr
