"""Walk-in check-in → queue token models."""

from __future__ import annotations

import time
import uuid

from pydantic import BaseModel, Field


class CheckInRequest(BaseModel):
    session_id: str
    patient_id: str | None = None
    department_id: str
    reason: str = Field(default="", max_length=500)
    priority: str = Field(default="normal")  # normal | urgent (set by red-flag intake)


class QueueToken(BaseModel):
    token_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    token_code: str  # short human-readable code, e.g. "A12"
    session_id: str
    department_id: str
    priority: str = "normal"
    position: int = 0
    estimated_wait_min: float = 0.0
    status: str = "waiting"  # waiting | called | served | cancelled
    created_at: float = Field(default_factory=time.time)


class QueueStatus(BaseModel):
    token: QueueToken
    ahead_count: int
    department_name: str
