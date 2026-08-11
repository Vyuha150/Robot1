"""Data-use consent capture — required before any PHI collection begins."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from bonbon_patient_kiosk.models.response_models import APIResponse
from bonbon_patient_kiosk.models.session_models import ConsentRecord

consent_router = APIRouter(prefix="/consent", tags=["consent"])

_DISCLOSURE_TEXT = (
    "BonBon will collect the information you enter (name, contact details, "
    "visit reason, and any symptoms/allergies/medications you share) to "
    "check you in, book or manage your appointment, and help you find your "
    "way. It is stored securely and only shared with hospital staff. You "
    "can ask a staff member to review or delete it at any time."
)


@consent_router.get("/disclosure", response_model=APIResponse)
async def get_disclosure(jurisdiction: str = "default") -> APIResponse:
    return APIResponse.ok({"jurisdiction": jurisdiction, "text": _DISCLOSURE_TEXT, "policy_version": "1.0"})


@consent_router.post("", response_model=APIResponse)
async def record_consent(request: Request, body: ConsentRecord) -> APIResponse:
    session = request.app.state.session_store.set_consent(body.session_id, body.consent_given)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found or has expired")
    request.app.state.audit_logger.log(
        actor_id=body.session_id,
        actor_role="patient",
        action="consent:record",
        outcome="success" if body.consent_given else "declined",
        request_data={"jurisdiction": body.jurisdiction, "policy_version": body.policy_version},
    )
    return APIResponse.ok(session)
