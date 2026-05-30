"""Integration tests for the bonbon_actuation core pipeline.

These exercise the full decision/execution chain that the ActuationNode wires
together — MotionQueue, ProximityGovernor, GestureLibrary, MotionProfileGenerator
and ServoValidator — without requiring rclpy. They verify that a gesture request
flows correctly from admission through to safe, clamped servo targets, and that
the safety derates actually take effect end-to-end.
"""

from __future__ import annotations

from bonbon_actuation.core.gesture_library import SERVO_LIMITS, GestureLibrary
from bonbon_actuation.core.motion_profile import MotionProfileGenerator
from bonbon_actuation.core.motion_queue import MotionQueue
from bonbon_actuation.core.proximity_governor import ProximityGovernor
from bonbon_actuation.core.servo_validator import ServoValidator


class TestGesturePipeline:
    """A named gesture must expand to validated, in-limit servo commands."""

    def test_wave_expands_to_valid_servo_targets(self):
        gesture = GestureLibrary.get("wave")
        assert gesture is not None

        gen = MotionProfileGenerator()
        validator = ServoValidator()
        steps = gen.generate_steps(gesture, speed_scale=1.0)
        assert steps, "wave should produce motion steps"

        for step in steps:
            result = validator.validate(step.targets)
            assert result.valid
            for tgt in result.clamped_targets:
                lo, hi = SERVO_LIMITS[tgt.servo_id]
                assert lo <= tgt.position_deg <= hi

    def test_all_library_gestures_validate(self):
        gen = MotionProfileGenerator()
        validator = ServoValidator()
        for name in GestureLibrary.list_names():
            gesture = GestureLibrary.get(name)
            for step in gen.generate_steps(gesture, speed_scale=1.0):
                result = validator.validate(step.targets)
                assert result.valid, f"{name} produced invalid targets: {result.errors}"


class TestProximityDeratesPipeline:
    """Proximity governor must slow the effective motion profile near people."""

    def test_near_person_reduces_step_velocity(self):
        gesture = GestureLibrary.get("nod_yes")
        gen = MotionProfileGenerator()
        gov = ProximityGovernor()

        # Far away → full speed reference.
        gov.clear_proximity()
        far = gov.evaluate(requested_priority=5)
        far_steps = gen.generate_steps(gesture, speed_scale=1.0 * far.speed_scale)

        # Person in caution band → derated.
        gov.update_proximity(1.5, "adult")
        near = gov.evaluate(requested_priority=5)
        near_steps = gen.generate_steps(gesture, speed_scale=1.0 * near.speed_scale)

        assert near.speed_scale < far.speed_scale
        # Derated profile takes at least as long to complete.
        assert near_steps[-1].elapsed_sec >= far_steps[-1].elapsed_sec

    def test_clear_space_gesture_blocked_close_to_child(self):
        gov = ProximityGovernor()
        gov.update_proximity(0.3, "child")
        decision = gov.evaluate(requested_priority=5)
        wave = GestureLibrary.get("wave")
        # wave sweeps an arm → requires clear space → must be suppressed.
        assert wave.requires_clear_space is True
        assert decision.block_large_motion is True


class TestQueuePreemption:
    """Queue + library priorities must serialise gestures correctly."""

    def test_emergency_jumps_ahead_of_idle(self):
        q = MotionQueue()
        q.enqueue("idle_scan", priority=0, event_id="idle")
        q.enqueue("nod_yes", priority=5, event_id="nod")
        q.enqueue("emergency_attention_pose", priority=20, event_id="emerg")
        order = [q.dequeue().event_id for _ in range(3)]
        assert order == ["emerg", "nod", "idle"]

    def test_preempt_decision_matches_priority(self):
        q = MotionQueue(preempt_threshold=10)
        q.enqueue("stop_gesture", priority=20, event_id="stop")
        # While running a normal-priority gesture, the emergency must preempt.
        assert q.should_preempt(running_priority=5) is True
