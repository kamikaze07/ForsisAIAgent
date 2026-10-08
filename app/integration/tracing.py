"""
Execution Tracing Engine for Integration Layer.
Tracks provider executions, latencies, errors, and verification results.
"""

import uuid
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from app.integration.models import ExecutionTraceRecord


class ExecutionTracer:
    def __init__(self):
        self._traces: List[ExecutionTraceRecord] = []

    def record_trace(
        self,
        provider_id: str,
        action_id: str,
        request_id: str,
        execution_id: str,
        duration_ms: float,
        status: str,
        verification_result: bool,
        errors: List[str],
        retry_history: List[Dict[str, Any]],
        metadata: Optional[Dict[str, Any]] = None
    ) -> ExecutionTraceRecord:
        trace_id = f"trace-{uuid.uuid4().hex[:8]}"
        record = ExecutionTraceRecord(
            trace_id=trace_id,
            provider_id=provider_id,
            action_id=action_id,
            request_id=request_id,
            execution_id=execution_id,
            start_time=datetime.now(timezone.utc).isoformat(),
            duration_ms=duration_ms,
            status=status,
            verification_result=verification_result,
            errors=errors,
            retry_history=retry_history,
            metadata=metadata or {}
        )
        self._traces.append(record)
        return record

    def list_traces(self, provider_id: Optional[str] = None) -> List[ExecutionTraceRecord]:
        if provider_id:
            return [t for t in self._traces if t.provider_id == provider_id]
        return list(self._traces)

    def get_traces_by_action(self, action_id: str) -> List[ExecutionTraceRecord]:
        return [t for t in self._traces if t.action_id == action_id]
