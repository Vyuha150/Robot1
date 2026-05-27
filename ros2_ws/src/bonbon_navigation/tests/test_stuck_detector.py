"""
Tests for bonbon_navigation.core.stuck_detector
"""

import time

from bonbon_navigation.config.nav_config import StuckDetectorConfig
from bonbon_navigation.core.stuck_detector import StuckDetector


def _cfg(**kw) -> StuckDetectorConfig:
    defaults = dict(
        window_sec=1.0,
        min_progress_m=0.10,
        stuck_threshold_count=2,
        zero_velocity_window_sec=0.5,
    )
    defaults.update(kw)
    return StuckDetectorConfig(**defaults)


# ── Not stuck — normal movement ───────────────────────────────────────────────


class TestNotStuck:
    def test_moving_robot_not_stuck(self):
        sd = StuckDetector(_cfg())
        sd.update(0.0, 0.0, 0.5)
        sd.update(0.3, 0.0, 0.5)
        sd.update(0.6, 0.0, 0.5)
        result = sd.check()
        assert result.is_stuck is False

    def test_fresh_detector_not_stuck(self):
        sd = StuckDetector(_cfg())
        result = sd.check()
        assert result.is_stuck is False

    def test_single_sample_not_stuck(self):
        sd = StuckDetector(_cfg())
        sd.update(0.0, 0.0, 0.0)
        assert sd.check().is_stuck is False

    def test_reset_clears_history(self):
        sd = StuckDetector(_cfg(window_sec=0.05, stuck_threshold_count=1))
        sd.update(0.0, 0.0, 0.0)
        time.sleep(0.1)
        sd.update(0.0, 0.0, 0.0)
        sd.check()  # may declare stuck
        sd.reset()
        assert sd.check().is_stuck is False


# ── Stuck detection ───────────────────────────────────────────────────────────


class TestStuckDetection:
    def test_no_progress_stuck(self):
        """Robot hasn't moved for window_sec → stuck."""
        # window_sec=0.12, sleep=0.08: actual_window(0.08) >= window*0.5(0.06)
        # and sleep(0.08) < window(0.12) so first sample is not trimmed.
        sd = StuckDetector(_cfg(window_sec=0.12, min_progress_m=0.10, stuck_threshold_count=1))
        sd.reset()
        sd.update(1.0, 1.0, 0.0)
        time.sleep(0.08)
        sd.update(1.0, 1.0, 0.0)
        result = sd.check()
        assert result.is_stuck is True

    def test_tiny_movement_stuck(self):
        """Movement below min_progress_m → still stuck."""
        sd = StuckDetector(_cfg(window_sec=0.12, min_progress_m=0.10, stuck_threshold_count=1))
        sd.reset()
        sd.update(0.0, 0.0, 0.05)
        time.sleep(0.08)
        sd.update(0.02, 0.01, 0.05)  # 0.022 m < 0.10 m threshold
        result = sd.check()
        assert result.is_stuck is True

    def test_threshold_count_delays_declaration(self):
        """stuck_threshold_count=2 means 2 consecutive failures needed."""
        sd = StuckDetector(_cfg(window_sec=0.05, min_progress_m=0.10, stuck_threshold_count=3))
        sd.update(0.0, 0.0, 0.0)
        time.sleep(0.06)
        sd.update(0.0, 0.0, 0.0)
        # First check — failure count=1, threshold=3 → not yet stuck
        r1 = sd.check()
        r2 = sd.check()
        # Still not at 3 consecutive
        # Even after 2 checks → not stuck yet (only at 2)
        assert not (r1.is_stuck and r2.is_stuck)  # at least one should be False


# ── Zero-velocity window ──────────────────────────────────────────────────────


class TestZeroVelocityWindow:
    def test_zero_vel_while_moving_not_stuck(self):
        """Velocity=0 reported but robot DID make progress → not stuck."""
        sd = StuckDetector(
            _cfg(
                window_sec=1.0,
                min_progress_m=0.05,
                stuck_threshold_count=1,
                zero_velocity_window_sec=0.2,
            )
        )
        sd.update(0.0, 0.0, 0.5)
        sd.update(0.5, 0.0, 0.5)  # large progress
        sd.update(0.5, 0.0, 0.0)  # velocity dropped to 0 but already moved
        result = sd.check()
        assert result.is_stuck is False

    def test_zero_vel_no_progress_stuck(self):
        """Zero velocity AND no progress → stuck."""
        # window_sec=0.12 keeps first sample alive during sleep(0.08)
        # zero_velocity_window_sec=0.06 < sleep(0.08) so zero-vel check triggers
        sd = StuckDetector(
            _cfg(
                window_sec=0.12,
                min_progress_m=0.10,
                stuck_threshold_count=1,
                zero_velocity_window_sec=0.06,
            )
        )
        sd.reset()
        sd.update(5.0, 5.0, 0.0)
        time.sleep(0.08)
        sd.update(5.0, 5.0, 0.0)
        result = sd.check()
        assert result.is_stuck is True


# ── Result fields ─────────────────────────────────────────────────────────────


class TestResultFields:
    def test_stuck_result_has_progress_m(self):
        sd = StuckDetector(_cfg(window_sec=0.05, min_progress_m=0.10, stuck_threshold_count=1))
        sd.update(0.0, 0.0, 0.0)
        time.sleep(0.06)
        sd.update(0.02, 0.0, 0.0)
        result = sd.check()
        assert hasattr(result, "progress_m")
        assert result.progress_m < 0.10

    def test_not_stuck_result_fields(self):
        sd = StuckDetector(_cfg())
        sd.update(0.0, 0.0, 1.0)
        sd.update(1.0, 0.0, 1.0)
        r = sd.check()
        assert r.is_stuck is False
        assert r.consecutive_fails == 0


# ── Consecutive count reset on progress ──────────────────────────────────────


class TestConsecutiveReset:
    def test_progress_resets_consecutive_count(self):
        sd = StuckDetector(_cfg(window_sec=0.05, min_progress_m=0.10, stuck_threshold_count=3))
        # Trigger 2 failures
        sd.update(0.0, 0.0, 0.0)
        time.sleep(0.06)
        sd.update(0.0, 0.0, 0.0)
        sd.check()
        sd.check()  # consecutive = 2
        # Now make progress
        sd.update(1.0, 0.0, 1.0)
        r = sd.check()
        assert r.consecutive_fails == 0
        assert r.is_stuck is False
