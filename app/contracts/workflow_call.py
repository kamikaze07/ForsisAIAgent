from typing import Any, Dict
from pydantic import BaseModel, Field


class WorkflowCall(BaseModel):
    workflow_name: str
    parameters: Dict[str, Any] = Field(default_factory=dict)
