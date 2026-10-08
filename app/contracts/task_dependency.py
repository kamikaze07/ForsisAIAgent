from enum import Enum

from pydantic import BaseModel


class TaskDependencyField(str, Enum):
    """
    Catálogo CERRADO de qué se puede extraer del resultado de una task
    previa para alimentar el parámetro de otra -- nunca una ruta arbitraria
    a un objeto Python (bloque Multi-Step Agent, sección 22: "NO permitir
    acceso arbitrario a objetos Python"). Los 4 valores cubren exactamente
    los dos patrones con evidencia real de negocio:

    - TOP_LABEL / TOP_VALUE: "¿quién es el primero de un ranking/valor
      único?" -- el ganador de una tabla ordenada (ej. "qué operador tiene
      más viajes y cuánto debe" -> el label/value de `rows[0]`).
    - EACH_ROW_LABEL / EACH_ROW_VALUE: "para cada fila de un ranking,
      repite esta consulta" -- el patrón fan-out (ej. "compara los 5
      operadores con más viajes contra su saldo deudor").

    Ambos leen de `AnalyticsResult.rows` -- hoy el único tipo de resultado
    del que tiene sentido depender (es el único con una lista ordenada de
    filas comparables). Si en el futuro otro dominio produce un resultado
    tabular equivalente, se resuelve igual sin tocar este catálogo.
    """

    TOP_LABEL = "top_label"
    TOP_VALUE = "top_value"
    EACH_ROW_LABEL = "each_row_label"
    EACH_ROW_VALUE = "each_row_value"


class TaskDependency(BaseModel):
    """
    Vínculo tipado y validado entre dos tasks del mismo ExecutionPlan:
    "el parámetro `target_parameter` de ESTA task se llena con
    `source_field` del resultado de la task `source_task_id`".

    Nunca es código, nunca es una cadena con sintaxis libre (`$result[0]`
    o similar) -- son 3 campos planos, cada uno validado por su propio
    tipo/enum antes de que el Executor los use.
    """

    source_task_id: str
    source_field: TaskDependencyField
    target_parameter: str
