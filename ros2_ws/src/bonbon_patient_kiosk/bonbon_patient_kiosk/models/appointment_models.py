"""Department/doctor directory, appointment slots, walk-in tokens."""

from __future__ import annotations

import time
import uuid

from pydantic import BaseModel, Field


class Department(BaseModel):
    department_id: str
    name: str
    floor: str
    named_location: str  # bonbon_navigation named_locations key, e.g. "cardiology_dept"
    description: str = ""


class Doctor(BaseModel):
    doctor_id: str
    display_name: str
    department_id: str
    named_location: str  # e.g. "dr_tan_room_204"
    languages: list[str] = Field(default_factory=lambda: ["en"])


class AvailabilitySlot(BaseModel):
    slot_id: str
    doctor_id: str
    start_ts: float
    end_ts: float
    is_available: bool = True


class AppointmentRequest(BaseModel):
    session_id: str
    patient_id: str | None = None
    doctor_id: str
    slot_id: str
    reason: str = Field(default="", max_length=500)


class Appointment(BaseModel):
    appointment_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str
    patient_id: str | None = None
    doctor_id: str
    slot_id: str
    reason: str = ""
    status: str = "confirmed"  # confirmed | rescheduled | cancelled
    created_at: float = Field(default_factory=time.time)


class RescheduleRequest(BaseModel):
    appointment_id: str
    new_slot_id: str


class CancelRequest(BaseModel):
    appointment_id: str
    reason: str = Field(default="", max_length=300)
