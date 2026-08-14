"""bonbon_hardware_telemetry.core.joint_metrics -- confirms stepper
lost_sync (error_code==1) fires a real ERROR trigger, PCA9685 servos
(whose error_code is always 0, no feedback sensor) never do, and
torque_enabled toggling is exposed as metrics but never auto-forwarded
as a fault (gesture/safety logic disables it deliberately elsewhere)."""

from __future__ import annotations

import unittest

from bonbon_hardware_telemetry.core.joint_metrics import (
    JointReading,
    compute_joint_group_metrics,
    joint_group_triggers,
)
from bonbon_hardware_telemetry.core.threshold_config import ThresholdConfig


def _stepper(servo_id: int, error_code: int = 0, torque_enabled: bool = True) -> JointReading:
    return JointReading(
        servo_id=servo_id,
        position_rad=0.0,
        velocity_rads=0.0,
        load_percent=0.0,
        temperature_c=0.0,
        voltage_v=0.0,
        error_code=error_code,
        torque_enabled=torque_enabled,
    )


def _servo(servo_id: int, torque_enabled: bool = True) -> JointReading:
    nan = float("nan")
    return JointReading(
        servo_id=servo_id,
        position_rad=1.0,
        velocity_rads=nan,
        load_percent=nan,
        temperature_c=nan,
        voltage_v=nan,
        error_code=0,
        torque_enabled=torque_enabled,
    )


class TestStepperJoints(unittest.TestCase):
    def setUp(self):
        self.thresholds = ThresholdConfig.defaults()

    def test_healthy_steppers_have_no_triggers(self):
        group = compute_joint_group_metrics(
            [_stepper(1), _stepper(2)], is_stepper=True, age_sec=0.05, thresholds=self.thresholds
        )
        self.assertFalse(any(j.lost_sync for j in group.joints))
        self.assertEqual(joint_group_triggers(group, "/bonbon/stepper/state"), [])

    def test_lost_sync_fires_error_trigger_named_by_joint(self):
        group = compute_joint_group_metrics(
            [_stepper(1), _stepper(2, error_code=1)],
            is_stepper=True,
            age_sec=0.05,
            thresholds=self.thresholds,
        )
        triggers = joint_group_triggers(group, "/bonbon/stepper/state")
        self.assertEqual(len(triggers), 1)
        self.assertEqual(triggers[0].code, "STEPPER_LOST_SYNC")
        self.assertIn("right_shoulder", triggers[0].message)
        # Must match bonbon_hal.nodes.stepper_node.StepperNode.DEVICE_NAME
        # exactly -- component_rules.DEVICE_INFO keys "stepper" and
        # "servo" as distinct categories.
        self.assertEqual(triggers[0].device, "stepper")

    def test_joint_names_match_gesture_library_topology(self):
        group = compute_joint_group_metrics(
            [_stepper(1), _stepper(2)], is_stepper=True, age_sec=0.05, thresholds=self.thresholds
        )
        names = {j.servo_id: j.joint_name for j in group.joints}
        self.assertEqual(names, {1: "head_pan", 2: "right_shoulder"})


class TestPca9685Servos(unittest.TestCase):
    def setUp(self):
        self.thresholds = ThresholdConfig.defaults()

    def test_servo_error_code_never_produces_a_trigger(self):
        # error_code is hardwired to 0 by PCA9685ServoDriver -- confirms
        # is_stepper=False suppresses lost_sync interpretation entirely.
        group = compute_joint_group_metrics(
            [_servo(1), _servo(2), _servo(3)],
            is_stepper=False,
            age_sec=0.05,
            thresholds=self.thresholds,
        )
        self.assertFalse(any(j.lost_sync for j in group.joints))
        self.assertEqual(joint_group_triggers(group, "/bonbon/servo/arm/state"), [])

    def test_torque_disabled_is_metrics_only_not_a_trigger(self):
        group = compute_joint_group_metrics(
            [_servo(2, torque_enabled=False)],
            is_stepper=False,
            age_sec=0.05,
            thresholds=self.thresholds,
        )
        self.assertFalse(group.joints[0].torque_enabled)
        self.assertEqual(joint_group_triggers(group, "/bonbon/servo/arm/state"), [])

    def test_stale_topic_fires_one_warn_trigger(self):
        stale_age = self.thresholds.liveness.stale_after_sec + 1.0
        group = compute_joint_group_metrics(
            [_servo(1)], is_stepper=False, age_sec=stale_age, thresholds=self.thresholds
        )
        triggers = joint_group_triggers(group, "/bonbon/servo/neck/state")
        self.assertEqual(len(triggers), 1)
        self.assertEqual(triggers[0].code, "JOINT_STATE_STALE")
        self.assertEqual(triggers[0].device, "servo")


if __name__ == "__main__":
    unittest.main()
