"""
Métricas in-process del agente (llm-provider.md §3.4 — V-1 medido desde el día 1).

Contadores por CAPA de parseo del LLM, exigidos por el criterio A6 del Sprint 2:

    llm_json_ok       : el modelo devolvió JSON válido en la capa 1 (parseo directo).
    llm_salvage       : el JSON vino dentro de texto/fences y se recuperó en capas 2-3.
    llm_failclosed    : tras los intentos permitidos no hubo JSON válido → LlmJsonInvalidError.
    llm_attempts      : reintentos de formato consumidos en total.
    llm_http_error    : Omniroute respondió != 200.
    llm_network_error : fallo de red / timeout contra Omniroute.
    llm_timeout       : la llamada superó el techo duro (60 s por llamada).
    turn_timeout      : el turno completo superó el techo de turno (120 s).
    cache_hit/miss    : caché semántica de OmniRoute, observable desde el agente.

Sin estado global en el módulo: un objeto por proceso, expuesto por
`GET /api/v1/metrics`. Es deliberadamente minimalista — Prometheus/OTel llegan en
el Sprint 8; lo que el Sprint 2 necesita es que las cifras existan y sean medibles.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict


class Metrics:
    """Contadores de latencia con bloqueo ligero. Seguro entre hilos."""

    _COUNTERS = (
        "llm_json_ok",
        "llm_salvage",
        "llm_failclosed",
        "llm_attempts",
        "llm_http_error",
        "llm_network_error",
        "llm_timeout",
        "turn_timeout",
        "cache_hit",
        "cache_miss",
        "turn_total",
        "turn_rejected",
        # Sprint 3 — métricas de tool (entregable 8).
        "tool_calls",
        "tool_ok",
        "tool_error",
        "tool_denied",
        "tool_timeout",
        "tool_calls_l0",
        "tool_calls_l1",
        "tool_calls_l2",
        "tool_calls_l3",
        "sql_queries",
        "sql_rejected",
    )

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: Dict[str, int] = {k: 0 for k in self._COUNTERS}
        self._started_at = time.time()
        # Latencia de tools: suma y cuenta por capability, para calcular la
        # media sin guardar un histograma (Prometheus llega en el Sprint 8).
        self._tool_ms_sum: Dict[str, int] = {}
        self._tool_ms_count: Dict[str, int] = {}
        self._tool_ms_max: Dict[str, int] = {}

    def observe_tool(self, capability_id: str, duration_ms: int, risk_class: str = "L0",
                     outcome: str = "ok") -> None:
        """
        Registra una invocación de tool: latencia, resultado y clase de riesgo
        (Sprint 3 entregable 8: "latencia, tasa de error, count por risk_class").
        """
        self.incr("tool_calls")
        self.incr(f"tool_calls_{str(risk_class).lower()}")
        self.incr({"ok": "tool_ok", "error": "tool_error",
                   "denied": "tool_denied", "timeout": "tool_timeout"}.get(outcome, "tool_error"))
        with self._lock:
            self._tool_ms_sum[capability_id] = self._tool_ms_sum.get(capability_id, 0) + int(duration_ms)
            self._tool_ms_count[capability_id] = self._tool_ms_count.get(capability_id, 0) + 1
            self._tool_ms_max[capability_id] = max(self._tool_ms_max.get(capability_id, 0), int(duration_ms))

    def tool_latency(self) -> Dict[str, Any]:
        with self._lock:
            sums = dict(self._tool_ms_sum)
            counts = dict(self._tool_ms_count)
            maxs = dict(self._tool_ms_max)
        return {
            cid: {
                "calls": counts[cid],
                "avg_ms": round(sums[cid] / counts[cid], 1) if counts[cid] else None,
                "max_ms": maxs.get(cid, 0),
            }
            for cid in counts
        }

    def incr(self, name: str, value: int = 1) -> None:
        if name not in self._counters:
            # Nunca silencies un nombre mal escrito: lo registras igual.
            with self._lock:
                self._counters.setdefault(name, 0)
        with self._lock:
            self._counters[name] += value

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            counters = dict(self._counters)

        parsed_ok = counters.get("llm_json_ok", 0) + counters.get("llm_salvage", 0)
        failclosed = counters.get("llm_failclosed", 0)
        total_attempts = parsed_ok + failclosed
        # V-1 = tasa de éxito de formato sobre turnos que llegaron a una
        # respuesta final. Es la métrica que decide si se avanza a tools de
        # escritura (sprint-plan-v2 §Sprint 2, "Riesgo").
        v1 = round(parsed_ok / total_attempts * 100, 2) if total_attempts else None

        return {
            "counters": counters,
            "derived": {
                "llm_format_attempts": total_attempts,
                "llm_format_success_rate_pct": v1,
                "salvage_rate_pct": (
                    round(counters.get("llm_salvage", 0) / parsed_ok * 100, 2) if parsed_ok else None
                ),
                "uptime_s": round(time.time() - self._started_at, 1),
                "tool_error_rate_pct": (
                    round(counters.get("tool_error", 0) / counters["tool_calls"] * 100, 2)
                    if counters.get("tool_calls") else None
                ),
                "tool_latency": self.tool_latency(),
            },
        }

    def reset(self) -> None:
        with self._lock:
            for k in self._counters:
                self._counters[k] = 0
            self._tool_ms_sum.clear()
            self._tool_ms_count.clear()
            self._tool_ms_max.clear()


# Instancia única del proceso.
metrics = Metrics()