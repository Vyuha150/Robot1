"""Diagnostics API — module health, restart, and audit log access."""

from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from bonbon_operator_api.auth.dependencies import require_permission
from bonbon_operator_api.models.auth_models import TokenPayload
from bonbon_operator_api.models.response_models import APIResponse

logger = logging.getLogger(__name__)

diag_router = APIRouter(prefix="/diagnostics", tags=["diagnostics"])

# Valid module names that can be restarted
_RESTARTABLE_MODULES = frozenset({
    "bonbon_tts",
    "bonbon_navigation",
    "bonbon_perception",
    "bonbon_actuation",
    "bonbon_data_stores",
    "bonbon_safety",
})


@diag_router.get("/modules", response_model=APIResponse)
async def get_module_status(
    request: Request,
    current_user: TokenPayload = Depends(require_permission("diagnostics:read")),
) -> APIResponse:
    """Return health status of all robot modules."""
    aggregator = request.app.state.status_aggregator
    status = aggregator.get_status()
    return APIResponse.ok({
        "modules": {
            name: m.model_dump() for name, m in status.modules.items()
        },
        "overall_health": status.overall_health(),
    })


@diag_router.post("/modules/{module_name}/restart", response_model=APIResponse)
async def restart_module(
    request: Request,
    module_name: str,
    current_user: TokenPayload = Depends(
        require_permission("diagnostics:restart_module")
    ),
) -> APIResponse:
    """Restart a named ROS2 module (engineer+)."""
    if module_name not in _RESTARTABLE_MODULES:
        raise HTTPException(
            status_code=400,
            detail=f"Module '{module_name}' is not restartable via the API. "
                   f"Valid modules: {sorted(_RESTARTABLE_MODULES)}",
        )
    bridge = request.app.state.ros2_bridge
    audit = request.app.state.audit_logger
    ip = request.client.host if request.client else ""

    result = bridge.call_restart_module(module_name)
    audit.log(
        actor_id=current_user.sub,
        actor_name=current_user.username,
        actor_role=current_user.role,
        action="diagnostics:restart_module",
        target=module_name,
        outcome="success" if result.get("success") else "failure",
        ip_address=ip,
    )
    request.app.state.metrics.record_audit_event()
    return APIResponse.ok({"module": module_name, "restart_requested": True})


@diag_router.get("/audit", response_model=APIResponse)
async def get_audit_log(
    request: Request,
    actor_id: Optional[str] = Query(default=None),
    action: Optional[str] = Query(default=None),
    since_ts: Optional[float] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    current_user: TokenPayload = Depends(require_permission("audit:read")),
) -> APIResponse:
    """Query the audit log (admin only)."""
    audit = request.app.state.audit_logger
    events = audit.query(
        actor_id=actor_id,
        action=action,
        since_ts=since_ts,
        limit=limit,
        offset=offset,
    )
    return APIResponse.ok({
        "events": events,
        "count": len(events),
        "limit": limit,
        "offset": offset,
    })


@diag_router.get("/ws-connections", response_model=APIResponse)
async def get_ws_connections(
    request: Request,
    current_user: TokenPayload = Depends(require_permission("diagnostics:read")),
) -> APIResponse:
    """Return current WebSocket connection counts per channel."""
    ws_mgr = request.app.state.ws_manager
    counts = ws_mgr.connection_counts()
    return APIResponse.ok({
        "total": ws_mgr.total_connections(),
        "by_channel": counts,
    })
