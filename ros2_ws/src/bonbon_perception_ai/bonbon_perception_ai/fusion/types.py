"""
bonbon_perception_ai.fusion.types
==================================
Pure-Python data transfer objects for the fusion pipeline.
Completely decoupled from ROS2 — the node layer converts ROS2 messages
into these types before passing them into the pipeline.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

# ── Input observations ────────────────────────────────────────────────────────


@dataclass
class ObjectObservation:
    """A single detected object, stripped of ROS2 boilerplate."""

    class_name: str
    confidence: float
    distance_m: float = math.nan  # NaN = unknown
    bearing_deg: float = 0.0
    track_id: str = ""
    timestamp: float = field(default_factory=time.monotonic)

    @property
    def has_depth(self) -> bool:
        return not math.isnan(self.distance_m)


@dataclass
class PersonObservation:
    """A single tracked person, stripped of ROS2 boilerplate."""

    person_id: str
    confidence: float
    distance_m: float = math.nan
    bearing_deg: float = 0.0
    facing_robot: bool = False
    age_group: str = "unknown"
    face_id: str = ""  # "" if face recognition disabled
    velocity_mps: float = 0.0
    timestamp: float = field(default_factory=time.monotonic)


@dataclass
class SpeechInput:
    """A transcribed speech command, stripped of ROS2 boilerplate."""

    text: str
    confidence: float
    speaker_id: str = ""
    is_low_confidence: bool = False
    is_silence: bool = False
    is_timeout: bool = False
    language: str = ""
    doa_angle_deg: float = 0.0
    timestamp: float = field(default_factory=time.monotonic)

    @property
    def is_valid(self) -> bool:
        """True when the input contains usable speech content."""
        return bool(self.text.strip()) and not self.is_silence and not self.is_timeout


@dataclass
class RobotPose:
    """2-D robot pose in the map frame."""

    x: float = 0.0
    y: float = 0.0
    theta_deg: float = 0.0
    timestamp: float = field(default_factory=time.monotonic)


@dataclass
class NavStatus:
    """Current navigation system state."""

    status: str = "idle"  # "idle"|"navigating"|"arrived"|"failed"
    is_moving: bool = False
    linear_vel_mps: float = 0.0
    angular_vel_rps: float = 0.0
    timestamp: float = field(default_factory=time.monotonic)


# ── Fused context (output of MultimodalFusion) ────────────────────────────────


@dataclass
class FusionContext:
    """
    Single-snapshot fusion of all active modalities.

    Produced by MultimodalFusion.fuse() and consumed by the understanding layer.
    """

    timestamp: float
    objects: list[ObjectObservation]
    persons: list[PersonObservation]
    speech: SpeechInput | None
    robot_pose: RobotPose | None
    nav_status: NavStatus | None
    stale_modalities: list[str]
    uncertainty_level: str  # "LOW" | "MEDIUM" | "HIGH"

    # ── Derived convenience properties ────────────────────────────────────────

    @property
    def nearest_person_distance_m(self) -> float:
        valid = [p.distance_m for p in self.persons if not math.isnan(p.distance_m)]
        return min(valid) if valid else math.inf

    @property
    def has_speech(self) -> bool:
        return self.speech is not None and self.speech.is_valid

    @property
    def person_count(self) -> int:
        return len(self.persons)

    @property
    def is_moving(self) -> bool:
        return self.nav_status is not None and self.nav_status.is_moving

    @property
    def uncertainty_score(self) -> float:
        """0.0 = LOW, 0.5 = MEDIUM, 1.0 = HIGH."""
        return {"LOW": 0.0, "MEDIUM": 0.5, "HIGH": 1.0}.get(self.uncertainty_level, 0.5)
