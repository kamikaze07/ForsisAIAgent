from typing import Any, Dict, List, Optional
import re
from app.contracts import CapabilityCall, ExecutionPlan, Task, TaskStatus
from .base import LLMProvider

class MockProvider(LLMProvider):
    def generate_plan(
        self,
        system_prompt: str,
        user_prompt: str,
        context: Optional[Dict[str, Any]] = None,
        capabilities: Optional[List[Dict[str, Any]]] = None,
        workflows: Optional[List[Dict[str, Any]]] = None,
        options: Optional[Dict[str, Any]] = None
    ) -> ExecutionPlan:
        
        prompt_lower = user_prompt.lower()

        if "error" in prompt_lower:
            raise Exception("MockProvider error simulation")

        if "hora" in prompt_lower:
            return ExecutionPlan(
                plan_id="plan-mock-1",
                tasks=[
                    Task(
                        task_id="task-1",
                        description="Obtener la hora actual",
                        status=TaskStatus.PENDING,
                        capability_call=CapabilityCall(
                            capability_name="hora_actual",
                            parameters={}
                        )
                    )
                ]
            )

        elif "suma" in prompt_lower or "+" in prompt_lower:
            numbers = re.findall(r'\d+', prompt_lower)
            a = int(numbers[0]) if len(numbers) > 0 else 25
            b = int(numbers[1]) if len(numbers) > 1 else 13
            return ExecutionPlan(
                plan_id="plan-mock-2",
                tasks=[
                    Task(
                        task_id="task-2",
                        description="Sumar dos números",
                        status=TaskStatus.PENDING,
                        capability_call=CapabilityCall(
                            capability_name="sumar",
                            parameters={"a": a, "b": b}
                        )
                    )
                ]
            )
            
        elif "versión" in prompt_lower or "version" in prompt_lower:
            return ExecutionPlan(
                plan_id="plan-mock-version",
                tasks=[
                    Task(
                        task_id="task-version",
                        description="Obtener versión",
                        status=TaskStatus.PENDING,
                        capability_call=CapabilityCall(
                            capability_name="version",
                            parameters={}
                        )
                    )
                ]
            )

        return ExecutionPlan(
            plan_id="plan-mock-empty",
            tasks=[]
        )

    def generate_text(
        self,
        system_prompt: str,
        user_prompt: str,
        options: Optional[Dict[str, Any]] = None
    ) -> str:
        # Determinista para tests: no redacta con IA, solo confirma que fue llamado.
        return f"[mock-response] {user_prompt}"
