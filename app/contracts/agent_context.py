from typing import Any, Dict, List
from pydantic import BaseModel, Field


class AgentContext(BaseModel):
    session_id: str
    history: List[Dict[str, Any]] = Field(default_factory=list)
    state: Dict[str, Any] = Field(default_factory=dict)
