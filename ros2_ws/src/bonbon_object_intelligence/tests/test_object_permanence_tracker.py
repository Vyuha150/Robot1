"""Tests for ObjectPermanenceTracker — visible/occluded/memory/lost lifecycle."""

from __future__ import annotations

from bonbon_object_intelligence.core.object_permanence_tracker import (
    ObjectPermanenceTracker,
    PermanenceConfig,
    PermanenceState,
    RawObjectDetection,
)


class _Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


def _det(class_name="chair", x=1.0, y=0.0, z=0.0, confidence=0.8):
    return RawObjectDetection(class_name, confidence, x, y, z)


def _tracker(**cfg_overrides):
    clock = _Clock()
    cfg = PermanenceConfig(**cfg_overrides)
    return ObjectPermanenceTracker(config=cfg, clock=clock), clock


class TestNewObject:
    def test_new_detection_creates_visible_track(self):
        tracker, _ = _tracker()
        snap = tracker.update([_det()])
        assert len(snap) == 1
        assert snap[0].state == PermanenceState.VISIBLE

    def test_repeated_detection_keeps_same_track_id(self):
        tracker, _ = _tracker()
        snap1 = tracker.update([_det(x=1.0)])
        snap2 = tracker.update([_det(x=1.05)])
        assert snap1[0].object_track_id == snap2[0].object_track_id


class TestOcclusionTolerance:
    def test_single_miss_goes_occluded_not_lost(self):
        tracker, clock = _tracker(occlusion_grace_sec=2.0)
        tracker.update([_det()])
        snap = tracker.update([])
        assert snap[0].state == PermanenceState.OCCLUDED

    def test_brief_occlusion_then_redetection_returns_to_visible(self):
        tracker, clock = _tracker(occlusion_grace_sec=2.0)
        tracker.update([_det(x=1.0)])
        tracker.update([])
        clock.advance(1.0)
        snap = tracker.update([_det(x=1.0)])
        assert snap[0].state == PermanenceState.VISIBLE

    def test_occluded_beyond_grace_becomes_memory(self):
        # Mirrors a periodic polling loop (update() called every tick) rather
        # than one big clock jump — _lost_since anchors to the FIRST missed
        # tick, so elapsed time must accumulate across repeated calls.
        tracker, clock = _tracker(occlusion_grace_sec=1.0, memory_grace_sec=10.0)
        tracker.update([_det()])
        snap = None
        for _ in range(4):
            clock.advance(0.5)
            snap = tracker.update([])
        assert snap[0].state == PermanenceState.MEMORY

    def test_memory_beyond_window_becomes_lost_and_evicted(self):
        tracker, clock = _tracker(occlusion_grace_sec=1.0, memory_grace_sec=2.0)
        tracker.update([_det()])
        for _ in range(10):
            clock.advance(0.5)
            tracker.update([])
        assert tracker.tracked_count == 0


class TestClassSeparation:
    def test_different_classes_never_merge_even_at_same_position(self):
        tracker, _ = _tracker()
        snap = tracker.update([_det(class_name="chair", x=1.0), _det(class_name="bag", x=1.0)])
        assert len(snap) == 2
        ids = {s.object_track_id for s in snap}
        assert len(ids) == 2


class TestBoundedTracking:
    def test_max_objects_enforced(self):
        tracker, _ = _tracker(max_objects=3)
        dets = [_det(class_name="item", x=float(i) * 10) for i in range(10)]
        tracker.update(dets)
        assert tracker.tracked_count <= 3


class TestVelocityEstimation:
    def test_moving_object_gets_nonzero_velocity(self):
        # Displacement must stay within the match-distance gate (default
        # 0.5 m) or the tracker correctly treats it as a different object.
        tracker, clock = _tracker()
        tracker.update([_det(x=0.0)])
        clock.advance(1.0)
        snap = tracker.update([_det(x=0.2)])
        assert abs(snap[0].vx - 0.2) < 0.05
