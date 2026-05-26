"""Shared API response envelope models."""

from __future__ import annotations

import time
from typing import Any, Generic, Optional, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class APIResponse(BaseModel):
    """Standard JSON envelope for all REST responses."""
    success: bool
    data: Optional[Any] = None
    error: Optional[str] = None
    timestamp: float = Field(default_factory=time.time)

    @classmethod
    def ok(cls, data: Any = None) -> "APIResponse":
        return cls(success=True, data=data)

    @classmethod
    def fail(cls, error: str) -> "APIResponse":
        return cls(success=False, error=error)


class HealthCheckResponse(BaseModel):
    status: str  # healthy | degraded | unhealthy | offline
    checks: dict = Field(default_factory=dict)
    details: dict = Field(default_factory=dict)
    timestamp: float = Field(default_factory=time.time)


class PaginatedResponse(BaseModel):
    items: list
    total: int
    page: int
    page_size: int
    has_more: bool


class WSMessage(BaseModel):
    """Standard WebSocket message envelope."""
    channel: str
    event: str
    data: Any
    timestamp: float = Field(default_factory=time.time)
