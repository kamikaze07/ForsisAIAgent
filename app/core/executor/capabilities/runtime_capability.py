"""
Runtime Capability Adapter for integrating Operational Runtime actions into the Executor.
"""

from typing import Any, Dict
from app.contracts import CapabilityDefinition
from app.core.executor.capability import Capability
from app.runtime.api.runtime_api import ForsisOperationalRuntime, UserContext


class RuntimeCapabilityAdapter(Capability):
    """
    Generic Capability implementation that delegates execution to the ForsisOperationalRuntime.
    """
    def __init__(self, action_id: str, runtime: ForsisOperationalRuntime):
        self.action_id = action_id
        self.runtime = runtime

    def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        user = UserContext(user_id="agent-executor", username="agent", roles=["SUPER USUARIO"])
        
        # Determine capability slug or ID
        cap_query = self.action_id.replace("action-", "")
        plan = self.runtime.plan_execution(user, cap_query, parameters)
        
        if not plan.is_executable:
            return {
                "status": "denied",
                "error": plan.rejection_reason or "Execution denied by runtime security policy."
            }

        result = self.runtime.execute(plan, user)
        
        if result.status == "APPROVAL_PENDING":
            return {
                "status": "approval_pending",
                "approval_id": result.outputs.get("approval_id"),
                "reason": result.outputs.get("reason"),
                "message": "Operación de mutación interceptada por el Gateway de Aprobación Humana. Requiere autorización explícita."
            }

        return {
            "status": result.status.lower(),
            "outputs": result.outputs,
            "verification": result.verification.verified if result.verification else True,
            "duration_ms": result.duration_ms
        }
