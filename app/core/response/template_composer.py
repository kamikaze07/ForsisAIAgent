"""
TemplateComposer determinista (agent-core.md §4.2 D-4).
Genera respuestas en español sin depender del LLM cuando:
- La consulta es smalltalk (saludos, despedidas, etc.).
- El LLM composer falla, devuelve formato inválido o supera el timeout.
- El agente opera en modo degradado o de contingencia.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from app.contracts.chat_contract import ResponseStatus
from app.core.smalltalk.smalltalk import detect_response as detect_smalltalk

logger = logging.getLogger(__name__)


class TemplateComposer:
    """Compositor determinista basado en plantillas fijas y smalltalk."""

    @staticmethod
    def compose_smalltalk(message: str) -> Optional[str]:
        """Devuelve respuesta determinista si es smalltalk, o None si es consulta de negocio."""
        return detect_smalltalk(message)

    @staticmethod
    def compose_fallback(
        status: ResponseStatus,
        message: str = "",
        error_detail: Optional[str] = None,
        tasks_count: int = 0,
    ) -> str:
        """Respuesta determinista según estado de respuesta."""
        if status == ResponseStatus.NO_CAPABILITY:
            return (
                "No encontré una herramienta o capacidad disponible para responder esa consulta directamente. "
                "Por favor formula tu pregunta sobre guías, operadores, unidades, remolques, facturas o clientes."
            )

        if status == ResponseStatus.CLARIFICATION_NEEDED:
            return "Se requiere información adicional para procesar tu consulta. Por favor proporciona más detalles."

        if status == ResponseStatus.CONFIRMATION_REQUIRED:
            return "Esta operación requiere confirmación explícita antes de ejecutarse."

        if status == ResponseStatus.DENIED:
            return "No tienes los permisos requeridos para ejecutar esta consulta o acción."

        if status == ResponseStatus.DEGRADED:
            return "El servicio se encuentra operando en modo degradado. Por favor reintenta en unos momentos."

        if status == ResponseStatus.ERROR:
            if error_detail:
                return f"Ocurrió un error al procesar la solicitud: {error_detail}"
            return "Ocurrió un error interno al procesar tu solicitud. Por favor intenta de nuevo."

        # Status OK por defecto sin tareas
        if tasks_count == 0:
            return "Entendido. ¿En qué más puedo ayudarte respecto a tráfico o liquidaciones?"

        return "Operación procesada correctamente."

    @staticmethod
    def compose_from_tasks(
        message: str,
        tasks_summary: List[str],
    ) -> str:
        """Renderiza resumen de tareas procesadas."""
        if not tasks_summary:
            return "No se obtuvieron resultados para tu consulta."
        return "\n".join(tasks_summary)

    # ------------------------------------------------------------------
    # Sprint 3 — composición determinista a partir del resultado de una tool.
    # El LLM NO redacta estas respuestas: los datos de negocio se renderizan
    # con plantillas para que ninguna cifra pueda ser alucinada. El modelo
    # elige la herramienta; el código presenta el resultado.
    # ------------------------------------------------------------------

    # Etiquetas legibles por columna de `guias`.
    _GUIA_LABELS = {
        "num_guia": "Guía",
        "fecha": "Fecha",
        "nombre": "Cliente",
        "estatus": "Estatus",
        "estado": "Estado",
        "tipo": "Tipo",
        "servicio": "Servicio",
        "operador": "Operador",
        "placas1": "Placas",
        "factura": "Factura",
        "linea": "Línea",
    }

    @staticmethod
    def _fmt_fecha(valor: Any) -> str:
        """'2026-10-05T15:49:39' → '05/10/2026 15:49'."""
        if not valor:
            return "—"
        texto = str(valor)
        try:
            from datetime import datetime as _dt
            d = _dt.fromisoformat(texto)
            return d.strftime("%d/%m/%Y %H:%M")
        except (ValueError, TypeError):
            return texto

    @staticmethod
    def _limpiar(valor: Any) -> str:
        """Quita los delimitadores <> con que SICRET guarda los estatus."""
        if valor is None or valor == "":
            return "—"
        return str(valor).strip().strip("<>").strip() or "—"

    @classmethod
    def compose_guias(cls, data: Dict[str, Any]) -> tuple[str, List[Dict[str, Any]]]:
        """
        Devuelve `(answer, components)` para un resultado de `traf.guias_listar`.
        `components` sigue el contrato `UIComponent` de `channels.md` §1.5.
        """
        rows: List[Dict[str, Any]] = data.get("rows") or []
        filtros = data.get("filters_applied") or {}
        empresa = data.get("company", "FORSIS")

        descripcion = []
        if filtros.get("cliente"):
            descripcion.append(f"cliente «{filtros['cliente']}»")
        if filtros.get("estatus"):
            descripcion.append(f"estatus «{filtros['estatus']}»")
        if filtros.get("operador"):
            descripcion.append(f"operador «{filtros['operador']}»")
        if filtros.get("num_guia"):
            descripcion.append(f"folio «{filtros['num_guia']}»")
        if filtros.get("fecha_desde") and filtros.get("fecha_hasta"):
            descripcion.append(f"del {filtros['fecha_desde']} al {filtros['fecha_hasta']}")
        elif filtros.get("fecha_desde"):
            descripcion.append(f"desde {filtros['fecha_desde']}")
        elif filtros.get("fecha_hasta"):
            descripcion.append(f"hasta {filtros['fecha_hasta']}")
        criterio = " con " + ", ".join(descripcion) if descripcion else ""

        if not rows:
            return (
                f"No encontré guías de {empresa}{criterio}.",
                [],
            )

        n = len(rows)
        plural = "guía" if n == 1 else "guías"
        encabezado = f"Encontré {n} {plural} de {empresa}{criterio}:"
        if data.get("truncated"):
            encabezado += f" (mostrando las primeras {n})"

        lineas = [encabezado, ""]
        for r in rows:
            lineas.append(
                f"• {cls._limpiar(r.get('num_guia'))} — {cls._fmt_fecha(r.get('fecha'))} — "
                f"{cls._limpiar(r.get('nombre'))} — {cls._limpiar(r.get('estatus'))}"
            )

        # Un componente `table` con las filas, más una card por guía cuando el
        # resultado es único (caso "dame la guía PR-228806").
        _COLS_GUIA = ("num_guia", "fecha", "nombre", "estatus")
        componentes: List[Dict[str, Any]] = [{
            "type": "table",
            "title": f"Guías {empresa}",
            "columns": [
                {"key": k, "label": cls._GUIA_LABELS.get(k, k), "align": "left"}
                for k in _COLS_GUIA
            ],
            "rows": [
                {
                    k: cls._limpiar(
                        cls._fmt_fecha(r.get(k)) if k == "fecha" else r.get(k)
                    )
                    for k in _COLS_GUIA
                }
                for r in rows
            ],
            "actions": [],
        }]

        if n == 1:
            r = rows[0]
            componentes = [{
                "type": "card",
                "title": f"Guía {cls._limpiar(r.get('num_guia'))}",
                "fields": [
                    {"label": cls._GUIA_LABELS.get(k, k),
                     "value": cls._fmt_fecha(r.get(k)) if k == "fecha" else cls._limpiar(r.get(k))}
                    for k in ("num_guia", "fecha", "nombre", "estatus", "tipo",
                              "servicio", "operador", "placas1", "factura", "linea")
                    if r.get(k) not in (None, "", 0)
                ],
                "actions": [],
            }]

        return "\n".join(lineas), componentes

    @classmethod
    def compose_tool_outcome(cls, tool_id: str, outcome: Any) -> tuple[str, List[Dict[str, Any]]]:
        """
        Despacho por capability. Una tool sin renderizador propio cae en una
        presentación genérica en vez de quedar sin respuesta.
        """
        if outcome.status == "denied":
            return (
                outcome.error_message
                or "No tienes los permisos requeridos para ejecutar esa operación.",
                [],
            )

        if outcome.status != "ok":
            detalle = outcome.error_message or "la herramienta no pudo completarse"
            return (
                f"No pude completar la consulta en este momento: {detalle} "
                "Los demás datos de la conversación siguen disponibles.",
                [],
            )

        data = outcome.data or {}
        if tool_id == "traf.guias_listar":
            return cls.compose_guias(data)
        if tool_id == "db.consulta_analitica":
            return cls.compose_consulta_analitica(data)
        if tool_id == "db.explorar_esquema":
            return cls.compose_esquema(data)

        # Genérico: nº de filas y nada inventado.
        rc = data.get("row_count")
        if rc is not None:
            return (f"La consulta devolvió {rc} registro(s).", [])
        return ("Consulta ejecutada correctamente.", [])

    @classmethod
    def compose_esquema(cls, data: Dict[str, Any]) -> tuple[str, List[Dict[str, Any]]]:
        """Renderizado de `db.explorar_esquema` (estructura, nunca datos).

        Es un paso intermedio de exploración: el usuario rara vez pregunta "qué
        columnas hay", así que el texto se mantiene escueto y la estructura va
        en el componente de tabla.
        """
        rows = data.get("rows") or []
        modo = str(data.get("modo") or "tablas")
        base = str((data.get("source") or {}).get("database") or "")

        if not rows:
            if modo == "columnas":
                return (
                    f"La tabla '{data.get('tabla')}' no existe en la base {base} "
                    "(o no tiene columnas visibles para el agente).",
                    [],
                )
            buscado = data.get("buscar")
            detalle = f" que coincidan con '{buscado}'" if buscado else ""
            return (f"No hay tablas{detalle} en la base {base}.", [])

        if modo == "columnas":
            columnas = [
                {"key": "columna", "label": "Columna", "align": "left"},
                {"key": "tipo", "label": "Tipo", "align": "left"},
                {"key": "acepta_nulos", "label": "Nulos", "align": "center"},
            ]
            texto = f"La tabla '{data.get('tabla')}' tiene {len(rows)} columna(s) en {base}."
        else:
            columnas = [
                {"key": "tabla", "label": "Tabla", "align": "left"},
                {"key": "filas_aprox", "label": "Filas aprox.", "align": "right"},
            ]
            texto = f"Encontré {len(rows)} tabla(s) en la base {base}."

        claves = [c["key"] for c in columnas]
        filas = [{k: str(r.get(k, "")) for k in claves} for r in rows]

        return (
            texto,
            [
                {
                    "type": "table",
                    "title": "Estructura de la base de datos",
                    "fields": [],
                    "columns": columnas,
                    "rows": filas,
                }
            ],
        )

    @staticmethod
    def _periodo_real(data: Dict[str, Any], desc: str) -> str:
        """
        Corrige el periodo que el LLM escribió en `descripcion`.

        El LLM puede redactar "en mayo" cuando la consulta usó funciones
        relativas que en realidad apuntan a octubre: la descripción es texto
        generado, no evidencia. Cuando el SQL trae el periodo del servidor se
        reescribe el texto con esa verdad, para que el usuario vea el mes que
        realmente se consultó y no el que el modelo imaginó.
        """
        sql = str(data.get("query_sql") or "").lower()
        if not sql:
            return desc

        from datetime import datetime
        from zoneinfo import ZoneInfo

        ahora = datetime.now(ZoneInfo("America/Mexico_City"))
        meses = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
                 "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
        mes_actual = meses[ahora.month - 1]
        anio_actual = str(ahora.year)

        # ¿La consulta se ancla al mes/año del servidor? Se buscan los
        # identificadores sin exigir el paréntesis: el SQL real trae
        # "MONTH(fecha)=MONTH(CURDATE())", y `split()` deja "curdate())".
        usa_mes_relativo = bool(
            re.search(r"\b(curdate|curmonth|curyear|current_date|current_timestamp)\s*\(",
                      sql)
        )

        # Un desplazamiento explícito de fecha ("mes anterior", "últimos 30
        # días") usa CURDATE() como ANCLA, no como periodo objetivo: el SQL
        # apunta a propósito a otro mes. Reescribir "septiembre" a "octubre"
        # en ese caso convierte una descripción correcta en una falsa, así que
        # ante un desplazamiento se respeta el texto del modelo.
        desplaza_fecha = bool(
            re.search(r"\b(interval|date_sub|date_add|subdate|adddate|last_day)\b", sql)
        )

        # Un mes LITERAL en el filtro ("MONTH(created_at) = 9") es la verdad
        # del periodo consultado, aunque el año venga de YEAR(CURDATE()). Si el
        # SQL dice 9 y la descripción dice "septiembre", no hay nada que
        # corregir: reescribirlo a "octubre" inventaría un periodo que la
        # consulta nunca cubrió.
        mes_literal = re.search(r"\bmonth\s*\([^)]*\)\s*(?:=|in)\s*\(?\s*(\d{1,2})", sql)
        if mes_literal:
            idx = int(mes_literal.group(1))
            if 1 <= idx <= 12 and meses[idx - 1] in desc.lower():
                return desc

        if usa_mes_relativo and not desplaza_fecha:
            # Sólo se corrige si el texto nombra un periodo explícito que no
            # coincide con el actual; si dice "este mes", se precisa.
            for m in meses:
                if m in desc.lower() and m != mes_actual:
                    # Si el texto ya trae el año junto al mes ("septiembre 2026",
                    # "septiembre de 2026"), se sustituye el bloque completo:
                    # reemplazar sólo el mes dejaría "octubre de 2026 de 2026".
                    return re.sub(
                        r"\b%s\b(\s+de\b)?(\s+\d{4})?" % m,
                        "%s de %s" % (mes_actual, anio_actual),
                        desc,
                        count=1,
                        flags=re.IGNORECASE,
                    )
            # El artículo contraído se absorbe en la sustitución: "del mes
            # actual" -> "de octubre de 2026", no "del octubre de 2026".
            if re.search(r"(del|de el|de)?\s*\b(mes actual|este mes)\b", desc, re.IGNORECASE):
                return re.sub(
                    r"\b(?:del|de el|de)\s+(?:mes actual|este mes)\b|\b(?:mes actual|este mes)\b",
                    "de %s de %s" % (mes_actual, anio_actual),
                    desc,
                    count=1,
                    flags=re.IGNORECASE,
                )
        return desc

    @classmethod
    def compose_consulta_analitica(cls, data: Dict[str, Any]) -> tuple[str, List[Dict[str, Any]]]:
        """Renderizado de db.consulta_analitica (agregaciones o tablas cuantitativas).

        El texto NO lleva tabla markdown: los canales insertan `answer` como
        texto escapado, de modo que los pipes se verían literales. La tabla va
        como componente estructurado y el texto queda como frase legible.
        """
        from decimal import Decimal

        rows: List[Dict[str, Any]] = data.get("rows") or []
        rc = data.get("row_count", len(rows))
        desc = (data.get("descripcion") or "Resultado de la consulta").rstrip(":.")
        desc = cls._periodo_real(data, desc)

        if rc == 0 or not rows:
            return ("No se encontraron registros para la consulta solicitada.", [])

        # Columna de agrupación degenerada: una sola categoría que absorbió TODOS
        # los registros ("SIN REMOLQUE 154", "SIN CLIENTE 100", "SIN REGISTRO 8").
        # Eso no es un ranking, es una columna sin datos capturados: presentarlo
        # como tabla de "top" miente sobre el periodo consultado.
        _PLACEHOLDERS = (
            "sin remolque", "sin cliente", "sin registro", "sin unidad",
            "sin operador", "sin destino", "sin origen", "sin nombre",
            "sin placa", "sin tractor", "sin valor", "n/a", "na", "null",
            "none", "desconocido", "no especificado", "(vacio)", "vacio",
        )

        def _es_placeholder(v: Any) -> bool:
            t = str(v or "").strip().strip("<>").lower()
            if not t:
                return True
            return any(t == p or t.startswith(p + " ") or t.startswith(p + "-")
                       for p in _PLACEHOLDERS)

        # `row_count` es 1 (el GROUP BY colapsó todo en una categoría), así que
        # la condición no puede apoyarse en el volumen: se basa en que la única
        # etiqueta sea un marcador de "sin dato".
        if len(rows) == 1 and len(rows[0]) == 2:
            solo_clave = list(rows[0].keys())[0]
            if _es_placeholder(rows[0].get(solo_clave)):
                clave = solo_clave.replace("_", " ").strip()
                total = next(iter(rows[0].values()))
                return (
                    "No es posible construir ese ranking: la columna «%s» no tiene datos "
                    "capturados en el periodo. Las %s guías consultadas la tienen vacía, "
                    "así que no hay nada que ordenar." % (clave, total),
                    [],
                )

        headers = list(rows[0].keys())

        MONETARIAS = ("monto", "subtotal", "iva", "retencion",
                      "saldo", "importe", "precio", "facturado", "moneda",
                      "usd", "mxn", "costo", "pago")
        # Un conteo también se llama "total_facturas" o "total_liberaciones": las
        # palabras de conteo tienen prioridad sobre las monetarias, o un COUNT(*)
        # saldría como "$4.00". `total` a secas ES un conteo salvo que el nombre
        # déclare una unidad monetaria explícita (total_monto, total_usd...),
        # porque en una consulta analítica "total" casi siempre es COUNT(*) y
        # formatearlo como dinero inventa un importe que no existe.
        CONTEO = ("conteo", "cantidad", "count", "num_", "_num", "numero",
                  "registros", "facturas", "guias", "liberaciones", "viajes",
                  "solicitudes", "total_filas", "detalle", "documentos")

        def _es_monetaria(k: str) -> bool:
            kl = k.lower()
            if any(w in kl for w in CONTEO):
                return False
            return any(w in kl for w in MONETARIAS)

        def _numerica(k: str) -> bool:
            for r in rows:
                v = r.get(k)
                if v is not None:
                    return isinstance(v, (int, float, Decimal)) and not isinstance(v, bool)
            return False

        def _etiqueta(k: str) -> str:
            return k.replace("_", " ").strip().capitalize()

        def _fmt_val(k: str, v: Any) -> str:
            if v is None:
                return "—"
            if isinstance(v, bool):
                return "Sí" if v else "No"
            if isinstance(v, (float, Decimal)):
                return (f"${v:,.2f}" if _es_monetaria(k) else f"{v:,.2f}")
            if isinstance(v, int):
                return (f"${v:,.2f}" if _es_monetaria(k) else f"{v:,}")
            return str(v).strip().strip("<>") or "—"

        # ------------------------------------------------- texto (sin markdown)
        if len(rows) == 1 and len(headers) <= 3:
            # Escalar o casi: una frase con los pares, sin tabla.
            pares = [f"{_etiqueta(h)}: {_fmt_val(h, rows[0].get(h))}" for h in headers]
            texto = f"{desc}. " + " · ".join(pares)
        else:
            texto = f"{desc} — {rc} registro(s)."
            # Resumen agregado: si hay exactamente una columna monetaria y pocas
            # filas, el total global es la cifra que el usuario venía a buscar.
            # Excepción: si el resultado está desglosado por moneda/divisa,
            # sumar las filas mezclaría pesos con dólares y daría una cifra
            # falsa — en ese caso no hay acumulado que tenga sentido.
            mezcla_monedas = any(
                h.lower() in ("moneda", "divisa", "currency") for h in headers
            )
            monetarias = [h for h in headers if _es_monetaria(h) and _numerica(h)]
            if not mezcla_monedas and len(monetarias) == 1 and 1 < len(rows) <= 12:
                col = monetarias[0]
                try:
                    suma = sum(Decimal(str(r.get(col) or 0)) for r in rows)
                    texto += f" {_etiqueta(col)} acumulado: {_fmt_val(col, suma)}."
                except Exception:
                    pass

        if data.get("truncated"):
            texto += " (Se muestran los primeros 50 registros.)"

        # ------------------------------------------- componente estructurado
        columnas = [
            {
                "key": h,
                "label": _etiqueta(h),
                "align": "right" if _numerica(h) else "left",
            }
            for h in headers
        ]
        filas_fmt = [{h: _fmt_val(h, r.get(h)) for h in headers} for r in rows]

        componente: Dict[str, Any] = {
            "type": "table",
            "title": desc,
            "columns": columnas,
            "rows": filas_fmt,
            "actions": [],
        }
        if data.get("truncated"):
            componente["caption"] = "Mostrando los primeros 50 registros."

        return texto, [componente]
