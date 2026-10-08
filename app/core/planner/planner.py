from app.contracts import AgentContext, ExecutionPlan, UserRequest
from app.core.executor.registry import CapabilityRegistry
from app.core.prompts import PromptBuilder
from app.infrastructure.llm_gateway.base import LLMProvider


class Planner:
    """
    Componente central encargado de interpretar la intención del usuario
    y generar un plan de ejecución determinista.
    Es completamente stateless.

    Consulta el CapabilityRegistry en cada llamada a plan() para construir
    el prompt con el catálogo REAL de capabilities disponibles — nunca con
    una lista fija ni vacía.
    """

    def __init__(self, llm_provider: LLMProvider, registry: CapabilityRegistry, runtime=None):
        self.llm_provider = llm_provider
        self.registry = registry
        self.runtime = runtime
        if self.runtime:
            self.registry.sync_with_runtime(self.runtime)

    def plan(self, request: UserRequest, context: AgentContext) -> ExecutionPlan:
        capabilities_available = self.registry.list_definitions()
        workflows_available = []

        # Extraemos la construcción del prompt al builder, con el catálogo real
        system_prompt = PromptBuilder.build_system_prompt(capabilities_available)

        plan_context = {
            "session_id": context.session_id,
            "request_context": request.context,
            "history": context.history,
            "state": context.state
        }

        # Generación directa y abstracta
        execution_plan = self.llm_provider.generate_plan(
            system_prompt=system_prompt,
            user_prompt=PromptBuilder.build_user_prompt(request.text),
            context=plan_context,
            capabilities=capabilities_available,
            workflows=workflows_available,
            options={}
        )

        return execution_plan
