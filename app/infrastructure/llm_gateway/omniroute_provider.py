"""
Proveedor LLM para OmniRoute compatible con API OpenAI (llm-provider.md §4).
Combo 'Forsis' sobre http://<host>:20130/v1.

Características obligatorias del Sprint 2:
1. Techo duro de 60 s por llamada con ThreadPoolExecutor + future.result().
2. 3 intentos de formato (Capa 1 json_object -> Capa 2 _salvage_json -> Capa 3 reintento con feedback).
3. Fail-closed: JSON inválido tras 3 intentos => LlmJsonInvalidError (nunca dict vacío).
4. Métricas por capa: llm_json_ok, llm_salvage, llm_failclosed, cache_hit, cache_miss.
5. Captura de `model_real` para la traza obligatoria (channels.md §1.5.3).
"""

from __future__ import annotations

import concurrent.futures
import json
import logging
import os
import re
import time
import uuid
from typing import Any, Dict, List, Optional, Set, Tuple
import httpx

from app.contracts import CapabilityCall, ExecutionPlan, Task, TaskDependency, TaskDependencyField, TaskStatus
from app.core.exceptions import (
    LlmJsonInvalidError,
    LlmUnavailableError,
    PlanValidationError,
    ProviderError,
)
from app.core.metrics import metrics
from app.infrastructure.llm_gateway.base import LLMProvider

logger = logging.getLogger(__name__)

_VALID_DEPENDENCY_FIELDS: Set[str] = {f.value for f in TaskDependencyField}
_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


class _PlanParseError(Exception):
    """Error interno al estructurar tareas; detona reintento en el bucle."""
    pass


class OmnirouteProvider(LLMProvider):
    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        timeout: float = 60.0,
        max_retries: int = 2,
    ):
        raw_url = base_url or os.getenv("OMNIROUTE_URL") or os.getenv("OMNIROUTE_BASE_URL") or "http://host.docker.internal:20130/v1"
        self.base_url = raw_url.rstrip("/")
        if not self.base_url.endswith("/v1") and "/v1" not in self.base_url:
            self.base_url = f"{self.base_url}/v1"
        self.api_key = api_key or os.getenv("OMNIROUTE_API_KEY", "")
        self.model = model or os.getenv("OMNIROUTE_MODEL", "Forsis")
        self.timeout = float(os.getenv("OMNIROUTE_TIMEOUT_S", timeout))
        self.max_retries = int(os.getenv("OMNIROUTE_MAX_RETRIES", max_retries))
        self.last_model_real: str = self.model
        self.last_usage: Dict[str, Any] = {}

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key and self.api_key != "***":
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def ping(self) -> bool:
        """Probe para readiness. Timeout generoso de 25 s."""
        endpoint = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 5,
        }
        try:
            with httpx.Client(timeout=25.0) as client:
                res = client.post(endpoint, json=payload, headers=self._headers())
                return res.status_code == 200
        except Exception as e:
            logger.warning("Error en probe de OmniRoute: %s", e)
            return False

    def _timeout_efectivo(self, timeout_s: Optional[float]) -> float:
        """Techo real de ESTA llamada.

        `self.timeout` es el techo de configuración (máximo absoluto). Cuando el
        llamador conoce el tiempo que le queda al turno pasa `timeout_s` y aquí
        se usa el MENOR de los dos: nunca se concede a una sola llamada más
        tiempo del que el turno completo tiene disponible. Era justo la
        incoherencia que hacía imposible terminar un turno multi-paso (3 vueltas
        x 3 intentos x 60 s = 540 s contra un techo de turno de 120 s).

        El piso de 5 s evita lanzar una petición HTTP condenada de antemano.
        """
        if timeout_s is None:
            return self.timeout
        return max(5.0, min(float(timeout_s), self.timeout))

    def _call_http(
        self,
        messages: List[Dict[str, str]],
        json_mode: bool = False,
        temperature: float = 0.0,
        options: Optional[Dict[str, Any]] = None,
        timeout_s: Optional[float] = None,
    ) -> Tuple[str, str, Dict[str, Any]]:
        """
        Llamada HTTP síncrona dentro de worker thread.
        Devuelve (content, model_real, usage).
        """
        techo = self._timeout_efectivo(timeout_s)
        endpoint = f"{self.base_url}/chat/completions"
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if options:
            payload.update(options)

        try:
            with httpx.Client(timeout=techo) as client:
                res = client.post(endpoint, json=payload, headers=self._headers())

                # Registro de caché semántica
                cache_header = res.headers.get("x-cache", "").lower()
                if "hit" in cache_header:
                    metrics.incr("cache_hit")
                else:
                    metrics.incr("cache_miss")

                if res.status_code != 200:
                    metrics.incr("llm_http_error")
                    raise LlmUnavailableError(
                        f"OmniRoute HTTP {res.status_code}: {res.text[:200]}"
                    )

                data = res.json()
                choices = data.get("choices", [])
                if not choices:
                    return ("", data.get("model", self.model), data.get("usage", {}))

                choice = choices[0]
                msg = choice.get("message", {})
                content = msg.get("content") or msg.get("reasoning_content") or ""
                model_real = data.get("model", self.model)
                usage = data.get("usage", {})

                self.last_model_real = model_real
                self.last_usage = usage
                return (content, model_real, usage)

        except httpx.TimeoutException as exc:
            metrics.incr("llm_timeout")
            metrics.incr("llm_network_error")
            raise LlmUnavailableError(f"Timeout contactando OmniRoute ({techo:.1f}s): {exc}") from exc
        except httpx.RequestError as exc:
            metrics.incr("llm_network_error")
            raise LlmUnavailableError(f"Error de red contactando OmniRoute: {exc}") from exc

    def _call_with_hard_ceiling(
        self,
        messages: List[Dict[str, str]],
        json_mode: bool = False,
        temperature: float = 0.0,
        options: Optional[Dict[str, Any]] = None,
        timeout_s: Optional[float] = None,
    ) -> Tuple[str, str, Dict[str, Any]]:
        """Techo duro ejecutado vía ThreadPoolExecutor acotado por timeout_efectivo."""
        techo = self._timeout_efectivo(timeout_s)
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                self._call_http, messages, json_mode, temperature, options, techo
            )
            try:
                return future.result(timeout=techo + 1.0)
            except concurrent.futures.TimeoutError as exc:
                metrics.incr("llm_timeout")
                raise LlmUnavailableError(f"OmniRoute superó el techo duro de {techo:.1f} s.") from exc

    def generate_text(
        self,
        system_prompt: str,
        user_prompt: str,
        options: Optional[Dict[str, Any]] = None,
        timeout_s: Optional[float] = None,
    ) -> str:
        """Generación de prosa para el ResponseComposer. Sin reintentos de formato."""
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        content, _, _ = self._call_with_hard_ceiling(
            messages, json_mode=False, temperature=0.3, options=options,
            timeout_s=timeout_s,
        )
        return content.strip()

    def generate_plan(
        self,
        system_prompt: str,
        user_prompt: str,
        context: Optional[Dict[str, Any]] = None,
        capabilities: Optional[List[Dict[str, Any]]] = None,
        workflows: Optional[List[Dict[str, Any]]] = None,
        options: Optional[Dict[str, Any]] = None,
        timeout_s: Optional[float] = None,
    ) -> ExecutionPlan:
        """
        Genera ExecutionPlan con defensa en 4 capas:
          1. Capa 1: json_object directo
          2. Capa 2: _salvage_json (strip de fences + recorte {})
          3. Capa 3: reintento con feedback (hasta max_retries)
          4. Capa 4: fail-closed => LlmJsonInvalidError (nunca plan vacío por error)

        `timeout_s` es el presupuesto TOTAL de esta planificación (lo que le
        queda al turno), NO el de cada intento: los reintentos de formato se
        reparten ese mismo presupuesto y dejan de intentarlo cuando se agota.
        Sin esto, 3 intentos x 60 s desbordaban por diseño el techo del turno.
        """
        valid_names: Set[str] = set()
        if capabilities:
            for cap in capabilities:
                if isinstance(cap, dict) and "name" in cap:
                    valid_names.add(str(cap["name"]))
                elif hasattr(cap, "name"):
                    valid_names.add(str(getattr(cap, "name")))

        messages: List[Dict[str, str]] = [
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

            # Observaciones del ciclo ReAct: resultados de herramientas de ESTE
            # mismo turno. Van sin el recorte de 400 chars que se aplica al
            # historial conversacional, porque un error de SQL o una muestra de
            # filas pierde todo su valor a medias — es precisamente el dato que
            # el modelo necesita completo para corregir el rumbo. El volumen ya
            # viene acotado en origen por `MAX_OBSERVACION_CHARS`.
            for item in context.get("observations") or []:
                role = item.get("role")
                content = item.get("content")
                if role in ("user", "assistant") and content:
                    messages.append({"role": role, "content": str(content).strip()})

        messages.append({"role": "user", "content": user_prompt})

        last_error: Optional[str] = None
        # Deadline compartido por todos los intentos de formato: el presupuesto
        # es del turno, no de cada intento.
        inicio_plan = time.monotonic()
        for attempt in range(self.max_retries + 1):
            restante: Optional[float] = None
            if timeout_s is not None:
                restante = float(timeout_s) - (time.monotonic() - inicio_plan)
                if restante <= 5.0 and attempt > 0:
                    # Queda menos que el piso útil de una llamada: no se quema
                    # el turno en un intento condenado, se falla en claro.
                    break
            if attempt > 0:
                metrics.incr("llm_attempts")
                if last_error:
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                f"Tu respuesta anterior no fue válida: {last_error}. "
                                "Responde de nuevo, EXCLUSIVAMENTE con el JSON solicitado "
                                "sin texto adicional ni explicaciones."
                            ),
                        }
                    )

            raw_content, model_real, _ = self._call_with_hard_ceiling(
                messages, json_mode=True, temperature=0.0, options=options,
                timeout_s=restante,
            )

            # Capa 1: json directo
            parsed_dict, is_salvaged = self._parse_json_multicapa(raw_content)
            if parsed_dict is None:
                last_error = "el contenido no es JSON válido o está vacío"
                continue

            if not isinstance(parsed_dict, dict):
                last_error = "la respuesta debe ser un objeto JSON {...}"
                continue

            # Multi-step
            if "plan" in parsed_dict:
                try:
                    tasks = self._parse_multi_step_plan(parsed_dict["plan"], valid_names)
                except _PlanParseError as exc:
                    last_error = str(exc)
                    continue

                if is_salvaged:
                    metrics.incr("llm_salvage")
                else:
                    metrics.incr("llm_json_ok")
                return ExecutionPlan(plan_id=str(uuid.uuid4()), tasks=tasks)

            # Single-step
            capability_name = parsed_dict.get("capability")

            # capability: null significa "ninguna capability del catálogo aplica" (éxito)
            if capability_name is None:
                if is_salvaged:
                    metrics.incr("llm_salvage")
                else:
                    metrics.incr("llm_json_ok")
                return ExecutionPlan(plan_id=str(uuid.uuid4()), tasks=[])

            if valid_names and capability_name not in valid_names:
                last_error = f"'{capability_name}' no es una capability del catálogo entregado"
                continue

            parameters = parsed_dict.get("parameters", {})
            if not isinstance(parameters, dict):
                last_error = "'parameters' debe ser un objeto JSON"
                continue

            task = Task(
                task_id=f"t-{uuid.uuid4().hex[:8]}",
                description=f"Ejecutar {capability_name}",
                status=TaskStatus.PENDING,
                capability_call=CapabilityCall(
                    capability_name=capability_name, parameters=parameters
                ),
            )

            if is_salvaged:
                metrics.incr("llm_salvage")
            else:
                metrics.incr("llm_json_ok")

            return ExecutionPlan(plan_id=str(uuid.uuid4()), tasks=[task])

        # Capa 4: Fail-closed
        metrics.incr("llm_failclosed")
        raise LlmJsonInvalidError(
            f"No se pudo obtener un plan JSON válido tras {self.max_retries + 1} intentos: {last_error}"
        )

    def _parse_json_multicapa(self, raw: str) -> Tuple[Optional[Dict[str, Any]], bool]:
        """
        Intenta parsear JSON directo (Capa 1). Si falla, aplica salvage (Capa 2).
        Devuelve (dict_resultado, fue_salvaged).
        """
        clean = (raw or "").strip()
        if not clean:
            return None, False

        # Intento directo
        try:
            data = json.loads(clean)
            if isinstance(data, dict):
                return data, False
        except json.JSONDecodeError:
            pass

        # Capa 2: Salvage
        salvaged = self._salvage_json(clean)
        if salvaged:
            try:
                data = json.loads(salvaged)
                if isinstance(data, dict):
                    return data, True
            except json.JSONDecodeError:
                pass

        return None, False

    @staticmethod
    def _salvage_json(raw: str) -> str:
        """Capa 2: quita markdown fences y recorta desde el primer { al último }."""
        m = _FENCE_RE.search(raw)
        if m:
            raw = m.group(1).strip()

        i, j = raw.find("{"), raw.rfind("}")
        if i >= 0 and j > i:
            raw = raw[i : j + 1]

        return raw.strip()

    @staticmethod
    def _parse_multi_step_plan(raw_plan: Any, valid_names: Set[str]) -> List[Task]:
        if not isinstance(raw_plan, list) or not raw_plan:
            raise _PlanParseError("'plan' debe ser una lista no vacía de tasks")

        tasks: List[Task] = []
        seen_ids: Set[str] = set()

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
            if not isinstance(capability_name, str) or not capability_name:
                raise _PlanParseError(f"'capability' de la task '{task_id}' debe ser un string no vacío")
            if valid_names and capability_name not in valid_names:
                raise _PlanParseError(
                    f"'{capability_name}' no es una capability del catálogo entregado"
                )

            parameters = raw_task.get("parameters", {})
            if not isinstance(parameters, dict):
                raise _PlanParseError(f"'parameters' de la task '{task_id}' debe ser un objeto")

            dependencies: List[str] = []
            depends_on: List[TaskDependency] = []
            raw_dep = raw_task.get("depends_on")
            if raw_dep is not None:
                if not isinstance(raw_dep, dict):
                    raise _PlanParseError(f"'depends_on' de '{task_id}' debe ser un objeto JSON")
                source_task_id = raw_dep.get("task")
                field = raw_dep.get("field")
                target_parameter = raw_dep.get("parameter")
                if not source_task_id or not field or not target_parameter:
                    raise _PlanParseError(
                        f"'depends_on' de '{task_id}' requiere 'task', 'field' y 'parameter'"
                    )
                if field not in _VALID_DEPENDENCY_FIELDS:
                    raise _PlanParseError(
                        f"'{field}' no es un 'field' válido en 'depends_on' ({sorted(_VALID_DEPENDENCY_FIELDS)})"
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
                    capability_call=CapabilityCall(
                        capability_name=capability_name, parameters=parameters
                    ),
                    dependencies=dependencies,
                    depends_on=depends_on,
                )
            )

        return tasks
