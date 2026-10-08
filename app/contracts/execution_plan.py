from typing import List
from pydantic import BaseModel, Field
from .task import Task


class ExecutionPlan(BaseModel):
    plan_id: str
    tasks: List[Task] = Field(default_factory=list)
