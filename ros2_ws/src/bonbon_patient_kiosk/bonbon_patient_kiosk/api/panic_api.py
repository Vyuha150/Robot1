"""Always-visible panic/"call staff" button.

Publishes a high-priority TTS acknowledgement and relies on
bonbon_behavior_engine's own OperatorAlerter (fed by upstream perception/
spatial signals) for the actual staff-facing alert channel in a full
deployment; this endpoint's job is only to give the patient immediate
on-screen/spoken confirmation and to leave an audit trail staff can review.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Request

from bonbon_patient_kiosk.models.response_models import APIResponse

panic_router = APIRouter(prefix="/panic", tags=["panic"])


@panic_router.post("", response_model=APIResponse)
async def trigger_panic(request: Request, session_id: str, reason: str = "patient_requested") -> APIResponse:
    if request.app.state.session_store.get(session_id) is None:
        raise HTTPException(status_code=404, detail="Session not found or has expired")

    gate = request.app.state.kiosk_safety_gate
    command_id = str(uuid.uuid4())
    gate.check_panic(reason, command_id, session_id)

    bridge = request.app.state.ros2_bridge
    bridge.publish_speak("Staff have been notified. Please wait — help is on the way.", priority="high")

    return APIResponse.ok({"acknowledged": True, "command_id": command_id})
