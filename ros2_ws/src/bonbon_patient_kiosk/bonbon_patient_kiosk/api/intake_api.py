"""Patient history intake — draft save (in-memory only) + confirmed submit.

Red-flag detection: free-text visit_reason/symptoms are checked against a
small set of emergency-symptom patterns. This NEVER produces a diagnosis —
it only forces priority="urgent" on check-in and immediately raises an
operator alert, exactly like bonbon_behavior_engine's spatial `collision_risk`
alert path. The patient is always told a staff member has been notified,
never given a medical assessment.
"""

from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, Request

from bonbon_patient_kiosk.models.patient_models import IntakeForm
from bonbon_patient_kiosk.models.response_models import APIResponse

intake_router = APIRouter(prefix="/intake", tags=["intake"])

_RED_FLAG_PATTERNS = re.compile(
    r"\b(chest\s*pain|can'?t\s*breathe|difficulty\s*breathing|severe\s*bleeding|"
    r"unconscious|stroke|numb(ness)?\s*(on\s*)?one\s*side|"
    r"severe\s*allergic|anaphylax|suicidal|overdose)\b",
    re.IGNORECASE,
)


def _is_red_flag(form: IntakeForm) -> bool:
    text = " ".join([form.visit_reason, *form.symptoms])
    return bool(_RED_FLAG_PATTERNS.search(text))


@intake_router.put("/{session_id}/draft", response_model=APIResponse)
async def save_draft(request: Request, session_id: str, body: IntakeForm) -> APIResponse:
    if request.app.state.session_store.get(session_id) is None:
        raise HTTPException(status_code=404, detail="Session not found or has expired")
    if body.session_id != session_id:
        raise HTTPException(status_code=400, detail="session_id mismatch")
    body.is_red_flag = _is_red_flag(body)
    request.app.state.session_store.save_draft(body)
    request.app.state.audit_logger.log(
        actor_id=session_id,
        actor_role="patient",
        action="intake:draft_saved",
        outcome="success",
        request_data={"fields": list(type(body).model_fields.keys()), "is_red_flag": body.is_red_flag},
    )
    return APIResponse.ok({"saved": True, "is_red_flag": body.is_red_flag})


@intake_router.get("/{session_id}/draft", response_model=APIResponse)
async def get_draft(request: Request, session_id: str) -> APIResponse:
    draft = request.app.state.session_store.get_draft(session_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="No draft found for this session")
    return APIResponse.ok(draft)


@intake_router.post("/{session_id}/submit", response_model=APIResponse, status_code=201)
async def submit_intake(request: Request, session_id: str) -> APIResponse:
    """Confirm-and-submit — the only point where intake data leaves memory
    and is written (encrypted) to the patient data store."""
    session = request.app.state.session_store.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found or has expired")
    if not session.consent_given:
        raise HTTPException(status_code=403, detail="Consent must be recorded before submitting intake")
    draft = request.app.state.session_store.get_draft(session_id)
    if draft is None:
        raise HTTPException(status_code=400, detail="No intake draft to submit")

    from bonbon_patient_kiosk.models.patient_models import IntakeRecord

    record = IntakeRecord(form=draft, consent_on_file=True)
    request.app.state.patient_store.save_intake(
        record.intake_id, session_id, record.model_dump()
    )
    request.app.state.audit_logger.log(
        actor_id=session_id,
        actor_role="patient",
        action="intake:submitted",
        target=record.intake_id,
        outcome="success",
        request_data={"is_red_flag": draft.is_red_flag},
    )

    if draft.is_red_flag:
        bridge = request.app.state.ros2_bridge
        bridge.publish_speak(
            "I've alerted a staff member — someone will be with you right away.",
            priority="high",
        )
        request.app.state.audit_logger.log(
            actor_id=session_id,
            actor_role="patient",
            action="intake:emergency_escalation",
            target=record.intake_id,
            outcome="escalated",
        )

    return APIResponse.ok({"intake_id": record.intake_id, "is_red_flag": draft.is_red_flag})
