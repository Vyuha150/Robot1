"""Conversational Q&A + navigation request models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ChatQueryRequest(BaseModel):
    session_id: str
    query_text: str = Field(min_length=1, max_length=1000)


class ChatQueryResponse(BaseModel):
    response_text: str
    status: str  # ok | low_conf | safety_block | hallucination | error | escalated
    confidence: float = 0.0
    suggested_department_id: str | None = None
    is_emergency_escalation: bool = False


class WayfindingRequest(BaseModel):
    session_id: str
    named_location: str = Field(max_length=128)
    mode: str = Field(default="directions")  # "directions" | "escort"


class WayfindingResponse(BaseModel):
    mode: str
    named_location: str
    accepted: bool
    message: str
    directions_summary: str | None = None
