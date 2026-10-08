"""
Forsis Integration Layer Package
Exposes standardized Provider abstraction, discovery, negotiation, health monitoring, resilience, and tracing.
"""

from app.integration.models import (
    ProviderMetadata, ProviderHealthStatus, ProviderMetrics,
    SystemStatusReport, ExecutionTraceRecord
)
from app.integration.provider import BaseProvider
from app.integration.registry import ProviderRegistry
from app.integration.resilience import ResilienceHandler, CircuitBreaker, CircuitBreakerOpenException
from app.integration.tracing import ExecutionTracer
from app.integration.manager import IntegrationManager
from app.integration.providers import (
    TraficoSystemProvider, LiquidacionesSystemProvider, AtlasProvider,
    ForsisAgentInternalProvider, MattermostProvider, BanxicoProvider,
    MercurioProvider, auto_register_all_providers
)

__all__ = [
    "BaseProvider",
    "ProviderRegistry",
    "ResilienceHandler",
    "CircuitBreaker",
    "CircuitBreakerOpenException",
    "ExecutionTracer",
    "IntegrationManager",
    "ProviderMetadata",
    "ProviderHealthStatus",
    "ProviderMetrics",
    "SystemStatusReport",
    "ExecutionTraceRecord",
    "TraficoSystemProvider",
    "LiquidacionesSystemProvider",
    "AtlasProvider",
    "ForsisAgentInternalProvider",
    "MattermostProvider",
    "BanxicoProvider",
    "MercurioProvider",
    "auto_register_all_providers",
]
