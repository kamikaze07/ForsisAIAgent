"""
Mercurio Document & Ingestion Provider.
"""

import time
from typing import Dict, List, Any, Optional
from app.integration.provider import BaseProvider
from app.integration.models import ProviderMetadata, ProviderHealthStatus


class MercurioProvider(BaseProvider):
    def __init__(self, base_url: str = "http://localhost:8004/api/mercurio"):
        self.base_url = base_url
        self._last_execution: Optional[str] = None
        self._last_failure: Optional[str] = None

    def health(self) -> ProviderHealthStatus:
        return ProviderHealthStatus(
            provider_id="Mercurio",
            available=True,
            latency_ms=22.0,
            last_execution_at=self._last_execution,
            last_failure_at=self._last_failure,
            authenticated=True,
            version="2.1.0"
        )

    def discover(self) -> Dict[str, Any]:
        return {
            "system": "Mercurio",
            "capabilities": ["document-reception", "reset-ingestion", "cfdi-stamping"],
            "endpoints": ["/documents", "/ingest/reset", "/cfdi/stamp"]
        }

    def execute(self, action_id: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        self._last_execution = time.strftime("%Y-%m-%dT%H:%M:%SZ")
        clean_action = action_id.replace("action-", "")
        return {
            "status": "success",
            "provider": "Mercurio",
            "action": clean_action,
            "result": f"Executed {clean_action} on Mercurio System",
            "parameters_received": parameters
        }

    def verify(self, action_id: str, execution_output: Dict[str, Any]) -> bool:
        return execution_output.get("status") == "success"

    def metadata(self) -> ProviderMetadata:
        return ProviderMetadata(
            provider_id="Mercurio",
            name="Mercurio Document & Ingestion Provider",
            system_type="document_gateway",
            version="2.1.0",
            description="Manages document reception, RESET file ingestion, and CFDI PAC stamping.",
            base_url_or_ref=self.base_url,
            supported_actions=[
                "action-ingest-reset-file", "ingest-reset-file",
                "action-receive-document", "receive-document",
                "action-stamp-cfdi", "stamp-cfdi"
            ],
            capabilities=["document_ingestion", "pac_stamping"]
        )

    def version(self) -> str:
        return "2.1.0"

    def supported_actions(self) -> List[str]:
        return self.metadata().supported_actions
