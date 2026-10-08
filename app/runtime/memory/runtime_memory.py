"""
Component 12: Runtime Memory
Maintains operational runtime state (recent executions, active workflows, failed executions, retry history).
Distinct from conversational memory.
"""

import threading
from typing import List, Dict, Any
from app.runtime.models import ExecutionResult, ApprovalRequest


class RuntimeMemory:
    def __init__(self, max_history: int = 100):
        self.max_history = max_history
        self._lock = threading.Lock()
        self._recent_executions: List[ExecutionResult] = []
        self._failed_executions: List[ExecutionResult] = []
        self._active_workflows: Dict[str, Dict[str, Any]] = {}
        self._retry_history: Dict[str, int] = {}

    def track_execution(self, result: ExecutionResult) -> None:
        with self._lock:
            self._recent_executions.insert(0, result)
            if len(self._recent_executions) > self.max_history:
                self._recent_executions.pop()

            if result.status == "FAILED":
                self._failed_executions.insert(0, result)
                self._retry_history[result.action_id] = self._retry_history.get(result.action_id, 0) + 1

    def get_recent_executions(self, limit: int = 10) -> List[ExecutionResult]:
        with self._lock:
            return list(self._recent_executions[:limit])

    def get_failed_executions(self) -> List[ExecutionResult]:
        with self._lock:
            return list(self._failed_executions)

    def get_retry_count(self, action_id: str) -> int:
        with self._lock:
            return self._retry_history.get(action_id, 0)
