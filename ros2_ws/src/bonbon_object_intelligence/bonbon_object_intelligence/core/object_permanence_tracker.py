"""ObjectPermanenceTracker — per-object tracking with occlusion tolerance.

bonbon_vision's own embedded tracker (vision_node._SimpleTracker) evicts a
track after `max_lost` frames with no further state — there is no concept of
"this object is probably just occluded, not gone." This module adds exactly
that: visible -> occluded (within a grace window) -> memory (retained,
low-confidence, beyond the window) -> lost (terminal, evicted).

Mirrors bonbon_multi_person_tracker's lifecycle-FSM shape (same project
convention for "don't declare something gone from one missed frame"), but
simpler — objects don't reappear-and-resume-identity the way people do
(re-identifying a chair after occlusion by appearance alone is out of scope
without a real re-id model), so there is no separate "reappeared" state:
a re-detection while occluded/memory just returns directly to visible.
"""

from __future__ import annotations

import itertools
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum


class PermanenceState(str, Enum):
    VISIBLE = "visible"
    OCCLUDED = "occluded"
    MEMORY = "memory"
    LOST = "lost"


@dataclass
class PermanenceConfig:
    occlusion_grace_sec: float = 2.0  # visible -> occluded -> memory boundary
    memory_grace_sec: float = 15.0  # occluded -> memory -> lost boundary (cumulative)
    max_objects: int = 50


@dataclass
class RawObjectDetection:
    class_name: str
    confidence: float
    x: float
    y: float
    z: float
    source_camera: str = ""


class _TrackedObjectRecord:
    def __init__(self, object_track_id: str, det: RawObjectDetection, now: float) -> None:
        self.object_track_id = object_track_id
        self.class_name = det.class_name
        self.confidence = det.confidence
        self.x, self.y, self.z = det.x, det.y, det.z
        self.vx, self.vy = 0.0, 0.0
        self.source_camera = det.source_camera
        self.first_seen = now
        self.last_seen = now
        self.state = PermanenceState.VISIBLE
        self._lost_since: float | None = None
        self.occlusion_duration_sec = 0.0

    def apply_detection(self, det: RawObjectDetection, now: float) -> None:
        dt = max(now - self.last_seen, 1.0 / 30.0)
        self.vx = (det.x - self.x) / dt
        self.vy = (det.y - self.y) / dt
        self.x, self.y, self.z = det.x, det.y, det.z
        self.confidence = det.confidence
        self.last_seen = now
        self.state = PermanenceState.VISIBLE
        self._lost_since = None
        self.occlusion_duration_sec = 0.0

    def age(self, now: float, cfg: PermanenceConfig) -> None:
        if self.state == PermanenceState.LOST:
            return
        if self._lost_since is None:
            self._lost_since = now
        elapsed = now - self._lost_since
        self.occlusion_duration_sec = elapsed
        if elapsed <= cfg.occlusion_grace_sec:
            self.state = PermanenceState.OCCLUDED
        elif elapsed <= cfg.occlusion_grace_sec + cfg.memory_grace_sec:
            self.state = PermanenceState.MEMORY
        else:
            self.state = PermanenceState.LOST


class ObjectPermanenceTracker:
    """Associates each cycle's RawObjectDetections to persistent
    object_track_ids by nearest-position-within-class matching, then ages
    everything not matched this cycle through the permanence states above.
    """

    def __init__(
        self,
        config: PermanenceConfig | None = None,
        max_match_distance_m: float = 0.5,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._cfg = config or PermanenceConfig()
        self._max_match_distance = max_match_distance_m
        self._clock = clock or time.monotonic
        self._records: dict[str, _TrackedObjectRecord] = {}
        self._counter = itertools.count(1)

    def update(self, detections: list[RawObjectDetection]) -> list[_TrackedObjectRecord]:
        now = self._clock()
        matched: set[str] = set()

        for det in detections:
            best_id = None
            best_dist = float("inf")
            for rec in self._records.values():
                if rec.object_track_id in matched or rec.class_name != det.class_name:
                    continue
                dist = ((det.x - rec.x) ** 2 + (det.y - rec.y) ** 2 + (det.z - rec.z) ** 2) ** 0.5
                if dist <= self._max_match_distance and dist < best_dist:
                    best_id, best_dist = rec.object_track_id, dist

            if best_id is not None:
                self._records[best_id].apply_detection(det, now)
                matched.add(best_id)
            elif len(self._records) < self._cfg.max_objects:
                track_id = f"obj_{next(self._counter)}"
                self._records[track_id] = _TrackedObjectRecord(track_id, det, now)
                matched.add(track_id)

        to_evict = []
        for rec in self._records.values():
            if rec.object_track_id not in matched:
                rec.age(now, self._cfg)
                if rec.state == PermanenceState.LOST:
                    to_evict.append(rec.object_track_id)

        snapshot = list(self._records.values())
        for track_id in to_evict:
            del self._records[track_id]

        return snapshot

    @property
    def tracked_count(self) -> int:
        return len(self._records)
