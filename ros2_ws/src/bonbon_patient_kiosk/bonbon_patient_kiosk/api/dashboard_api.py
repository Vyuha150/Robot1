"""Customer Interaction Dashboard — staff-only read aggregate.

Composes existing stores/adapters into one snapshot so reception staff
can see the live queue, today's appointments, recent intake (with
red-flag alerts), recent panic/emergency escalations, and feedback —
without needing to already know a specific token/appointment id. No new
persistence; this router only reads.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Request

from bonbon_patient_kiosk.auth.dependencies import require_permission
from bonbon_patient_kiosk.models.auth_models import TokenPayload
from bonbon_patient_kiosk.models.dashboard_models import (
    AppointmentView,
    DashboardOverview,
    EscalationView,
    FeedbackItemView,
    FeedbackSummaryView,
    IntakeAlertView,
    QueueDepartmentView,
    QueueTokenView,
)
from bonbon_patient_kiosk.models.response_models import APIResponse

dashboard_router = APIRouter(prefix="/staff/dashboard", tags=["staff-dashboard"])

_ESCALATION_ACTIONS = ("intake:emergency_escalation", "chat:emergency_escalation", "command:panic")
_ESCALATION_FALLBACK_MESSAGE = {
    "intake:emergency_escalation": "Emergency symptom language detected during intake.",
    "chat:emergency_escalation": "Emergency symptom language detected in chat.",
    "command:panic": "Panic button pressed.",
}


def _escalation_message(row: dict) -> str:
    if row.get("detail"):
        return row["detail"]
    try:
        request_data = json.loads(row.get("request_data") or "{}")
    except (TypeError, ValueError):
        request_data = {}
    if request_data.get("reason"):
        return str(request_data["reason"])
    return _ESCALATION_FALLBACK_MESSAGE.get(row["action"], row["action"])


def _build_queue_view(request: Request) -> list[QueueDepartmentView]:
    store = request.app.state.patient_store
    scheduler = request.app.state.scheduling_adapter
    tokens = store.list_all_waiting_tokens()

    by_department: dict[str, list[QueueTokenView]] = {}
    for t in tokens:
        by_department.setdefault(t["department_id"], []).append(
            QueueTokenView(
                token_id=t["token_id"],
                token_code=t["token_code"],
                priority=t["priority"],
                position=t["position"],
                estimated_wait_min=t["estimated_wait_min"],
                created_at=t["created_at"],
            )
        )

    views = []
    for department_id, department_tokens in by_department.items():
        department = scheduler.get_department(department_id)
        views.append(
            QueueDepartmentView(
                department_id=department_id,
                department_name=department.name if department else department_id,
                tokens=department_tokens,
            )
        )
    return views


def _build_appointments_view(request: Request) -> list[AppointmentView]:
    store = request.app.state.patient_store
    scheduler = request.app.state.scheduling_adapter
    views = []
    for appt in store.list_appointments():
        doctor = scheduler.get_doctor(appt["doctor_id"])
        department = scheduler.get_department(doctor.department_id) if doctor else None
        slot = scheduler.get_slot(appt["slot_id"])
        views.append(
            AppointmentView(
                appointment_id=appt["appointment_id"],
                doctor_name=doctor.display_name if doctor else appt["doctor_id"],
                department_name=department.name if department else "",
                start_ts=slot.start_ts if slot else None,
                status=appt["status"],
            )
        )
    return views


def _build_intake_view(request: Request, limit: int = 20) -> list[IntakeAlertView]:
    # PatientDataStore has no list-all for intake yet -- the audit log
    # already records every "intake:submitted" event with the intake_id as
    # target, so use that as the index and fetch each record by id. Bounded
    # by `limit` since this is a "recent" view, not a full export.
    audit = request.app.state.audit_logger
    store = request.app.state.patient_store
    events = audit.query(action="intake:submitted", limit=limit)
    views = []
    for event in events:
        try:
            record = store.get_intake(event["target"])
        except Exception:
            # A record encrypted under a since-rotated/lost key (or any other
            # single-row corruption) must not take down the whole dashboard
            # for every other patient's data -- skip it, don't crash.
            continue
        if record is None:
            continue
        form = record.get("form", {})
        views.append(
            IntakeAlertView(
                intake_id=record["intake_id"],
                full_name=form.get("full_name", ""),
                visit_reason=form.get("visit_reason", ""),
                is_red_flag=form.get("is_red_flag", False),
                submitted_at=record.get("submitted_at", event["timestamp"]),
            )
        )
    return views


def _build_escalations_view(request: Request, limit: int = 20) -> list[EscalationView]:
    audit = request.app.state.audit_logger
    rows = []
    for action in _ESCALATION_ACTIONS:
        rows.extend(audit.query(action=action, limit=limit))
    rows.sort(key=lambda r: r["timestamp"], reverse=True)
    return [
        EscalationView(
            action=r["action"],
            detail=_escalation_message(r),
            outcome=r["outcome"],
            timestamp=r["timestamp"],
        )
        for r in rows[:limit]
    ]


def _build_feedback_view(request: Request) -> FeedbackSummaryView:
    store = request.app.state.patient_store
    summary = store.feedback_summary()
    recent = [
        FeedbackItemView(rating=f["rating"], comment=f.get("comment", ""), submitted_at=f["submitted_at"])
        for f in store.list_recent_feedback(limit=10)
    ]
    return FeedbackSummaryView(**summary, recent=recent)


@dashboard_router.get("/overview", response_model=APIResponse)
async def get_overview(
    request: Request,
    current_user: TokenPayload = Depends(require_permission("dashboard:read")),
) -> APIResponse:
    overview = DashboardOverview(
        queue=_build_queue_view(request),
        appointments_today=_build_appointments_view(request),
        recent_intake=_build_intake_view(request),
        recent_escalations=_build_escalations_view(request),
        feedback=_build_feedback_view(request),
    )
    return APIResponse.ok(overview)
