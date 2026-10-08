"""
Router `/api/v1/ui/*` — endpoints ADICIONALES que la UI standalone necesita
(web-ui-design.md §6). No forman parte del contrato estable de `channels.md`:
el prefijo los mantiene separados a propósito.

Reglas transversales aplicadas aquí (§6, A-1..A-10):
  A-1 cookie de sesión, nunca el bearer por canal (ese autentica al adaptador)
  A-2 CSRF de doble envío en todo método mutante
  A-3 `extra="forbid"` en todos los modelos
  A-4 forma de error idéntica al contrato, con `answer` siempre presente
  A-6 aislamiento por dueño: lo ajeno responde 404, no 403
  A-9 paginación explícita con techo de 200

El turno de chat NO se reimplementa: este router construye un `ChatRequest`
canónico y llama al mismo `agent_service.process_turn` que usa el canal
estable. Si la UI tuviera su propio camino de ejecución, validar la UI dejaría
de validar el agente — que es justamente el objetivo del hito.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from app.contracts.chat_contract import (
    Actor,
    ChatRequest,
    Channel,
    ClientMeta,
    Company,
    Mode,
    SubjectType,
)
from app.core.agent_service import ProgressEmitter, agent_service
from app.core.exceptions import AgentException, ContractError
from app.core.store import _connect
from app.web import auth as uiauth

# Mensaje al usuario por error_code de contrato. Se mapea aquí y no en
# core/exceptions porque el texto es de UI (y en español), mientras que el
# error_code es del contrato: el agente no debe saber cómo se redacta la UI.
_MENSAJE_CONTRACT_ERROR: Dict[str, str] = {
    "LLM_UNAVAILABLE": (
        "El modelo de lenguaje no respondió a tiempo. Vuelve a intentarlo en un momento."
    ),
    "TURN_TIMEOUT": (
        "La consulta tardó más de lo permitido para un turno. Intenta formularla "
        "de forma más específica (por ejemplo, acotando el periodo o el cliente)."
    ),
    "DEPENDENCY_UNAVAILABLE": (
        "Una de las bases de datos consultadas no está disponible en este momento."
    ),
    "QUERY_TIMEOUT": "La consulta a la base de datos tardó demasiado y fue cancelada.",
    "RATE_LIMITED": "Se alcanzó el límite de consultas. Espera unos segundos.",
    "SQL_NOT_ALLOWED": "La consulta generada no está permitida por las reglas de seguridad.",
    "SQL_LIMIT_EXCEEDED": "La consulta devolvería demasiados registros.",
    "CAPABILITY_DENIED": "No tienes permisos para ejecutar esa operación.",
}

logger = logging.getLogger(__name__)

router = APIRouter(tags=["UI"])


# --------------------------------------------------------------- utilidades

def _err(status: int, code: str, answer: str, retryable: bool = False,
         details: Optional[Dict[str, Any]] = None,
         headers: Optional[Dict[str, str]] = None) -> JSONResponse:
    """A-4: misma forma de error que el contrato. `answer` nunca es null."""
    return JSONResponse(
        status_code=status,
        content={
            "answer": answer,
            "status": "error",
            "error": {
                "code": code,
                "message": answer,
                "retryable": retryable,
                "details": details or {},
            },
        },
        headers=headers or {},
    )


async def require_ui_user(request: Request) -> uiauth.UISession:
    """
    Dependencia de autenticación para la API de la UI.

    Lanza una `UnauthenticatedUI` que el handler global traduce a 401 con la
    forma de error del contrato; las páginas HTML usan su propia variante que
    redirige en lugar de responder JSON.
    """
    token = request.cookies.get(uiauth.COOKIE_SESSION)
    sess = await uiauth.resolve_session(token)
    if sess is None:
        raise UnauthenticatedUI()
    return sess


class UnauthenticatedUI(Exception):
    """Sesión de UI ausente o expirada."""


def _require_csrf(request: Request, sess: uiauth.UISession) -> Optional[JSONResponse]:
    """A-2. Devuelve una respuesta de error si el doble envío no cuadra."""
    if not uiauth.csrf_ok(
        sess,
        request.headers.get(uiauth.HEADER_CSRF),
        request.cookies.get(uiauth.COOKIE_CSRF),
    ):
        return _err(403, "CSRF_INVALID",
                    "La petición no superó la validación de seguridad. Recarga la página.")
    return None


# --------------------------------------------------------------- §6.1 login

class LoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=128)


@router.post("/login")
async def ui_login(body: LoginIn, request: Request) -> Response:
    ip = request.client.host if request.client else ""
    ua = request.headers.get("user-agent", "")
    try:
        token, sess = await uiauth.login(body.username, body.password, ip=ip, user_agent=ua)
    except uiauth.LoginLockedOut as e:
        return _err(429, e.code, e.answer,
                    details={"locked_until": e.locked_until.isoformat(), "attempts_remaining": 0},
                    headers={"Retry-After": str(e.retry_after)})
    except uiauth.LoginFailed as e:
        return _err(401, e.code, e.answer)
    except uiauth.IdentityUnavailable as e:
        # Sprint 5: `trafico-db` caído NO es una contraseña incorrecta. Un 503
        # con Retry-After evita que el usuario insista y queme sus intentos de
        # lockout por una caída de infraestructura que él no puede arreglar.
        return _err(503, e.code, e.answer,
                    headers={"Retry-After": "30"})

    resp = JSONResponse({
        "redirect": "/ui/chat",
        "user": {
            "username": sess.user.username,
            "display_name": sess.user.display_name,
            "role": sess.user.role,
            "must_change_password": sess.user.must_change_password,
        },
    })
    resp.set_cookie(uiauth.COOKIE_SESSION, token, **uiauth.cookie_kwargs())
    # La cookie CSRF es legible por JS a propósito: es la mitad del doble envío.
    csrf_attrs = uiauth.cookie_kwargs()
    csrf_attrs["httponly"] = False
    resp.set_cookie(uiauth.COOKIE_CSRF, sess.csrf_token, **csrf_attrs)
    return resp


# --------------------------------------------------------------- §6.2 logout

@router.post("/logout")
async def ui_logout(request: Request) -> Response:
    # Idempotente por diseño: sin sesión también responde 200 (§6.2).
    await uiauth.logout(request.cookies.get(uiauth.COOKIE_SESSION))
    resp = JSONResponse({"redirect": "/ui/login"})
    resp.delete_cookie(uiauth.COOKIE_SESSION, path="/")
    resp.delete_cookie(uiauth.COOKIE_CSRF, path="/")
    return resp


# --------------------------------------------------------------- §6.9 me

@router.get("/me")
async def ui_me(sess: uiauth.UISession = Depends(require_ui_user)) -> Dict[str, Any]:
    u = sess.user
    return {
        "username": u.username,
        "display_name": u.display_name,
        "role": u.role,
        "agent_roles": u.agent_roles,
        # B-U8: la UI debe poder avisar que la cuenta no está mapeada, en vez
        # de dejar que el usuario descubra el ROL_NO_MAPEADO a base de choques.
        "mapped": bool(u.traf_username or u.liq_nombre_usu),
        "write_allowlisted": u.write_allowlisted,
        "csrf_token": sess.csrf_token,
        "session_expires_at": sess.expires_at.isoformat(),
        "companies": [c.value for c in Company],
    }


# --------------------------------------------------------------- chat

class ChatIn(BaseModel):
    """
    Entrada del compositor. Deliberadamente más estrecha que `ChatRequest`:
    el navegador NO elige canal, actor ni roles — esos los pone el servidor a
    partir de la sesión. Si el cliente pudiera mandar `actor.roles`, el RBAC
    sería decorativo.
    """

    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=4000)
    company: Company
    session_id: Optional[str] = Field(default=None, max_length=128)
    inputs: Optional[Dict[str, Any]] = None
    debug: bool = False


@router.post("/chat")
async def ui_chat(
    body: ChatIn,
    request: Request,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    sess: uiauth.UISession = Depends(require_ui_user),
) -> Response:
    bad = _require_csrf(request, sess)
    if bad is not None:
        return bad

    u = sess.user
    req = ChatRequest(
        message=body.message,
        session_id=body.session_id,
        channel=Channel.UI_STANDALONE,
        company=body.company,
        actor=Actor(
            subject=u.actor_subject(),
            subject_type=SubjectType.TRAFICO_USER,
            display_name=u.display_name,
            roles=list(u.agent_roles),
            authorized=True,
        ),
        inputs=body.inputs,
        mode=Mode.CHAT,
        client=ClientMeta(adapter="ui-standalone", locale="es-MX"),
        # P5 solo existe para admin: un validador no puede pedir debug.
        debug=bool(body.debug and u.is_admin),
    )

    resp = await agent_service.process_turn(
        req=req,
        client_ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        idempotency_key=idempotency_key,
    )

    payload = resp.model_dump(mode="json")
    # Marca de propiedad del hilo para el historial (A-6) sin tocar el contrato.
    await _marcar_dueno(resp.session_id, u.id)
    return JSONResponse(payload, headers={"X-Forsis-Trace-Id": resp.trace.trace_id})


# Etiquetas visibles por etapa — el stream nunca manda SQL ni datos de
# negocio, solo esta traducción fija de la etapa interna a texto para humanos.
_ETAPA_TEXTO = {
    "planning": "Analizando tu pregunta…",
    "executing_tool": "Consultando {detalle}…",
    "composing": "Preparando la respuesta…",
}


@router.post("/chat/stream")
async def ui_chat_stream(
    body: ChatIn,
    request: Request,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    sess: uiauth.UISession = Depends(require_ui_user),
) -> Response:
    """
    Variante SSE de `/chat`: mismo `ChatRequest`/`process_turn`, pero el
    cliente recibe eventos de progreso (`stage`) mientras el turno corre y un
    evento final `result` con el mismo payload que el endpoint síncrono.

    No es un segundo camino de ejecución (regla del módulo): es el mismo
    `process_turn`, solo que se le pasa un `ProgressEmitter` para poder
    adelantar texto de estado al cliente antes de que termine.
    """
    bad = _require_csrf(request, sess)
    if bad is not None:
        return bad

    u = sess.user
    req = ChatRequest(
        message=body.message,
        session_id=body.session_id,
        channel=Channel.UI_STANDALONE,
        company=body.company,
        actor=Actor(
            subject=u.actor_subject(),
            subject_type=SubjectType.TRAFICO_USER,
            display_name=u.display_name,
            roles=list(u.agent_roles),
            authorized=True,
        ),
        inputs=body.inputs,
        mode=Mode.CHAT,
        client=ClientMeta(adapter="ui-standalone", locale="es-MX"),
        debug=bool(body.debug and u.is_admin),
    )

    async def generar() -> AsyncIterator[bytes]:
        cola: asyncio.Queue = asyncio.Queue()
        emisor = ProgressEmitter(cola)

        def _sse(evento: str, data: Dict[str, Any]) -> bytes:
            return f"event: {evento}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode("utf-8")

        tarea = asyncio.create_task(
            agent_service.process_turn(
                req=req,
                client_ip=request.client.host if request.client else None,
                user_agent=request.headers.get("user-agent"),
                idempotency_key=idempotency_key,
                progress=emisor,
            )
        )

        try:
            while not tarea.done():
                try:
                    evento_progreso = await asyncio.wait_for(cola.get(), timeout=0.5)
                except asyncio.TimeoutError:
                    continue
                etapa = evento_progreso.get("stage", "")
                detalle = evento_progreso.get("detail")
                texto = _ETAPA_TEXTO.get(etapa, "Procesando…").format(detalle=detalle or "los sistemas")
                yield _sse("stage", {"stage": etapa, "text": texto})

            # Vacía cualquier evento que llegó justo antes de que la tarea
            # terminara, para no perder el último "Preparando la respuesta…".
            while not cola.empty():
                evento_progreso = cola.get_nowait()
                etapa = evento_progreso.get("stage", "")
                detalle = evento_progreso.get("detail")
                texto = _ETAPA_TEXTO.get(etapa, "Procesando…").format(detalle=detalle or "los sistemas")
                yield _sse("stage", {"stage": etapa, "text": texto})

            resp = tarea.result()
            payload = resp.model_dump(mode="json")
            await _marcar_dueno(resp.session_id, u.id)
            yield _sse("result", payload)
        except ContractError as exc:
            # Los errores de contrato YA saben lo que son (error_code,
            # http_status, retryable). Aplanarlos a INTERNAL_ERROR le mentía al
            # usuario: un timeout del proveedor no es un bug del servidor y sí
            # se puede reintentar. Se respeta la taxonomía de core/exceptions.
            logger.warning("ContractError en turno SSE: %s (%s)", exc.error_code, exc)
            yield _sse("error", {
                "error_code": exc.error_code,
                "answer": _MENSAJE_CONTRACT_ERROR.get(
                    exc.error_code,
                    "No se pudo completar la consulta en este momento.",
                ),
                "retryable": exc.retryable,
            })
        except AgentException as exc:
            # Resto de la jerarquía del agente: sin http_status propio, pero
            # tampoco es un fallo desconocido del servidor.
            logger.warning("AgentException en turno SSE: %s", exc)
            yield _sse("error", {
                "error_code": "AGENT_ERROR",
                "answer": "No se pudo completar la consulta en este momento.",
                "retryable": True,
            })
        except Exception as exc:  # pragma: no cover - el cliente ve un evento de error, no un stream roto
            logger.exception("fallo en turno SSE")
            yield _sse("error", {
                "error_code": "INTERNAL_ERROR",
                "answer": "Ocurrió un error inesperado al procesar la solicitud.",
                "retryable": True,
            })
        finally:
            if not tarea.done():
                tarea.cancel()

    return StreamingResponse(
        generar(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # nginx no debe bufferizar el SSE
        },
    )


async def _marcar_dueno(session_id: str, ui_user_id: str) -> None:
    """
    Asocia el hilo conversacional al usuario de UI que lo creó.

    Se hace aquí y no en el store del agente porque `ui_user_id` es un concepto
    exclusivo de esta UI: el agente no debe saber que existe una tabla de
    usuarios web. Un fallo aquí no debe tumbar el turno ya respondido.
    """
    try:
        conn = await _connect()
        try:
            await conn.execute(
                """UPDATE chat_sessions SET ui_user_id = $2
                    WHERE session_id = $1 AND ui_user_id IS NULL""",
                session_id, ui_user_id,
            )
        finally:
            await conn.close()
    except Exception as e:
        logger.warning("No se pudo marcar el dueño del hilo %s: %s", session_id, type(e).__name__)


# --------------------------------------------------------------- §6.3 historial

@router.get("/sessions")
async def ui_sessions(
    sess: uiauth.UISession = Depends(require_ui_user),
    limit: int = Query(default=25, ge=1, le=200),     # A-9
    offset: int = Query(default=0, ge=0),
    company: Optional[Company] = Query(default=None),
    only_errors: bool = Query(default=False),
    scope: Literal["mine", "all"] = Query(default="mine"),
) -> Response:
    if scope == "all" and not sess.user.is_admin:
        return _err(403, "FORBIDDEN", "No tienes permiso para ver los hilos de otras personas.")

    where = ["1=1"]
    args: List[Any] = []

    if scope == "mine":
        args.append(sess.user.id)
        where.append(f"s.ui_user_id = ${len(args)}")
    if company is not None:
        args.append(company.value)
        where.append(f"s.company = ${len(args)}")
    if only_errors:
        where.append("""EXISTS (SELECT 1 FROM chat_messages m
                                 WHERE m.session_id = s.session_id
                                   AND m.status IN ('error','denied','degraded'))""")

    args.extend([limit, offset])
    sql = f"""
        SELECT s.session_id, s.channel, s.company, s.actor_subject, s.last_seen_at, s.created_at,
               (SELECT count(*) FROM chat_messages m WHERE m.session_id = s.session_id) AS n_msgs,
               (SELECT m.content FROM chat_messages m
                 WHERE m.session_id = s.session_id AND m.role = 'user'
                 ORDER BY m.created_at ASC, m.id ASC LIMIT 1) AS primer_mensaje,
               (SELECT m.status FROM chat_messages m
                 WHERE m.session_id = s.session_id AND m.status IS NOT NULL
                 ORDER BY m.created_at DESC, m.id DESC LIMIT 1) AS ultimo_status
          FROM chat_sessions s
         WHERE {' AND '.join(where)}
         ORDER BY s.last_seen_at DESC
         LIMIT ${len(args) - 1} OFFSET ${len(args)}
    """

    conn = await _connect()
    try:
        rows = await conn.fetch(sql, *args)
    finally:
        await conn.close()

    def _recorte(txt: Optional[str]) -> str:
        if not txt:
            return "(sin mensajes)"
        return txt if len(txt) <= 120 else txt[:117] + "…"

    return JSONResponse({
        "items": [{
            "session_id": r["session_id"],
            "company": r["company"],
            "channel": r["channel"],
            "titulo": _recorte(r["primer_mensaje"]),
            "mensajes": r["n_msgs"],
            "ultimo_status": r["ultimo_status"],
            "last_seen_at": r["last_seen_at"].isoformat() if r["last_seen_at"] else None,
        } for r in rows],
        "limit": limit,
        "offset": offset,
    })


@router.get("/sessions/{session_id}")
async def ui_session_detail(
    session_id: str,
    sess: uiauth.UISession = Depends(require_ui_user),
) -> Response:
    conn = await _connect()
    try:
        own = await conn.fetchrow(
            "SELECT session_id, company, ui_user_id FROM chat_sessions WHERE session_id = $1",
            session_id,
        )
        # A-6: lo ajeno no existe. 404, no 403: un 403 confirmaría que el hilo
        # es de alguien y permitiría enumerar identificadores de sesión.
        if own is None or (not sess.user.is_admin and str(own["ui_user_id"] or "") != sess.user.id):
            return _err(404, "NOT_FOUND", "No encontré esa conversación.")

        msgs = await conn.fetch(
            """SELECT role, content, status, trace_id, created_at
                 FROM chat_messages WHERE session_id = $1
                ORDER BY created_at ASC, id ASC LIMIT 500""",
            session_id,
        )
        tools = await conn.fetch(
            """SELECT id, tool_name, risk_class, status, row_count, duration_ms, created_at
                 FROM agent_ui_tool_executions WHERE session_id = $1
                ORDER BY created_at ASC LIMIT 200""",
            session_id,
        )
    finally:
        await conn.close()

    return JSONResponse({
        "session_id": session_id,
        "company": own["company"],
        "turns": [{
            "role": m["role"],
            "content": m["content"],
            "status": m["status"],
            "trace_id": m["trace_id"],
            "created_at": m["created_at"].isoformat() if m["created_at"] else None,
        } for m in msgs],
        "tool_executions": [{
            "id": str(t["id"]),
            "tool": t["tool_name"],
            "risk_class": t["risk_class"],
            "status": t["status"],
            "rows": t["row_count"],
            "ms": t["duration_ms"],
        } for t in tools],
    })


# --------------------------------------------------------------- §6.10 capabilities

@router.get("/capabilities")
async def ui_capabilities(sess: uiauth.UISession = Depends(require_ui_user)) -> Dict[str, Any]:
    """
    Alimenta el botón "Ver qué puedo hacer" del estado 7 (sin capacidad).

    Muestra solo lo visible para los roles del actor: una lista que incluyera
    lo inaccesible sería una invitación a pedir cosas que van a ser denegadas.
    """
    items: List[Dict[str, Any]] = []
    roles = set(sess.user.agent_roles)
    # El riesgo por capability vive en el catálogo, no en la definición.
    from app.capabilities.catalog import RISK_BY_CAPABILITY

    try:
        for d in agent_service.registry.list_definitions():
            # `required_permissions` usa el vocabulario de permissions.md; se
            # compara contra los roles del actor. Admin ve todo el catálogo.
            req = set(d.required_permissions or [])
            if req and not (req & roles) and not sess.user.is_admin:
                continue
            riesgo = RISK_BY_CAPABILITY.get(d.id)
            riesgo = riesgo.value if riesgo is not None else "L0"
            items.append({
                "id": d.id,
                "nombre": d.name,
                "descripcion": d.description or "",
                "riesgo": riesgo,
                "categoria": d.category,
            })
    except Exception as e:
        logger.warning("No se pudo listar el catálogo: %s", type(e).__name__)
        return {"items": [], "degradado": True}
    return {"items": items, "degradado": False}


# --------------------------------------------------------------- §6.11 contraseña

class PasswordIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actual: str = Field(min_length=1, max_length=128)
    nueva: str = Field(min_length=12, max_length=128)


@router.post("/password")
async def ui_password(
    body: PasswordIn,
    request: Request,
    sess: uiauth.UISession = Depends(require_ui_user),
) -> Response:
    """
    Cambio de contraseña por el propio usuario.

    Se re-verifica la contraseña actual aunque la sesión ya esté autenticada:
    una sesión robada no debe poder apropiarse de la cuenta cambiando la clave.
    Al terminar se revocan TODAS las sesiones salvo la actual, que es el
    comportamiento esperado si el motivo del cambio fue una sospecha de robo.
    """
    bad = _require_csrf(request, sess)
    if bad is not None:
        return bad

    if body.nueva == body.actual:
        return _err(400, "SAME_PASSWORD", "La contraseña nueva debe ser distinta de la actual.")

    ok = await uiauth.change_password(sess.user.id, body.actual, body.nueva, keep_session_id=sess.id)
    if not ok:
        return _err(401, "INVALID_CREDENTIALS", "La contraseña actual no es correcta.")

    logger.info("Contraseña actualizada para el usuario de UI %s", sess.user.username)
    return JSONResponse({
        "status": "ok",
        "answer": "Contraseña actualizada. Se cerraron tus demás sesiones.",
    })
