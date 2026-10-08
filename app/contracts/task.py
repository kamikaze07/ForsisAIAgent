from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field

from .capability_call import CapabilityCall
from .task_dependency import TaskDependency
from .workflow_call import WorkflowCall


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class Task(BaseModel):
    task_id: str
    description: str
    status: TaskStatus = TaskStatus.PENDING
    capability_call: Optional[CapabilityCall] = None
    workflow_call: Optional[WorkflowCall] = None
    # IDs de tasks que deben completarse (con éxito) antes que esta --
    # existía desde el diseño original pero nunca se usaba (el MVP solo
    # producía planes de 0 o 1 task). El Executor (bloque Multi-Step
    # Agent) ahora sí la usa para ordenar la ejecución.
    dependencies: List[str] = Field(default_factory=list)
    # Bindings tipados: qué parámetro de ESTA task se llena con qué campo
    # del resultado de cuál task previa. Cada entrada aquí implica que su
    # `source_task_id` también debe estar en `dependencies` (validado por
    # el Executor, no aquí, para no acoplar contratos a lógica de negocio).
    depends_on: List[TaskDependency] = Field(default_factory=list)
