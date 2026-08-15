"""Typed annotation record schemas for the five domains the data pipeline
brief names (Phase 4): object detection, gesture, ASR, emotion, navigation.

Distinct from bonbon_field_learning.annotation_exporter.LabeledExample,
which pairs a generic AnonymizedEvent with its ReviewItem for regression-
test generation. These schemas are the per-domain RAW ANNOTATION record
shape a human reviewer (or an annotation tool) fills in when labeling a
training example -- richer and domain-specific, feeding
dataset_registry-tracked training sets rather than the field-failure log.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class ObjectAnnotation:
    image_id: str
    object_class: str
    bounding_box: tuple[float, float, float, float]  # (x, y, w, h), normalized 0-1
    occlusion: str  # "none" | "partial" | "heavy"
    lighting: str  # "good" | "dim" | "backlit" | "overexposed"
    confidence: float
    reviewer: str

    def validate(self) -> list[str]:
        problems = []
        if len(self.bounding_box) != 4:
            problems.append("bounding_box must be (x, y, w, h)")
        elif not all(0.0 <= v <= 1.0 for v in self.bounding_box):
            problems.append("bounding_box values must be normalized to 0.0-1.0")
        if not 0.0 <= self.confidence <= 1.0:
            problems.append("confidence must be 0.0-1.0")
        if self.occlusion not in ("none", "partial", "heavy"):
            problems.append(f"unknown occlusion value {self.occlusion!r}")
        if not self.reviewer:
            problems.append("reviewer is required")
        return problems

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GestureAnnotation:
    person_track_id: str
    gesture_class: str
    start_time_sec: float
    end_time_sec: float
    confidence: float
    reviewer: str
    video_clip_id: str | None = None
    landmark_sequence_id: str | None = None

    def validate(self) -> list[str]:
        problems = []
        if self.video_clip_id is None and self.landmark_sequence_id is None:
            problems.append("one of video_clip_id or landmark_sequence_id is required")
        if self.end_time_sec < self.start_time_sec:
            problems.append("end_time_sec must be >= start_time_sec")
        if not 0.0 <= self.confidence <= 1.0:
            problems.append("confidence must be 0.0-1.0")
        if not self.reviewer:
            problems.append("reviewer is required")
        return problems

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ASRAnnotation:
    audio_id: str
    language: str
    transcript: str
    noisy: bool
    speaker_distance_m: float
    corrected_text: str
    reviewer: str

    def validate(self) -> list[str]:
        problems = []
        if not self.language:
            problems.append("language is required")
        if self.speaker_distance_m < 0:
            problems.append("speaker_distance_m cannot be negative")
        if not self.reviewer:
            problems.append("reviewer is required")
        return problems

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EmotionAnnotation:
    person_track_id: str
    face_cue: str  # "" if not available (e.g. face out of frame) -- absence is meaningful, never fabricated
    voice_cue: str
    text_cue: str
    final_human_state: str
    uncertainty: float  # 0.0 (certain) - 1.0 (fully uncertain); brief requires uncertainty to always be preserved
    reviewer: str

    def validate(self) -> list[str]:
        problems = []
        if not 0.0 <= self.uncertainty <= 1.0:
            problems.append("uncertainty must be 0.0-1.0")
        if not self.face_cue and not self.voice_cue and not self.text_cue:
            problems.append("at least one of face_cue/voice_cue/text_cue must be non-empty")
        if not self.reviewer:
            problems.append("reviewer is required")
        return problems

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class NavigationAnnotation:
    map_id: str
    start: tuple[float, float]
    goal: tuple[float, float]
    failure_reason: str
    obstacle_type: str
    correction: str
    reviewer: str = ""

    def validate(self) -> list[str]:
        problems = []
        if not self.map_id:
            problems.append("map_id is required")
        if not self.failure_reason:
            problems.append("failure_reason is required")
        return problems

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


SCHEMA_BY_DOMAIN: dict[str, type] = {
    "object": ObjectAnnotation,
    "gesture": GestureAnnotation,
    "asr": ASRAnnotation,
    "emotion": EmotionAnnotation,
    "navigation": NavigationAnnotation,
}
