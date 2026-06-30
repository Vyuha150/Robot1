"""Tests for StaleFrameDropper."""

from __future__ import annotations

from bonbon_perception_efficiency.core.stale_frame_dropper import StaleFrameDropper


class _Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


class TestNeverReceived:
    def test_never_received_is_stale(self):
        dropper = StaleFrameDropper(timeout_sec=1.0)
        result = dropper.check()
        assert result.is_stale is True
        assert result.age_sec == float("inf")


class TestFreshness:
    def test_just_received_is_fresh(self):
        clock = _Clock()
        dropper = StaleFrameDropper(timeout_sec=1.0, clock=clock)
        dropper.mark_received()
        result = dropper.check()
        assert result.is_stale is False
        assert result.age_sec == 0.0

    def test_within_timeout_is_fresh(self):
        clock = _Clock()
        dropper = StaleFrameDropper(timeout_sec=1.0, clock=clock)
        dropper.mark_received()
        clock.advance(0.5)
        assert dropper.check().is_stale is False

    def test_beyond_timeout_is_stale(self):
        clock = _Clock()
        dropper = StaleFrameDropper(timeout_sec=1.0, clock=clock)
        dropper.mark_received()
        clock.advance(2.0)
        result = dropper.check()
        assert result.is_stale is True
        assert abs(result.age_sec - 2.0) < 1e-6

    def test_new_message_resets_freshness(self):
        clock = _Clock()
        dropper = StaleFrameDropper(timeout_sec=1.0, clock=clock)
        dropper.mark_received()
        clock.advance(2.0)
        assert dropper.check().is_stale is True
        dropper.mark_received()
        assert dropper.check().is_stale is False
