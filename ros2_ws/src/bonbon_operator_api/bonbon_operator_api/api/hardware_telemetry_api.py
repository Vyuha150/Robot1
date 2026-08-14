"""Hardware telemetry dashboard endpoint. Relays the real, live state
hardware_telemetry_node published from whichever Pi it runs on via
websocket/hardware_telemetry_snapshots.py -- so the WebSocket push and
REST pull paths can never disagree, same principle used throughout this
dashboard (see api/edge_ai_status_api.py for the identical pattern).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request

from bonbon_operator_api.auth.dependencies import require_permission
from bonbon_operator_api.models.auth_models import TokenPayload
from bonbon_operator_api.models.response_models import APIResponse
from bonbon_operator_api.websocket.hardware_telemetry_snapshots import hardware_telemetry_snapshot

logger = logging.getLogger(__name__)

hardware_telemetry_router = APIRouter(tags=["hardware-telemetry"])


@hardware_telemetry_router.get("/hardware-telemetry/status", response_model=APIResponse)
async def get_hardware_telemetry_status(
    request: Request, current_user: TokenPayload = Depends(require_permission("diagnostics:read"))
) -> APIResponse:
    snapshot = hardware_telemetry_snapshot(request.app)
    if not snapshot.get("available"):
        return APIResponse.error(snapshot.get("message", "unavailable"))
    return APIResponse.ok(snapshot)
