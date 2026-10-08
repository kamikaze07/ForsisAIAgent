import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Union

from app.contracts import ExecutionPlan, ExecutionResult, Task
from app.contracts.error_response import ErrorResponse
from app.core.executor.dependency_resolver import (
    DependencyNotUsable,
    DependencySourceEmpty,
    is_fan_out,
    resolve_fan_out,
    resolve_single,
)
from app.core.executor.factory import CapabilityFactory
from app.core.executor.plan_ordering import order_tasks
from app.core.executor.registry import CapabilityRegistry
from app.core.exceptions import CapabilityExecutionError, CapabilityNotFound

TaskOutcome = Union[ExecutionResult, List[ExecutionResult]]


class Executor:
    """
    Componente encargado de ejecutar físicamente un ExecutionPlan.
    Resuelve CapabilityDefinitions a clases mediante Factory y ejecuta
    deterministamente.

    Soporta planes de una sola task (comportamiento histórico, sin
    cambios) y planes multi-task con dependencias tipadas (bloque
    Multi-Step Agent): valida el plan, calcula un orden topológico,
    resuelve cada `TaskDependency` contra resultados YA calculados de
    tasks previas, y ejecuta un patrón fan-out cuando corresponde
    (`each_row_*` -- una ejecución de la Tool POR FILA del resultado
    fuente, ej. "saldo de cada uno de los 5 operadores del ranking").
    """

    def __init__(self, registry: CapabilityRegistry, factory: CapabilityFactory, runtime=None):
        self.registry = registry
        self.factory = factory
        self.runtime = runtime

    def execute_plan(self, plan: ExecutionPlan) -> ExecutionResult:
        if not plan.tasks:
            return ExecutionResult(success=True, data={"task_results": {}})

        ordered_tasks = order_tasks(plan.tasks)

        results: Dict[str, TaskOutcome] = {}
        warnings: List[str] = []
        overall_success = True
        started_at = datetime.now(timezone.utc)
        start_time = time.time()

        for task in ordered_tasks:
            if not task.capability_call:
                continue

            skip_error = self._check_dependencies_ready(task, results)
            if skip_error is not None:
                skipped = self._skipped_result(skip_error)
                results[task.task_id] = skipped
                overall_success = False
                warnings.append(f"{task.task_id}: {skip_error}")
                continue

            task_is_fan_out = any(is_fan_out(dep) for dep in task.depends_on)
            try:
                if task_is_fan_out:
                    outcome = self._execute_fan_out(task, results)
                else:
                    outcome = self._execute_single(task, results)
            except (DependencyNotUsable, DependencySourceEmpty) as exc:
                # Defensa en profundidad: `_check_dependencies_ready` ya
                # debería haber detectado esto, pero si un binding fan-out
                # individual falla a mitad de ejecución se trata igual,
                # nunca como excepción de sistema.
                skipped = self._skipped_result(str(exc))
                results[task.task_id] = skipped
                overall_success = False
                warnings.append(f"{task.task_id}: {exc}")
                continue

            results[task.task_id] = outcome
            # Solo se itera elemento por elemento cuando ESTA task es
            # fan-out por construcción (lo sabemos por su propio plan, no
            # adivinando por el tipo de `outcome`) -- una Tool clásica que
            # devuelve una lista cruda como valor de negocio (ej.
            # ListReturnCap en los tests) nunca se confunde con esto.
            for result_data in outcome if task_is_fan_out else [outcome]:
                if isinstance(result_data, ExecutionResult) and not result_data.success:
                    overall_success = False
                    if result_data.error:
                        warnings.append(f"{task.task_id} ({task.capability_call.capability_name}): {result_data.error.message}")

        finished_at = datetime.now(timezone.utc)
        execution_time_ms = int((time.time() - start_time) * 1000)

        return ExecutionResult(
            success=overall_success,
            data={"task_results": results},
            warnings=warnings,
            started_at=started_at,
            finished_at=finished_at,
            execution_time_ms=execution_time_ms,
        )

    # --- Dependencias -----------------------------------------------------

    def _check_dependencies_ready(self, task: Task, results: Dict[str, TaskOutcome]):
        """Devuelve un mensaje de error humano si ALGUNA dependencia no es
        usable (no corrió, falló, o no trajo filas) -- en ese caso la task
        NUNCA se ejecuta (sección 13). Devuelve None si puede ejecutarse."""
        for dep_id in task.dependencies:
            source = results.get(dep_id)
            if source is None:
                return f"la task previa '{dep_id}' no se ejecutó."
            if isinstance(source, ExecutionResult) and not source.success:
                return f"la task previa '{dep_id}' no encontró resultados."
        for binding in task.depends_on:
            source = results.get(binding.source_task_id)
            try:
                if is_fan_out(binding):
                    resolve_fan_out(binding, source)
                else:
                    resolve_single(binding, source)
            except (DependencyNotUsable, DependencySourceEmpty) as exc:
                return str(exc)
        return None

    @staticmethod
    def _skipped_result(message: str) -> ExecutionResult:
        return ExecutionResult(
            success=False,
            error=ErrorResponse(error_code="DEPENDENCY_UNRESOLVED", message=message),
        )

    def _resolved_parameters(self, task: Task, results: Dict[str, TaskOutcome]) -> Dict[str, Any]:
        params = dict(task.capability_call.parameters)
        for binding in task.depends_on:
            if is_fan_out(binding):
                continue  # el fan-out se resuelve por fila en _execute_fan_out
            source = results[binding.source_task_id]
            params[binding.target_parameter] = resolve_single(binding, source)
        return params

    # --- Ejecución ----------------------------------------------------

    def _execute_single(self, task: Task, results: Dict[str, TaskOutcome]) -> ExecutionResult:
        params = self._resolved_parameters(task, results)
        return self._run_capability(task.capability_call.capability_name, params)

    def _execute_fan_out(self, task: Task, results: Dict[str, TaskOutcome]) -> List[ExecutionResult]:
        base_params = self._resolved_parameters(task, results)
        fan_out_binding = next(dep for dep in task.depends_on if is_fan_out(dep))
        source = results[fan_out_binding.source_task_id]
        values = resolve_fan_out(fan_out_binding, source)

        outcomes: List[ExecutionResult] = []
        for value in values:
            params = dict(base_params)
            params[fan_out_binding.target_parameter] = value
            outcomes.append(self._run_capability(task.capability_call.capability_name, params))
        return outcomes

    def _run_capability(self, cap_name: str, params: Dict[str, Any]) -> Any:
        definition = self.registry.get_definition_by_name(cap_name)
        if not definition:
            definition = self.registry.get_definition_by_id(cap_name)

        if not definition:
            raise CapabilityNotFound(f"Capability '{cap_name}' no encontrada en el registro.")

        cap_class = self.registry.resolve_implementation(definition.id)
        if not cap_class:
            if self.runtime:
                from app.core.executor.capabilities.runtime_capability import RuntimeCapabilityAdapter
                capability_instance = RuntimeCapabilityAdapter(definition.id, self.runtime)
                return capability_instance.execute(params)
            raise CapabilityNotFound(f"Implementación para '{cap_name}' no está registrada.")

        try:
            capability_instance = self.factory.create(cap_class)
            return capability_instance.execute(params)
        except Exception as e:
            raise CapabilityExecutionError(f"Error ejecutando '{cap_name}': {str(e)}") from e
