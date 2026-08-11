"""RolePermissionManager — staff-only RBAC.

Two roles only: `staff` (check-in desk, can view queue/appointments, cannot
edit facility labels) and `admin` (adds Facility Map Editor access + user
management). Patients hold no role at all — public endpoints simply don't
require auth (see auth/dependencies.py's `optional_session` vs `require_permission`).
"""

from __future__ import annotations

_STAFF_PERMS: frozenset[str] = frozenset(
    {
        "queue:read",
        "queue:manage",
        "appointment:read",
        "appointment:manage",
        "facility_map:read",
        "audit:read:own",
        "dashboard:read",
    }
)

_ADMIN_PERMS: frozenset[str] = _STAFF_PERMS | frozenset(
    {
        "facility_map:write",
        "facility_map:export",
        "user:manage",
        "audit:read",
    }
)

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "staff": _STAFF_PERMS,
    "admin": _ADMIN_PERMS,
}

VALID_ROLES = frozenset(ROLE_PERMISSIONS.keys())


class RolePermissionManager:
    def __init__(self) -> None:
        self._perms = ROLE_PERMISSIONS

    def has_permission(self, role: str, permission: str) -> bool:
        return permission in self._perms.get(role, frozenset())

    def is_valid_role(self, role: str) -> bool:
        return role in VALID_ROLES
