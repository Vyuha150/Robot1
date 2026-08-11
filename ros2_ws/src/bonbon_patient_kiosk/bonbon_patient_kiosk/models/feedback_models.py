"""End-of-visit CSAT feedback."""

from __future__ import annotations

import time
import uuid

from pydantic import BaseModel, Field


class FeedbackSubmission(BaseModel):
    session_id: str
    rating: int = Field(ge=1, le=5)
    comment: str = Field(default="", max_length=1000)


class FeedbackRecord(BaseModel):
    feedback_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str
    rating: int
    comment: str = ""
    submitted_at: float = Field(default_factory=time.time)
