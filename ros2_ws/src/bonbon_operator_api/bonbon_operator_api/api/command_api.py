"""Command API — issue motion and speech commands to BonBon.

Every command is gated by SafetyCommandGate before reaching the ROS2 bridge.
The Safety Supervisor is NEVER bypassed.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status

from bonbon_operator_api.auth.dependencies import get_current_user, require_permission
from bonbon_operator_api.models.auth_models import TokenPayload
from bonbon_operator_api.models.command_models import (
    CancelTaskCommand,
    CommandResponse,
    DockCommand,
    EmergencyStopCommand,
    NavigateCommand,
    PauseCommand,
    ResumeCommand,
    SpeakCommand,
)
from bonbon_operator_api.models.response_models import APIResponse
from bonbon_operator_api.safety.safety_gate import SafetyGateError
from bonbon_operator_api.safety.command_validator import ValidationError

logger = logging.getLogger(__name__)

cmd_router = APIRouter(prefix="/robot/commands", tags=["commands"])


def _gate_and_dispatch(
    request: Request,
    current_user: TokenPayload,
    command_type: str,
    payload,
    command_id: str,
) -> None:
    """Run safety gate; raises HTTP 400/409/503 on rejection."""
    gate = request.app.state.safety_gate
    ip = request.client.host if request.client else ""
    try:
        gate.check_and_validate(
            command_type=command_type,
            payload=payload,
            command_id=command_id,
            actor_id=current_user.sub,
            actor_name=current_user.username,
            actor_role=current_user.role,
            ip_address=ip,
        )
    except ValidationError as exc:
        request.app.state.metrics.record_command(command_type, "validation_error")
        raise HTTPException(status_code=400, detail=str(exc))
    except SafetyGateError as exc:
        code = getattr(exc, "code", "SAFETY_GATE_REJECTED")
        if code == "DUPLICATE_COMMAND":
            request.app.state.metrics.record_command(command_type, "duplicate")
            raise HTTPException(status_code=409, detail=str(exc))
        request.app.state.metrics.record_command(command_type, "safety_blocked")
        raise HTTPException(status_code=503, detail=str(exc))


@cmd_router.post("/emergency_stop", response_model=APIResponse)
async def emergency_stop(
    request: Request,
    body: EmergencyStopCommand,
    current_user: TokenPayload = Depends(
        require_permission("robot:command:emergency_stop")
    ),
) -> APIResponse:
    """Immediately halt the robot — always accepted regardless of safety state."""
    command_id = str(uuid.uuid4())
    metrics = request.app.state.metrics

    with metrics.time_command("emergency_stop"):
        _gate_and_dispatch(request, current_user, "emergency_stop", body, command_id)
        bridge = request.app.state.ros2_bridge
        bridge.call_emergency_stop(body.reason)

    metrics.record_command("emergency_stop", "accepted")
    return APIResponse.ok(CommandResponse(
        accepted=True,
        command_id=command_id,
        message="Emergency stop issued",
        queued_at=time.time(),
    ))


@cmd_router.post("/speak", response_model=APIResponse)
async def speak(
    request: Request,
    body: SpeakCommand,
    current_user: TokenPayload = Depends(require_permission("robot:command:speak")),
) -> APIResponse:
    """Queue a TTS speech command."""
    command_id = str(uuid.uuid4())
    metrics = request.app.state.metrics

    with metrics.time_command("speak"):
        _gate_and_dispatch(request, current_user, "speak", body, command_id)
        bridge = request.app.state.ros2_bridge
        bridge.call_speak(
            text=body.text,
            language=body.language or "en",
            priority=body.priority or "normal",
        )

    metrics.record_command("speak", "accepted")
    return APIResponse.ok(CommandResponse(
        accepted=True,
        command_id=command_id,
        message="Speak command queued",
        queued_at=time.time(),
    ))


@cmd_router.post("/navigate", response_model=APIResponse)
async def navigate(
    request: Request,
    body: NavigateCommand,
    current_user: TokenPayload = Depends(require_permission("robot:command:navigate")),
) -> APIResponse:
    """Send the robot to a navigation goal."""
    command_id = str(uuid.uuid4())
    metrics = request.app.state.metrics

    with metrics.time_command("navigate"):
        _gate_and_dispatch(request, current_user, "navigate", body, command_id)
        bridge = request.app.state.ros2_bridge
        bridge.call_navigate(
            goal_x=body.goal_x,
            goal_y=body.goal_y,
            goal_yaw=body.goal_yaw,
            map_id=body.map_id,
            speed_limit_mps=body.speed_limit_mps,
        )

    metrics.record_command("navigate", "accepted")
    return APIResponse.ok(CommandResponse(
        accepted=True,
        command_id=command_id,
        message=f"Navigate to ({body.goal_x}, {body.goal_y}) accepted",
        queued_at=time.time(),
    ))


@cmd_router.post("/pause", response_model=APIResponse)
async def pause(
    request: Request,
    body: PauseCommand,
    current_user: TokenPayload = Depends(require_permission("robot:command:pause")),
) -> APIResponse:
    """Pause current navigation/task."""
    command_id = str(uuid.uuid4())
    metrics = request.app.state.metrics

    with metrics.time_command("pause"):
        _gate_and_dispatch(request, current_user, "pause", body, command_id)
        bridge = request.app.state.ros2_bridge
        bridge.call_pause()

    metrics.record_command("pause", "accepted")
    return APIResponse.ok(CommandResponse(
        accepted=True,
        command_id=command_id,
        message="Pause command accepted",
        queued_at=time.time(),
    ))


@cmd_router.post("/resume", response_model=APIResponse)
async def resume(
    request: Request,
    body: ResumeCommand,
    current_user: TokenPayload = Depends(require_permission("robot:command:resume")),
) -> APIResponse:
    """Resume paused navigation/task."""
    command_id = str(uuid.uuid4())
    metrics = request.app.state.metrics

    with metrics.time_command("resume"):
        _gate_and_dispatch(request, current_user, "resume", body, command_id)
        bridge = request.app.state.ros2_bridge
        bridge.call_resume()

    metrics.record_command("resume", "accepted")
    return APIResponse.ok(CommandResponse(
        accepted=True,
        command_id=command_id,
        message="Resume command accepted",
        queued_at=time.time(),
    ))


@cmd_router.post("/dock", response_model=APIResponse)
async def dock(
    request: Request,
    body: DockCommand,
    current_user: TokenPayload = Depends(require_permission("robot:command:dock")),
) -> APIResponse:
    """Navigate to a docking station."""
    command_id = str(uuid.uuid4())
    metrics = request.app.state.metrics

    with metrics.time_command("dock"):
        _gate_and_dispatch(request, current_user, "dock", body, command_id)
        bridge = request.app.state.ros2_bridge
        bridge.call_dock(station_id=body.station_id)

    metrics.record_command("dock", "accepted")
    return APIResponse.ok(CommandResponse(
        accepted=True,
        command_id=command_id,
        message="Dock command accepted",
        queued_at=time.time(),
    ))


@cmd_router.post("/cancel_task", response_model=APIResponse)
async def cancel_task(
    request: Request,
    body: CancelTaskCommand,
    current_user: TokenPayload = Depends(require_permission("robot:command:cancel_task")),
) -> APIResponse:
    """Cancel the current or specified task."""
    command_id = str(uuid.uuid4())
    metrics = request.app.state.metrics

    with metrics.time_command("cancel_task"):
        _gate_and_dispatch(request, current_user, "cancel_task", body, command_id)
        bridge = request.app.state.ros2_bridge
        bridge.call_cancel_task(task_id=body.task_id)

    metrics.record_command("cancel_task", "accepted")
    return APIResponse.ok(CommandResponse(
        accepted=True,
        command_id=command_id,
        message="Cancel task accepted",
        queued_at=time.time(),
    ))
