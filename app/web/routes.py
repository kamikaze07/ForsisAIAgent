"""
Páginas HTML de la UI standalone (web-ui-design.md §5.5).

Navegación clásica de servidor, una página por pantalla y **sin router de SPA**:
el botón Atrás, abrir en pestaña nueva y copiar la URL funcionan sin escribir
una línea de código. En una UI de auditoría, "copiar el enlace de esta
ejecución y pegarlo en un mensaje" es un requisito real, no una comodidad.

La diferencia con el router de API: aquí una sesión ausente **redirige** a
`/ui/login` en lugar de responder 401 JSON. Un 401 en una navegación de
documento deja al usuario mirando texto crudo.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from app.web import auth as uiauth

logger = logging.getLogger(__name__)

router = APIRouter(tags=["UI-Pages"], include_in_schema=False)

_TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

APP_VERSION = os.getenv("APP_VERSION", "dev")


def _asset_version() -> str:
    """
    Versión de los estáticos para el cache-busting del `?v=`.

    No puede ser una constante: el navegador sólo recarga `chat.js` si el `?v=`
    cambia, así que una constante sirve para siempre el JS viejo y una mejora
    (una tabla HTML, un stream de progreso) queda invisible en la UI aunque el
    contenedor ya sirva el archivo nuevo. Se deriva del mtime del más reciente
    estático para que cualquier edición lo bumpee sola.
    """
    static = Path(__file__).parent / "static"
    if not static.is_dir():
        return APP_VERSION
    try:
        mas_reciente = max(
            (p.stat().st_mtime for p in static.rglob("*") if p.is_file()),
            default=0.0,
        )
    except OSError:
        return APP_VERSION
    return "%s.%d" % (APP_VERSION, int(mas_reciente))
DEBUG_ENABLED = os.getenv("AGENT_UI_DEBUG_ENABLED", "0") == "1"

# CSP sin 'unsafe-inline': posible precisamente porque no hay framework que lo
# exija. Todo el JS vive en archivos servidos desde el mismo origen (§5.5).
CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; "
    "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; "
    "base-uri 'none'; object-src 'none'"
)


def _secure_headers(resp: Response) -> Response:
    resp.headers["Content-Security-Policy"] = CSP
    # Nginx pone SAMEORIGIN global; para la UI se endurece: esto no se embebe.
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "same-origin"
    # El HTML nunca se cachea: solo los estáticos versionados (§5.4).
    resp.headers["Cache-Control"] = "no-store"
    return resp


async def _sesion(request: Request) -> Optional[uiauth.UISession]:
    return await uiauth.resolve_session(request.cookies.get(uiauth.COOKIE_SESSION))


def _render(request: Request, plantilla: str, sess: Optional[uiauth.UISession] = None, **ctx) -> Response:
    base = {
        "request": request,
        "v": _asset_version(),
        "debug_enabled": DEBUG_ENABLED,
        "user": sess.user if sess else None,
    }
    base.update(ctx)
    resp = templates.TemplateResponse(plantilla, base)
    return _secure_headers(resp)


def _a_login(request: Request, motivo: str = "") -> Response:
    destino = "/ui/login" + (f"?motivo={motivo}" if motivo else "")
    return _secure_headers(RedirectResponse(destino, status_code=303))


# --------------------------------------------------------------- rutas

@router.get("/", response_class=HTMLResponse)
async def ui_root(request: Request) -> Response:
    sess = await _sesion(request)
    destino = "/ui/chat" if sess else "/ui/login"
    return _secure_headers(RedirectResponse(destino, status_code=303))


@router.get("/login", response_class=HTMLResponse)
async def ui_login_page(request: Request, motivo: str = "") -> Response:
    # Si ya hay sesión no se muestra el login: se entra (§5.5).
    if await _sesion(request):
        return _secure_headers(RedirectResponse("/ui/chat", status_code=303))
    avisos = {
        "expirada": "Tu sesión expiró. Vuelve a entrar.",
        "salida": "Cerraste sesión correctamente.",
    }
    return _render(request, "login.html", None, aviso=avisos.get(motivo, ""))


@router.get("/chat", response_class=HTMLResponse)
async def ui_chat_page(request: Request) -> Response:
    sess = await _sesion(request)
    if sess is None:
        return _a_login(request, "expirada")
    return _render(request, "chat.html", sess, csrf=sess.csrf_token)


@router.get("/historial", response_class=HTMLResponse)
async def ui_historial_page(request: Request) -> Response:
    sess = await _sesion(request)
    if sess is None:
        return _a_login(request, "expirada")
    return _render(request, "historial.html", sess, csrf=sess.csrf_token)


@router.get("/ejecucion/{session_id}", response_class=HTMLResponse)
async def ui_ejecucion_page(request: Request, session_id: str) -> Response:
    sess = await _sesion(request)
    if sess is None:
        return _a_login(request, "expirada")
    # La comprobación de pertenencia (A-6) la hace el endpoint de datos, que es
    # el único que puede responder 404 sin confirmar la existencia del recurso.
    return _render(request, "ejecucion.html", sess, csrf=sess.csrf_token, session_id=session_id)


@router.get("/cuenta", response_class=HTMLResponse)
async def ui_cuenta_page(request: Request) -> Response:
    sess = await _sesion(request)
    if sess is None:
        return _a_login(request, "expirada")
    return _render(request, "cuenta.html", sess, csrf=sess.csrf_token)


@router.get("/depuracion", response_class=HTMLResponse)
async def ui_depuracion_page(request: Request) -> Response:
    sess = await _sesion(request)
    if sess is None:
        return _a_login(request, "expirada")
    # Doble llave: rol admin Y bandera de entorno. P5 expone el plan y los
    # tiempos internos; no debe quedar accesible por olvido de configuración.
    if not sess.user.is_admin or not DEBUG_ENABLED:
        return _render(request, "denegado.html", sess, csrf=sess.csrf_token)
    return _render(request, "depuracion.html", sess, csrf=sess.csrf_token)
