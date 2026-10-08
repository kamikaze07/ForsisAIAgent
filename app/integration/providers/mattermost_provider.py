"""
Mattermost Notification System Provider.
"""

import time
from typing import Dict, List, Any, Optional
from app.integration.provider import BaseProvider
from app.integration.models import ProviderMetadata, ProviderHealthStatus


class MattermostProvider(BaseProvider):
    def __init__(self, webhook_url: str = "http://localhost:8065/hooks/channel"):
        self.webhook_url = webhook_url
        self._last_execution: Optional[str] = None
        self._last_failure: Optional[str] = None

    def health(self) -> ProviderHealthStatus:
        return ProviderHealthStatus(
            provider_id="Mattermost",
            available=True,
            latency_ms=15.0,
            last_execution_at=self._last_execution,
            last_failure_at=self._last_failure,
            authenticated=True,
            version="7.8.0"
        )

    def discover(self) -> Dict[str, Any]:
        return {
            "system": "Mattermost",
            "capabilities": ["mattermost-notifications", "channel-alerts"],
            "endpoints": ["/hooks/channel", "/api/v4/posts"]
        }

    def execute(self, action_id: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        self._last_execution = time.strftime("%Y-%m-%dT%H:%M:%SZ")
        clean_action = action_id.replace("action-", "")
        return {
            "status": "success",
            "provider": "Mattermost",
            "action": clean_action,
            "result": f"Sent Mattermost notification: {parameters.get('message', 'Default notification')}",
            "parameters_received": parameters
        }

    def verify(self, action_id: str, execution_output: Dict[str, Any]) -> bool:
        return execution_output.get("status") == "success"

    def metadata(self) -> ProviderMetadata:
        return ProviderMetadata(
            provider_id="Mattermost",
            name="Mattermost Enterprise Messaging Provider",
            system_type="notification_gateway",
            version="7.8.0",
            description="Exposes channel notifications, operational broadcasts, and alert delivery.",
            base_url_or_ref=self.webhook_url,
            supported_actions=[
                "action-send-mattermost-notification", "send-mattermost-notification"
            ],
            capabilities=["notifications", "messaging"]
        )

    def version(self) -> str:
        return "7.8.0"

    def supported_actions(self) -> List[str]:
        return self.metadata().supported_actions
