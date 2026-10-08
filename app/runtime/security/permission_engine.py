"""
Component 6: Permission Engine
Evaluates requested capability permissions against user roles.
Determines allowed vs denied with explicit explanations and missing permissions list.
"""

from typing import List, Tuple, Dict, Set
from app.runtime.models import UserContext, RegistryEntryModel, ActionModel


class PermissionEngine:
    def __init__(self):
        # Role hierarchy mappings
        self._role_hierarchy: Dict[str, Set[str]] = {
            "SUPER USUARIO": {
                "SUPER USUARIO", "ADMINISTRADOR", "FACTURACION", "TRAFICO",
                "LIQUIDACIONES", "RECURSOS HUMANOS", "COBRANZA", "FLOTA",
                "RECEPCION", "SISTEMAS", "INGENIERIA", "AUTHENTICATED_USER", "ROLES_OPERAN_GUIAS",
                "GERENTE DE OPERACIONES"
            },
            "ADMINISTRADOR": {
                "ADMINISTRADOR", "FACTURACION", "TRAFICO", "LIQUIDACIONES",
                "RECURSOS HUMANOS", "COBRANZA", "FLOTA", "RECEPCION",
                "AUTHENTICATED_USER", "ROLES_OPERAN_GUIAS"
            },
            "GERENTE DE OPERACIONES": {
                "GERENTE DE OPERACIONES", "TRAFICO", "FLOTA", "AUTHENTICATED_USER"
            },
            "FACTURACION": {"FACTURACION", "COBRANZA", "AUTHENTICATED_USER"},
            "TRAFICO": {"TRAFICO", "AUTHENTICATED_USER"},
            "LIQUIDACIONES": {"LIQUIDACIONES", "AUTHENTICATED_USER"},
            "RECURSOS HUMANOS": {"RECURSOS HUMANOS", "AUTHENTICATED_USER"},
            "FLOTA": {"FLOTA", "AUTHENTICATED_USER"},
            "RECEPCION": {"RECEPCION", "AUTHENTICATED_USER"},
            "AUTHENTICATED_USER": {"AUTHENTICATED_USER"}
        }

    def evaluate(self, user: UserContext, required_permissions: List[str]) -> Tuple[bool, List[str], str]:
        """
        Evaluate user permissions.
        Returns: (allowed, missing_permissions, explanation)
        """
        if not required_permissions:
            return True, [], "No specific permissions required for this capability."

        # Expand user's effective permissions based on roles
        effective_permissions: Set[str] = set()
        for role in user.roles:
            role_upper = role.upper()
            effective_permissions.add(role_upper)
            if role_upper in self._role_hierarchy:
                effective_permissions.update(self._role_hierarchy[role_upper])

        missing: List[str] = []
        for perm in required_permissions:
            perm_clean = perm.split(":")[0].strip().upper()
            if perm_clean in ["AUTOMATIC_CRON", "AUTOMATIC_DAEMON", "AUTOMATIC_BATCH"]:
                continue

            # Check if any user role matches permission string or options after colon
            all_permitted_roles = [perm_clean]
            if ":" in perm:
                options_str = perm.split(":", 1)[1]
                all_permitted_roles.extend([r.strip().upper() for r in options_str.split(",")])

            if not any(r in effective_permissions for r in all_permitted_roles):
                missing.append(perm)

        if not missing:
            return True, [], f"Access granted for user '{user.username}' with roles {user.roles}."

        explanation = (
            f"Access denied for user '{user.username}'. "
            f"Required permissions: {required_permissions}, "
            f"Missing permissions: {missing}."
        )

        return False, missing, explanation
