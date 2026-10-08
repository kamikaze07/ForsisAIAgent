"""
Component 7: Dry Run Engine
Simulates mutating Actions without modifying production databases or external services.
Produces structured DryRunReport.
"""

from app.runtime.models import CapabilityPlan, DryRunReport


class DryRunEngine:
    def simulate(self, plan: CapabilityPlan) -> DryRunReport:
        """
        Produce a non-destructive execution simulation.
        Never modifies production database or executes live webhooks.
        """
        reg = plan.registry_entry
        act = plan.action

        affected_systems = [reg.owning_system]
        affected_entities = reg.entity_types
        affected_tables = reg.entity_types  # In Forsis DB schema, entity types map directly to critical tables

        irreversible = not reg.reversible
        rollback_available = reg.reversible

        return DryRunReport(
            plan_id=plan.plan_id,
            registry_id=reg.registry_id,
            action_id=reg.action_id,
            display_name=reg.display_name,
            mutates_state=reg.mutates_state,
            affected_systems=affected_systems,
            affected_entities=affected_entities,
            affected_tables=affected_tables,
            external_integrations=reg.external_integrations,
            irreversible_operation=irreversible,
            rollback_available=rollback_available,
            approval_required=plan.requires_approval,
            required_permissions=reg.required_permissions,
            simulated_inputs=plan.resolved_inputs,
            expected_outputs=reg.outputs
        )
