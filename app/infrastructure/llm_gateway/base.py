from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from app.contracts import ExecutionPlan


class LLMProvider(ABC):
    """
    Abstracción base para cualquier proveedor de Modelos de Lenguaje.
    """

    @abstractmethod
    def generate_plan(
        self,
        system_prompt: str,
        user_prompt: str,
        context: Optional[Dict[str, Any]] = None,
        capabilities: Optional[List[Dict[str, Any]]] = None,
        workflows: Optional[List[Dict[str, Any]]] = None,
        options: Optional[Dict[str, Any]] = None
    ) -> ExecutionPlan:
        """
        Genera un plan de ejecución considerando el contexto, capabilities y workflows disponibles.
        Retorna directamente una instancia de ExecutionPlan en lugar de JSON crudo.
        """
        pass

    @abstractmethod
    def generate_text(
        self,
        system_prompt: str,
        user_prompt: str,
        options: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Genera texto libre en lenguaje natural (no un ExecutionPlan). Lo usa
        el ResponseComposer para redactar -- nunca para decidir qué hacer.
        """
        pass
