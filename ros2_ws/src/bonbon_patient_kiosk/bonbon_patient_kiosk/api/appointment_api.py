"""Department/doctor directory + appointment booking, reschedule, cancel.

Delegates directory/slot data to SchedulingAdapter (mock by default) and
persists confirmed appointments to PatientDataStore.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from bonbon_patient_kiosk.models.appointment_models import (
    Appointment,
    AppointmentRequest,
    CancelRequest,
    RescheduleRequest,
)
from bonbon_patient_kiosk.models.response_models import APIResponse

appointment_router = APIRouter(prefix="/appointments", tags=["appointments"])


@appointment_router.get("/departments", response_model=APIResponse)
async def list_departments(request: Request) -> APIResponse:
    return APIResponse.ok(request.app.state.scheduling_adapter.list_departments())


@appointment_router.get("/doctors", response_model=APIResponse)
async def list_doctors(request: Request, department_id: str | None = None) -> APIResponse:
    return APIResponse.ok(request.app.state.scheduling_adapter.list_doctors(department_id))


@appointment_router.get("/doctors/{doctor_id}/slots", response_model=APIResponse)
async def list_slots(request: Request, doctor_id: str) -> APIResponse:
    return APIResponse.ok(request.app.state.scheduling_adapter.list_available_slots(doctor_id))


@appointment_router.post("", response_model=APIResponse, status_code=201)
async def book_appointment(request: Request, body: AppointmentRequest) -> APIResponse:
    if request.app.state.session_store.get(body.session_id) is None:
        raise HTTPException(status_code=404, detail="Session not found or has expired")
    scheduler = request.app.state.scheduling_adapter
    slot = scheduler.reserve_slot(body.slot_id)
    if slot is None:
        raise HTTPException(status_code=409, detail="Slot is no longer available")

    appointment = Appointment(
        session_id=body.session_id,
        patient_id=body.patient_id,
        doctor_id=body.doctor_id,
        slot_id=body.slot_id,
        reason=body.reason,
    )
    request.app.state.patient_store.save_appointment(
        appointment.appointment_id, appointment.model_dump()
    )
    request.app.state.audit_logger.log(
        actor_id=body.session_id,
        actor_role="patient",
        action="appointment:book",
        target=appointment.appointment_id,
        outcome="success",
    )
    return APIResponse.ok(appointment)


@appointment_router.post("/reschedule", response_model=APIResponse)
async def reschedule_appointment(request: Request, body: RescheduleRequest) -> APIResponse:
    store = request.app.state.patient_store
    scheduler = request.app.state.scheduling_adapter
    existing = store.get_appointment(body.appointment_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Appointment not found")
    new_slot = scheduler.reserve_slot(body.new_slot_id)
    if new_slot is None:
        raise HTTPException(status_code=409, detail="New slot is no longer available")
    scheduler.release_slot(existing["slot_id"])
    existing["slot_id"] = body.new_slot_id
    existing["status"] = "rescheduled"
    store.update_appointment(body.appointment_id, existing)
    request.app.state.audit_logger.log(
        actor_id=existing.get("session_id", "unknown"),
        actor_role="patient",
        action="appointment:reschedule",
        target=body.appointment_id,
        outcome="success",
    )
    return APIResponse.ok(existing)


@appointment_router.post("/cancel", response_model=APIResponse)
async def cancel_appointment(request: Request, body: CancelRequest) -> APIResponse:
    store = request.app.state.patient_store
    scheduler = request.app.state.scheduling_adapter
    existing = store.get_appointment(body.appointment_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Appointment not found")
    scheduler.release_slot(existing["slot_id"])
    existing["status"] = "cancelled"
    store.update_appointment(body.appointment_id, existing)
    request.app.state.audit_logger.log(
        actor_id=existing.get("session_id", "unknown"),
        actor_role="patient",
        action="appointment:cancel",
        target=body.appointment_id,
        outcome="success",
        detail=body.reason,
    )
    return APIResponse.ok(existing)
