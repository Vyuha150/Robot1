"""Session lifecycle — create, heartbeat, privacy mode, end.

Starting a session activates SetPrivacyMode(level="face_only") on the robot
if the ROS2 bridge is live, so face-identification is suppressed for the
whole kiosk interaction, not just during intake — a kiosk conversation is
PHI-adjacent from the first tap.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request

from bonbon_patient_kiosk.models.response_models import APIResponse
from bonbon_patient_kiosk.models.session_models import SessionCreate, SessionInfo

logger = logging.getLogger(__name__)

session_router = APIRouter(prefix="/session", tags=["session"])


@session_router.post("", response_model=APIResponse, status_code=201)
async def create_session(request: Request, body: SessionCreate) -> APIResponse:
    store = request.app.state.session_store
    session = store.create(SessionInfo(language=body.language, kiosk_id=body.kiosk_id))

    bridge = request.app.state.ros2_bridge
    privacy_result = bridge.call_set_privacy_mode(True, "face_only", operator_id="kiosk")
    store.set_privacy_mode(session.session_id, bool(privacy_result.get("success")))

    request.app.state.audit_logger.log(
        actor_id=session.session_id,
        actor_role="patient",
        action="session:create",
        outcome="success",
        request_data={"privacy_mode_engaged": bool(privacy_result.get("success"))},
    )
    return APIResponse.ok(store.get(session.session_id))


@session_router.post("/{session_id}/heartbeat", response_model=APIResponse)
async def heartbeat(request: Request, session_id: str) -> APIResponse:
    session = request.app.state.session_store.touch(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found or has expired")
    return APIResponse.ok(session)


@session_router.get("/{session_id}", response_model=APIResponse)
async def get_session(request: Request, session_id: str) -> APIResponse:
    session = request.app.state.session_store.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found or has expired")
    return APIResponse.ok(session)


@session_router.post("/{session_id}/end", response_model=APIResponse)
async def end_session(request: Request, session_id: str) -> APIResponse:
    """Wipe all in-memory state for this session — PHI safety control used
    by 'start over', explicit logout, and the idle-timeout UI countdown."""
    bridge = request.app.state.ros2_bridge
    bridge.call_set_privacy_mode(False, "none", operator_id="kiosk")
    request.app.state.session_store.end(session_id)
    request.app.state.audit_logger.log(
        actor_id=session_id, actor_role="patient", action="session:end", outcome="success"
    )
    return APIResponse.ok({"ended": True, "session_id": session_id})
