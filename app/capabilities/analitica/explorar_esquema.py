"""
`db.explorar_esquema` — Introspección de catálogo (L0 · sólo lectura).

Resuelve la pregunta previa a cualquier consulta: *¿qué tablas y columnas
existen realmente?* Sin esto el planificador sólo conoce el esquema que
alguien transcribió a mano en el prompt de `consulta_sql`, así que cualquier
tabla nueva —o cualquier dato que viva en otra base— es invisible para el
agente por más que tenga credenciales de lectura.

Lee exclusivamente `information_schema`: nombres de tablas, columnas, tipos y
comentarios. Nunca devuelve filas de negocio, así que no hay superficie de
fuga de datos: el peor caso es revelar que una columna existe.

Se consulta `information_schema` y NO `SHOW TABLES` porque el sandbox
(`ReadOnlyPool._enforce_limit`) añade `LIMIT` a toda consulta sin uno, y
MySQL/MariaDB rechaza `SHOW TABLES ... LIMIT n` con error 1064.
"""

from __future__ import annotations

from typing import Any, Dict, List

from app.contracts.capability_definition import CapabilityDefinition
from app.core.exceptions import CapabilityExecutionError
from app.core.executor.capability import Capability
from app.infrastructure.db.readonly_pool import ro_pool

# Mismos destinos que la capability analítica: un único mapa mental para el
# modelo. Si puede consultar una fuente, puede explorar su esquema.
_COMPANY_TARGET = {"FORSIS": "sicret_pr", "GERO": "sicret_gero"}
_FUENTE_TARGET = {"ATLAS": "atlas", "TRAFICO": "trafico"}

MAX_FILAS = 120

PARAMS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "buscar": {
            "type": "string",
            "maxLength": 60,
            "description": (
                "Palabra o fragmento a buscar en los nombres de tabla/columna "
                "(p.ej. 'liberacion', 'factura', 'operador'). Omitir para listar todo."
            ),
        },
        "tabla": {
            "type": "string",
            "maxLength": 64,
            "description": (
                "Nombre EXACTO de una tabla. Si se indica, devuelve sus columnas "
                "con tipo. Si se omite, devuelve la lista de tablas que coinciden "
                "con 'buscar'."
            ),
        },
        "fuente": {
            "type": "string",
            "enum": ["ATLAS", "TRAFICO"],
            "description": (
                "Sistema cuyo esquema explorar. OMITIR para la base de la empresa "
                "de la sesión (SICRET). 'ATLAS' para liberaciones y timbrado."
            ),
        },
    },
}

DEFINITION = CapabilityDefinition(
    id="db.explorar_esquema",
    name="db_explorar_esquema",
    description=(
        "Explora el catálogo de la base de datos: qué tablas existen y qué columnas "
        "tiene una tabla, con sus tipos. Úsala ANTES de consultar cuando no sepas "
        "con certeza el nombre de una tabla o columna, o cuando una consulta falle "
        "porque algo no existe. Sólo devuelve nombres de estructura, nunca datos."
    ),
    version="1.0.0",
    category="analitica",
    tags=["esquema", "introspeccion", "catalogo", "lectura"],
    required_permissions=["analitica.consultar"],
    input_schema=PARAMS_SCHEMA,
    output_schema={
        "type": "object",
        "properties": {
            "modo": {"type": "string"},
            "rows": {"type": "array", "items": {"type": "object"}},
            "row_count": {"type": "integer"},
        },
    },
    timeout=20,
)

EXAMPLES: List[Dict[str, Any]] = [
    {
        "pregunta": "¿qué tablas hay sobre liberaciones?",
        "parameters": {"buscar": "liberacion", "fuente": "ATLAS"},
    },
    {
        "pregunta": "¿qué columnas tiene la tabla guias?",
        "parameters": {"tabla": "guias"},
    },
]


class ExplorarEsquemaCapability(Capability):
    """Introspección de `information_schema` acotada a la base del destino."""

    definition = DEFINITION

    def __init__(self, pool=None) -> None:
        self.pool = pool or ro_pool

    def _target(self, company: str, fuente: str) -> str:
        if fuente:
            target = _FUENTE_TARGET.get(fuente)
            if target is None:
                raise CapabilityExecutionError(
                    f"Fuente '{fuente}' desconocida. Válidas: {sorted(_FUENTE_TARGET)}"
                )
            return target
        target = _COMPANY_TARGET.get(company)
        if target is None:
            raise CapabilityExecutionError(
                f"Empresa '{company}' sin base asociada. Válidas: {sorted(_COMPANY_TARGET)}"
            )
        return target

    def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        p = dict(parameters or {})
        company = str(p.pop("company", "FORSIS")).upper()
        fuente = str(p.pop("fuente", "") or "").strip().upper()
        target = self._target(company, fuente)

        buscar = str(p.get("buscar", "") or "").strip()
        tabla = str(p.get("tabla", "") or "").strip()

        # Los identificadores no se interpolan: van como parámetros ligados, de
        # modo que un nombre de tabla inventado por el LLM no puede alterar la
        # forma de la consulta.
        if tabla:
            modo = "columnas"
            sql = (
                "SELECT column_name AS columna, column_type AS tipo, "
                "is_nullable AS acepta_nulos, column_comment AS comentario "
                "FROM information_schema.columns "
                "WHERE table_schema = DATABASE() AND table_name = %s "
                "ORDER BY ordinal_position"
            )
            args: tuple = (tabla,)
        else:
            modo = "tablas"
            if buscar:
                sql = (
                    "SELECT table_name AS tabla, table_rows AS filas_aprox "
                    "FROM information_schema.tables "
                    "WHERE table_schema = DATABASE() AND table_name LIKE %s "
                    "ORDER BY table_rows DESC"
                )
                args = (f"%{buscar}%",)
            else:
                sql = (
                    "SELECT table_name AS tabla, table_rows AS filas_aprox "
                    "FROM information_schema.tables "
                    "WHERE table_schema = DATABASE() "
                    "ORDER BY table_rows DESC"
                )
                args = ()

        rows, meta = self.pool.query(
            target_key=target,
            sql=sql,
            params=args,
            max_rows=MAX_FILAS,
            timeout_ms=int(self.definition.timeout or 20) * 1000,
        )

        # information_schema devuelve las claves en mayúsculas en algunos
        # motores; se normalizan para que el compositor no dependa de eso.
        limpias: List[Dict[str, Any]] = []
        for r in rows:
            limpias.append({str(k).lower(): ("" if v is None else v) for k, v in r.items()})

        return {
            "modo": modo,
            "rows": limpias,
            "row_count": meta["row_count"],
            "truncated": meta["truncated"],
            "tabla": tabla,
            "buscar": buscar,
            "company": company,
            "source": {
                "system": "atlas" if target == "atlas" else "sicret",
                "database": meta["database"],
                "query_ms": meta["duration_ms"],
            },
        }