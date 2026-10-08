"""
Component 9: Executor Engine
Dispatches execution based on registry and action execution_type using pluggable adapters.
"""

import time
import uuid
from typing import Dict, Any
from app.runtime.models import CapabilityPlan, ExecutionResult
from app.runtime.execution.adapters import (
    ExecutionAdapter, HttpExecutionAdapter, WorkflowExecutionAdapter,
    CliExecutionAdapter, ManualExecutionAdapter
)


class Executor:
    def __init__(self):
        self._adapters: Dict[str, ExecutionAdapter] = {
            "http": HttpExecutionAdapter(),
            "workflow": WorkflowExecutionAdapter(),
            "cli": CliExecutionAdapter(),
            "manual": ManualExecutionAdapter()
        }

    def register_adapter(self, execution_type: str, adapter: ExecutionAdapter) -> None:
        self._adapters[execution_type.lower()] = adapter

    def execute(self, plan: CapabilityPlan) -> ExecutionResult:
        """Execute capability plan using matched adapter."""
        if not plan.is_executable:
            return ExecutionResult(
                execution_id=f"exec-{uuid.uuid4().hex[:8]}",
                plan_id=plan.plan_id,
                registry_id=plan.registry_entry.registry_id,
                action_id=plan.action.action_id,
                status="DENIED",
                outputs={},
                verification=None,
                error_message=plan.rejection_reason or "Execution denied."
            )

        exec_type = plan.action.execution_type.lower()
        adapter = self._adapters.get(exec_type, self._adapters["http"])

        start_time = time.time()
        try:
            raw_output = adapter.execute(plan)
            duration = (time.time() - start_time) * 1000.0

            return ExecutionResult(
                execution_id=f"exec-{uuid.uuid4().hex[:8]}",
                plan_id=plan.plan_id,
                registry_id=plan.registry_entry.registry_id,
                action_id=plan.action.action_id,
                status="SUCCESS",
                outputs=raw_output,
                verification=None,
                duration_ms=duration
            )
        except Exception as ex:
            duration = (time.time() - start_time) * 1000.0
            return ExecutionResult(
                execution_id=f"exec-{uuid.uuid4().hex[:8]}",
                plan_id=plan.plan_id,
                registry_id=plan.registry_entry.registry_id,
                action_id=plan.action.action_id,
                status="FAILED",
                outputs={},
                verification=None,
                error_message=str(ex),
                duration_ms=duration
            )
