"""Privacy-safe storage for field failure events.

The privacy contract is enforced structurally, not by convention:
`AnonymizedEvent` has no raw-media fields at all, and `metadata` is a
str->str dict that `AnonymizedEventStore.append` scans for a denylist of
field names that would indicate someone tried to smuggle raw biometric
data through it. There is no `debug_mode` bypass on this store -- raw
snapshots go through a deliberately separate path (see
`failure_case_logger.DebugSnapshotStore`) so the default event log can
never contain them, even by mistake.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path


class FailureCategory(StrEnum):
    WRONG_OBJECT = "wrong_object"
    MISSED_OBJECT = "missed_object"
    WRONG_GESTURE = "wrong_gesture"
    MISSED_GESTURE = "missed_gesture"
    WRONG_SPEAKER = "wrong_speaker"
    WRONG_PERSON_IDENTITY = "wrong_person_identity"
    WRONG_EMOTION = "wrong_emotion"
    WRONG_RESPONSE = "wrong_response"
    UNSAFE_PROPOSAL_BLOCKED = "unsafe_proposal_blocked"
    NAVIGATION_FAILURE = "navigation_failure"
    DASHBOARD_MISMATCH = "dashboard_mismatch"
    DEGRADED_MODE_FAILURE = "degraded_mode_failure"
    # Added for the data/training/fine-tuning pipeline brief's failure
    # category list (Phase 3): these four were previously only reachable
    # through the generic WRONG_RESPONSE bucket, which made ASR transcript
    # errors, RAG answer errors, intent-classification errors, and semantic
    # location errors indistinguishable in the failure-rate breakdown and
    # in generated regression test IDs. Purely additive -- existing values
    # and every existing caller/test keeps working unchanged.
    WRONG_ASR_TRANSCRIPT = "wrong_asr_transcript"
    WRONG_INTENT = "wrong_intent"
    WRONG_RAG_ANSWER = "wrong_rag_answer"
    WRONG_SEMANTIC_LOCATION = "wrong_semantic_location"
    STAFF_INTERVENTION = "staff_intervention"


# Any metadata key containing one of these substrings is rejected -- defense
# in depth against raw biometric data being smuggled in through the
# free-form metadata dict.
_FORBIDDEN_METADATA_SUBSTRINGS = (
    "raw_face",
    "raw_audio",
    "face_image",
    "audio_waveform",
    "face_embedding",
    "voiceprint",
    "biometric_raw",
)


@dataclass(frozen=True)
class AnonymizedEvent:
    event_id: str
    timestamp: float
    family: str
    failure_category: FailureCategory
    scenario_id: str | None
    oracle_reason: str
    metadata: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["failure_category"] = self.failure_category.value
        return d

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> AnonymizedEvent:
        return cls(
            event_id=str(data["event_id"]),
            timestamp=float(data["timestamp"]),
            family=str(data["family"]),
            failure_category=FailureCategory(data["failure_category"]),
            scenario_id=data.get("scenario_id"),
            oracle_reason=str(data["oracle_reason"]),
            metadata=dict(data.get("metadata", {})),
        )

    @classmethod
    def create(
        cls,
        family: str,
        failure_category: FailureCategory,
        oracle_reason: str,
        scenario_id: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> AnonymizedEvent:
        return cls(
            event_id=str(uuid.uuid4()),
            timestamp=time.time(),
            family=family,
            failure_category=failure_category,
            scenario_id=scenario_id,
            oracle_reason=oracle_reason,
            metadata=dict(metadata or {}),
        )


class PrivacyViolationError(ValueError):
    """Raised when an event's metadata looks like it carries raw biometric
    data -- the store refuses to persist it rather than silently dropping
    just the offending field."""


class AnonymizedEventStore:
    """JSON-lines-backed store of `AnonymizedEvent`s. Append-only; never
    raw face/audio, by construction (see module docstring)."""

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, event: AnonymizedEvent) -> None:
        for key in event.metadata:
            lowered = key.lower()
            if any(bad in lowered for bad in _FORBIDDEN_METADATA_SUBSTRINGS):
                raise PrivacyViolationError(
                    f"metadata key {key!r} looks like raw biometric data; rejected"
                )
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event.to_dict()) + "\n")

    def all_events(self) -> list[AnonymizedEvent]:
        if not self._path.exists():
            return []
        events = []
        with open(self._path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    events.append(AnonymizedEvent.from_dict(json.loads(line)))
        return events

    def events_by_category(self, category: FailureCategory) -> list[AnonymizedEvent]:
        return [e for e in self.all_events() if e.failure_category == category]

    def failure_rate_by_family(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for e in self.all_events():
            counts[e.family] = counts.get(e.family, 0) + 1
        return counts
