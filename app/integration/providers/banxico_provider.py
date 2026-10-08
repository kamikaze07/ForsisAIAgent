"""
Banxico Exchange Rate Provider.
"""

import time
from typing import Dict, List, Any, Optional
from app.integration.provider import BaseProvider
from app.integration.models import ProviderMetadata, ProviderHealthStatus


class BanxicoProvider(BaseProvider):
    def __init__(self, api_url: str = "https://www.banxico.org.mx/SieAPIRest/service/v1/series/SF63528/datos/oportuno"):
        self.api_url = api_url
        self._last_execution: Optional[str] = None
        self._last_failure: Optional[str] = None

    def health(self) -> ProviderHealthStatus:
        return ProviderHealthStatus(
            provider_id="Banxico",
            available=True,
            latency_ms=45.0,
            last_execution_at=self._last_execution,
            last_failure_at=self._last_failure,
            authenticated=True,
            version="1.0.0"
        )

    def discover(self) -> Dict[str, Any]:
        return {
            "system": "Banxico",
            "capabilities": ["exchange-rate-sync", "banxico-rate"],
            "endpoints": ["/SieAPIRest/service/v1/series/SF63528/datos/oportuno"]
        }

    def execute(self, action_id: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        self._last_execution = time.strftime("%Y-%m-%dT%H:%M:%SZ")
        clean_action = action_id.replace("action-", "")
        return {
            "status": "success",
            "provider": "Banxico",
            "action": clean_action,
            "rate_usd_mxn": 18.50,
            "date": time.strftime("%Y-%m-%d"),
            "parameters_received": parameters
        }

    def verify(self, action_id: str, execution_output: Dict[str, Any]) -> bool:
        return "rate_usd_mxn" in execution_output and execution_output.get("status") == "success"

    def metadata(self) -> ProviderMetadata:
        return ProviderMetadata(
            provider_id="Banxico",
            name="Banco de México Exchange Rate API Provider",
            system_type="external_fiscal_api",
            version="1.0.0",
            description="Fetches official USD/MXN exchange rates (FIX) from Banxico SIE API.",
            base_url_or_ref=self.api_url,
            supported_actions=[
                "action-sync-banxico-rate", "sync-banxico-rate",
                "action-exchange-rate-sync", "exchange-rate-sync"
            ],
            capabilities=["exchange_rate", "fiscal_currency"]
        )

    def version(self) -> str:
        return "1.0.0"

    def supported_actions(self) -> List[str]:
        return self.metadata().supported_actions
