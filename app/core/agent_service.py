"""
AgentService (sprint-plan-v2.md D-6).
Orquesta el ciclo de vida del turno:
1. Validación fail-closed
2. Idempotencia (reserva / replay)
3. Gestión de sesión multi-empresa
4. Desvío determinista Smalltalk
5. Planificación con OmniRoute LLM (catálogo de tools, Sprint 3)
6. Ejecución de la tool vía ToolRunner (PlanGuard + sandbox read-only)
7. Composición de respuesta determinista a partir de los datos reales
8. Auditoría inmutable (fail-open)
9. Persistencia de turno
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from typing import Any, ClassVar, Dict, List, Optional

from app.contracts.chat_contract import (
    ChatRequest,
    ChatResponse,
    MAX_MESSAGE_LEN,
    ResponseStatus,
    ToolExecutionRef,
    Trace,
    TraceLatency,
)
from app.capabilities.catalog import build_registry, planner_catalog
from app.core.audit import audit_store
from app.core.exceptions import (
    ContractError,
    ForbiddenError,
    LlmUnavailableError,
    MessageTooLongError,
    TurnTimeoutError,
)
from app.core.executor.tool_runner import ToolRunner
from app.core.metrics import metrics
from app.core.response.template_composer import TemplateComposer
from app.core.store import IdempotencyStore, SessionStore
from app.infrastructure.llm_gateway.omniroute_provider import OmnirouteProvider

logger = logging.getLogger(__name__)

TURN_TIMEOUT_SECONDS = 120.0

# Techo de vueltas del ciclo ReAct. Ya NO es el presupuesto real: el que manda
# es el deadline del turno (ver _presupuesto_llm). Este número sólo existe como
# tope de seguridad contra un modelo que gire sin converger, por eso es
# holgado: las preguntas que cruzan dos bases necesitan 3-4 vueltas (consultar
# ATLAS -> ver folios -> consultar SICRET excluyéndolos -> concluir).
MAX_ITERACIONES_REACT = int(os.getenv("AGENT_MAX_ITERACIONES", "6"))

# Segundos que se reservan del turno para lo que viene DESPUÉS de la última
# llamada al LLM (ejecutar la herramienta, componer, auditar). Sin esta reserva
# el planner se come el presupuesto entero y el turno muere sin respuesta.
RESERVA_COMPOSICION_S = 12.0

# Piso útil de una llamada al LLM. Por debajo de esto no se intenta: se cierra
# el ciclo con lo que ya se reunió en vez de gastar el remanente en una llamada
# condenada a expirar (causa raíz del "Ocurrió un error inesperado").
PISO_LLM_S = 8.0

# Longitud máxima de una observación devuelta al modelo. Es generosa a
# propósito: en un ciclo agéntico la observación es el canal por el que viajan
# los datos de un paso al siguiente (ej. la lista de folios liberados de ATLAS
# que la siguiente consulta a SICRET necesita para su NOT IN). Truncarla a una
# muestra de 5 filas hacía IMPOSIBLE el encadenamiento entre bases distintas.
MAX_OBSERVACION_CHARS = int(os.getenv("AGENT_MAX_OBSERVACION_CHARS", "6000"))

# Filas que se devuelven al modelo en la observación. Coincide con el MAX_ROWS
# del sandbox analítico: si la consulta ya está acotada a 50 filas, mostrarlas
# todas no abre ninguna vía nueva y sí permite usarlas como insumo.
MAX_OBSERVACION_FILAS = 50

# Capabilities que son introspección, nunca respuesta de negocio.
CAPABILITIES_INTROSPECCION = {"db.explorar_esquema"}


def _es_solo_introspeccion(outcomes: List[Any]) -> bool:
    """¿Esta vuelta se compuso ÚNICAMENTE de introspección de esquema?

    Preserva la intención del fix estructural previo: `db.explorar_esquema`
    devuelve nombres de tabla y columna, nunca el saldo que el usuario pidió.
    Un turno NUNCA puede terminar mostrando eso como respuesta — el síntoma
    observado fue "¿cuánto debe el operador X?" contestado con la lista de
    tablas que mencionan 'operador'. Por eso el resultado de una vuelta de pura
    introspección se usa como observación para el modelo, pero no se promueve
    a respuesta visible.
    """
    if not outcomes:
        return False
    return {cap_id for cap_id, _o in outcomes} <= CAPABILITIES_INTROSPECCION


def _firma_llamada(cap_id: str, parametros: Dict[str, Any]) -> str:
    """Huella estable de una llamada a herramienta (capability + parámetros).

    Sirve para detectar que el modelo está repitiendo una acción ya ejecutada.
    En un ciclo agéntico eso no es un error: es como el modelo dice "no tengo
    nada nuevo que hacer". Re-ejecutarla sólo quemaría presupuesto y arriesgaría
    cambiar una respuesta correcta, así que se trata como señal de cierre.
    """
    import json as _json

    try:
        firma_params = _json.dumps(parametros, sort_keys=True, ensure_ascii=False, default=str)
    except Exception:  # pragma: no cover - parámetros no serializables
        firma_params = repr(sorted(parametros.items()))
    return f"{cap_id}::{firma_params}"


def _amerita_otra_vuelta(outcomes: List[Any]) -> bool:
    """Compatibilidad: la decisión de continuar ya NO se infiere del resultado.

    En el diseño agéntico es el MODELO quien decide si da otro paso (emitiendo
    otra acción) o si concluye (devolviendo `capability: null` / repitiendo la
    última llamada). Esta función se conserva porque expresa el único caso en
    que el sistema fuerza otra vuelta por su cuenta, sin preguntar al modelo:
    una vuelta de pura introspección de esquema, que por definición no es una
    respuesta de negocio.

    El antiguo cortocircuito "row_count > 0 => terminar" se ELIMINÓ: era lo que
    hacía imposible el patrón "paso intermedio con datos -> consulta final", es
    decir cualquier pregunta que cruce dos bases (ATLAS + SICRET).
    """
    if not outcomes:
        return False
    if _es_solo_introspeccion(outcomes):
        return True
    for _cap_id, outcome in outcomes:
        if outcome.status == "degraded":
            return True
        datos = outcome.data or {}
        rc = datos.get("row_count")
        if rc is not None and int(rc) == 0:
            return True
    return False



def _hay_nombres_en_conflicto(filas: List[Dict[str, Any]]) -> bool:
    """True si el resultado trae más de una persona distinta.

    Heurística genérica sobre el dato devuelto, no sobre un dominio: mira las
    columnas cuyo nombre parece contener un nombre de persona (nombre, ape,
    nombrecompleto, operador, chofer...) y compara sus valores normalizados.
    Si hay 2 o más distintos, la consulta fue demasiado laxa y el agente va a
    responder por la persona equivocada si no se le avisa.
    """
    import json as _json

    valores = set()
    for fila in filas:
        if not isinstance(fila, dict):
            continue
        for col, val in fila.items():
            c = str(col).lower()
            if not any(k in c for k in ("nombre", "ape", "nombrecomp", "operador", "chofer", "empleado")):
                continue
            s = _json.dumps(val, ensure_ascii=False, default=str).strip().upper()
            if s and s not in ("NULL", "NONE", '""'):
                valores.add(s)
    return len(valores) > 1


def _observacion(outcomes: List[Any]) -> List[Dict[str, str]]:
    """Convierte los resultados de las herramientas en turnos de conversación.

    Se inyectan como mensajes `assistant`/`user` porque es lo que el proveedor
    ya sabe serializar, sin tocar el prompt firmado del planner: el modelo ve
    lo que hizo y lo que obtuvo, y decide la siguiente acción.

    ESTE es el mecanismo de encadenamiento de datos del ciclo agéntico, y por
    eso devuelve las filas COMPLETAS (hasta MAX_OBSERVACION_FILAS) y no una
    muestra de 5. El modelo lee los valores reales (folios, IDs, placas) y los
    escribe literalmente en el SQL del paso siguiente. Es deliberadamente más
    general que el enum cerrado de TaskDependencyField (TOP_*/EACH_ROW_*), que
    sólo sabía encadenar "el ganador de un ranking", y NO introduce ninguna vía
    de acceso a objetos Python: lo único que viaja es texto JSON de filas que
    ya pasaron por el sandbox read-only, y el SQL que el modelo escribe con él
    vuelve a pasar por sql_guard y PlanGuard como cualquier otro.
    """
    import json as _json

    mensajes: List[Dict[str, str]] = []
    for cap_id, outcome in outcomes:
        datos = outcome.data or {}
        if outcome.status == "denied":
            resultado = (
                f"DENEGADO por política al ejecutar {cap_id}: "
                f"{outcome.error_message or outcome.error_code or 'no permitido'}"
            )
        elif outcome.status != "ok":
            resultado = (
                f"ERROR al ejecutar {cap_id}: "
                f"{outcome.error_message or outcome.error_code or 'fallo desconocido'}"
            )
        else:
            rc = datos.get("row_count", 0)
            filas = (datos.get("rows") or [])[:MAX_OBSERVACION_FILAS]
            muestra = _json.dumps(filas, ensure_ascii=False, default=str)
            if len(muestra) > MAX_OBSERVACION_CHARS:
                muestra = muestra[:MAX_OBSERVACION_CHARS] + "...(truncado)"
            resultado = f"Resultado de {cap_id}: row_count={rc}, filas={muestra}"
            if int(rc or 0) == 0 and cap_id in CAPABILITIES_INTROSPECCION:
                # Una búsqueda de esquema sin aciertos suele ser vocabulario, no
                # ausencia del dato: el usuario dice "deuda" y la tabla se llama
                # 'tarjeta_deudor'. Decirlo explícitamente evita que el modelo
                # concluya "no existe" tras un único intento fallido.
                resultado += (
                    "\nATENCIÓN: la búsqueda no encontró nada, pero eso casi nunca "
                    "significa que el dato no exista: significa que buscaste una "
                    "palabra que no aparece en el nombre. Reintenta con la RAÍZ de "
                    "la palabra o con sinónimos del sistema (p. ej. si buscaste "
                    "'deuda' prueba 'deud', 'tarjeta', 'vale'; si buscaste 'cliente' "
                    "prueba 'emp', 'gene'). Las tablas de SICRET usan abreviaturas."
                )
            elif filas and _hay_nombres_en_conflicto(filas):
                # Búsqueda por persona: si lo devuelto trae VARIOS nombres
                # distintos, la consulta fue demasiado laxa (normalmente sólo
                # por el apellido) y estás a punto de responder por la persona
                # equivocada. Se advert aquí, en la observación, en vez de
                # documentar el caso en el prompt: es una propiedad del dato
                # devuelto, no un dominio concreto.
                resultado += (
                    "\nATENCIÓN: la consulta trae VARIAS personas distintas "
                    "({n}) y no necesariamente la que pidió el usuario. "
                    "Refina el filtro para que coincidan TODAS las palabras del "
                    "nombre que dio el usuario (primer nombre Y apellido), y "
                    "revisa también el estatus del registro (p.ej. BAJA) antes "
                    "de responder: si sólo encaja un registro por apellido, "
                    "ese no es el dato que se pidió.".format(n=len(filas))
                )

        sql = datos.get("query_sql")
        accion = f"Ejecuté {cap_id}." + (f" SQL: {sql}" if sql else "")
        mensajes.append({"role": "assistant", "content": accion})
        mensajes.append(
            {
                "role": "user",
                "content": (
                    f"{resultado}\n\n"
                    "DECIDE EL SIGUIENTE PASO:\n"
                    "- Si este resultado ya responde COMPLETAMENTE la pregunta del "
                    "usuario, responde {\"capability\": null, \"parameters\": {}} para "
                    "concluir el turno. La respuesta que verá el usuario es la de "
                    "esta última consulta, no hace falta repetirla ni resumirla.\n"
                    "- Si todavía falta un dato, ENCADENA otro paso: toma los valores "
                    "concretos que acabas de obtener arriba (folios, IDs, claves, "
                    "nombres) y escríbelos LITERALMENTE dentro del SQL de la "
                    "siguiente consulta (por ejemplo en un IN (...) o NOT IN (...)). "
                    "Así se cruzan datos entre bases distintas: una consulta a ATLAS "
                    "(parámetro fuente='ATLAS') y otra a SICRET no pueden ir en el "
                    "mismo SQL, pero sí en dos pasos encadenados.\n"
                    "- Si falló o vino vacío, puede que la tabla o columna no exista "
                    "o que el dato viva en otro sistema: usa db_explorar_esquema "
                    "para verificar nombres reales antes de reintentar.\n"
                    "- Nunca inventes los valores: usa sólo los que aparecen en el "
                    "resultado de arriba."
                ),
            }
        )
    return mensajes


class ProgressEmitter:
    """Canal de eventos de progreso del turno.

    `process_turn` lo recibe como parámetro opcional, de modo que los canales
    no interactivos (Mattermost, widget, verificadores) lo omiten y el turno se
    comporta exactamente como antes: `emit` sobre el emisor nulo no hace nada.
    Los eventos son informativos — nunca transportan datos de negocio ni SQL,
    solo la etapa y la herramienta, para no abrir una vía de fuga por el stream.
    """

    __slots__ = ("_cola",)

    def __init__(self, cola: Optional["asyncio.Queue"] = None) -> None:
        self._cola = cola

    def emit(self, etapa: str, detalle: Optional[str] = None) -> None:
        if self._cola is None:
            return
        try:
            self._cola.put_nowait({"stage": etapa, "detail": detalle})
        except Exception:  # pragma: no cover - cola llena/cerrada no rompe el turno
            logger.debug("progreso descartado: %s", etapa)


PLANNER_SYSTEM_PROMPT_BASE = """Eres el Planner del agente empresarial Forsis Intelligence.
Tu tarea es analizar la consulta del usuario y responder EXCLUSIVAMENTE con un JSON con la estructura:
{"capability": "<nombre_capability>", "parameters": {...}}
o si no aplica ninguna capability del catálogo, responde:
{"capability": null, "parameters": {}}

REGLAS ESTRICTAS:
- Usa SOLO las capabilities del catálogo de abajo, con su nombre EXACTO.
- Los parámetros deben respetar el esquema de la capability. No inventes parámetros.
- NUNCA inventes datos de negocio (folios, cifras, nombres). Tú sólo eliges la
  herramienta y sus parámetros; los datos los obtiene el sistema de la base.
- No incluyas el parámetro "company": lo determina el sistema, no tú.
- PREFERENCIA POR HERRAMIENTA: si la pregunta pide un dato, conteo, monto, ranking o
  reporte de la operación (tráfico o facturación), usa SIEMPRE la capability analítica aunque
  la entidad no esté mencionada en su catálogo (remolques, placas, tractocamiones, destinos,
  tipos de servicio, etc.). Sólo usa capability null si la pregunta NO pide datos de la
  operación (saludos, preguntas sobre el agente, o temas sin relación con tráfico/facturación).
- CONTINUIDAD CONVERSACIONAL (MEMORIA): Si hay mensajes previos en la conversación,
  úsalos para resolver referencias de seguimiento, aclaraciones o correcciones del usuario
  (ej. 'pero no hablo de mayo hablo de octubre', 'de esas cuántas fueron de samsung?', 'y del año pasado?').
  Mantén la intención o tema de la consulta anterior sustituyendo o refinando los filtros que el
  usuario indique, y responde con el JSON de la capability adecuada.

CICLO DE TRABAJO (trabajas por PASOS, no de un solo tiro):
- Cada respuesta tuya es UN paso: una sola llamada a una capability. Después el
  sistema la ejecuta y te devuelve el resultado real para que decidas el siguiente.
- NO intentes resolver de antemano una pregunta que necesita varios pasos: haz el
  primer paso útil y espera a ver lo que devuelve.
- ENCADENAMIENTO DE DATOS: cuando un paso te devuelve valores que el siguiente
  necesita (folios, IDs, claves, placas, nombres), escríbelos LITERALMENTE en el
  SQL del paso siguiente, típicamente dentro de IN (...) o NOT IN (...). Es la
  única forma de cruzar datos entre bases distintas, porque cada consulta va a
  UNA sola base: las consultas con fuente='ATLAS' no pueden leer tablas de
  SICRET ni al contrario. Dos bases = dos pasos encadenados.
- NO CONOCES EL ESQUEMA DE MEMORIA: si no estás seguro de qué tabla o columna
  tiene el dato, tu primer paso debe ser db_explorar_esquema para averiguarlo con
  nombres reales, y recién después la consulta analítica. Nunca adivines nombres
  de tabla ni de columna.
- CÓMO CONCLUIR: cuando el último resultado ya responde COMPLETAMENTE la
  pregunta, responde {"capability": null, "parameters": {}}. Eso cierra el turno
  y el usuario ve el resultado de tu última consulta. No cierres el turno con una
  exploración de esquema como respuesta: eso es sólo un paso intermedio.

No incluyas explicaciones ni texto fuera del bloque JSON.
"""


def build_planner_prompt() -> str:
    """Prompt del Planner = base + catálogo L0/L1 serializado con ejemplos."""
    import json as _json

    catalogo = planner_catalog()
    lineas = [PLANNER_SYSTEM_PROMPT_BASE, "", "CATÁLOGO DE CAPABILITIES DISPONIBLES:"]
    for cap in catalogo:
        definicion = _registry.get_definition_by_id(cap["tool"])
        nombre = definicion.name if definicion else cap["tool"]
        lineas.append("")
        lineas.append(f'- nombre: "{nombre}"  (id: {cap["tool"]}, riesgo: {cap["risk_class"]})')
        lineas.append(f'  descripcion: {cap["description"]}')
        lineas.append(f'  parametros_schema: {_json.dumps(cap["params_schema"], ensure_ascii=False)}')
        for ej in cap.get("examples") or []:
            lineas.append(
                f'  ejemplo: "{ej["pregunta"]}" -> '
                f'{{"capability": "{nombre}", "parameters": {_json.dumps(ej["parameters"], ensure_ascii=False)}}}'
            )
    return "\n".join(lineas)


# Registry y runner del proceso: se construyen una vez al importar.
_registry = build_registry()
_tool_runner = ToolRunner(_registry)

PLANNER_SYSTEM_PROMPT = PLANNER_SYSTEM_PROMPT_BASE


class AgentService:
    # Defaults a nivel de CLASE: el registry y el runner son del proceso, no del
    # turno. Así una instancia creada sin pasar por __init__ (p. ej. en pruebas
    # con __new__) sigue teniendo catálogo, en vez de romper con AttributeError.
    registry: ClassVar[Any] = _registry
    runner: ClassVar[Any] = _tool_runner

    def __init__(self, provider: Optional[OmnirouteProvider] = None, runner: Optional[ToolRunner] = None):
        self.provider = provider or OmnirouteProvider()
        if runner is not None:
            self.runner = runner

    async def process_turn(
        self,
        req: ChatRequest,
        client_ip: Optional[str] = None,
        user_agent: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        progress: Optional[ProgressEmitter] = None,
    ) -> ChatResponse:
        metrics.incr("turn_total")
        start_time = time.perf_counter()
        trace_id = req.nuevo_trace_id()
        prog = progress or ProgressEmitter()

        # 1. Validaciones fail-closed
        if not req.actor.authorized:
            metrics.incr("turn_rejected")
            raise ForbiddenError("Actor no autorizado para interactuar con el agente.")

        if len(req.message) > MAX_MESSAGE_LEN:
            metrics.incr("turn_rejected")
            raise MessageTooLongError(f"El mensaje excede el límite de {MAX_MESSAGE_LEN} caracteres.")

        # 2. Idempotencia - Reserva / Replay
        if idempotency_key:
            action, cached = await IdempotencyStore.reserve(req, idempotency_key)
            if action == "replay" and cached:
                return ChatResponse(**cached)

        session_id = await SessionStore.ensure(req)
        plan_id: Optional[str] = None
        tasks_count = 0
        tools_called: List[str] = []
        model_real = self.provider.model
        llm_duration_ms = 0
        tools_duration_ms = 0
        components: List[Dict[str, Any]] = []
        sql_count = 0
        tool_audit: List[Dict[str, Any]] = []
        # ADJ-1: referencias opacas por ejecución (web-ui-design.md §6.0).
        tool_exec_refs: List[ToolExecutionRef] = []

        try:
            # 3. Smalltalk - Desvío determinista antes de LLM
            smalltalk_reply = TemplateComposer.compose_smalltalk(req.message)
            if smalltalk_reply:
                status = ResponseStatus.OK
                answer = smalltalk_reply
                model_real = self.provider.last_model_real or "Forsis"
            else:
                # 4-5. Ciclo ReAct acotado: planificar -> ejecutar -> observar.
                #
                # El modelo ve el RESULTADO de cada herramienta y puede volver a
                # decidir. Es la diferencia entre "no encontré nada" y explorar
                # el esquema para descubrir cómo se llama realmente la tabla.
                #
                # El presupuesto REAL del ciclo es el deadline del turno, no un
                # número fijo de vueltas: antes 3 vueltas x 3 intentos x 60 s
                # daban 540 s contra un techo de 120 s, así que el turno no
                # podía completarse por diseño. Ahora cada vuelta comprueba
                # cuánto queda y, si no alcanza para una llamada útil, cierra
                # con lo que ya reunió en vez de morir con un error opaco.
                observaciones: List[Dict[str, str]] = []
                # `partes`/`components` visibles = resultado del último paso de
                # NEGOCIO. Se conservan entre vueltas a propósito: cuando el
                # modelo concluye el turno (capability null) la respuesta es la
                # del último paso real, no un fallback vacío. Antes se borraban
                # al inicio de cada vuelta y concluir borraba la respuesta.
                partes: List[str] = []
                hubo_degradado = False
                hubo_denegado = False
                status = ResponseStatus.OK
                answer = ""
                tools_start = time.perf_counter()
                # Firmas de llamadas ya ejecutadas: repetir una es la señal de
                # que el modelo no tiene nada nuevo que aportar.
                firmas_ejecutadas: set = set()
                pasos_ejecutados = 0
                motivo_cierre = "sin_pasos"

                for iteracion in range(MAX_ITERACIONES_REACT):
                    es_ultima = iteracion == MAX_ITERACIONES_REACT - 1
                    prog.emit("planning")
                    llm_start = time.perf_counter()

                    remaining_time = max(
                        1.0, TURN_TIMEOUT_SECONDS - (time.perf_counter() - start_time)
                    )
                    # Presupuesto de ESTA llamada al LLM: lo que queda del turno
                    # menos la reserva para ejecutar la herramienta y componer.
                    presupuesto_llm = remaining_time - RESERVA_COMPOSICION_S
                    if presupuesto_llm < PISO_LLM_S and pasos_ejecutados > 0:
                        # No alcanza para otra vuelta útil y YA hay algo que
                        # mostrar: se cierra con la respuesta reunida. Esto es lo
                        # que convierte un "Ocurrió un error inesperado" en una
                        # respuesta parcial honesta.
                        motivo_cierre = "presupuesto_agotado"
                        metrics.incr("react_cierre_por_presupuesto")
                        break
                    # Si aún no hay ningún paso, se intenta de todos modos con lo
                    # que quede: sin esto el turno no tendría nada que responder.
                    presupuesto_llm = max(PISO_LLM_S, presupuesto_llm)
                    try:
                        catalogo = [
                            {"name": d.name, "id": d.id}
                            for d in self.registry.list_definitions()
                            if d.id in {c["tool"] for c in planner_catalog()}
                        ]
                        # Contexto conversacional (turnos previos del hilo) más
                        # las observaciones de esta misma pregunta.
                        historial_turnos = await SessionStore.history(session_id, limit=6)
                        plan_context = {
                            "session_id": session_id,
                            "history": historial_turnos,
                            "observations": observaciones,
                        }
                        plan = await asyncio.wait_for(
                            asyncio.to_thread(
                                self.provider.generate_plan,
                                build_planner_prompt(),
                                req.message,
                                plan_context,
                                catalogo,
                                None,
                                None,
                                presupuesto_llm,
                            ),
                            timeout=min(remaining_time, presupuesto_llm + 2.0),
                        )
                    except asyncio.TimeoutError as exc:
                        metrics.incr("turn_timeout")
                        if pasos_ejecutados > 0:
                            # Ya hay un resultado de negocio reunido: vale más
                            # entregarlo que convertir el turno en un 504.
                            motivo_cierre = "timeout_parcial"
                            logger.warning(
                                "ReAct: timeout de planificación en vuelta %s, "
                                "se responde con los %s paso(s) ya ejecutados",
                                iteracion, pasos_ejecutados,
                            )
                            break
                        raise TurnTimeoutError(
                            f"El turno excedió el límite de {TURN_TIMEOUT_SECONDS} s."
                        ) from exc
                    except LlmUnavailableError:
                        # El proveedor no respondió. Si ya hay datos reunidos el
                        # turno sigue siendo útil; si no, la excepción sube y
                        # ui.py la reporta como LLM_UNAVAILABLE (no INTERNAL_ERROR).
                        if pasos_ejecutados > 0:
                            motivo_cierre = "llm_no_disponible_parcial"
                            logger.warning(
                                "ReAct: proveedor no disponible en vuelta %s, "
                                "se responde con los %s paso(s) ya ejecutados",
                                iteracion, pasos_ejecutados,
                            )
                            break
                        raise

                    llm_duration_ms += int((time.perf_counter() - llm_start) * 1000)
                    model_real = self.provider.last_model_real
                    plan_id = plan.plan_id
                    tasks_count = len(plan.tasks)

                    if tasks_count == 0:
                        # `capability: null` es la forma en que el modelo CIERRA
                        # el turno en un ciclo agéntico. En la primera vuelta
                        # significa que ninguna capability aplica; en una vuelta
                        # posterior significa "ya tengo la respuesta", y lo que
                        # se muestra es el resultado del último paso de negocio,
                        # que `partes`/`components` ya conservan.
                        if iteracion == 0:
                            status = ResponseStatus.NO_CAPABILITY
                            answer = TemplateComposer.compose_fallback(status, req.message)
                            motivo_cierre = "sin_capability"
                            break

                        if partes or es_ultima or presupuesto_llm < PISO_LLM_S:
                            motivo_cierre = "modelo_concluyo"
                            metrics.incr("react_cierre_por_modelo")
                            break

                        # No hay NINGÚN paso de negocio todavía: el modelo quiere
                        # cerrar tras una exploración de esquema (o tras un paso
                        # vacío). Eso dejaría al usuario con el fallback degradado
                        # en vez de su dato — exactamente el síntoma que el fix
                        # estructural previo atacaba. Se le devuelve el control
                        # con la observación de lo que ya descubrió y la
                        # instrucción explícita de consultar los datos.
                        motivo_cierre = "cierre_prematuro_rechazado"
                        metrics.incr("react_cierre_prematuro_rechazado")
                        logger.info(
                            "ReAct: el modelo intentó cerrar en la vuelta %s sin "
                            "ningún resultado de negocio; se le pide continuar",
                            iteracion,
                        )
                        observaciones.append(
                            {
                                "role": "user",
                                "content": (
                                    "TODAVÍA NO HAY RESPUESTA para el usuario: hasta "
                                    "ahora sólo inspeccionaste el esquema o no "
                                    "obtuviste datos, y eso no es una respuesta de "
                                    "negocio. Con los nombres de tabla y columna que "
                                    "ya viste arriba, ejecuta AHORA la consulta "
                                    "db_consulta_analitica que responde la pregunta "
                                    "original. Si una tabla que esperabas no existe, "
                                    "explora otro nombre; si de plano el dato no está "
                                    "en ninguna base accesible, responde con una "
                                    "consulta que lo demuestre. No vuelvas a cerrar "
                                    "el turno sin datos."
                                ),
                            }
                        )
                        continue

                    # Resultados de ESTA vuelta. `partes`/`components` sólo se
                    # reemplazan si la vuelta produce un paso de negocio (ver
                    # más abajo): así una exploración de esquema intermedia no
                    # borra ni se convierte en la respuesta visible.
                    partes_iter: List[str] = []
                    components_iter: List[Dict[str, Any]] = []
                    outcomes_iter: List[Any] = []
                    hubo_degradado = False
                    hubo_denegado = False
                    repeticion_detectada = False

                    for task in plan.tasks:
                        call = task.capability_call
                        if call is None:
                            continue
                        definicion = self.registry.get_definition_by_name(call.capability_name)
                        cap_id = definicion.id if definicion else call.capability_name
                        parametros = dict(call.parameters or {})

                        firma = _firma_llamada(cap_id, parametros)
                        if firma in firmas_ejecutadas:
                            # El modelo propuso exactamente la misma llamada que
                            # ya se ejecutó: no hay información nueva por ganar y
                            # sí presupuesto por perder. Se trata como cierre.
                            repeticion_detectada = True
                            metrics.incr("react_llamada_repetida")
                            logger.info(
                                "ReAct: el modelo repitió %s con los mismos "
                                "parámetros; se cierra el ciclo", cap_id,
                            )
                            continue
                        firmas_ejecutadas.add(firma)

                        prog.emit("executing_tool", cap_id)
                        outcome = await asyncio.to_thread(
                            self.runner.run,
                            cap_id,
                            parametros,
                            req.company.value,
                            list(req.actor.roles or []),
                        )

                        tools_called.append(cap_id)
                        tool_audit.append(outcome.as_audit())
                        outcomes_iter.append((cap_id, outcome))
                        tool_exec_refs.append(
                            ToolExecutionRef(
                                id=uuid.uuid4().hex,
                                tool=cap_id,
                                risk_class=outcome.risk_class or "L0",
                                status=outcome.status,
                                rows=(outcome.data or {}).get("row_count"),
                                ms=outcome.duration_ms,
                            )
                        )
                        if (outcome.data or {}).get("row_count") is not None:
                            sql_count += 1

                        prog.emit("composing", cap_id)
                        texto, comps = TemplateComposer.compose_tool_outcome(cap_id, outcome)
                        partes_iter.append(texto)
                        components_iter.extend(comps)

                        if outcome.status == "denied":
                            hubo_denegado = True
                        elif outcome.status != "ok":
                            hubo_degradado = True

                    if outcomes_iter:
                        pasos_ejecutados += 1

                    solo_introspeccion = _es_solo_introspeccion(outcomes_iter)
                    if outcomes_iter and not solo_introspeccion:
                        # Esta vuelta produjo un paso de NEGOCIO: su resultado
                        # reemplaza al visible. Una vuelta de pura introspección
                        # no lo hace nunca — es el fix estructural que evita
                        # responder "¿cuánto debe X?" con una lista de tablas,
                        # ahora expresado como "la introspección no se promueve
                        # a respuesta" en vez de "la introspección reintenta".
                        partes = partes_iter
                        components = components_iter

                    # Una denegación es una decisión de política: no se reintenta,
                    # porque otra vuelta no la va a convertir en permiso.
                    if hubo_denegado:
                        motivo_cierre = "denegado"
                        break

                    # El modelo repitió una llamada ya hecha = no tiene nada nuevo.
                    if repeticion_detectada and not outcomes_iter:
                        motivo_cierre = "repeticion"
                        break

                    if es_ultima:
                        motivo_cierre = "techo_iteraciones"
                        metrics.incr("react_techo_iteraciones")
                        break

                    # NOTA ARQUITECTÓNICA: aquí ya NO se decide si continuar
                    # mirando el row_count. En un ciclo agéntico la decisión es
                    # del MODELO: se le entrega la observación y, si considera
                    # que la pregunta está respondida, cierra con
                    # `capability: null` en la vuelta siguiente. El antiguo
                    # cortocircuito "vinieron filas => terminar" hacía imposible
                    # cualquier pregunta de dos pasos (cruzar ATLAS con SICRET),
                    # porque el primer paso SIEMPRE devuelve filas.
                    observaciones.extend(_observacion(outcomes_iter))
                    metrics.incr("react_iteracion_extra")

                tools_duration_ms = int((time.perf_counter() - tools_start) * 1000)
                logger.info(
                    "ReAct: %s paso(s), cierre=%s, llm_ms=%s",
                    pasos_ejecutados, motivo_cierre, llm_duration_ms,
                )

                if status != ResponseStatus.NO_CAPABILITY:
                    answer = "\n\n".join(p for p in partes if p) or \
                        TemplateComposer.compose_fallback(ResponseStatus.DEGRADED)

                    # Precedencia de estado: denegado > degradado > ok. Una
                    # denegación es una decisión de política y debe verse como tal.
                    if hubo_denegado:
                        status = ResponseStatus.DENIED
                    elif hubo_degradado:
                        status = ResponseStatus.DEGRADED
                    else:
                        status = ResponseStatus.OK

            total_duration_ms = int((time.perf_counter() - start_time) * 1000)

            # 5. Construcción de respuesta
            trace = Trace(
                trace_id=trace_id,
                plan_id=plan_id,
                llm_model_real=model_real,
                llm_attempts=1,
                latency_ms=TraceLatency(
                    llm=llm_duration_ms,
                    tools=tools_duration_ms,
                    total=total_duration_ms,
                ),
                tools_executed=tools_called,
                tool_executions=tool_exec_refs,
            )

            resp = ChatResponse(
                answer=answer,
                session_id=session_id,
                status=status,
                components=components,
                clarification=None,
                confirmation=None,
                context_updated=False,
                updated_context={},
                trace=trace,
                debug=None if not req.debug else {
                    "duration_ms": total_duration_ms,
                    "tools": tool_audit,
                },
            )

            # 6. Persistencia y Auditoría
            await SessionStore.append_turn(
                session_id=session_id,
                req=req,
                answer=answer,
                status=status.value,
                context_state={},
            )

            await audit_store.record_turn(
                turn_id=trace_id,
                session_id=session_id,
                channel=req.channel.value,
                company=req.company.value,
                actor_subject=req.actor.subject,
                actor_roles=req.actor.roles,
                ip=client_ip,
                user_agent=user_agent,
                status=status.value,
                duration_ms=total_duration_ms,
                error_code=None,
                plan_id=plan_id,
                tasks_count=tasks_count,
                tools_called=tools_called,
                sql_statements_count=sql_count,
                write_calls_count=0,
            )

            # 7. Completar idempotencia para replay
            if idempotency_key:
                await IdempotencyStore.complete(
                    key=idempotency_key,
                    req=req,
                    response_body=resp.model_dump(mode="json"),
                )

            return resp

        except Exception as exc:
            total_duration_ms = int((time.perf_counter() - start_time) * 1000)
            err_code = getattr(exc, "error_code", "INTERNAL_ERROR")

            # Liberar reserva de idempotencia ante fallos
            if idempotency_key:
                await IdempotencyStore.release(idempotency_key, req)

            # Auditoría del turno fallido (fail-open)
            await audit_store.record_turn(
                turn_id=trace_id,
                session_id=session_id,
                channel=req.channel.value,
                company=req.company.value,
                actor_subject=req.actor.subject,
                actor_roles=req.actor.roles,
                ip=client_ip,
                user_agent=user_agent,
                status="error",
                duration_ms=total_duration_ms,
                error_code=err_code,
                plan_id=plan_id,
                tasks_count=tasks_count,
                tools_called=tools_called,
                sql_statements_count=0,
                write_calls_count=0,
            )
            raise exc


# Singleton de servicio
agent_service = AgentService()
