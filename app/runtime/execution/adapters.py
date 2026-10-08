"""
Component 9: Pluggable Execution Adapters
Handles execution dispatch for HTTP, Workflow, CLI, and Manual execution models.
"""

import time
from abc import ABC, abstractmethod
from typing import Dict, Any
from app.runtime.models import CapabilityPlan


class ExecutionAdapter(ABC):
    @abstractmethod
    def execute(self, plan: CapabilityPlan) -> Dict[str, Any]:
        pass


class HttpExecutionAdapter(ExecutionAdapter):
    def __init__(self, integration_manager=None):
        self.integration_manager = integration_manager

    def execute(self, plan: CapabilityPlan) -> Dict[str, Any]:
        act = plan.action
        ref = act.entrypoint_ref
        
        if self.integration_manager:
            res = self.integration_manager.execute_action(act.action_id, plan.resolved_inputs)
            if res.get("status") != "error":
                return res

        return {
            "status": "success",
            "execution_type": "http",
            "entrypoint": ref,
            "system": act.system,
            "payload_received": plan.resolved_inputs,
            "simulated_response": {out: f"value_for_{out}" for out in act.outputs}
        }


class WorkflowExecutionAdapter(ExecutionAdapter):
    def execute(self, plan: CapabilityPlan) -> Dict[str, Any]:
        act = plan.action
        ref = act.entrypoint_ref
        return {
            "status": "success",
            "execution_type": "workflow",
            "entrypoint": ref,
            "system": act.system,
            "trigger": act.trigger,
            "simulated_workflow_output": {out: f"workflow_out_{out}" for out in act.outputs}
        }


class CliExecutionAdapter(ExecutionAdapter):
    def execute(self, plan: CapabilityPlan) -> Dict[str, Any]:
        act = plan.action
        ref = act.entrypoint_ref
        return {
            "status": "success",
            "execution_type": "cli",
            "script": ref,
            "system": act.system,
            "exit_code": 0,
            "simulated_cli_output": {out: f"cli_val_{out}" for out in act.outputs}
        }


class ManualExecutionAdapter(ExecutionAdapter):
    def execute(self, plan: CapabilityPlan) -> Dict[str, Any]:
        act = plan.action
        return {
            "status": "manual_procedure_recorded",
            "execution_type": "manual",
            "entrypoint": act.entrypoint_ref,
            "instructions": f"Manual procedure '{act.name}' acknowledged by operator.",
            "simulated_manual_output": {out: f"manual_val_{out}" for out in act.outputs}
        }
