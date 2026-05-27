"""Robot status API — read-only robot state endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request

from bonbon_operator_api.auth.dependencies import require_permission
from bonbon_operator_api.models.auth_models import TokenPayload
from bonbon_operator_api.models.response_models import APIResponse

logger = logging.getLogger(__name__)

status_router = APIRouter(prefix="/robot", tags=["robot-status"])


@status_router.get("/status", response_model=APIResponse)
async def get_robot_status(
    request: Request,
    current_user: TokenPayload = Depends(require_permission("robot:read")),
) -> APIResponse:
    """Return the current full robot status snapshot."""
    aggregator = request.app.state.status_aggregator
    status = aggregator.get_status()
    return APIResponse.ok(status.model_dump())


@status_router.get("/status/safety", response_model=APIResponse)
async def get_safety_state(
    request: Request,
    current_user: TokenPayload = Depends(require_permission("robot:read")),
) -> APIResponse:
    """Return safety subsystem state only."""
    aggregator = request.app.state.status_aggregator
    status = aggregator.get_status()
    return APIResponse.ok(
        {
            "state": status.safety.state,
            "active_faults": status.safety.active_faults,
            "watchdog_ok": status.safety.watchdog_ok,
            "last_event_ts": status.safety.last_event_ts,
            "overall_health": status.overall_health(),
        }
    )


@status_router.get("/status/battery", response_model=APIResponse)
async def get_battery_status(
    request: Request,
    current_user: TokenPayload = Depends(require_permission("robot:read")),
) -> APIResponse:
    """Return battery state."""
    aggregator = request.app.state.status_aggregator
    status = aggregator.get_status()
    return APIResponse.ok(status.battery.model_dump())


@status_router.get("/status/navigation", response_model=APIResponse)
async def get_navigation_status(
    request: Request,
    current_user: TokenPayload = Depends(require_permission("robot:read")),
) -> APIResponse:
    """Return navigation state."""
    aggregator = request.app.state.status_aggregator
    status = aggregator.get_status()
    return APIResponse.ok(status.navigation.model_dump())


@status_router.get("/status/health", response_model=APIResponse)
async def get_health_summary(
    request: Request,
    current_user: TokenPayload = Depends(require_permission("robot:read")),
) -> APIResponse:
    """Return a concise health summary."""
    aggregator = request.app.state.status_aggregator
    status = aggregator.get_status()
    return APIResponse.ok(
        {
            "is_online": status.is_online,
            "overall_health": status.overall_health(),
            "safety_state": status.safety.state,
            "battery_pct": status.battery.percentage,
            "navigation_state": status.navigation.state,
            "active_task": status.active_task,
            "last_updated": status.last_updated,
            "modules": {
                name: {"state": m.state, "health": m.health} for name, m in status.modules.items()
            },
        }
    )
