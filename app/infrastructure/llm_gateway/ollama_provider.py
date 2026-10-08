import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from typing import Any, Dict, List, Optional

import httpx

from app.contracts import (
    CapabilityCall,
    ExecutionPlan,
    Task,
    TaskDependency,
    TaskDependencyField,
    TaskStatus,
)
from app.contracts.capability_definition import CapabilityDefinition
from app.core.exceptions import PlanValidationError, ProviderError
from app.core.executor.plan_ordering import order_tasks

from .base import LLMProvider

_VALID_DEPENDENCY_FIELDS = {f.value for f in TaskDependencyField}


class _PlanParseError(Exception):
    """Error de FORMATO en la respuesta del modelo (JSON con la forma
    incorrecta) -- se convierte en `last_error` para el mismo bucle de
    reintento que ya existe para el plan de una sola task, nunca se deja
    escapar como excepción de sistema."""


class OllamaProvider(LLMProvider):
    """
    LLMProvider real contra un servidor Ollama local.

    Traduce lenguaje natural a un ExecutionPlan de 0 o 1 Task, validando
    estrictamente la salida del modelo contra el catálogo de capabilities
    entregado. Nunca genera SQL ni ejecuta nada: únicamente elige, como
    máximo, una capability de la lista y extrae sus parámetros.
    """

    def __init__(
        self,
        base_url: str,
        model: str,
        timeout_s: float = 45.0,
        max_retries: int = 2,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self._client = httpx.Client(timeout=timeout_s)
        # Límite duro independiente del timeout de httpx -- evidencia real
        # (bloque Analytics): una petición de composición quedó colgada
        # más de 50 minutos con `httpx.Client(timeout=120.0)` configurado,
        # sin que httpx.ReadTimeout se disparara (Ollama aceptó la
        # conexión y dejó de responder sin cerrarla; el timeout de httpx
        # por sí solo no lo cubrió esa vez). Este ThreadPoolExecutor fuerza
        # un techo real de pared: si `_call` no termina en `timeout_s`,
        # `future.result()` lanza TimeoutError y seguimos adelante -- el
        # hilo bloqueado queda huérfano (Python no puede matar hilos),
        # pero nunca vuelve a bloquear al llamador.
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="ollama-call")

    def generate_plan(
        self,
        system_prompt: str,
        user_prompt: str,
        context: Optional[Dict[str, Any]] = None,
        capabilities: Optional[List[Dict[str, Any]]] = None,
        workflows: Optional[List[Dict[str, Any]]] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> ExecutionPlan:
        valid_names = {
            cap.name for cap in (capabilities or []) if isinstance(cap, CapabilityDefinition)
        }
        messages = [
            {"role": "system", "content": system_prompt},
        ]
        if context and isinstance(context, dict):
            hist = context.get("history") or []
            for item in hist:
                role = item.get("role")
                content = item.get("content")
                if role in ("user", "assistant") and content:
                    texto = str(content).strip()
                    if len(texto) > 400:
                        texto = texto[:397] + "..."
                    messages.append({"role": role, "content": texto})

        messages.append({"role": "user", "content": user_prompt})

        last_error: Optional[str] = None
        for _ in range(self.max_retries + 1):
            if last_error:
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            f"Tu respuesta anterior no fue válida: {last_error}. "
                            "Responde de nuevo, EXCLUSIVAMENTE con el JSON solicitado."
                        ),
                    }
                )

            try:
                raw_content = self._call(messages)
            except httpx.HTTPError as exc:
                raise ProviderError(f"Ollama no respondió correctamente: {exc}") from exc

            try:
                decision = json.loads(raw_content)
            except json.JSONDecodeError as exc:
                last_error = f"el contenido no es JSON válido ({exc})"
                continue

            if not isinstance(decision, dict):
                last_error = "la respuesta debe ser un objeto JSON"
                continue

            if "plan" in decision:
                try:
                    tasks = self._parse_multi_step_plan(decision["plan"], valid_names)
                except _PlanParseError as exc:
                    last_error = str(exc)
                    continue
                return ExecutionPlan(plan_id=self._new_plan_id(), tasks=tasks)

            capability_name = decision.get("capability")

            if capability_name is None:
                return ExecutionPlan(plan_id=self._new_plan_id(), tasks=[])

            if capability_name not in valid_names:
                last_error = f"'{capability_name}' no es una capability del catálogo entregado"
                continue

            parameters = decision.get("parameters", {})
            if not isinstance(parameters, dict):
                last_error = "'parameters' debe ser un objeto JSON"
                continue

            task = Task(
                task_id=f"task-{uuid.uuid4().hex[:8]}",
                description=f"Ejecutar {capability_name}",
                status=TaskStatus.PENDING,
                capability_call=CapabilityCall(
                    capability_name=capability_name, parameters=parameters
                ),
            )
            return ExecutionPlan(plan_id=self._new_plan_id(), tasks=[task])

        raise ProviderError(
            f"Ollama no produjo un plan válido tras {self.max_retries + 1} intento(s): {last_error}"
        )

    @staticmethod
    def _parse_multi_step_plan(raw_plan: Any, valid_names: set) -> List[Task]:
        """Convierte la forma `{"plan": [...]}` (ver MULTI_STEP_INSTRUCTIONS)
        en `List[Task]` -- valida CADA campo contra un catálogo cerrado
        (capability real, 'field' de TaskDependencyField) antes de
        construir un solo objeto tipado; cualquier desvío levanta
        _PlanParseError para que el bucle de reintento le pida al modelo
        que lo corrija, en vez de propagar un plan a medio validar."""
        if not isinstance(raw_plan, list) or not raw_plan:
            raise _PlanParseError("'plan' debe ser una lista no vacía de tasks")

        tasks: List[Task] = []
        seen_ids = set()
        for raw_task in raw_plan:
            if not isinstance(raw_task, dict):
                raise _PlanParseError("cada elemento de 'plan' debe ser un objeto JSON")

            task_id = raw_task.get("id")
            if not isinstance(task_id, str) or not task_id:
                raise _PlanParseError("cada task de 'plan' necesita un 'id' de tipo string")
            if task_id in seen_ids:
                raise _PlanParseError(f"id de task duplicado en 'plan': '{task_id}'")
            seen_ids.add(task_id)

            capability_name = raw_task.get("capability")
            if capability_name not in valid_names:
                raise _PlanParseError(
                    f"'{capability_name}' no es una capability del catálogo entregado"
                )

            parameters = raw_task.get("parameters", {})
            if not isinstance(parameters, dict):
                raise _PlanParseError(f"'parameters' de la task '{task_id}' debe ser un objeto JSON")

            dependencies: List[str] = []
            depends_on: List[TaskDependency] = []
            raw_dep = raw_task.get("depends_on")
            if raw_dep is not None:
                if not isinstance(raw_dep, dict):
                    raise _PlanParseError(f"'depends_on' de la task '{task_id}' debe ser un objeto JSON")
                source_task_id = raw_dep.get("task")
                field = raw_dep.get("field")
                target_parameter = raw_dep.get("parameter")
                if not source_task_id or not field or not target_parameter:
                    raise _PlanParseError(
                        f"'depends_on' de la task '{task_id}' requiere 'task', 'field' y 'parameter'"
                    )
                if field not in _VALID_DEPENDENCY_FIELDS:
                    raise _PlanParseError(
                        f"'{field}' no es un 'field' válido en 'depends_on' "
                        f"(solo: {sorted(_VALID_DEPENDENCY_FIELDS)})"
                    )
                dependencies = [source_task_id]
                depends_on = [
                    TaskDependency(
                        source_task_id=source_task_id,
                        source_field=TaskDependencyField(field),
                        target_parameter=target_parameter,
                    )
                ]

            tasks.append(
                Task(
                    task_id=task_id,
                    description=f"Ejecutar {capability_name}",
                    status=TaskStatus.PENDING,
                    capability_call=CapabilityCall(capability_name=capability_name, parameters=parameters),
                    dependencies=dependencies,
                    depends_on=depends_on,
                )
            )

        try:
            order_tasks(tasks)
        except PlanValidationError as exc:
            raise _PlanParseError(f"plan estructuralmente inválido: {exc}") from exc

        return tasks

    def generate_text(
        self,
        system_prompt: str,
        user_prompt: str,
        options: Optional[Dict[str, Any]] = None,
    ) -> str:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        try:
            return self._call(messages, json_mode=False, options=options).strip()
        except httpx.HTTPError as exc:
            raise ProviderError(f"Ollama no respondió correctamente: {exc}") from exc

    def _call(
        self,
        messages: List[Dict[str, str]],
        json_mode: bool = True,
        options: Optional[Dict[str, Any]] = None,
    ) -> str:
        payload_options = {"temperature": 0.0}
        if options:
            payload_options.update(options)
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": payload_options,
        }
        if json_mode:
            payload["format"] = "json"

        future = self._executor.submit(
            self._client.post, f"{self.base_url}/api/chat", json=payload
        )
        try:
            response = future.result(timeout=self.timeout_s)
        except FutureTimeoutError as exc:
            raise ProviderError(
                f"Ollama no respondió dentro del límite de {self.timeout_s}s (techo duro)."
            ) from exc

        response.raise_for_status()
        body = response.json()
        return body.get("message", {}).get("content", "")

    @staticmethod
    def _new_plan_id() -> str:
        return f"plan-{uuid.uuid4().hex[:12]}"
