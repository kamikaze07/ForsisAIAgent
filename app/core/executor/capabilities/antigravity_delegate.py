"""
Tool experimental y completamente aislada (prueba de concepto): delega un
prompt a Antigravity (el CLI `agy`) en modo no interactivo y devuelve su
respuesta cruda, sin interpretarla.

Investigación real hecha antes de escribir este código (ver evidencia en
la conversación / docs de la POC):
  - `agy --print "<prompt>" --output-format json` es un modo NO interactivo
    de un solo turno: no imprime banners de arranque, no requiere detectar
    "listo para recibir input" -- el proceso simplemente corre y termina.
    No hace falta pexpect ni un PTY.
  - stdout es SIEMPRE un único JSON (tanto en éxito como en error), con
    forma {"status": "SUCCESS"|"ERROR", "response": str, "error": str, ...}.
  - Exit code 0 en éxito, 1 en cualquier error (modelo inválido, timeout
    interno, etc.).
  - `--print-timeout` (default 5m) controla el timeout interno del propio
    `agy`; igual le damos un margen extra por subprocess como red de
    seguridad.

Este archivo se puede borrar sin afectar el resto del proyecto: sólo hay
que quitar su registro en bootstrap.py (import + registry.register()).
"""
import json
import shutil
import subprocess
import time
from datetime import datetime, timezone
from typing import Any, Dict

from pydantic import BaseModel, Field, ValidationError

from app.contracts.capability_definition import CapabilityDefinition
from app.contracts.error_response import ErrorResponse
from app.contracts.execution_result import ExecutionResult
from app.core.executor.capability import Capability

AGY_BINARY_FALLBACK = "/home/servidor/.local/bin/agy"
AGY_PRINT_TIMEOUT = "300s"
SUBPROCESS_TIMEOUT_S = 330  # margen extra sobre el timeout interno de `agy`


class DelegarAntigravityInput(BaseModel):
    prompt: str = Field(
        ..., min_length=1, description="Prompt a enviar a Antigravity tal cual, sin modificarlo."
    )


class DelegarAntigravityTool(Capability):
    """
    POC aislada: lanza `agy --print <prompt>` y devuelve exactamente el
    texto de su respuesta. No interpreta, no resume, no reformatea.
    """

    def execute(self, parameters: Dict[str, Any]) -> ExecutionResult[str]:
        started_at = datetime.now(timezone.utc)
        start = time.perf_counter()

        def _finish(**kwargs) -> ExecutionResult[str]:
            return ExecutionResult[str](
                started_at=started_at,
                finished_at=datetime.now(timezone.utc),
                execution_time_ms=int((time.perf_counter() - start) * 1000),
                **kwargs,
            )

        try:
            input_data = DelegarAntigravityInput(**parameters)
        except ValidationError as exc:
            return _finish(
                success=False,
                error=ErrorResponse(error_code="INVALID_PARAMETERS", message=str(exc)),
            )

        agy_bin = shutil.which("agy") or AGY_BINARY_FALLBACK

        try:
            proc = subprocess.run(
                [
                    agy_bin,
                    "--print", input_data.prompt,
                    "--output-format", "json",
                    "--print-timeout", AGY_PRINT_TIMEOUT,
                ],
                capture_output=True,
                text=True,
                timeout=SUBPROCESS_TIMEOUT_S,
            )
        except FileNotFoundError:
            return _finish(
                success=False,
                error=ErrorResponse(
                    error_code="ANTIGRAVITY_NOT_FOUND",
                    message=f"No se encontró el binario de Antigravity ('{agy_bin}').",
                ),
            )
        except subprocess.TimeoutExpired:
            return _finish(
                success=False,
                error=ErrorResponse(
                    error_code="ANTIGRAVITY_TIMEOUT",
                    message=f"Antigravity no respondió dentro de {SUBPROCESS_TIMEOUT_S}s.",
                ),
            )
        except Exception as exc:
            return _finish(
                success=False,
                error=ErrorResponse(error_code="ANTIGRAVITY_LAUNCH_ERROR", message=str(exc)),
            )

        try:
            payload = json.loads(proc.stdout)
        except (json.JSONDecodeError, TypeError):
            return _finish(
                success=False,
                error=ErrorResponse(
                    error_code="ANTIGRAVITY_UNEXPECTED_OUTPUT",
                    message=(
                        "Antigravity no devolvió JSON válido "
                        f"(exit={proc.returncode}). stdout={proc.stdout!r} stderr={proc.stderr!r}"
                    ),
                ),
            )

        if proc.returncode != 0 or payload.get("status") != "SUCCESS":
            return _finish(
                success=False,
                error=ErrorResponse(
                    error_code="ANTIGRAVITY_ERROR",
                    message=payload.get("error") or f"Antigravity terminó con exit={proc.returncode}.",
                ),
            )

        return _finish(success=True, data=payload.get("response", ""))


delegar_antigravity_definition = CapabilityDefinition(
    id="delegar_antigravity",
    name="delegar_antigravity",
    description=(
        "[EXPERIMENTAL / POC] Delega un prompt textual a Antigravity (agy) en modo "
        "no interactivo y devuelve su respuesta cruda, sin interpretarla ni resumirla. "
        "Únicamente para validar la integración técnica -- no usar en flujos reales."
    ),
    category="experimental",
    input_schema=DelegarAntigravityInput.model_json_schema(),
    experimental=True,
    timeout=SUBPROCESS_TIMEOUT_S,
)
