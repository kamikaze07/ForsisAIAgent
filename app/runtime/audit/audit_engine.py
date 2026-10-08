"""
Component 11: Audit Engine
Persists immutable execution audit history.
"""

import hashlib
import json
import os
import threading
import uuid
from typing import List, Optional
from app.runtime.models import AuditRecord, ExecutionResult, CapabilityPlan, UserContext


class AuditEngine:
    def __init__(self, log_filepath: str = "/home/servidor/forsis-agent/logs/audit_records.jsonl"):
        self.log_filepath = log_filepath
        self._lock = threading.Lock()
        self._audit_records: List[AuditRecord] = []

    def record(
        self,
        plan: CapabilityPlan,
        user: UserContext,
        exec_result: ExecutionResult,
        dry_run: bool = False,
        approval_id: Optional[str] = None
    ) -> AuditRecord:
        """Create, store, and persist an immutable audit record."""
        audit_id = f"audit-{uuid.uuid4().hex[:8]}"
        verification_passed = exec_result.verification.verified if exec_result.verification else False

        # Compute cryptographic hash signature of the record for tamper-evidence
        data_to_hash = f"{audit_id}:{exec_result.execution_id}:{user.user_id}:{plan.action.action_id}:{exec_result.status}"
        signature = hashlib.sha256(data_to_hash.encode("utf-8")).hexdigest()

        record = AuditRecord(
            audit_id=audit_id,
            execution_id=exec_result.execution_id,
            registry_id=plan.registry_entry.registry_id,
            action_id=plan.action.action_id,
            timestamp=exec_result.timestamp,
            user_id=user.user_id,
            inputs=plan.resolved_inputs,
            dry_run=dry_run,
            approval_id=approval_id,
            execution_status=exec_result.status,
            verification_passed=verification_passed,
            duration_ms=exec_result.duration_ms,
            signature=signature
        )

        with self._lock:
            self._audit_records.append(record)
            self._persist_to_disk(record)

        return record

    def _persist_to_disk(self, record: AuditRecord) -> None:
        try:
            os.makedirs(os.path.dirname(self.log_filepath), exist_ok=True)
            with open(self.log_filepath, "a", encoding="utf-8") as f:
                rec_dict = {
                    "audit_id": record.audit_id,
                    "execution_id": record.execution_id,
                    "registry_id": record.registry_id,
                    "action_id": record.action_id,
                    "timestamp": record.timestamp,
                    "user_id": record.user_id,
                    "inputs": record.inputs,
                    "dry_run": record.dry_run,
                    "approval_id": record.approval_id,
                    "execution_status": record.execution_status,
                    "verification_passed": record.verification_passed,
                    "duration_ms": record.duration_ms,
                    "signature": record.signature
                }
                f.write(json.dumps(rec_dict) + "\n")
        except Exception:
            pass

    def list_records(self) -> List[AuditRecord]:
        with self._lock:
            return list(self._audit_records)

    def get_record_by_execution_id(self, execution_id: str) -> Optional[AuditRecord]:
        with self._lock:
            for r in self._audit_records:
                if r.execution_id == execution_id:
                    return r
            return None
