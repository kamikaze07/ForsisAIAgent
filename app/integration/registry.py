"""
Provider Registry for self-registration, discovery, and dynamic capability negotiation.
"""

import threading
from typing import Dict, List, Optional, Type
from app.integration.provider import BaseProvider
from app.integration.models import ProviderMetadata, ProviderHealthStatus, ProviderMetrics


class ProviderRegistry:
    """
    Central registry for integration providers.
    Supports self-registration and dynamic capability negotiation without hardcoded routing.
    """
    def __init__(self):
        self._lock = threading.Lock()
        self._providers: Dict[str, BaseProvider] = {}
        self._metrics: Dict[str, ProviderMetrics] = {}

    def register(self, provider: BaseProvider) -> None:
        """Register a provider instance dynamically."""
        with self._lock:
            meta = provider.metadata()
            pid = meta.provider_id
            self._providers[pid] = provider

            if pid not in self._metrics:
                self._metrics[pid] = ProviderMetrics(
                    provider_id=pid,
                    total_executions=0,
                    successful_executions=0,
                    failed_executions=0,
                    circuit_breaker_state="CLOSED",
                    average_latency_ms=0.0
                )

    def get_provider(self, provider_id: str) -> Optional[BaseProvider]:
        with self._lock:
            return self._providers.get(provider_id)

    def list_providers(self) -> List[BaseProvider]:
        with self._lock:
            return list(self._providers.values())

    def negotiate_provider_for_action(self, action_id: str) -> Optional[BaseProvider]:
        """
        Dynamic capability negotiation:
        Finds which registered provider can execute action_id without hardcoded routing.
        """
        # Strip action- prefix if needed
        clean_action = action_id.replace("action-", "")

        for provider in self._providers.values():
            supported = provider.supported_actions()
            if action_id in supported or clean_action in supported or f"action-{clean_action}" in supported:
                # Check health before returning
                h = provider.health()
                if h.available:
                    return provider
                # If unavailable, continue searching for secondary provider

        # Fallback search matching system type or substring
        for provider in self._providers.values():
            for supp in provider.supported_actions():
                if clean_action in supp or supp in clean_action:
                    return provider

        return None

    def get_metrics(self, provider_id: str) -> Optional[ProviderMetrics]:
        return self._metrics.get(provider_id)

    def record_execution_metric(self, provider_id: str, success: bool, latency_ms: float, error: Optional[str] = None) -> None:
        m = self._metrics.get(provider_id)
        if m:
            m.total_executions += 1
            if success:
                m.successful_executions += 1
            else:
                m.failed_executions += 1
                m.last_error = error

            # Exponential moving average for latency
            if m.average_latency_ms == 0.0:
                m.average_latency_ms = latency_ms
            else:
                m.average_latency_ms = (m.average_latency_ms * 0.8) + (latency_ms * 0.2)
