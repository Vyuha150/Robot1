"""Config API — view and update robot configuration parameters.

Two permission tiers:
  config:write:limited   — operator-accessible params (tts volume, speed preference)
  config:write:critical  — safety-critical params (emergency distance, watchdog)

Config changes are always audit-logged.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from bonbon_operator_api.auth.dependencies import get_current_user, require_permission
from bonbon_operator_api.config.api_config import CRITICAL_CONFIG_KEYS, LIMITED_CONFIG_KEYS
from bonbon_operator_api.models.auth_models import TokenPayload
from bonbon_operator_api.models.response_models import APIResponse

logger = logging.getLogger(__name__)

config_router = APIRouter(prefix="/config", tags=["configuration"])

# All writable keys = limited + critical
_ALL_WRITABLE = CRITICAL_CONFIG_KEYS | LIMITED_CONFIG_KEYS


class ConfigUpdateRequest(BaseModel):
    key: str
    value: Any


class _ConfigStore:
    """Simple JSON file-backed config store."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            self._path.write_text("{}", encoding="utf-8")

    def get_all(self) -> Dict[str, Any]:
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def get(self, key: str) -> Optional[Any]:
        return self.get_all().get(key)

    def set(self, key: str, value: Any) -> None:
        data = self.get_all()
        data[key] = value
        self._path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _get_config_store(request: Request) -> _ConfigStore:
    return request.app.state.config_store


@config_router.get("/", response_model=APIResponse)
async def get_all_config(
    request: Request,
    current_user: TokenPayload = Depends(require_permission("config:read")),
) -> APIResponse:
    """Return all stored configuration values."""
    store = _get_config_store(request)
    return APIResponse.ok(store.get_all())


@config_router.get("/{key:path}", response_model=APIResponse)
async def get_config_key(
    request: Request,
    key: str,
    current_user: TokenPayload = Depends(require_permission("config:read")),
) -> APIResponse:
    """Return the value for a single config key."""
    store = _get_config_store(request)
    value = store.get(key)
    if value is None and key not in store.get_all():
        raise HTTPException(status_code=404, detail=f"Config key '{key}' not found")
    return APIResponse.ok({"key": key, "value": value})


@config_router.put("/", response_model=APIResponse)
async def set_config_key(
    request: Request,
    body: ConfigUpdateRequest,
    current_user: TokenPayload = Depends(get_current_user),
) -> APIResponse:
    """Update a configuration key.

    Requires ``config:write:critical`` for safety-critical keys,
    ``config:write:limited`` for operator-accessible keys.
    """
    role_mgr = request.app.state.role_manager
    audit = request.app.state.audit_logger
    ip = request.client.host if request.client else ""

    key = body.key

    # Determine required permission
    if key in CRITICAL_CONFIG_KEYS:
        required_perm = "config:write:critical"
    elif key in LIMITED_CONFIG_KEYS:
        required_perm = "config:write:limited"
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Key '{key}' is not a writable config key. "
                   f"Writable keys: {sorted(_ALL_WRITABLE)}",
        )

    if not role_mgr.has_permission(current_user.role, required_perm):
        audit.log(
            actor_id=current_user.sub,
            actor_name=current_user.username,
            actor_role=current_user.role,
            action="config:write",
            target=key,
            outcome="forbidden",
            detail=f"Required permission: {required_perm}",
            ip_address=ip,
        )
        request.app.state.metrics.record_audit_event()
        raise HTTPException(
            status_code=403,
            detail=f"Insufficient permissions. Required: {required_perm}",
        )

    store = _get_config_store(request)
    store.set(key, body.value)

    # Propagate to ROS2 if bridge is available
    bridge = request.app.state.ros2_bridge
    bridge.call_set_config(key, body.value)

    audit.log(
        actor_id=current_user.sub,
        actor_name=current_user.username,
        actor_role=current_user.role,
        action="config:write",
        target=key,
        request_data={"key": key, "value": str(body.value)[:200]},
        outcome="success",
        ip_address=ip,
    )
    request.app.state.metrics.record_audit_event()
    return APIResponse.ok({"key": key, "value": body.value, "updated": True})
