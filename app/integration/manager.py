"""
IntegrationManager: High-level orchestration facade for the Forsis Integration Layer.
Exposes ListProviders(), ProviderHealth(), ProviderCapabilities(), ProviderMetrics(), RuntimeStatus().
Handles execution dispatch with resilience, circuit breaker, metrics, and tracing.
"""

import time
import uuid
from typing import Dict, List, Any, Optional
from app.integration.models import (
    ProviderMetadata, ProviderHealthStatus, ProviderMetrics,
    SystemStatusReport, ExecutionTraceRecord
)
from app.integration.registry import ProviderRegistry
from app.integration.providers import auto_register_all_providers
from app.integration.resilience import ResilienceHandler, CircuitBreaker
from app.integration.tracing import ExecutionTracer


class IntegrationManager:
    def __init__(self, registry: Optional[ProviderRegistry] = None):
        self.registry = registry or ProviderRegistry()
        auto_register_all_providers(self.registry)
        self.tracer = ExecutionTracer()
        self._circuit_breakers: Dict[str, CircuitBreaker] = {}
        for p in self.registry.list_providers():
            pid = p.metadata().provider_id
            self._circuit_breakers[pid] = CircuitBreaker()

    def list_providers(self) -> List[ProviderMetadata]:
        return [p.metadata() for p in self.registry.list_providers()]

    def provider_health(self, provider_id: Optional[str] = None) -> List[ProviderHealthStatus]:
        if provider_id:
            p = self.registry.get_provider(provider_id)
            return [p.health()] if p else []
        return [p.health() for p in self.registry.list_providers()]

    def provider_capabilities(self, provider_id: Optional[str] = None) -> Dict[str, List[str]]:
        result = {}
        if provider_id:
            p = self.registry.get_provider(provider_id)
            if p:
                result[provider_id] = p.supported_actions()
        else:
            for p in self.registry.list_providers():
                result[p.metadata().provider_id] = p.supported_actions()
        return result

    def provider_metrics(self, provider_id: Optional[str] = None) -> List[ProviderMetrics]:
        if provider_id:
            m = self.registry.get_metrics(provider_id)
            return [m] if m else []
        return [self.registry.get_metrics(p.metadata().provider_id) for p in self.registry.list_providers() if self.registry.get_metrics(p.metadata().provider_id)]

    def runtime_status(self) -> SystemStatusReport:
        all_providers = self.registry.list_providers()
        total = len(all_providers)
        healthy = 0
        pids = []
        for p in all_providers:
            pids.append(p.metadata().provider_id)
            if p.health().available:
                healthy += 1
        unhealthy = total - healthy
        ratio = (healthy / total * 100.0) if total > 0 else 0.0

        return SystemStatusReport(
            total_providers=total,
            healthy_providers=healthy,
            unhealthy_providers=unhealthy,
            registered_providers=pids,
            system_health_ratio=ratio
        )

    def execute_action(self, action_id: str, parameters: Dict[str, Any], request_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Negotiate provider, apply resilience, execute, verify, record metrics, and log trace.
        """
        request_id = request_id or f"req-{uuid.uuid4().hex[:8]}"
        execution_id = f"exec-{uuid.uuid4().hex[:8]}"

        # 1. Dynamic Capability Negotiation
        provider = self.registry.negotiate_provider_for_action(action_id)
        if not provider:
            err_msg = f"No healthy Provider found supporting capability/action '{action_id}'."
            self.tracer.record_trace(
                provider_id="UNRESOLVED",
                action_id=action_id,
                request_id=request_id,
                execution_id=execution_id,
                duration_ms=0.0,
                status="FAILED",
                verification_result=False,
                errors=[err_msg],
                retry_history=[]
            )
            return {"status": "error", "error": err_msg}

        pid = provider.metadata().provider_id
        cb = self._circuit_breakers.get(pid, CircuitBreaker())
        resilience = ResilienceHandler(max_retries=2, retry_delay_s=0.05, timeout_s=5.0, circuit_breaker=cb)

        # Fallback function for graceful degradation
        def fallback():
            return {
                "status": "degraded",
                "provider": pid,
                "action": action_id,
                "message": f"System '{pid}' unavailable. Graceful degradation response generated."
            }

        t_start = time.time()
        res_result = resilience.execute_with_resilience(
            func=lambda: provider.execute(action_id, parameters),
            fallback_func=fallback
        )
        duration_ms = (time.time() - t_start) * 1000.0

        if not res_result.success:
            self.registry.record_execution_metric(pid, success=False, latency_ms=duration_ms, error=res_result.error)
            self.tracer.record_trace(
                provider_id=pid,
                action_id=action_id,
                request_id=request_id,
                execution_id=execution_id,
                duration_ms=duration_ms,
                status="FAILED",
                verification_result=False,
                errors=[res_result.error or "Execution failed"],
                retry_history=res_result.retries
            )
            return {"status": "failed", "error": res_result.error}

        output = res_result.data
        verified = provider.verify(action_id, output)

        self.registry.record_execution_metric(pid, success=True, latency_ms=duration_ms)
        self.tracer.record_trace(
            provider_id=pid,
            action_id=action_id,
            request_id=request_id,
            execution_id=execution_id,
            duration_ms=duration_ms,
            status="DEGRADED" if output.get("_degraded") else "SUCCESS",
            verification_result=verified,
            errors=[res_result.error] if res_result.error else [],
            retry_history=res_result.retries,
            metadata={"degraded": output.get("_degraded", False)}
        )

        return output
