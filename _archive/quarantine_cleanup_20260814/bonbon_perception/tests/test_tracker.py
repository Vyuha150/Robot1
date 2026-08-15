"""
test_tracker.py
================
Tests for Track, TrackState, and SimpleTracker.
Pure Python — no ROS2 required.
"""

from __future__ import annotations

import time

from bonbon_perception.detectors.person_detector import Detection
from bonbon_perception.trackers.person_tracker import Track, TrackState
from bonbon_perception.trackers.simple_tracker import SimpleTracker

# ── Helpers ───────────────────────────────────────────────────────────────────


def _det(
    x: int = 100,
    y: int = 100,
    w: int = 80,
    h: int = 180,
    conf: float = 0.9,
    depth: float = 2.0,
    bearing: float = 0.0,
) -> Detection:
    d = Detection(bbox=(x, y, w, h), confidence=conf)
    d.depth_m = depth
    d.bearing_deg = bearing
    return d


# ═══════════════════════════════════════════════════════════════════════════════
# Track
# ═══════════════════════════════════════════════════════════════════════════════


class TestTrack:
    def test_initial_state_tentative(self):
        t = Track(track_id="person_0")
        assert t.state == TrackState.TENTATIVE

    def test_single_update_stays_tentative(self):
        t = Track(track_id="person_0")
        t.update(_det())
        assert t.state == TrackState.TENTATIVE

    def test_two_consecutive_updates_confirmed(self):
        t = Track(track_id="person_0")
        t.update(_det())
        t.update(_det())
        assert t.state == TrackState.CONFIRMED

    def test_confirmed_track_should_publish(self):
        t = Track(track_id="person_0")
        t.update(_det())
        t.update(_det())
        assert t.should_publish is True

    def test_tentative_track_not_published(self):
        t = Track(track_id="person_0")
        t.update(_det())
        assert t.should_publish is False

    def test_mark_lost_from_confirmed(self):
        t = Track(track_id="person_0")
        t.update(_det())
        t.update(_det())
        t.mark_lost()
        assert t.state == TrackState.LOST

    def test_mark_lost_from_tentative_deletes(self):
        t = Track(track_id="person_0")
        t.update(_det())  # still TENTATIVE after 1 update
        t.mark_lost()
        assert t.state == TrackState.DELETED

    def test_lost_track_not_active(self):
        t = Track(track_id="person_0")
        t.update(_det())
        t.update(_det())
        t.mark_lost()
        assert t.is_active is False

    def test_age_increments(self):
        t = Track(track_id="person_0")
        t.update(_det())
        t.update(_det())
        t.mark_lost()
        assert t.age_frames == 3

    def test_hit_streak_resets_on_lost(self):
        t = Track(track_id="person_0")
        t.update(_det())
        t.update(_det())
        t.mark_lost()
        assert t.hit_streak == 0

    def test_depth_smooth_on_update(self):
        t = Track(track_id="person_0")
        t.update(_det(depth=2.0))
        t.update(_det(depth=3.0))
        # EMA: second value should be between 2.0 and 3.0
        assert 2.0 <= t.distance_m <= 3.0

    def test_bearing_smooth_on_update(self):
        t = Track(track_id="person_0")
        t.update(_det(bearing=0.0))
        t.update(_det(bearing=10.0))
        assert 0.0 <= t.bearing_deg <= 10.0

    def test_uptime_increases(self):
        t = Track(track_id="person_0")
        time.sleep(0.05)
        assert t.uptime_sec >= 0.04


# ═══════════════════════════════════════════════════════════════════════════════
# SimpleTracker
# ═══════════════════════════════════════════════════════════════════════════════


class TestSimpleTrackerBasic:
    def test_empty_frame_returns_empty(self):
        tracker = SimpleTracker()
        result = tracker.update([])
        assert result == []

    def test_single_detection_creates_tentative_then_confirmed(self):
        tracker = SimpleTracker()
        # Frame 1 — tentative
        tracker.update([_det()])
        assert len(tracker.confirmed_tracks) == 0

        # Frame 2 — confirmed
        tracker.update([_det()])
        assert len(tracker.confirmed_tracks) == 1

    def test_single_track_id_stable(self):
        tracker = SimpleTracker()
        tracker.update([_det()])
        tracker.update([_det()])
        confirmed = tracker.confirmed_tracks
        assert len(confirmed) == 1
        assert confirmed[0].track_id == "person_0"

    def test_two_separate_persons(self):
        tracker = SimpleTracker(iou_threshold=0.3)
        dets = [_det(x=0), _det(x=400)]  # non-overlapping
        tracker.update(dets)
        tracker.update(dets)
        assert len(tracker.confirmed_tracks) == 2

    def test_different_track_ids(self):
        tracker = SimpleTracker(iou_threshold=0.3)
        dets = [_det(x=0), _det(x=400)]
        tracker.update(dets)
        tracker.update(dets)
        ids = {t.track_id for t in tracker.confirmed_tracks}
        assert len(ids) == 2

    def test_track_survives_brief_occlusion(self):
        tracker = SimpleTracker(max_lost_frames=5)
        # Establish track
        tracker.update([_det()])
        tracker.update([_det()])
        assert len(tracker.confirmed_tracks) == 1

        # Person disappears for 2 frames (below max_lost_frames=5)
        tracker.update([])
        tracker.update([])
        assert len(tracker.active_tracks) == 1  # LOST but still active

    def test_track_deleted_after_max_lost(self):
        tracker = SimpleTracker(max_lost_frames=2)
        tracker.update([_det()])
        tracker.update([_det()])

        # Disappear for 3 frames (> max_lost_frames=2)
        tracker.update([])
        tracker.update([])
        tracker.update([])
        assert len(tracker.active_tracks) == 0

    def test_re_entering_person_gets_new_id(self):
        """After deletion, a re-entering detection creates a NEW track."""
        tracker = SimpleTracker(max_lost_frames=1)
        tracker.update([_det()])
        tracker.update([_det()])
        old_ids = {t.track_id for t in tracker.confirmed_tracks}

        # Delete
        tracker.update([])
        tracker.update([])

        # Re-enter
        tracker.update([_det()])
        tracker.update([_det()])
        new_ids = {t.track_id for t in tracker.confirmed_tracks}
        assert new_ids != old_ids

    def test_reset_clears_all_tracks(self):
        tracker = SimpleTracker()
        tracker.update([_det()])
        tracker.update([_det()])
        tracker.reset()
        assert len(tracker.active_tracks) == 0

    def test_max_tracks_cap(self):
        """Tracker should not exceed max_tracks."""
        tracker = SimpleTracker(max_tracks=3)
        many = [_det(x=i * 100) for i in range(10)]
        tracker.update(many)
        assert len(tracker.active_tracks) <= 3


# ═══════════════════════════════════════════════════════════════════════════════
# Association (IoU matching correctness)
# ═══════════════════════════════════════════════════════════════════════════════


class TestAssociation:
    def test_high_iou_associates_correctly(self):
        """Two frames with the same bounding box: same track maintained."""
        tracker = SimpleTracker(iou_threshold=0.3)
        d1 = _det(x=100, y=100, w=80, h=160)
        d2 = _det(x=102, y=102, w=80, h=160)  # slightly shifted — high IoU

        tracker.update([d1])
        tracker.update([d2])  # should match the existing track
        assert len(tracker.active_tracks) == 1

    def test_low_iou_creates_second_track(self):
        """Non-overlapping bounding boxes should create separate tracks."""
        tracker = SimpleTracker(iou_threshold=0.3)
        d1 = _det(x=0, y=0, w=80, h=160)
        d2 = _det(x=500, y=0, w=80, h=160)  # far away — IoU ≈ 0

        tracker.update([d1])
        tracker.update([d1, d2])  # second frame has two detections
        assert len(tracker.active_tracks) == 2

    def test_greedy_picks_best_match(self):
        """Three tracks and three detections in random order — all matched."""
        tracker = SimpleTracker(iou_threshold=0.3)
        dets = [_det(x=i * 150) for i in range(3)]
        tracker.update(dets)
        tracker.update(dets)  # all should match their respective tracks
        assert len(tracker.confirmed_tracks) == 3


# ═══════════════════════════════════════════════════════════════════════════════
# Velocity estimation
# ═══════════════════════════════════════════════════════════════════════════════


class TestVelocityEstimation:
    def test_stationary_person_near_zero_velocity(self):
        tracker = SimpleTracker()
        d = _det(depth=2.0)
        for _ in range(5):
            tracker.update([d])
        track = tracker.confirmed_tracks[0]
        assert track.velocity_mps < 0.5  # nearly stationary

    def test_approaching_person_positive_velocity(self):
        tracker = SimpleTracker()
        # Establish track
        tracker.update([_det(depth=4.0)])
        tracker.update([_det(depth=4.0)])
        time.sleep(0.05)
        # Approach rapidly
        tracker.update([_det(depth=2.0)])
        track = tracker.confirmed_tracks[0]
        # velocity should be > 0 (getting closer)
        assert track.velocity_mps >= 0.0
