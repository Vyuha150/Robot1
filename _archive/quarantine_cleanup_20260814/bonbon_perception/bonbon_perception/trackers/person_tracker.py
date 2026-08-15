"""
bonbon_perception.trackers.person_tracker
==========================================
Data classes and abstract base for person trackers.

A Track represents a single person moving through the scene.  It has:
  - A persistent track_id  (e.g. "person_0") that survives occlusion up to
    max_lost_frames frames.
  - Estimated state: position in image space, distance, bearing, velocity.
  - An age (frames since creation) and lost_count (frames since last matched).
  - Optional face_id set externally by face_node.

TrackState enum drives downstream behaviour:
  TENTATIVE  — first 1–2 frames: not yet published (avoids false positives)
  CONFIRMED  — published to /bonbon/vision/persons
  LOST       — not matched this frame; still retained for re-identification
  DELETED    — removed from active set; final cleanup
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from enum import IntEnum

from ..detectors.person_detector import Detection


class TrackState(IntEnum):
    TENTATIVE = 0
    CONFIRMED = 1
    LOST = 2
    DELETED = 3


@dataclass
class Track:
    """
    Single multi-frame person track.

    Positions are stored in image pixel space (cx, cy) and in robot-relative
    polar space (distance_m, bearing_deg) for direct feed to PersonState.
    """

    track_id: str
    state: TrackState = TrackState.TENTATIVE

    # Image-space smoothed centre (exponential moving average)
    cx: float = 0.0
    cy: float = 0.0

    # Last matched bounding box
    bbox: tuple[int, int, int, int] = (0, 0, 0, 0)

    # Robot-relative measurements
    distance_m: float = float("nan")
    bearing_deg: float = 0.0

    # Velocity estimate (m/s) — smoothed over track lifetime
    velocity_mps: float = 0.0

    # Identity
    face_id: str = ""
    age_group: str = "unknown"
    facing_robot: bool = False

    # Track lifecycle
    age_frames: int = 0  # total frames since creation
    lost_count: int = 0  # consecutive unmatched frames
    hit_streak: int = 0  # consecutive matched frames

    # Timing
    first_seen: float = field(default_factory=time.monotonic)
    last_seen: float = field(default_factory=time.monotonic)

    # Exponential smoothing alpha (lower = smoother, higher = more responsive)
    alpha: float = 0.4

    def update(self, det: Detection) -> None:
        """
        Update track with a new matched Detection.
        Applies exponential moving average smoothing to position and distance.
        """
        new_cx, new_cy = det.centre_px

        # Position smoothing
        if self.age_frames == 0:
            self.cx, self.cy = new_cx, new_cy
        else:
            self.cx = self.alpha * new_cx + (1 - self.alpha) * self.cx
            self.cy = self.alpha * new_cy + (1 - self.alpha) * self.cy

        # Distance smoothing (ignore NaN)
        if math.isfinite(det.depth_m):
            old_dist = self.distance_m if math.isfinite(self.distance_m) else det.depth_m
            dt = time.monotonic() - self.last_seen
            if dt > 0 and math.isfinite(old_dist):
                raw_vel = abs(det.depth_m - old_dist) / dt
                self.velocity_mps = self.alpha * raw_vel + (1 - self.alpha) * self.velocity_mps
            self.distance_m = self.alpha * det.depth_m + (1 - self.alpha) * old_dist

        self.bearing_deg = self.alpha * det.bearing_deg + (1 - self.alpha) * self.bearing_deg
        self.bbox = det.bbox
        self.hit_streak += 1
        self.lost_count = 0
        self.age_frames += 1
        self.last_seen = time.monotonic()

        # TENTATIVE → CONFIRMED after 2 consecutive hits
        if self.state == TrackState.TENTATIVE and self.hit_streak >= 2:
            self.state = TrackState.CONFIRMED

    def mark_lost(self) -> None:
        """Called when no detection matched this track this frame."""
        self.lost_count += 1
        self.hit_streak = 0
        self.age_frames += 1
        if self.state == TrackState.CONFIRMED:
            self.state = TrackState.LOST
        elif self.state == TrackState.TENTATIVE:
            self.state = TrackState.DELETED  # single-frame tentatives discarded

    @property
    def is_active(self) -> bool:
        return self.state in (TrackState.TENTATIVE, TrackState.CONFIRMED)

    @property
    def should_publish(self) -> bool:
        return self.state == TrackState.CONFIRMED

    @property
    def uptime_sec(self) -> float:
        return time.monotonic() - self.first_seen
