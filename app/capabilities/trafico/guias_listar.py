"""
`traf.guias_listar` — primera capability real del agente (Sprint 3, entregable 1).

Lectura pura sobre `sicrePR.guias` / `sicreGero.guias` (`tools-design.md` §5.1).
risk_class **L0**: idempotente, sin efectos, sin inferencia — devuelve filas
tal como están en la base.

Decisión de diseño: el SQL se construye SIEMPRE con parámetros vinculados y
un mapa cerrado de columnas ordenables. El LLM nunca aporta SQL ni nombres de
columna: aporta *valores* para un esqueleto fijo. Un parámetro inesperado es
un 422 del JSON Schema, no una cadena concatenada.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

from app.contracts.capability_definition import CapabilityDefinition
from app.core.exceptions import CapabilityExecutionError
from app.core.executor.capability import Capability
from app.core.risk import RiskClass
from app.infrastructure.db.readonly_pool import ro_pool

# Mapa CERRADO empresa → destino de lectura. No se deriva de la entrada.
_COMPANY_TARGET = {"FORSIS": "sicret_pr", "GERO": "sicret_gero"}

# Columnas devueltas. Lista fija: nunca `SELECT *` — una columna nueva en la
# tabla no debe filtrarse sola a la respuesta del agente.
_SELECT_COLUMNS = (
    "num", "num_guia", "fecha", "nombre", "estatus", "estado",
    "tipo", "servicio", "operador", "placas1", "factura", "linea",
)

# Orden permitido: clave lógica → columna real. Cierra la puerta a ORDER BY
# arbitrario (vector clásico de inyección por nombre de columna).
_SORT_COLUMNS = {
    "fecha": "fecha",
    "num_guia": "num_guia",
    "num": "num",
    "nombre": "nombre",
    "estatus": "estatus",
}

MAX_LIMIT = 100
DEFAULT_LIMIT = 20

PARAMS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "cliente": {
            "type": "string", "minLength": 2, "maxLength": 90,
            "description": "Nombre (o parte) del cliente/razón social. Coincidencia parcial.",
        },
        "estatus": {
            "type": "string", "minLength": 2, "maxLength": 250,
            "description": "Estatus de la guía, ej. 'Facturada', 'Por Timbrar'. Coincidencia parcial.",
        },
        "operador": {
            "type": "string", "minLength": 2, "maxLength": 60,
            "description": "Nombre (o parte) del operador asignado.",
        },
        "num_guia": {
            "type": "string", "minLength": 2, "maxLength": 15,
            "description": "Folio exacto o parcial de la guía, ej. 'PR-228806'.",
        },
        "fecha_desde": {
            "type": "string", "format": "date",
            "description": "Fecha inicial inclusive (YYYY-MM-DD).",
        },
        "fecha_hasta": {
            "type": "string", "format": "date",
            "description": "Fecha final inclusive (YYYY-MM-DD).",
        },
        "order_by": {
            "type": "string", "enum": sorted(_SORT_COLUMNS.keys()), "default": "fecha",
        },
        "order_dir": {
            "type": "string", "enum": ["asc", "desc"], "default": "desc",
        },
        "limit": {
            "type": "integer", "minimum": 1, "maximum": MAX_LIMIT, "default": DEFAULT_LIMIT,
        },
    },
    "required": [],
}

DEFINITION = CapabilityDefinition(
    id="traf.guias_listar",
    name="traf_guias_listar",
    description=(
        "Lista y filtra guías de embarque de trafico-system (SICRET) por cliente, "
        "estatus, operador, folio o rango de fechas. Solo lectura. Devuelve folio, "
        "fecha, cliente, estatus, tipo, servicio, operador, placas y factura."
    ),
    version="1.0.0",
    category="trafico",
    tags=["guias", "trafico", "sicret", "lectura"],
    required_permissions=["trafico.guias.read"],
    input_schema=PARAMS_SCHEMA,
    output_schema={
        "type": "object",
        "properties": {
            "rows": {"type": "array", "items": {"type": "object"}},
            "row_count": {"type": "integer"},
            "truncated": {"type": "boolean"},
            "filters_applied": {"type": "object"},
        },
    },
    timeout=30,
)

# Ejemplos para el prompt del Planner (entregable 3: "ejemplos").
EXAMPLES: List[Dict[str, Any]] = [
    {
        "pregunta": "¿cuáles son las últimas 5 guías?",
        "parameters": {"limit": 5, "order_by": "fecha", "order_dir": "desc"},
    },
    {
        "pregunta": "guías facturadas de septiembre de 2026",
        "parameters": {"estatus": "Facturada", "fecha_desde": "2026-09-01", "fecha_hasta": "2026-09-30"},
    },
    {
        "pregunta": "dame la guía PR-228806",
        "parameters": {"num_guia": "PR-228806"},
    },
    {
        "pregunta": "qué guías trae el operador Ruben Fernandez",
        "parameters": {"operador": "RUBEN", "limit": 20},
    },
]


def _parse_fecha(valor: str, campo: str) -> str:
    """Normaliza a 'YYYY-MM-DD'. Fecha inválida = error de parámetro, no 500."""
    try:
        return datetime.strptime(valor.strip()[:10], "%Y-%m-%d").date().isoformat()
    except (ValueError, AttributeError) as exc:
        raise CapabilityExecutionError(
            f"'{campo}' no es una fecha válida (se espera YYYY-MM-DD): {valor!r}"
        ) from exc


class GuiasListarCapability(Capability):
    """Implementación L0 de `traf.guias_listar`."""

    definition = DEFINITION
    risk_class = RiskClass.L0

    def __init__(self, pool=None) -> None:
        self.pool = pool or ro_pool

    # ----------------------------------------------------------- construcción

    def _build_query(self, p: Dict[str, Any]) -> Tuple[str, List[Any], Dict[str, Any]]:
        where: List[str] = []
        params: List[Any] = []
        aplicados: Dict[str, Any] = {}

        if p.get("cliente"):
            where.append("nombre LIKE %s")
            params.append(f"%{p['cliente'].strip()}%")
            aplicados["cliente"] = p["cliente"].strip()

        if p.get("estatus"):
            where.append("estatus LIKE %s")
            params.append(f"%{p['estatus'].strip()}%")
            aplicados["estatus"] = p["estatus"].strip()

        if p.get("operador"):
            where.append("operador LIKE %s")
            params.append(f"%{p['operador'].strip()}%")
            aplicados["operador"] = p["operador"].strip()

        if p.get("num_guia"):
            # Folio: igualdad si viene completo, prefijo si viene parcial.
            folio = p["num_guia"].strip()
            if "-" in folio and len(folio) >= 8:
                where.append("num_guia = %s")
                params.append(folio)
            else:
                where.append("num_guia LIKE %s")
                params.append(f"%{folio}%")
            aplicados["num_guia"] = folio

        if p.get("fecha_desde"):
            f = _parse_fecha(p["fecha_desde"], "fecha_desde")
            where.append("fecha >= %s")
            params.append(f"{f} 00:00:00")
            aplicados["fecha_desde"] = f

        if p.get("fecha_hasta"):
            f = _parse_fecha(p["fecha_hasta"], "fecha_hasta")
            where.append("fecha <= %s")
            params.append(f"{f} 23:59:59")
            aplicados["fecha_hasta"] = f

        order_col = _SORT_COLUMNS.get(str(p.get("order_by") or "fecha"), "fecha")
        order_dir = "ASC" if str(p.get("order_dir") or "desc").lower() == "asc" else "DESC"

        limit = int(p.get("limit") or DEFAULT_LIMIT)
        limit = max(1, min(limit, MAX_LIMIT))

        sql = f"SELECT {', '.join(_SELECT_COLUMNS)} FROM guias"
        if where:
            sql += " WHERE " + " AND ".join(where)
        # order_col y order_dir salen de mapas cerrados: no son entrada libre.
        sql += f" ORDER BY {order_col} {order_dir} LIMIT {limit}"

        aplicados["order_by"] = order_col
        aplicados["order_dir"] = order_dir.lower()
        aplicados["limit"] = limit
        return sql, params, aplicados

    @staticmethod
    def _serializar(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """datetime/date → ISO 8601, y limpieza de latin1 mal formado."""
        out: List[Dict[str, Any]] = []
        for r in rows:
            fila: Dict[str, Any] = {}
            for k, v in r.items():
                if isinstance(v, (datetime, date)):
                    fila[k] = v.isoformat()
                elif isinstance(v, bytes):
                    fila[k] = v.decode("latin1", errors="replace")
                elif isinstance(v, str):
                    fila[k] = v.strip()
                else:
                    fila[k] = v
            out.append(fila)
        return out

    # -------------------------------------------------------------- ejecución

    def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        p = dict(parameters or {})
        company = str(p.pop("company", "FORSIS")).upper()
        target = _COMPANY_TARGET.get(company)
        if target is None:
            raise CapabilityExecutionError(
                f"Empresa '{company}' sin base de datos asociada. Válidas: {sorted(_COMPANY_TARGET)}"
            )

        sql, params, aplicados = self._build_query(p)
        rows, meta = self.pool.query(
            target_key=target,
            sql=sql,
            params=params,
            max_rows=aplicados["limit"],
            timeout_ms=self.definition.timeout * 1000,
        )

        return {
            "rows": self._serializar(rows),
            "row_count": meta["row_count"],
            "truncated": meta["truncated"],
            "filters_applied": aplicados,
            "company": company,
            "source": {
                "system": "trafico-system",
                "database": meta["database"],
                "table": "guias",
                "query_ms": meta["duration_ms"],
            },
        }
