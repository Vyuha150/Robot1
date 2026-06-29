"""Tests for SpeakerIdentityManager — DOA+recency based persistent speaker IDs.

Documents the honest limitation up front: this is NOT a voiceprint model.
"""

from __future__ import annotations

from bonbon_speaker_intelligence.core.speaker_identity_manager import (
    SpeakerIdentityConfig,
    SpeakerIdentityManager,
)


class _Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


def _mgr(**overrides):
    clock = _Clock()
    cfg = SpeakerIdentityConfig(**overrides)
    return SpeakerIdentityManager(config=cfg, clock=clock), clock


class TestNewSpeakerAllocation:
    def test_first_utterance_allocates_new_speaker(self):
        mgr, _ = _mgr()
        speaker_id, is_new = mgr.resolve(doa_deg=30.0)
        assert is_new is True
        assert speaker_id.startswith("voice_")

    def test_unknown_doa_always_allocates_new(self):
        mgr, _ = _mgr()
        mgr.resolve(doa_deg=30.0)
        _, is_new = mgr.resolve(doa_deg=-1.0)
        assert is_new is True


class TestContinuity:
    def test_same_bearing_within_window_reuses_speaker(
        self,
    ):
        mgr, clock = _mgr(doa_tolerance_deg=15.0, recency_window_sec=10.0)
        id1, _ = mgr.resolve(30.0)
        clock.advance(1.0)
        id2, is_new = mgr.resolve(33.0)
        assert id2 == id1
        assert is_new is False

    def test_different_bearing_allocates_new_speaker(self):
        mgr, clock = _mgr(doa_tolerance_deg=10.0, recency_window_sec=10.0)
        id1, _ = mgr.resolve(30.0)
        clock.advance(1.0)
        id2, is_new = mgr.resolve(-60.0)
        assert id2 != id1
        assert is_new is True

    def test_same_bearing_after_recency_window_allocates_new(self):
        mgr, clock = _mgr(doa_tolerance_deg=15.0, recency_window_sec=5.0)
        id1, _ = mgr.resolve(30.0)
        clock.advance(10.0)  # past recency window
        id2, is_new = mgr.resolve(30.0)
        assert id2 != id1
        assert is_new is True

    def test_angle_wraparound_near_180(self):
        mgr, clock = _mgr(doa_tolerance_deg=10.0, recency_window_sec=10.0)
        id1, _ = mgr.resolve(178.0)
        clock.advance(1.0)
        id2, is_new = mgr.resolve(-179.0)  # 3 degrees away, wrapping
        assert id2 == id1
        assert is_new is False


class TestMultipleConcurrentSpeakers:
    def test_two_distinct_bearings_stay_distinct(self):
        mgr, clock = _mgr(doa_tolerance_deg=10.0, recency_window_sec=10.0)
        left_id, _ = mgr.resolve(45.0)
        right_id, _ = mgr.resolve(-45.0)
        assert left_id != right_id
        clock.advance(1.0)
        left_again, is_new_left = mgr.resolve(47.0)
        right_again, is_new_right = mgr.resolve(-43.0)
        assert left_again == left_id
        assert right_again == right_id
        assert is_new_left is False
        assert is_new_right is False


class TestEviction:
    def test_long_silent_speaker_is_forgotten(self):
        mgr, clock = _mgr(doa_tolerance_deg=10.0, recency_window_sec=2.0)
        mgr.resolve(30.0)
        assert mgr.known_speaker_count == 1
        clock.advance(100.0)  # far beyond eviction window (4x recency)
        mgr.resolve(90.0)
        assert mgr.known_speaker_count == 1  # old one evicted, only new remains
