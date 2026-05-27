"""Pydantic v2 domain models for bonbon_data_stores.

Every record that passes through the store is typed here.  Raw dicts are
accepted at the repository boundary and immediately converted.
"""

from __future__ import annotations

import time
import uuid
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class PrivacyLevel(StrEnum):
    """Privacy classification for stored events and records.

    ``do_not_store`` is special: any event carrying this level MUST be
    discarded immediately and never written to any storage backend.
    """

    PUBLIC = "public"
    INTERNAL = "internal"
    SENSITIVE = "sensitive"
    RESTRICTED = "restricted"
    DO_NOT_STORE = "do_not_store"


class RetentionPolicy(StrEnum):
    """How long a record is kept before automatic deletion."""

    EPHEMERAL = "ephemeral"  # purge when session ends
    SESSION_ONLY = "session_only"  # purge at session close
    SEVEN_DAYS = "7_days"
    THIRTY_DAYS = "30_days"
    ONE_YEAR = "1_year"
    PERMANENT_UNTIL_DELETED = "permanent_until_deleted"


class RobotMode(StrEnum):
    IDLE = "idle"
    ACTIVE = "active"
    NAVIGATING = "navigating"
    SERVING = "serving"
    CHARGING = "charging"
    MAINTENANCE = "maintenance"
    EMERGENCY = "emergency"
    SHUTDOWN = "shutdown"


class SafetyEventType(StrEnum):
    COLLISION_RISK = "collision_risk"
    EMERGENCY_STOP = "emergency_stop"
    SAFETY_STOP = "safety_stop"
    HARDWARE_FAULT = "hardware_fault"
    WATCHDOG_TIMEOUT = "watchdog_timeout"
    MANUAL_OVERRIDE = "manual_override"
    RECOVERY = "recovery"


class NavigationOutcome(StrEnum):
    SUCCESS = "success"
    ABORTED = "aborted"
    FAILED = "failed"
    PREEMPTED = "preempted"
    REPLANNED = "replanned"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _new_id() -> str:
    return str(uuid.uuid4())


def _now() -> float:
    return time.time()


# ---------------------------------------------------------------------------
# Base event
# ---------------------------------------------------------------------------


class BaseEvent(BaseModel):
    """Common fields shared by every storable event."""

    event_id: str = Field(default_factory=_new_id)
    timestamp: float = Field(default_factory=_now)
    session_id: str | None = None
    privacy_level: PrivacyLevel = PrivacyLevel.INTERNAL
    retention_policy: RetentionPolicy = RetentionPolicy.THIRTY_DAYS
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("privacy_level", mode="before")
    @classmethod
    def _coerce_privacy(cls, v: Any) -> PrivacyLevel:
        if isinstance(v, PrivacyLevel):
            return v
        return PrivacyLevel(str(v).lower())

    @field_validator("retention_policy", mode="before")
    @classmethod
    def _coerce_retention(cls, v: Any) -> RetentionPolicy:
        if isinstance(v, RetentionPolicy):
            return v
        return RetentionPolicy(str(v).lower())

    def is_storable(self) -> bool:
        """Return False for do_not_store events — callers MUST check this."""
        return self.privacy_level != PrivacyLevel.DO_NOT_STORE


# ---------------------------------------------------------------------------
# User / profile models
# ---------------------------------------------------------------------------


class UserPreference(BaseModel):
    key: str
    value: str
    category: str = "general"


class UserRecord(BaseModel):
    """A known user of the BonBon robot."""

    user_id: str = Field(default_factory=_new_id)
    display_name: str
    language: str = "en"
    preferred_interaction_style: str = "friendly"
    accessibility_needs: list[str] = Field(default_factory=list)
    preferences: list[UserPreference] = Field(default_factory=list)
    # Biometric references — stored only with explicit consent
    face_encoding_ref: str | None = Field(
        default=None,
        description=(
            "Reference token to the face encoding; actual biometric data is "
            "stored separately and only when store_face_data=True."
        ),
    )
    voice_profile_ref: str | None = None
    # Provenance
    created_at: float = Field(default_factory=_now)
    last_seen_at: float = Field(default_factory=_now)
    interaction_count: int = 0
    privacy_level: PrivacyLevel = PrivacyLevel.SENSITIVE
    retention_policy: RetentionPolicy = RetentionPolicy.PERMANENT_UNTIL_DELETED
    is_anonymous: bool = False


# ---------------------------------------------------------------------------
# Interaction history
# ---------------------------------------------------------------------------


class InteractionEvent(BaseEvent):
    """One turn in a conversation between user and robot."""

    user_id: str | None = None
    input_modality: str = "speech"  # speech | touch | gesture | text
    input_text: str | None = None
    intent: str | None = None
    intent_confidence: float = 0.0
    response_text: str | None = None
    response_modality: str = "speech"
    tts_latency_ms: float = 0.0
    satisfaction_score: float | None = None
    language: str = "en"
    # raw audio NEVER stored unless privacy.store_audio=True
    audio_ref: str | None = Field(
        default=None,
        description="Reference token; raw audio only stored when privacy.store_audio=True.",
    )


# ---------------------------------------------------------------------------
# Robot state
# ---------------------------------------------------------------------------


class RobotState(BaseEvent):
    """Periodic snapshot of the robot's operational state."""

    mode: RobotMode = RobotMode.IDLE
    battery_level: float = Field(default=1.0, ge=0.0, le=1.0)
    position_x: float = 0.0
    position_y: float = 0.0
    position_z: float = 0.0
    orientation_yaw: float = 0.0
    map_id: str | None = None
    active_task: str | None = None
    cpu_load: float = Field(default=0.0, ge=0.0)
    memory_used_mb: float = Field(default=0.0, ge=0.0)
    active_nodes: list[str] = Field(default_factory=list)
    error_flags: list[str] = Field(default_factory=list)
    retention_policy: RetentionPolicy = RetentionPolicy.SEVEN_DAYS


# ---------------------------------------------------------------------------
# Safety events
# ---------------------------------------------------------------------------


class SafetyEvent(BaseEvent):
    """Record of a safety-critical occurrence."""

    event_type: SafetyEventType
    severity: int = Field(default=1, ge=1, le=5)
    source_node: str = ""
    description: str = ""
    position_x: float = 0.0
    position_y: float = 0.0
    obstacle_distance_m: float | None = None
    resolved: bool = False
    resolved_at: float | None = None
    privacy_level: PrivacyLevel = PrivacyLevel.INTERNAL
    retention_policy: RetentionPolicy = RetentionPolicy.ONE_YEAR


# ---------------------------------------------------------------------------
# Navigation events
# ---------------------------------------------------------------------------


class NavigationEvent(BaseEvent):
    """Record of a navigation goal and its outcome."""

    goal_id: str = Field(default_factory=_new_id)
    map_id: str | None = None
    start_x: float = 0.0
    start_y: float = 0.0
    goal_x: float = 0.0
    goal_y: float = 0.0
    outcome: NavigationOutcome = NavigationOutcome.SUCCESS
    distance_m: float = 0.0
    duration_sec: float = 0.0
    replanning_count: int = 0
    planner_used: str = ""
    retention_policy: RetentionPolicy = RetentionPolicy.THIRTY_DAYS


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------


class AuditLogEntry(BaseModel):
    """Immutable append-only audit trail record."""

    log_id: str = Field(default_factory=_new_id)
    timestamp: float = Field(default_factory=_now)
    actor: str  # node or user that performed the action
    action: str  # e.g. "delete_user", "export_data"
    target_type: str = ""  # e.g. "user", "interaction"
    target_id: str = ""
    outcome: str = "success"  # success | failure
    detail: str = ""
    privacy_level: PrivacyLevel = PrivacyLevel.INTERNAL
    retention_policy: RetentionPolicy = RetentionPolicy.ONE_YEAR


# ---------------------------------------------------------------------------
# Map metadata
# ---------------------------------------------------------------------------


class EnvironmentZone(BaseModel):
    """A named zone within a map."""

    zone_id: str = Field(default_factory=_new_id)
    map_id: str
    zone_name: str
    zone_type: str = "room"  # room | corridor | charging_station | service_point
    polygon_json: str = "[]"  # JSON array of [x, y] vertices
    description: str = ""


class MapMetadata(BaseModel):
    """Metadata for a stored robot map."""

    map_id: str = Field(default_factory=_new_id)
    map_name: str
    file_path: str = ""
    pgm_path: str = ""
    yaml_path: str = ""
    resolution_m: float = Field(default=0.05, gt=0.0)
    origin_x: float = 0.0
    origin_y: float = 0.0
    width_cells: int = 0
    height_cells: int = 0
    created_at: float = Field(default_factory=_now)
    last_updated_at: float = Field(default_factory=_now)
    is_active: bool = False
    zones: list[EnvironmentZone] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# AI / LLM context
# ---------------------------------------------------------------------------


class AIContextRecord(BaseEvent):
    """Stored AI context window fragment for session continuity."""

    context_type: str = "conversation"  # conversation | task | knowledge
    content_hash: str = ""  # SHA-256 of content for deduplication
    content_text: str = ""
    token_count: int = 0
    model_name: str = ""
    embedding_ref: str | None = None  # FAISS / ChromaDB vector id
    retention_policy: RetentionPolicy = RetentionPolicy.SEVEN_DAYS


# ---------------------------------------------------------------------------
# Vector search result
# ---------------------------------------------------------------------------


class VectorSearchResult(BaseModel):
    """Returned by FAISSVectorStore.search()."""

    vector_id: str
    score: float  # cosine similarity or L2 distance
    payload: dict[str, Any] = Field(default_factory=dict)
    source_index: str = ""


# ---------------------------------------------------------------------------
# RAG search result
# ---------------------------------------------------------------------------


class RAGSearchResult(BaseModel):
    """Returned by RAGQueryEngine.query()."""

    doc_id: str
    collection: str
    score: float
    document: str
    metadata: dict[str, Any] = Field(default_factory=dict)
