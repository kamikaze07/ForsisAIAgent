"""
Integration Providers package with self-registration capabilities.
"""

from app.integration.registry import ProviderRegistry
from app.integration.providers.trafico_provider import TraficoSystemProvider
from app.integration.providers.liquidaciones_provider import LiquidacionesSystemProvider
from app.integration.providers.atlas_provider import AtlasProvider
from app.integration.providers.forsis_agent_provider import ForsisAgentInternalProvider
from app.integration.providers.mattermost_provider import MattermostProvider
from app.integration.providers.banxico_provider import BanxicoProvider
from app.integration.providers.mercurio_provider import MercurioProvider


def auto_register_all_providers(registry: ProviderRegistry) -> ProviderRegistry:
    """Self-registers all available integration providers without hardcoding list in caller."""
    registry.register(TraficoSystemProvider())
    registry.register(LiquidacionesSystemProvider())
    registry.register(AtlasProvider())
    registry.register(ForsisAgentInternalProvider())
    registry.register(MattermostProvider())
    registry.register(BanxicoProvider())
    registry.register(MercurioProvider())
    return registry


__all__ = [
    "TraficoSystemProvider",
    "LiquidacionesSystemProvider",
    "AtlasProvider",
    "ForsisAgentInternalProvider",
    "MattermostProvider",
    "BanxicoProvider",
    "MercurioProvider",
    "auto_register_all_providers",
]
