"""
Component 13: Runtime API / Facade
Main public runtime interface enforcing strict flow: Registry -> Action -> Playbook -> Execution -> Verification -> Audit.
"""

from typing import List, Dict, Any, Optional
from app.runtime.models import (
    UserContext, RegistryEntryModel, CapabilityPlan, DryRunReport,
    ExecutionResult, ApprovalRequest, AuditRecord, KnowledgeModel,
    OperationalContext, CapabilityCategory
)
from app.runtime.loaders.registry_loader import RegistryLoader
from app.runtime.loaders.action_loader import ActionLoader
from app.runtime.loaders.playbook_loader import PlaybookLoader
from app.runtime.loaders.knowledge_loader import KnowledgeLoader
from app.runtime.validation.startup_validator import StartupValidator
from app.runtime.security.permission_engine import PermissionEngine
from app.runtime.planner.planner import Planner
from app.runtime.simulation.dry_run_engine import DryRunEngine
from app.runtime.approval.approval_gateway import ApprovalGateway
from app.runtime.execution.executor import Executor
from app.runtime.verification.verification_engine import VerificationEngine
from app.runtime.audit.audit_engine import AuditEngine
from app.runtime.memory.runtime_memory import RuntimeMemory


from app.integration.manager import IntegrationManager
from app.integration.models import ProviderMetadata, ProviderHealthStatus, ProviderMetrics, SystemStatusReport


class ForsisOperationalRuntime:
    def __init__(
        self,
        base_dir: str = "/home/servidor/forsis-agent",
        auto_startup_validation: bool = True
    ):
        registry_dir = f"{base_dir}/operational-registry"
        actions_dir = f"{base_dir}/operational-actions"
        playbooks_dir = f"{base_dir}/operational-playbooks"
        knowledge_dir = f"{base_dir}/operational-knowledge"

        self.registry_loader = RegistryLoader(registry_dir)
        self.action_loader = ActionLoader(actions_dir)
        self.playbook_loader = PlaybookLoader(playbooks_dir)
        self.knowledge_loader = KnowledgeLoader(knowledge_dir)

        self.startup_validator = StartupValidator(
            self.registry_loader, self.action_loader,
            self.playbook_loader, self.knowledge_loader
        )

        self.permission_engine = PermissionEngine()
        self.planner = Planner(
            self.registry_loader, self.action_loader,
            self.playbook_loader, self.permission_engine
        )
        self.dry_run_engine = DryRunEngine()
        self.approval_gateway = ApprovalGateway()
        self.integration_manager = IntegrationManager()
        self.executor = Executor()
        
        # Attach IntegrationManager to HTTP adapter
        from app.runtime.execution.adapters import HttpExecutionAdapter
        self.executor.register_adapter("http", HttpExecutionAdapter(self.integration_manager))

        self.verification_engine = VerificationEngine()
        self.audit_engine = AuditEngine()
        self.runtime_memory = RuntimeMemory()
        self._operational_contexts: Dict[str, OperationalContext] = {}

        # Load all components
        self.registry_loader.load_all()
        self.action_loader.load_all()
        self.playbook_loader.load_all()
        self.knowledge_loader.load_all()

        if auto_startup_validation:
            self.initialize_and_validate()

    # --- Operational Context API ---
    def get_context(self, session_id: str) -> OperationalContext:
        if session_id not in self._operational_contexts:
            self._operational_contexts[session_id] = OperationalContext(session_id=session_id)
        return self._operational_contexts[session_id]

    def set_context(self, session_id: str, context: OperationalContext) -> None:
        context.session_id = session_id
        self._operational_contexts[session_id] = context

    def update_context(self, session_id: str, **kwargs) -> OperationalContext:
        ctx = self.get_context(session_id)
        for k, v in kwargs.items():
            if hasattr(ctx, k):
                setattr(ctx, k, v)
            else:
                ctx.metadata[k] = v
        return ctx

    def merge_context(self, session_id: str, context_dict: Dict[str, Any]) -> OperationalContext:
        return self.update_context(session_id, **context_dict)

    def clear_context(self, session_id: str) -> None:
        self._operational_contexts[session_id] = OperationalContext(session_id=session_id)

    def initialize_and_validate(self) -> List[str]:
        """Startup sequence: load architecture files and validate integrity."""
        return self.startup_validator.validate()

    def list_capabilities(self, domain: Optional[str] = None) -> List[RegistryEntryModel]:
        """List all capabilities in the Operational Registry, optionally filtered by domain."""
        if domain:
            return self.registry_loader.get_by_domain(domain)
        return self.registry_loader.list_all()

    def list_providers(self) -> List[ProviderMetadata]:
        """Observability endpoint: List all registered system integration providers."""
        return self.integration_manager.list_providers()

    def provider_health(self, provider_id: Optional[str] = None) -> List[ProviderHealthStatus]:
        """Observability endpoint: Track provider health status and latency."""
        return self.integration_manager.provider_health(provider_id)

    def provider_capabilities(self, provider_id: Optional[str] = None) -> Dict[str, List[str]]:
        """Observability endpoint: Negotiate and list provider capabilities."""
        return self.integration_manager.provider_capabilities(provider_id)

    def provider_metrics(self, provider_id: Optional[str] = None) -> List[ProviderMetrics]:
        """Observability endpoint: Expose operational metrics per provider."""
        return self.integration_manager.provider_metrics(provider_id)

    def runtime_status(self) -> SystemStatusReport:
        """Observability endpoint: Overall System Status and provider health ratio."""
        return self.integration_manager.runtime_status()

    def describe_capability(self, capability_query: str) -> Dict[str, Any]:
        """Describe a capability by resolving its Registry entry, Action contract, and Playbook procedure."""
        q = capability_query.strip()
        reg = (
            self.registry_loader.get_by_id(q)
            or self.registry_loader.get_by_action_id(q)
            or self.registry_loader.get_by_id(f"reg-{q}")
            or self.registry_loader.get_by_action_id(f"action-{q}")
        )
        if not reg:
            matches = self.registry_loader.get_by_capability(capability_query)
            if matches:
                reg = matches[0]

        if not reg:
            raise KeyError(f"Capability '{capability_query}' not found in Registry.")

        act = self.action_loader.get_by_id(reg.action_id)
        pb = None
        if reg.related_playbooks:
            pb = self.playbook_loader.get_by_slug(reg.related_playbooks[0])

        return {
            "registry_entry": reg,
            "action": act,
            "playbook": pb
        }

    def answer_what_is(self, term: str) -> Optional[KnowledgeModel]:
        """Answer 'What is this?' deterministically from Operational Knowledge Base."""
        return self.knowledge_loader.search_what_is(term)

    def plan_execution(
        self,
        user: UserContext,
        intent_query: str,
        inputs: Optional[Dict[str, Any]] = None
    ) -> CapabilityPlan:
        """Plan execution for a user request."""
        return self.planner.plan(user, intent_query, inputs)

    def simulate(self, plan: CapabilityPlan) -> DryRunReport:
        """Simulate plan execution without modifying production."""
        return self.dry_run_engine.simulate(plan)

    def execute(self, plan: CapabilityPlan, user: UserContext) -> ExecutionResult:
        """
        Execute a planned capability.
        Strict Flow: Registry -> Action -> Playbook -> Approval -> Execution -> Verification -> Audit
        """
        # 1. Permission evaluation check
        if not plan.is_executable:
            result = self.executor.execute(plan)
            self.audit_engine.record(plan, user, result, dry_run=False)
            self.runtime_memory.track_execution(result)
            return result

        # 2. Approval Interception Check
        pending_approval = self.approval_gateway.intercept_if_required(plan, user)
        if pending_approval:
            result = ExecutionResult(
                execution_id=f"exec-pending-{pending_approval.approval_id}",
                plan_id=plan.plan_id,
                registry_id=plan.registry_entry.registry_id,
                action_id=plan.action.action_id,
                status="APPROVAL_PENDING",
                outputs={"approval_id": pending_approval.approval_id, "reason": pending_approval.reason},
                verification=None
            )
            self.audit_engine.record(plan, user, result, dry_run=False, approval_id=pending_approval.approval_id)
            self.runtime_memory.track_execution(result)
            return result

        # 3. Execution Dispatch via Pluggable Adapters
        result = self.executor.execute(plan)

        # 4. Post-Execution Verification
        verif_result = self.verification_engine.verify(plan, result)
        result.verification = verif_result

        # 5. Immutable Audit Log Recording
        self.audit_engine.record(plan, user, result, dry_run=False)
        self.runtime_memory.track_execution(result)

        return result

    def verify(self, plan: CapabilityPlan, result: ExecutionResult) -> ExecutionResult:
        """Trigger explicit verification step."""
        verif = self.verification_engine.verify(plan, result)
        result.verification = verif
        return result

    def list_pending_approvals(self) -> List[ApprovalRequest]:
        """List all pending human approval requests."""
        return self.approval_gateway.list_pending_approvals()

    def resume_execution(self, approval_id: str, approver: UserContext, decision: str) -> ExecutionResult:
        """Resume execution after human approval decision."""
        if decision.upper() == "APPROVE":
            appr = self.approval_gateway.approve(approval_id, approver.user_id)
            reg = self.registry_loader.get_by_id(appr.registry_id)
            act = self.action_loader.get_by_id(appr.action_id)

            plan = CapabilityPlan(
                plan_id=appr.plan_id,
                user_request=appr.reason,
                registry_entry=reg,
                action=act,
                playbook=None,
                resolved_inputs=appr.inputs,
                required_permissions=reg.required_permissions,
                automation_level=reg.automation_level,
                requires_approval=False,
                is_executable=True
            )

            result = self.executor.execute(plan)
            result.verification = self.verification_engine.verify(plan, result)
            self.audit_engine.record(plan, approver, result, dry_run=False, approval_id=approval_id)
            self.runtime_memory.track_execution(result)
            return result
        else:
            appr = self.approval_gateway.reject(approval_id, approver.user_id)
            reg = self.registry_loader.get_by_id(appr.registry_id)
            act = self.action_loader.get_by_id(appr.action_id)

            plan = CapabilityPlan(
                plan_id=appr.plan_id,
                user_request=appr.reason,
                registry_entry=reg,
                action=act,
                playbook=None,
                resolved_inputs=appr.inputs,
                required_permissions=reg.required_permissions,
                automation_level=reg.automation_level,
                requires_approval=False,
                is_executable=False,
                rejection_reason=f"Human approval rejected by user {approver.username}."
            )

            result = ExecutionResult(
                execution_id=f"exec-rejected-{approval_id}",
                plan_id=appr.plan_id,
                registry_id=appr.registry_id,
                action_id=appr.action_id,
                status="DENIED",
                outputs={},
                verification=None,
                error_message=f"Human approval rejected by user {approver.username}."
            )

            self.audit_engine.record(plan, approver, result, dry_run=False, approval_id=approval_id)
            self.runtime_memory.track_execution(result)
            return result
