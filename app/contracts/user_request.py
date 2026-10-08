from typing import Any, Dict
from pydantic import BaseModel, Field


class UserRequest(BaseModel):
    request_id: str
    user_id: str
    text: str
    context: Dict[str, Any] = Field(default_factory=dict)
