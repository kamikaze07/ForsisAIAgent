from typing import Any, Dict, List
from pydantic import BaseModel, Field

class CapabilityDefinition(BaseModel):
    id: str
    name: str
    description: str
    version: str = "1.0.0"
    category: str = "general"
    tags: List[str] = Field(default_factory=list)
    required_permissions: List[str] = Field(default_factory=list)
    input_schema: Dict[str, Any] = Field(default_factory=dict)
    output_schema: Dict[str, Any] = Field(default_factory=dict)
    timeout: int = 30
    retry_policy: Dict[str, Any] = Field(default_factory=dict)
    async_supported: bool = False
    experimental: bool = False
