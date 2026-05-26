"""RolePermissionManager — define and enforce role-based access control.

Roles (ascending privilege):  viewer < operator < engineer < admin

Each role has a set of permission strings.  Higher roles inherit all
permissions of lower roles.
"""

from __future__ import annotations

from typing import Dict, FrozenSet, Optional

# Fine-grained permission strings
_VIEWER_PERMS: FrozenSet[str] = frozenset({
    "robot:read",
    "diagnostics:read",
    "config:read",
})

_OPERATOR_PERMS: FrozenSet[str] = _VIEWER_PERMS | frozenset({
    "robot:command:speak",
    "robot:command:navigate",
    "robot:command:pause",
    "robot:command:resume",
    "robot:command:dock",
    "robot:command:emergency_stop",
    "robot:command:cancel_task",
})

_ENGINEER_PERMS: FrozenSet[str] = _OPERATOR_PERMS | frozenset({
    "diagnostics:write",
    "diagnostics:restart_module",
    "diagnostics:run_healthcheck",
    "config:write:limited",
    "memory:read",
    "rag:query",
})

_ADMIN_PERMS: FrozenSet[str] = _ENGINEER_PERMS | frozenset({
    "config:write:critical",
    "memory:write",
    "user:manage",
    "audit:read",
    "diagnostics:force_restart",
})

ROLE_PERMISSIONS: Dict[str, FrozenSet[str]] = {
    "viewer":   _VIEWER_PERMS,
    "operator": _OPERATOR_PERMS,
    "engineer": _ENGINEER_PERMS,
    "admin":    _ADMIN_PERMS,
}

VALID_ROLES = frozenset(ROLE_PERMISSIONS.keys())


class RolePermissionManager:
    """Check whether a role holds a given permission."""

    def __init__(self) -> None:
        self._perms = ROLE_PERMISSIONS

    def has_permission(self, role: str, permission: str) -> bool:
        """Return True if *role* holds *permission*."""
        return permission in self._perms.get(role, frozenset())

    def get_permissions(self, role: str) -> FrozenSet[str]:
        """Return the full permission set for *role*."""
        return self._perms.get(role, frozenset())

    def is_valid_role(self, role: str) -> bool:
        return role in VALID_ROLES

    def require_permission(self, role: str, permission: str) -> None:
        """Raise ``PermissionError`` if *role* does not hold *permission*."""
        if not self.has_permission(role, permission):
            raise PermissionError(
                f"Role '{role}' does not have permission '{permission}'"
            )

    def can_update_config_key(self, role: str, key: str) -> bool:
        """Return True if *role* may update config *key*."""
        from bonbon_operator_api.config.api_config import (
            CRITICAL_CONFIG_KEYS,
            LIMITED_CONFIG_KEYS,
        )
        if key in CRITICAL_CONFIG_KEYS:
            return self.has_permission(role, "config:write:critical")
        if key in LIMITED_CONFIG_KEYS:
            return self.has_permission(role, "config:write:limited")
        return False  # unknown keys always denied
