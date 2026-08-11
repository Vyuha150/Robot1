"""End-of-visit CSAT feedback."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from bonbon_patient_kiosk.models.feedback_models import FeedbackRecord, FeedbackSubmission
from bonbon_patient_kiosk.models.response_models import APIResponse

feedback_router = APIRouter(prefix="/feedback", tags=["feedback"])


@feedback_router.post("", response_model=APIResponse, status_code=201)
async def submit_feedback(request: Request, body: FeedbackSubmission) -> APIResponse:
    if request.app.state.session_store.get(body.session_id) is None:
        raise HTTPException(status_code=404, detail="Session not found or has expired")
    record = FeedbackRecord(session_id=body.session_id, rating=body.rating, comment=body.comment)
    feedback_id = request.app.state.patient_store.save_feedback(record.model_dump())
    request.app.state.audit_logger.log(
        actor_id=body.session_id,
        actor_role="patient",
        action="feedback:submit",
        target=feedback_id,
        outcome="success",
        request_data={"rating": body.rating},
    )
    return APIResponse.ok({"feedback_id": feedback_id})
