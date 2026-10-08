"""
Sonda del endpoint SSE `/api/v1/ui/chat/stream`.

Corre DENTRO del contenedor con TestClient y sustituye la dependencia de
sesión de UI (no la autenticación del agente: el turno se ejecuta completo,
con planner, SQL guard y pool read-only reales). Lo que se verifica es el
transporte de eventos: que lleguen `stage` antes del `result` y que el
`result` traiga el mismo payload que el endpoint síncrono.
"""
from __future__ import annotations

import json
import sys

from fastapi.testclient import TestClient

from app.api.v1 import ui as ui_mod
from app.main import app
from app.web import auth as uiauth

PREGUNTA = sys.argv[1] if len(sys.argv) > 1 else "cuanto se ha facturado en este mes de octubre, agrupado por moneda"


class _User:
    id = "probe-sse"
    display_name = "Probe SSE"
    agent_roles = ("admin",)
    is_admin = True
    username = "probe"

    def actor_subject(self) -> str:
        return "probe-sse"


class _Sess:
    user = _User()
    csrf_token = "probe-csrf"


app.dependency_overrides[ui_mod.require_ui_user] = lambda: _Sess()
# El CSRF de doble envío compara cookie contra header; la sonda no pasa por
# /ui/login, así que se neutraliza solo esa comprobación.
ui_mod._require_csrf = lambda request, sess: None

client = TestClient(app)

etapas: list[str] = []
resultado = None

with client.stream(
    "POST",
    "/api/v1/ui/chat/stream",
    json={"message": PREGUNTA, "company": "FORSIS", "session_id": None},
    headers={"Idempotency-Key": "probe-sse-1", "Accept": "text/event-stream"},
) as r:
    print("HTTP", r.status_code, "|", r.headers.get("content-type"))
    if r.status_code != 200:
        print(r.read().decode()[:600])
        raise SystemExit(1)

    evento = None
    for linea in r.iter_lines():
        if isinstance(linea, bytes):
            linea = linea.decode()
        if linea.startswith("event:"):
            evento = linea[6:].strip()
        elif linea.startswith("data:"):
            payload = json.loads(linea[5:].strip())
            if evento == "stage":
                etapas.append(payload.get("stage", ""))
                print("  STAGE:", payload.get("stage"), "->", payload.get("text"))
            elif evento == "result":
                resultado = payload
                print("  RESULT recibido")
            elif evento == "error":
                print("  ERROR:", payload)

print()
print("etapas:", etapas)
assert resultado is not None, "no llegó el evento result"
print("status:", resultado.get("status"))
print("answer:", resultado.get("answer"))
for c in resultado.get("components") or []:
    print("componente:", c.get("type"), "|", c.get("title"))
    print("  columns:", json.dumps(c.get("columns"), ensure_ascii=False))
    for fila in c.get("rows") or []:
        print("  row:", json.dumps(fila, ensure_ascii=False))
print("tools:", (resultado.get("trace") or {}).get("tools_executed"))

assert etapas, "no llegó ninguna etapa de progreso"
assert "planning" in etapas, "falta la etapa planning"
print("\nSSE OK: %d etapas + result" % len(etapas))
