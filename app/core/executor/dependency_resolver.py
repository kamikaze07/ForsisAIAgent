"""
Resuelve un `TaskDependency` contra el resultado YA CALCULADO de una task
previa -- nunca ejecuta nada, nunca accede a datos por su cuenta. Bloque
Multi-Step Agent, sección 6 y 11: el mecanismo de paso de datos entre
Tools debe ser tipado, validado, seguro y determinista.

Solo sabe leer `AnalyticsResult.rows` (label/value de la fila 0, o de
TODAS las filas para el patrón fan-out) -- es, hoy, el único tipo de
resultado con una lista ordenada de filas comparables. Cualquier otro
tipo de resultado como fuente de una dependencia es un error de
validación del plan, no un caso que se intente adivinar.
"""

from typing import Any, List

from app.contracts import ExecutionResult, TaskDependency, TaskDependencyField
from app.domains.analytics.analytics_types import AnalyticsResult

_FAN_OUT_FIELDS = (TaskDependencyField.EACH_ROW_LABEL, TaskDependencyField.EACH_ROW_VALUE)


class DependencyNotUsable(Exception):
    """La task fuente no es un resultado del que se pueda depender (no
    corrió como un único ExecutionResult, no tuvo éxito, o no es un
    AnalyticsResult) -- error de PLAN: nunca debería ocurrir si
    `plan_ordering`/el Planner construyeron el plan correctamente."""


class DependencySourceEmpty(Exception):
    """El resultado fuente es válido pero no trae filas -- señal semántica
    de "no encontrado" (sección 13): la task dependiente NUNCA se ejecuta,
    se registra como resultado semántico, no como error técnico."""


def is_fan_out(dependency: TaskDependency) -> bool:
    return dependency.source_field in _FAN_OUT_FIELDS


def _rows(source_result: Any) -> List[Any]:
    if not isinstance(source_result, ExecutionResult):
        raise DependencyNotUsable(
            "La task fuente produjo varios resultados (fan-out) -- no puede encadenarse."
        )
    if not source_result.success or not isinstance(source_result.data, AnalyticsResult):
        raise DependencyNotUsable("La task fuente no produjo un AnalyticsResult exitoso.")
    return source_result.data.rows


def resolve_single(dependency: TaskDependency, source_result: Any) -> Any:
    """Para TOP_LABEL/TOP_VALUE: SIEMPRE `rows[0]` -- el primero de un
    ranking/valor único ya viene ordenado por el Domain Service
    (CountTripsQuery/ListDebtorCardBalancesQuery ordenan DESC), nunca se
    reordena aquí."""
    rows = _rows(source_result)
    if not rows:
        raise DependencySourceEmpty("La consulta previa no encontró resultados.")
    row = rows[0]
    if dependency.source_field == TaskDependencyField.TOP_LABEL:
        return row.label
    if dependency.source_field == TaskDependencyField.TOP_VALUE:
        return row.value
    raise ValueError(f"'{dependency.source_field}' no es un binding de valor único.")


def resolve_fan_out(dependency: TaskDependency, source_result: Any) -> List[Any]:
    rows = _rows(source_result)
    if not rows:
        raise DependencySourceEmpty("La consulta previa no encontró resultados.")
    if dependency.source_field == TaskDependencyField.EACH_ROW_LABEL:
        return [row.label for row in rows]
    if dependency.source_field == TaskDependencyField.EACH_ROW_VALUE:
        return [row.value for row in rows]
    raise ValueError(f"'{dependency.source_field}' no es un binding fan-out.")
