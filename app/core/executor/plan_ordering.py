"""
Valida la forma de un ExecutionPlan multi-task y calcula un orden de
ejecución seguro (topológico) -- ANTES de ejecutar nada. Puro, sin efectos
secundarios, sin acceso a datos: solo mira `Task.dependencies`/
`Task.depends_on` (bloque Multi-Step Agent, sección 12, paso 1 y 2).

Deliberadamente separado de `executor.py`: el Executor decide QUÉ pasa
cuando una dependencia no trae datos (semántica de negocio); este módulo
solo decide en qué ORDEN es válido intentarlo (estructura).
"""

from typing import Dict, List

from app.contracts import Task
from app.core.exceptions import PlanValidationError


def order_tasks(tasks: List[Task]) -> List[Task]:
    """Orden topológico estable (preserva el orden original entre tasks
    sin relación de dependencia entre sí) o levanta PlanValidationError si
    el plan es estructuralmente inválido."""
    by_id: Dict[str, Task] = {}
    for task in tasks:
        if task.task_id in by_id:
            raise PlanValidationError(f"task_id duplicado en el plan: '{task.task_id}'.")
        by_id[task.task_id] = task

    for task in tasks:
        if task.task_id in task.dependencies:
            raise PlanValidationError(f"La task '{task.task_id}' depende de sí misma.")
        for dep_id in task.dependencies:
            if dep_id not in by_id:
                raise PlanValidationError(
                    f"La task '{task.task_id}' depende de '{dep_id}', que no existe en el plan."
                )
        for binding in task.depends_on:
            if binding.source_task_id not in task.dependencies:
                raise PlanValidationError(
                    f"La task '{task.task_id}' tiene un binding hacia "
                    f"'{binding.source_task_id}' que no está declarado en 'dependencies'."
                )

    ordered: List[Task] = []
    resolved_ids: set = set()
    remaining = list(tasks)
    while remaining:
        progressed = False
        still_remaining = []
        for task in remaining:
            if all(dep_id in resolved_ids for dep_id in task.dependencies):
                ordered.append(task)
                resolved_ids.add(task.task_id)
                progressed = True
            else:
                still_remaining.append(task)
        if not progressed:
            stuck = ", ".join(t.task_id for t in still_remaining)
            raise PlanValidationError(
                f"Dependencia circular detectada entre las tasks: {stuck}."
            )
        remaining = still_remaining

    return ordered
