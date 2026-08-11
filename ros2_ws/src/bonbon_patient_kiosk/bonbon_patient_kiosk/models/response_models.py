"""Shared API response envelope — identical shape to bonbon_operator_api's,
so both dashboards' frontends can reuse the same fetch-wrapper pattern."""

from __future__ import annotations

import time
from typing import Any

from pydantic import BaseModel, Field


class APIResponse(BaseModel):
    success: bool
    data: Any | None = None
    error: str | None = None
    timestamp: float = Field(default_factory=time.time)

    @classmethod
    def ok(cls, data: Any = None) -> "APIResponse":
        return cls(success=True, data=data)

    @classmethod
    def fail(cls, error: str) -> "APIResponse":
        return cls(success=False, error=error)
