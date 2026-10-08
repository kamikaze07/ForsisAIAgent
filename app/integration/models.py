"""
Data models and contracts for the Forsis Integration Layer.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional
from datetime import datetime, timezone


@dataclass
class ProviderMetadata:
    provider_id: str
    name: str
    system_type: str
    version: str
    description: str
    base_url_or_ref: str
    supported_actions: List[str]
    capabilities: List[str]


@dataclass
class ProviderHealthStatus:
    provider_id: str
    available: bool
    latency_ms: float
    last_execution_at: Optional[str]
    last_failure_at: Optional[str]
    authenticated: bool
    version: str
    error_message: Optional[str] = None
    checked_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class ExecutionTraceRecord:
    trace_id: str
    provider_id: str
    action_id: str
    request_id: str
    execution_id: str
    start_time: str
    duration_ms: float
    status: str  # SUCCESS, FAILED, TIMEOUT, CIRCUIT_BROKEN
    verification_result: bool
    errors: List[str]
    retry_history: List[Dict[str, Any]]
    metadata: Dict[str, Any]


@dataclass
class ProviderMetrics:
    provider_id: str
    total_executions: int
    successful_executions: int
    failed_executions: int
    circuit_breaker_state: str  # CLOSED, OPEN, HALF_OPEN
    average_latency_ms: float
    last_error: Optional[str] = None


@dataclass
class SystemStatusReport:
    total_providers: int
    healthy_providers: int
    unhealthy_providers: int
    registered_providers: List[str]
    system_health_ratio: float
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
