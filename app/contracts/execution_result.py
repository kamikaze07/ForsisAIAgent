from typing import Any, Dict, Generic, List, Optional, TypeVar
from datetime import datetime
from pydantic import BaseModel, Field
from .error_response import ErrorResponse

T = TypeVar("T")


class ExecutionResult(BaseModel, Generic[T]):
    """
    Genérico sobre el tipo de `data`. Uso sin parametrizar (ej. el envelope
    del Executor, que agrupa resultados heterogéneos de varias tasks) sigue
    funcionando exactamente igual que antes -- `data` se comporta como `Any`.
    Una Tool que devuelve un objeto de dominio tipado puede parametrizar
    explícitamente, ej. `ExecutionResult[GuideProfile]`, y Pydantic valida
    `data` contra ese tipo.
    """

    success: bool
    data: Optional[T] = None
    error: Optional[ErrorResponse] = None

    execution_time_ms: Optional[int] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    capability_id: Optional[str] = None
    correlation_id: Optional[str] = None
    task_id: Optional[str] = None
    warnings: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
