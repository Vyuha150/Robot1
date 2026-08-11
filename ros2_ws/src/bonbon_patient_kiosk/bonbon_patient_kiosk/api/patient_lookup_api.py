"""Returning-patient lookup — delegates to EMRAdapter (mock by default)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from bonbon_patient_kiosk.models.patient_models import PatientLookupRequest
from bonbon_patient_kiosk.models.response_models import APIResponse

patient_lookup_router = APIRouter(prefix="/patients", tags=["patients"])


@patient_lookup_router.post("/lookup", response_model=APIResponse)
async def lookup_patient(request: Request, body: PatientLookupRequest) -> APIResponse:
    emr = request.app.state.emr_adapter
    summary = emr.lookup(body)
    audit = request.app.state.audit_logger
    audit.log(
        actor_id="kiosk",
        actor_role="patient",
        action="patient:lookup",
        outcome="found" if summary else "not_found",
        request_data={"identifier_type": body.identifier_type},
    )
    if summary is None:
        raise HTTPException(status_code=404, detail="No matching patient record found")
    return APIResponse.ok(summary)
