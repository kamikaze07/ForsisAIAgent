from typing import Any, Dict
from datetime import datetime, timezone

from app.contracts.capability_definition import CapabilityDefinition
from app.core.executor.capability import Capability


class EchoCapability(Capability):
    def execute(self, parameters: Dict[str, Any]) -> Any:
        return parameters.get("message", "")


class SumarCapability(Capability):
    def execute(self, parameters: Dict[str, Any]) -> Any:
        a = parameters.get("a")
        b = parameters.get("b")
        if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
            raise ValueError("Los parámetros 'a' y 'b' deben ser numéricos.")
        return a + b


class FechaActualCapability(Capability):
    def execute(self, parameters: Dict[str, Any]) -> Any:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")


class HoraActualCapability(Capability):
    def execute(self, parameters: Dict[str, Any]) -> Any:
        return datetime.now(timezone.utc).strftime("%H:%M:%S")


class VersionCapability(Capability):
    def execute(self, parameters: Dict[str, Any]) -> Any:
        return "1.0.0-dummy"


def get_dummy_definitions():
    return [
        (CapabilityDefinition(id="cap-echo", name="echo", description="Eco"), EchoCapability),
        (CapabilityDefinition(id="cap-sumar", name="sumar", description="Suma a+b"), SumarCapability),
        (CapabilityDefinition(id="cap-fecha", name="fecha_actual", description="Fecha UTC"), FechaActualCapability),
        (CapabilityDefinition(id="cap-hora", name="hora_actual", description="Hora UTC"), HoraActualCapability),
        (CapabilityDefinition(id="cap-version", name="version", description="Versión interna"), VersionCapability),
    ]
