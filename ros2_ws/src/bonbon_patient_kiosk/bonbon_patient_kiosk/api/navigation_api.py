"""Wayfinding — "show me directions" vs "please guide me" (physical escort).

Both modes resolve to a `named_location`. "directions" never touches
ROS2 — it is answered client-side from the facility label directory so
the robot doesn't need to move. "escort" calls the exact same
`/navigation/navigate_to` service bonbon_operator_api uses, through this
package's own KioskSafetyGate first.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Request

from bonbon_patient_kiosk.models.chat_models import WayfindingRequest, WayfindingResponse
from bonbon_patient_kiosk.models.response_models import APIResponse
from bonbon_patient_kiosk.safety.kiosk_safety_gate import SafetyGateError
from bonbon_patient_kiosk.safety.command_validator import ValidationError

navigation_router = APIRouter(prefix="/navigation", tags=["navigation"])


@navigation_router.post("/wayfind", response_model=APIResponse)
async def wayfind(request: Request, body: WayfindingRequest) -> APIResponse:
    if request.app.state.session_store.get(body.session_id) is None:
        raise HTTPException(status_code=404, detail="Session not found or has expired")

    audit = request.app.state.audit_logger
    label_store = request.app.state.facility_label_store
    label = next((label for label in label_store.list() if label.name == body.named_location), None)

    if body.mode == "directions":
        summary = (
            f"{label.display_label} is on the map — follow the on-screen route."
            if label
            else "I don't have that location labelled yet — please ask a staff member."
        )
        audit.log(
            actor_id=body.session_id,
            actor_role="patient",
            action="navigation:directions",
            outcome="ok" if label else "unknown_location",
            request_data={"named_location": body.named_location},
        )
        return APIResponse.ok(
            WayfindingResponse(
                mode="directions",
                named_location=body.named_location,
                accepted=label is not None,
                message=summary,
                directions_summary=summary,
            )
        )

    # mode == "escort"
    gate = request.app.state.kiosk_safety_gate
    command_id = str(uuid.uuid4())
    try:
        gate.check_navigation(body.named_location, command_id, body.session_id)
    except (ValidationError, SafetyGateError) as exc:
        audit.log(
            actor_id=body.session_id,
            actor_role="patient",
            action="navigation:escort",
            outcome="rejected",
            detail=str(exc),
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    bridge = request.app.state.ros2_bridge
    result = bridge.call_navigate(body.named_location, requester_id="patient_kiosk")
    accepted = bool(result.get("success"))
    # Never surface the bridge's internal error/message text to a patient
    # (e.g. "bridge not ready", a raw NavigateTo failure code) — the detail
    # goes to the audit log below; the patient always gets a next step.
    message = (
        "Following me — let's go!"
        if accepted
        else "I can't guide you there right now. Please ask a staff member for directions."
    )
    audit.log(
        actor_id=body.session_id,
        actor_role="patient",
        action="navigation:escort",
        outcome="accepted" if accepted else "failed",
        request_data={"named_location": body.named_location},
        detail="" if accepted else str(result.get("error") or result.get("message") or ""),
    )
    return APIResponse.ok(
        WayfindingResponse(
            mode="escort", named_location=body.named_location, accepted=accepted, message=message
        )
    )
