"""
Taxonomía de riesgo L0–L3 (`tools-design.md` §1).

Una sola escala para todo el agente. El Registry no registra L3 como
invocable: existe en el enum para poder **denegar explícitamente** y dejar
rastro, no para ejecutarse (`tools-design.md` §1, nota "L3 → NO EXPUESTO").
"""

from __future__ import annotations

from enum import Enum


class RiskClass(str, Enum):
    L0 = "L0"   # Lectura segura, idempotente
    L1 = "L1"   # Lectura con inferencia/agregación: condiciona decisiones
    L2 = "L2"   # Escritura reversible o que solo encola una solicitud
    L3 = "L3"   # Escritura irreversible → PROHIBIDA en MVP

    @property
    def is_read_only(self) -> bool:
        return self in (RiskClass.L0, RiskClass.L1)

    @property
    def requires_dry_run(self) -> bool:
        return self in (RiskClass.L2, RiskClass.L3)

    @property
    def requires_human_confirmation(self) -> bool:
        return self is RiskClass.L2

    @property
    def is_executable(self) -> bool:
        """
        L3 nunca es ejecutable. L2 lo es sólo tras dry-run + confirmación
        (Sprint 7); en Fase 1 el PlanGuard la rechaza igualmente por no
        existir allowlist de escritura (`AGENT_WRITE_ALLOWLIST=""`).
        """
        return self in (RiskClass.L0, RiskClass.L1, RiskClass.L2)


# Clases admitidas para EJECUCIÓN en Sprint 3. Deliberadamente sin L2:
# "sin escrituras a propósito. La primera escritura llega en el Sprint 7"
# (sprint-plan-v2.md §Sprint 3, Nota de alcance).
SPRINT3_ALLOWED = frozenset({RiskClass.L0, RiskClass.L1})
