"""Staff-only Customer Interaction Dashboard — read models.

Composed from existing per-record stores/adapters; no new persistence.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class QueueTokenView(BaseModel):
    token_id: str
    token_code: str
    priority: str
    position: int
    estimated_wait_min: float
    created_at: float


class QueueDepartmentView(BaseModel):
    department_id: str
    department_name: str
    tokens: list[QueueTokenView] = Field(default_factory=list)


class AppointmentView(BaseModel):
    appointment_id: str
    doctor_name: str
    department_name: str
    start_ts: float | None = None
    status: str


class IntakeAlertView(BaseModel):
    intake_id: str
    full_name: str
    visit_reason: str
    is_red_flag: bool
    submitted_at: float


class EscalationView(BaseModel):
    action: str
    detail: str
    outcome: str
    timestamp: float


class FeedbackItemView(BaseModel):
    rating: int
    comment: str
    submitted_at: float


class FeedbackSummaryView(BaseModel):
    average_rating: float
    count: int
    recent: list[FeedbackItemView] = Field(default_factory=list)


class DashboardOverview(BaseModel):
    queue: list[QueueDepartmentView] = Field(default_factory=list)
    appointments_today: list[AppointmentView] = Field(default_factory=list)
    recent_intake: list[IntakeAlertView] = Field(default_factory=list)
    recent_escalations: list[EscalationView] = Field(default_factory=list)
    feedback: FeedbackSummaryView
