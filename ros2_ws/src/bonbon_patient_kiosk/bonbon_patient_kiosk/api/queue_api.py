"""Walk-in check-in → queue token issuance + live status.

Token codes use a department-letter + running-number scheme (e.g. "C4" for
the 4th Cardiology check-in of the day) so they read naturally on a kiosk
receipt/screen without needing a lookup.
"""

from __future__ import annotations

import threading

from fastapi import APIRouter, Depends, HTTPException, Request

from bonbon_patient_kiosk.auth.dependencies import require_permission
from bonbon_patient_kiosk.models.auth_models import TokenPayload
from bonbon_patient_kiosk.models.queue_models import CheckInRequest, QueueStatus, QueueToken
from bonbon_patient_kiosk.models.response_models import APIResponse

queue_router = APIRouter(prefix="/queue", tags=["queue"])

_AVG_CONSULT_MIN = 12.0
_counter_lock = threading.Lock()
_dept_counters: dict[str, int] = {}


def _next_token_code(department_id: str) -> str:
    with _counter_lock:
        n = _dept_counters.get(department_id, 0) + 1
        _dept_counters[department_id] = n
    letter = (department_id[-1] or "X").upper()
    return f"{letter}{n}"


@queue_router.post("/check-in", response_model=APIResponse, status_code=201)
async def check_in(request: Request, body: CheckInRequest) -> APIResponse:
    if request.app.state.session_store.get(body.session_id) is None:
        raise HTTPException(status_code=404, detail="Session not found or has expired")
    scheduler = request.app.state.scheduling_adapter
    department = scheduler.get_department(body.department_id)
    if department is None:
        raise HTTPException(status_code=404, detail="Unknown department")

    store = request.app.state.patient_store
    existing = store.list_waiting_tokens(body.department_id)
    position = len(existing) + 1
    token = QueueToken(
        token_code=_next_token_code(body.department_id),
        session_id=body.session_id,
        department_id=body.department_id,
        priority=body.priority,
        position=position,
        estimated_wait_min=position * _AVG_CONSULT_MIN,
    )
    if body.priority == "urgent":
        token.position = 0
        token.estimated_wait_min = 0.0
    store.save_token(token.token_id, token.model_dump())

    notifier = request.app.state.notifier_adapter
    notifier.print_token(token.token_code, department.name, token.estimated_wait_min)

    request.app.state.audit_logger.log(
        actor_id=body.session_id,
        actor_role="patient",
        action="queue:check_in",
        target=token.token_id,
        outcome="success",
        request_data={"department_id": body.department_id, "priority": body.priority},
    )
    return APIResponse.ok(QueueStatus(token=token, ahead_count=len(existing), department_name=department.name))


@queue_router.get("/tokens/{token_id}", response_model=APIResponse)
async def get_token_status(request: Request, token_id: str) -> APIResponse:
    store = request.app.state.patient_store
    scheduler = request.app.state.scheduling_adapter
    data = store.get_token(token_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Token not found")
    token = QueueToken(**data)
    department = scheduler.get_department(token.department_id)
    ahead = [
        t for t in store.list_waiting_tokens(token.department_id) if t["created_at"] < data["created_at"]
    ]
    return APIResponse.ok(
        QueueStatus(
            token=token,
            ahead_count=len(ahead),
            department_name=department.name if department else token.department_id,
        )
    )


@queue_router.post("/tokens/{token_id}/serve", response_model=APIResponse)
async def mark_served(
    request: Request,
    token_id: str,
    current_user: TokenPayload = Depends(require_permission("queue:manage")),
) -> APIResponse:
    """Staff-facing: mark a token as served."""
    store = request.app.state.patient_store
    data = store.get_token(token_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Token not found")
    data["status"] = "served"
    store.update_token(token_id, data)
    request.app.state.audit_logger.log(
        actor_id=current_user.sub,
        actor_role=current_user.role,
        action="queue:mark_served",
        target=token_id,
        outcome="success",
    )
    return APIResponse.ok(data)
