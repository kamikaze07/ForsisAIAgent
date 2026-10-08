"""
`db.consulta_analitica` — Capability analítica abierta (L0 - solo lectura).

Permite responder preguntas cuantitativas, agregaciones y consultas ad-hoc
(facturación mensual, guías por estatus, métricas por operador, promedios, conteos)
ejecutando consultas SELECT en un sandbox seguro sobre SICRET (sicrePR / sicreGero).

Seguridad:
- L0: Solo lectura (SELECT), idempotente.
- El SQL se valida contra `sql_guard.py` (rechazo de tokens de escritura y sentencias múltiples).
- Ejecución sobre `ReadOnlyPool` con usuario de solo lectura y timeout estricto.
- Límite forzado de filas (max 50 filas) para evitar desbordes de memoria.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from app.contracts.capability_definition import CapabilityDefinition
from app.core.exceptions import CapabilityExecutionError
from app.core.executor.capability import Capability
from app.core.risk import RiskClass
from app.infrastructure.db.readonly_pool import ro_pool

# Mapa empresa → base de datos destino
_COMPANY_TARGET = {"FORSIS": "sicret_pr", "GERO": "sicret_gero"}

# `fuente` permite desviar la consulta a un sistema que NO es SICRET: las
# liberaciones y el timbrado viven en ATLAS (base `atlas`), donde el solicitante
# y el aceptante son la única fuente -- en SICRET no queda registro de la
# aprobación. Sin `fuente`, se usa el destino de la empresa de la sesión
# (comportamiento por defecto, sin cambios para FORSIS/GERO).
_EMPRESA_FUENTE = {"ATLAS": "atlas"}

MAX_ROWS = 50

PARAMS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["query_sql"],
    "properties": {
        "query_sql": {
            "type": "string",
            "minLength": 10,
            "maxLength": 2000,
            "description": (
                "Consulta SQL de solo lectura (SELECT o WITH) para responder CUALQUIER pregunta "
                "de dato, conteo, monto, ranking o reporte sobre trafico (guias) o facturacion "
                "(facturas33), aunque la entidad no este en el catalogo (remolques, placas, "
                "tractocamiones, destinos, tipos de servicio). Usala SIEMPRE que la pregunta "
                "pida datos de la operacion. "
                "FECHAS: nunca escribas fechas literales ('2026-10-01', 'octubre de 2026'); el "
                "usuario dice 'este mes', 'octubre', 'este ano'. Usa siempre funciones relativas: "
                "CURDATE(), MONTH(CURDATE()), YEAR(CURDATE()), DATE_SUB(CURDATE(), INTERVAL n MONTH). "
                "Mes en curso: MONTH(fecha)=MONTH(CURDATE()) AND YEAR(fecha)=YEAR(CURDATE()). "
                "Mes nombrado DISTINTO al actual (ej. usuario dice 'septiembre' y hoy es octubre): "
                "NUNCA calcules el desplazamiento en meses a mano ni uses MAKEDATE con INTERVAL de "
                "meses inventado -- ese calculo se equivoca y acaba abarcando varios meses en vez "
                "de uno. Para 'el mes pasado' usa MONTH(fecha)=MONTH(DATE_SUB(CURDATE(), INTERVAL 1 "
                "MONTH)) AND YEAR(fecha)=YEAR(DATE_SUB(CURDATE(), INTERVAL 1 MONTH)). Para un mes "
                "nombrado explicito usa MONTH(fecha)=N AND YEAR(fecha)=YEAR(CURDATE()), con N el "
                "numero de ese mes (enero=1 ... septiembre=9 ... diciembre=12); si N es MAYOR que "
                "MONTH(CURDATE()) ese mes aun no ha ocurrido este ano, usa YEAR(CURDATE())-1. "
                "Verifica siempre que el filtro cubra UN solo mes. "
                "TABLAS: "
                "1) 'facturas33': [folio, cliente, fecha, subtotal, iva, total, moneda, estatus]. "
                "'total'/'subtotal'/'iva' son TEXTO con $ y comas ('$1,060.64'): para sumar usa "
                "CAST(REGEXP_REPLACE(total, '[$,]', '') AS DECIMAL(12,2)). Monedas: 'USD' y 'MXN'. "
                "Excluir canceladas: estatus NOT LIKE '%Cancelada%'. "
                "2) 'guias': [num_guia, num_llama, fecha, nombre, estatus, operador, tipo, servicio, "
                "placas1, placas2, factura]. "
                "CLIENTES: la tabla 'clientes' NO EXISTE y 'guias.nombre' es elpersonal que capturo "
                "la guia, NUNCA el cliente. Para clientes haz JOIN: "
                "FROM guias g LEFT JOIN llamadas_historicas lh ON lh.num_llama = g.num_llama "
                "LEFT JOIN emp_generadora eg ON eg.clave_gene = lh.clave_gene "
                "y usa COALESCE(eg.empresa, 'SIN CLIENTE') AS cliente. "
                "REMOLQUES: no hay columna 'remolque'; 'placas1' es el tractor y 'placas2' el remolque, "
                "pero desde sept-2026 'placas2' viene vacia en todas las guias y las guias del mes "
                "actual aun no se timbran, asi que un reporte de remolques NO es posible: decláralo "
                "en 'descripcion' en vez de inventar un ranking. Para tractores si funciona 'placas1'. "
                "3) 'operadores': [num_ope, nombre, ap_pat, ap_mat, actual]. El nombre viene "
                "PARTIDO en 3 columnas: para buscar por nombre completo usa "
                "CONCAT_WS(' ', nombre, ap_pat, ap_mat) LIKE '%X%'; 'actual'=1 son vigentes. "
                "CUALQUIER OTRA TABLA (deudas, saldos, tarjetas, viaticos, remolques, rutas, "
                "nominas...): NO la adivines. SICRET tiene mas de 130 tablas y aqui solo se "
                "documentan las 3 anteriores. Si la pregunta pide un dato que no esta en ellas, "
                "tu PRIMER paso debe ser db_explorar_esquema para localizar la tabla y sus "
                "columnas REALES, y solo despues escribes el SELECT. Al inspeccionar una tabla "
                "nueva, revisa el tipo de cada columna: en SICRET los importes suelen venir como "
                "TEXTO con $ y comas y hay que envolverlos en "
                "CAST(REGEXP_REPLACE(col, '[$,]', '') AS DECIMAL(12,2)), y varios campos de "
                "estatus traen delimitadores propios, asi que filtralos con LIKE '%VALOR%' en "
                "vez de con igualdad exacta. "
                "Sin comentarios ni punto y coma. Usa GROUP BY al agregar. "
                "'descripcion' debe reflejar el periodo REAL consultado segun el servidor, no el "
                "que escribio el usuario."
            ),
        },
        "descripcion": {
            "type": "string",
            "maxLength": 600,
            "description": "Breve descripción de la métrica o cálculo que realiza la consulta.",
        },
        "fuente": {
            "type": "string",
            "enum": ["ATLAS"],
            "description": (
                "Sistema a consultar. OMITIR para los datos de la empresa de la sesión "
                "(SICRET: guías, operadores, facturación). Usa 'ATLAS' SÓLO para "
                "liberaciones y timbrado: ahí están las tablas solicitud_liberacion* "
                "y solicitud_timbrado*, y es el ÚNICO lugar donde existe quién pidió "
                "una liberación y quién la aceptó."
            ),
        },
    },
}

DEFINITION = CapabilityDefinition(
    id="db.consulta_analitica",
    name="db_consulta_analitica",
    description=(
        "Ejecuta consultas analíticas SELECT en la base de datos de Tráfico/Facturación (SICRET) "
        "para responder preguntas sobre facturación, totales, promedios, conteos, sumatorias por divisa "
        "y métricas operativas ad-hoc. Solo lectura validada por sandbox."
    ),
    version="1.0.0",
    category="analitica",
    tags=["analitica", "facturacion", "metricas", "sql", "lectura"],
    required_permissions=["analitica.consultar"],
    input_schema=PARAMS_SCHEMA,
    output_schema={
        "type": "object",
        "properties": {
            "rows": {"type": "array", "items": {"type": "object"}},
            "row_count": {"type": "integer"},
            "truncated": {"type": "boolean"},
            "query_sql": {"type": "string"},
            "descripcion": {"type": "string"},
        },
    },
    timeout=30,
)

EXAMPLES: List[Dict[str, Any]] = [
    {
        "pregunta": "¿cuánto se ha facturado en este mes de octubre?",
        "parameters": {
            "query_sql": (
                "SELECT moneda, COUNT(*) AS facturas, "
                "SUM(CAST(REGEXP_REPLACE(total, '[$,]', '') AS DECIMAL(12,2))) AS total_facturado "
                "FROM facturas33 "
                "WHERE fecha >= '2026-10-01 00:00:00' AND fecha <= '2026-10-31 23:59:59' "
                "AND estatus NOT LIKE '%Cancelada%' "
                "GROUP BY moneda"
            ),
            "descripcion": "Total facturado en octubre de 2026 por moneda",
        },
    },
    {
        "pregunta": "¿cuántas facturas se emitieron hoy?",
        "parameters": {
            "query_sql": (
                "SELECT moneda, COUNT(*) AS total_facturas, "
                "SUM(CAST(REGEXP_REPLACE(total, '[$,]', '') AS DECIMAL(12,2))) AS total "
                "FROM facturas33 "
                "WHERE DATE(fecha) = CURDATE() AND estatus NOT LIKE '%Cancelada%' "
                "GROUP BY moneda"
            ),
            "descripcion": "Facturas emitidas hoy agrupadas por moneda",
        },
    },
    {
        "pregunta": "¿cuántas guías activas hay por estatus?",
        "parameters": {
            "query_sql": (
                "SELECT estatus, COUNT(*) AS total "
                "FROM guias "
                "WHERE fecha >= DATE_SUB(CURDATE(), INTERVAL 30 DAY) "
                "GROUP BY estatus "
                "ORDER BY total DESC "
                "LIMIT 10"
            ),
            "descripcion": "Top de estatus de guías en los últimos 30 días",
        },
    },
    {
        "pregunta": "¿cuántos viajes ha hecho cada operador este mes?",
        "parameters": {
            "query_sql": (
                "SELECT operador, COUNT(*) AS total_viajes "
                "FROM guias "
                "WHERE fecha >= '2026-10-01 00:00:00' "
                "AND operador IS NOT NULL AND operador != '' "
                "GROUP BY operador "
                "ORDER BY total_viajes DESC "
                "LIMIT 10"
            ),
            "descripcion": "Top 10 operadores con más viajes en octubre",
        },
    },
    {
        "pregunta": "¿cuántas guías se generaron este mes y de qué clientes?",
        "parameters": {
            "query_sql": (
                "SELECT COALESCE(eg.empresa, 'SIN CLIENTE') AS cliente, "
                "COUNT(*) AS total_guias "
                "FROM guias g "
                "LEFT JOIN llamadas_historicas lh ON lh.num_llama = g.num_llama "
                "LEFT JOIN emp_generadora eg ON eg.clave_gene = lh.clave_gene "
                "WHERE MONTH(g.fecha) = MONTH(CURDATE()) AND YEAR(g.fecha) = YEAR(CURDATE()) "
                "GROUP BY COALESCE(eg.empresa, 'SIN CLIENTE') "
                "ORDER BY total_guias DESC "
                "LIMIT 20"
            ),
            "descripcion": "Guías generadas en el mes en curso agrupadas por cliente",
        },
    },
    {
        "pregunta": "puedes darme un reporte de los remolques mas utilizados este mes?",
        "parameters": {
            "query_sql": (
                "SELECT COALESCE(NULLIF(placas2, ''), 'SIN REMOLQUE') AS remolque, "
                "COUNT(*) AS viajes "
                "FROM guias "
                "WHERE MONTH(fecha) = MONTH(CURDATE()) AND YEAR(fecha) = YEAR(CURDATE()) "
                "GROUP BY COALESCE(NULLIF(placas2, ''), 'SIN REMOLQUE') "
                "ORDER BY viajes DESC "
                "LIMIT 20"
            ),
            "descripcion": "Remolques en el mes en curso, con vacíos declarados como SIN REMOLQUE",
        },
    },
    {
        # Encadenamiento entre bases: el patron generico que sustituye a los
        # few-shot por pregunta concreta. Ensena la MECANICA (un paso por base,
        # valores del paso 1 incrustados en el SQL del paso 2), no un dominio.
        "pregunta": "¿cuánto se facturó este mes excluyendo los CFDI liberados en ATLAS?",
        "parameters": {
            "query_sql": (
                "SELECT DISTINCT d.cfdi_nuevo_folio AS folio "
                "FROM solicitud_liberacion_detalle d "
                "JOIN solicitud_liberacion s ON s.id = d.solicitud_id "
                "WHERE s.estado = 'COMPLETADA' AND d.cfdi_nuevo_folio IS NOT NULL"
            ),
            "descripcion": (
                "PASO 1 de 2: folios de CFDI efectivamente liberados en ATLAS. "
                "El PASO 2 consultara facturas33 en SICRET con esos folios "
                "literales en un NOT IN, porque ambas bases no se pueden unir "
                "en un mismo SQL"
            ),
            "fuente": "ATLAS",
        },
    },
    {
        "pregunta": "quien ha solicitado mas liberaciones en los ultimos 3 meses?",
        "parameters": {
            "query_sql": (
                "SELECT h.actor AS solicitante, COUNT(*) AS solicitudes "
                "FROM solicitud_liberacion s "
                "JOIN solicitud_liberacion_historial h "
                "  ON h.solicitud_id = s.id AND h.evento = 'CREADA' "
                "WHERE s.created_at >= DATE_SUB(CURDATE(), INTERVAL 3 MONTH) "
                "GROUP BY h.actor ORDER BY solicitudes DESC LIMIT 20"
            ),
            "descripcion": "Solicitantes de liberaciones en los ultimos 3 meses",
            "fuente": "ATLAS",
        },
    },
    {
        # Mes nombrado explicito: filtro de UN solo mes con MONTH()/YEAR(),
        # nunca aritmetica de meses a mano (MAKEDATE + INTERVAL calculado se
        # desborda a rangos de varios meses y falsea el conteo).
        "pregunta": "cuantas solicitudes de liberacion hubo en septiembre y quien las solicito?",
        "parameters": {
            "query_sql": (
                "SELECT h.actor AS solicitante, COUNT(DISTINCT s.id) AS solicitudes "
                "FROM solicitud_liberacion s "
                "JOIN solicitud_liberacion_historial h "
                "  ON h.solicitud_id = s.id AND h.evento = 'CREADA' "
                "WHERE MONTH(s.created_at) = 9 AND YEAR(s.created_at) = YEAR(CURDATE()) "
                "GROUP BY h.actor ORDER BY solicitudes DESC LIMIT 20"
            ),
            "descripcion": "Solicitantes de liberaciones en septiembre del ano en curso",
            "fuente": "ATLAS",
        },
    },
]


class ConsultaSqlCapability(Capability):
    """Implementación de la capability analítica abierta sobre SICRET."""

    definition = DEFINITION

    def __init__(self, pool=None) -> None:
        self.pool = pool or ro_pool

    @staticmethod
    def _serializar(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """datetime/date → ISO 8601, Decimal → float/str, y bytes a string decodificado."""
        out: List[Dict[str, Any]] = []
        for r in rows:
            fila: Dict[str, Any] = {}
            for k, v in r.items():
                if isinstance(v, (datetime, date)):
                    fila[k] = v.isoformat()
                elif isinstance(v, Decimal):
                    fila[k] = float(v)
                elif isinstance(v, bytes):
                    fila[k] = v.decode("latin1", errors="replace")
                elif isinstance(v, str):
                    fila[k] = v.strip()
                else:
                    fila[k] = v
            out.append(fila)
        return out

    def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        p = dict(parameters or {})
        company = str(p.pop("company", "FORSIS")).upper()
        fuente = str(p.pop("fuente", "") or "").strip().upper()
        if fuente:
            target = _EMPRESA_FUENTE.get(fuente)
            if target is None:
                raise CapabilityExecutionError(
                    f"Fuente '{fuente}' desconocida. Válidas: {sorted(_EMPRESA_FUENTE)}"
                )
        else:
            target = _COMPANY_TARGET.get(company)
            if target is None:
                raise CapabilityExecutionError(
                    f"Empresa '{company}' sin base de datos asociada. "
                    f"Válidas: {sorted(_COMPANY_TARGET)}"
                )

        query_sql = str(p.get("query_sql", "")).strip()
        if not query_sql:
            raise CapabilityExecutionError("El parámetro 'query_sql' es obligatorio.")

        descripcion = str(p.get("descripcion", "")).strip()
        # La descripción es metadato explicativo, no un dato de negocio: si el
        # modelo se extiende (p.ej. al justificar por qué una métrica no es
        # consultable), se recorta. Nunca debe invalidar un resultado correcto
        # ya calculado -- antes un texto de 290 chars abortaba toda la consulta.
        if len(descripcion) > 600:
            descripcion = descripcion[:597].rstrip() + "..."

        timeout_s = int(self.definition.timeout or 30) if self.definition else 30
        rows, meta = self.pool.query(
            target_key=target,
            sql=query_sql,
            max_rows=MAX_ROWS,
            timeout_ms=timeout_s * 1000,
        )

        return {
            "rows": self._serializar(rows),
            "row_count": meta["row_count"],
            "truncated": meta["truncated"],
            "query_sql": query_sql,
            "descripcion": descripcion,
            "company": company,
            "source": {
                "system": "sicret",
                "database": meta["database"],
                "query_ms": meta["duration_ms"],
            },
        }
