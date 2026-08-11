"""Patient identity + intake (history) models.

These carry PHI. They are never embedded into bonbon_llm's RAG vector
store and never logged verbatim by the audit layer (see audit/audit_logger.py
— audit entries record *that* a field was accessed, not its value).
"""

from __future__ import annotations

import time
import uuid

from pydantic import BaseModel, Field


class PatientLookupRequest(BaseModel):
    """Returning-patient lookup key. Real deployments resolve this through
    EMRAdapter against the hospital's actual identifier scheme."""

    identifier: str = Field(min_length=1, max_length=128)
    identifier_type: str = Field(default="phone", max_length=32)  # phone | mrn | qr


class PatientSummary(BaseModel):
    patient_id: str
    display_name: str
    date_of_birth: str | None = None
    last_visit_at: float | None = None


class IntakeForm(BaseModel):
    """Structured patient-history intake. Never auto-submitted — the UI
    always shows a confirmation step before this reaches the store."""

    session_id: str
    full_name: str = Field(min_length=1, max_length=200)
    date_of_birth: str = Field(max_length=10)  # YYYY-MM-DD
    contact_phone: str = Field(max_length=32)
    contact_email: str | None = Field(default=None, max_length=200)
    visit_reason: str = Field(min_length=1, max_length=1000)
    symptoms: list[str] = Field(default_factory=list)
    allergies: list[str] = Field(default_factory=list)
    current_medications: list[str] = Field(default_factory=list)
    preferred_language: str = Field(default="en", max_length=10)
    emergency_contact_name: str | None = Field(default=None, max_length=200)
    emergency_contact_phone: str | None = Field(default=None, max_length=32)
    insurance_provider: str | None = Field(default=None, max_length=200)
    insurance_id: str | None = Field(default=None, max_length=100)
    is_red_flag: bool = Field(
        default=False,
        description="Set true by intake_api when free-text matches emergency-symptom "
        "patterns; forces immediate staff escalation instead of normal queueing.",
    )


class IntakeRecord(BaseModel):
    intake_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    patient_id: str | None = None
    form: IntakeForm
    submitted_at: float = Field(default_factory=time.time)
    consent_on_file: bool = False
