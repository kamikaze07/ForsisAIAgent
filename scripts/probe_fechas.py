"""
Repite una pregunta varias veces y muestra el SQL realmente generado.

Sirve para diagnosticar incoherencia de rango de fechas: si el LLM escribe
fechas literales en vez de funciones relativas (CURDATE), cada respuesta
puede cubrir un periodo distinto aunque la pregunta sea la misma.
"""
from __future__ import annotations

import json
import sys

from fastapi.testclient import TestClient

from app.api.v1 import ui as ui_mod
from app.main import app

PREGUNTAS = sys.argv[1:] or [
    "cuantas guias se generaron en este mes en forsis y de que clientes?",
    "cuanto se ha facturado en este mes de octubre?",
]


class _User:
    id = "probe-fecha"
    display_name = "Probe Fecha"
    agent_roles = ("admin",)
    is_admin = True
    username = "probe"

    def actor_subject(self) -> str:
        return "probe-fecha"


class _Sess:
    user = _User()
    csrf_token = "probe-csrf"


app.dependency_overrides[ui_mod.require_ui_user] = lambda: _Sess()
ui_mod._require_csrf = lambda request, sess: None
client = TestClient(app)

for pregunta in PREGUNTAS:
    print("=" * 78)
    print("PREGUNTA:", pregunta)
    r = client.post(
        "/api/v1/ui/chat",
        json={"message": pregunta, "company": "FORSIS"},
        headers={"Idempotency-Key": "probe-fecha-%s" % abs(hash(pregunta))},
    )
    d = r.json()
    print("HTTP", r.status_code, "| status:", d.get("status"))
    print("answer:", d.get("answer"))
    tr = d.get("trace") or {}
    print("tools:", tr.get("tools_executed"))

    # El SQL vive en el detalle de la traza si el turno lo expone; si no, se
    # busca en el cualquier representation serializada de la respuesta.
    blob = json.dumps(d, ensure_ascii=False)
    sqls: list[str] = []
    def _walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k in ("query_sql", "sql") and isinstance(v, str):
                    sqls.append(v)
                _walk(v)
        elif isinstance(o, list):
            for v in o:
                _walk(v)
    _walk(d)
    for s in sqls:
        print("SQL:", " ".join(s.split()))
    if not sqls:
        print("(el turno no expone query_sql en la respuesta)")
    for c in d.get("components") or []:
        if c.get("type") == "table":
            for fila in c.get("rows") or []:
                print("row:", json.dumps(fila, ensure_ascii=False))