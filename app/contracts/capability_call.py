from typing import Any, Dict
from pydantic import BaseModel, Field


class CapabilityCall(BaseModel):
    capability_name: str
    parameters: Dict[str, Any] = Field(default_factory=dict)
