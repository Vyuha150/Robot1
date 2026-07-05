"""Tests for StepConverter and StallFaultTracker -- the pure-Python core
of the NEMA17 closed-loop stepper driver."""

from __future__ import annotations

import math

import pytest
from bonbon_hal.drivers.stepper.stepper_kinematics import (
    StallFaultConfig,
    StallFaultTracker,
    StepConverter,
    StepConverterConfig,
)


class TestStepConverterConfig:
    def test_rejects_nonpositive_steps_per_rev(self):
        with pytest.raises(ValueError):
            StepConverterConfig(steps_per_rev=0)

    def test_rejects_nonpositive_microstepping(self):
        with pytest.raises(ValueError):
            StepConverterConfig(microstepping=0)


class TestStepConverter:
    def setup_method(self):
        # 200 full steps/rev * 8 microsteps = 1600 microsteps/rev
        self.conv = StepConverter(StepConverterConfig(steps_per_rev=200, microstepping=8))

    def test_full_revolution_is_steps_per_rev_times_microstepping(self):
        steps = self.conv.radians_to_steps(2 * math.pi)
        assert steps == 1600

    def test_half_revolution(self):
        steps = self.conv.radians_to_steps(math.pi)
        assert steps == 800

    def test_zero_radians_is_zero_steps(self):
        assert self.conv.radians_to_steps(0.0) == 0

    def test_negative_radians_negative_steps(self):
        steps = self.conv.radians_to_steps(-math.pi)
        assert steps == -800

    def test_steps_to_radians_roundtrip(self):
        original = 1.2345
        steps = self.conv.radians_to_steps(original)
        recovered = self.conv.steps_to_radians(steps)
        # Rounding to the nearest integer step bounds the error to half a
        # step's worth of radians (1600 microsteps/rev here).
        half_step_rad = math.pi / 1600
        assert recovered == pytest.approx(original, abs=half_step_rad)

    def test_step_delta_forward_motion(self):
        delta = self.conv.step_delta(current_rad=0.0, target_rad=math.pi)
        assert delta == 800

    def test_step_delta_reverse_motion(self):
        delta = self.conv.step_delta(current_rad=math.pi, target_rad=0.0)
        assert delta == -800

    def test_step_delta_no_motion_is_zero(self):
        assert self.conv.step_delta(current_rad=1.0, target_rad=1.0) == 0

    def test_higher_microstepping_gives_finer_resolution(self):
        coarse = StepConverter(StepConverterConfig(steps_per_rev=200, microstepping=1))
        fine = StepConverter(StepConverterConfig(steps_per_rev=200, microstepping=16))
        small_angle = 0.001
        assert fine.radians_to_steps(small_angle) >= coarse.radians_to_steps(small_angle)


class TestStallFaultConfig:
    def test_rejects_nonpositive_confirm_polls(self):
        with pytest.raises(ValueError):
            StallFaultConfig(confirm_after_n_polls=0)

    def test_rejects_nonpositive_clear_polls(self):
        with pytest.raises(ValueError):
            StallFaultConfig(clear_after_n_polls=0)


class TestStallFaultTracker:
    def setup_method(self):
        self.tracker = StallFaultTracker(
            StallFaultConfig(confirm_after_n_polls=3, clear_after_n_polls=3)
        )

    def test_initial_state_is_healthy(self):
        assert self.tracker.is_stalled is False
        assert self.tracker.lost_sync is False

    def test_single_alarm_read_does_not_confirm_stall(self):
        self.tracker.poll(alarm_asserted=True)
        assert self.tracker.is_stalled is False
        assert self.tracker.lost_sync is False

    def test_two_of_three_required_reads_does_not_confirm(self):
        self.tracker.poll(True)
        self.tracker.poll(True)
        assert self.tracker.is_stalled is False

    def test_three_consecutive_alarm_reads_confirms_stall(self):
        for _ in range(3):
            self.tracker.poll(True)
        assert self.tracker.is_stalled is True
        assert self.tracker.lost_sync is True

    def test_intermittent_alarm_reads_never_confirm(self):
        # alternating true/false never reaches 3 consecutive
        for _ in range(10):
            self.tracker.poll(True)
            self.tracker.poll(False)
        assert self.tracker.is_stalled is False

    def test_lost_sync_stays_latched_after_alarm_clears(self):
        for _ in range(3):
            self.tracker.poll(True)
        assert self.tracker.lost_sync is True
        self.tracker.poll(False)
        # alarm reading clear now, but lost_sync must still be latched --
        # a real closed-loop driver's fault output doesn't self-clear.
        assert self.tracker.lost_sync is True
        assert self.tracker.is_stalled is False  # no longer CURRENTLY asserted

    def test_clear_stall_refuses_before_enough_clear_polls(self):
        for _ in range(3):
            self.tracker.poll(True)
        self.tracker.poll(False)
        self.tracker.poll(False)  # only 2 of 3 required clear polls
        assert self.tracker.clear_stall() is False
        assert self.tracker.lost_sync is True

    def test_clear_stall_succeeds_after_enough_clear_polls(self):
        for _ in range(3):
            self.tracker.poll(True)
        for _ in range(3):
            self.tracker.poll(False)
        assert self.tracker.can_clear is True
        assert self.tracker.clear_stall() is True
        assert self.tracker.lost_sync is False

    def test_clear_stall_is_noop_when_never_stalled(self):
        for _ in range(5):
            self.tracker.poll(False)
        assert self.tracker.clear_stall() is True
        assert self.tracker.lost_sync is False

    def test_new_alarm_after_clear_can_confirm_again(self):
        for _ in range(3):
            self.tracker.poll(True)
        for _ in range(3):
            self.tracker.poll(False)
        self.tracker.clear_stall()
        for _ in range(3):
            self.tracker.poll(True)
        assert self.tracker.lost_sync is True


if __name__ == "__main__":
    pytest.main([__file__])
