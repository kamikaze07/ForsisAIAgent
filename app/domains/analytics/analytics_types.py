"""
Catálogo cerrado de métricas/operaciones/dimensiones/periodos del dominio
Analítico -- primera clase, no strings libres. Ningún componente aguas
abajo (Query Objects, Domain Service, Tool) acepta un valor fuera de estos
enums: es lo que garantiza "no aceptar SQL, no aceptar expresiones
arbitrarias" (auditoría/blueprint de Analytics, sección 17) sin necesidad
de sanitizar texto libre en ningún punto.

AnalyticsResult es el "resultado estructurado" único (sección 14 del
blueprint) que devuelve AnalyticsDomainService para CUALQUIER combinación
de métrica/dimensión -- un valor suelto (saldo de tarjeta deudor) es
`rows` con un solo elemento; una tabla/ranking es `rows` con varios. El
Response Composer (plantilla u Ollama) nunca ve nada más específico que
esto, igual que ya pasa con GuideProfile/InvoiceProfile.
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field
from enum import Enum


class AnalyticsMetric(str, Enum):
    TRIPS_COUNT = "trips_count"
    TRIPS_AVERAGE_PER_WEEK = "trips_average_per_week"
    DEBTOR_CARD_BALANCE = "debtor_card_balance"
    DEBTOR_CARD_CHARGES = "debtor_card_charges"
    DEBTOR_CARD_PAYMENTS = "debtor_card_payments"


class AnalyticsOperation(str, Enum):
    """Solo aplica a TRIPS_COUNT -- las demás métricas tienen una única
    operación implícita (ver AnalyticsDomainService._HANDLERS)."""

    COUNT = "count"
    AVERAGE = "average"


class AnalyticsDimension(str, Enum):
    OPERATOR = "operator"
    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    YEAR = "year"


class AnalyticsPeriod(str, Enum):
    TODAY = "today"
    YESTERDAY = "yesterday"
    CURRENT_WEEK = "current_week"
    PREVIOUS_WEEK = "previous_week"
    CURRENT_MONTH = "current_month"
    PREVIOUS_MONTH = "previous_month"
    CURRENT_YEAR = "current_year"
    PREVIOUS_YEAR = "previous_year"


class AnalyticsRow(BaseModel):
    label: str
    value: float
    extra: Dict[str, Any] = Field(default_factory=dict)


class AnalyticsResult(BaseModel):
    metric: str
    operation: str
    group_by: List[str] = Field(default_factory=list)
    scope: Optional[str] = None  # nombre canónico del operador/cliente, si la consulta se acotó a uno
    period_label: Optional[str] = None
    unit: Optional[str] = None  # "viajes" | "MXN"
    rows: List[AnalyticsRow] = Field(default_factory=list)
    note: Optional[str] = None  # ej. "Sin viajes registrados en el periodo."
    # Bloque Multi-Step Agent / Complex Analytics: cuando ResponseComposer
    # combina un ranking con una consulta de seguimiento por cada fila
    # (ej. "compara los 5 operadores con más viajes contra su saldo
    # deudor"), cada nombre aquí es una clave presente en `row.extra` de
    # TODAS las filas -- el frontend la usa para agregar una columna más
    # a la tabla sin que AnalyticsResultCard necesite saber qué métrica
    # es. Vacío en el caso normal (una sola métrica, sin combinar).
    extra_columns: List[str] = Field(default_factory=list)
