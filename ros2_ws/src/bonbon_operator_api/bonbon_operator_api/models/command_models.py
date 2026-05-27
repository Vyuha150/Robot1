"""Command request and response pydantic models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class SpeakCommand(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    language: str = Field(default="en", pattern=r"^[a-z]{2}(-[A-Z]{2})?$")
    priority: str = Field(
        default="normal",
        pattern=r"^(emergency|high|normal|low|background)$",
    )
    emotion: str = Field(default="neutral")


class NavigateCommand(BaseModel):
    goal_x: float = Field(ge=-1000.0, le=1000.0)
    goal_y: float = Field(ge=-1000.0, le=1000.0)
    goal_yaw: float = Field(default=0.0, ge=-3.15, le=3.15)
    map_id: str | None = None
    speed_limit_mps: float | None = Field(default=None, ge=0.05, le=1.5)
    allow_replanning: bool = True


class PauseCommand(BaseModel):
    reason: str = Field(default="operator_pause", max_length=200)


class ResumeCommand(BaseModel):
    pass


class DockCommand(BaseModel):
    station_id: str | None = None


class EmergencyStopCommand(BaseModel):
    reason: str = Field(default="operator_triggered", max_length=200)


class CancelTaskCommand(BaseModel):
    task_id: str | None = None
    reason: str = Field(default="", max_length=200)


class RestartModuleCommand(BaseModel):
    module_name: str = Field(min_length=1, max_length=64)
    reason: str = Field(default="", max_length=200)


class ConfigUpdateRequest(BaseModel):
    key: str = Field(min_length=1, max_length=128)
    value: object
    reason: str = Field(default="", max_length=200)


class RAGQueryRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    collections: list | None = None
    n_results: int = Field(default=5, ge=1, le=20)
    min_score: float = Field(default=0.0, ge=0.0, le=1.0)


class CommandResponse(BaseModel):
    accepted: bool
    command_id: str
    message: str
    queued_at: float
