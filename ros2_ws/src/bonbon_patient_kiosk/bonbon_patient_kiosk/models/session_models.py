"""Patient kiosk session models.

A session is an opaque, anonymous, short-lived handle — not a user account.
It is how a single patient's in-progress intake/appointment/queue data is
scoped and how it gets wiped (idle timeout, explicit end, privacy-mode
failure) before the next patient approaches the kiosk.
"""

from __future__ import annotations

import time
import uuid

from pydantic import BaseModel, Field


class SessionCreate(BaseModel):
    language: str = Field(default="en", max_length=10)
    kiosk_id: str = Field(default="kiosk-1", max_length=64)


class SessionInfo(BaseModel):
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    language: str = "en"
    kiosk_id: str = "kiosk-1"
    created_at: float = Field(default_factory=time.time)
    last_activity_at: float = Field(default_factory=time.time)
    consent_given: bool = False
    privacy_mode_active: bool = False


class ConsentRecord(BaseModel):
    session_id: str
    consent_given: bool
    jurisdiction: str = Field(default="default", max_length=32)
    policy_version: str = Field(default="1.0", max_length=16)
    recorded_at: float = Field(default_factory=time.time)
