"""OdometryIntegrator — standard differential-drive dead-reckoning: turns
CUMULATIVE left/right wheel distance readings (as reported by
bonbon_hal's MotorDriver.read_wheels(), open-loop-estimated for the real
Cytron driver until confirmed encoders exist -- see that driver's
docstring) into a 2D pose estimate for Nav2's odometry input.

This is dead reckoning, not ground truth -- error accumulates over time
and compounds with the open-loop wheel-speed estimate's own error. It is
still strictly better than no odometry at all (Nav2 needs SOME pose
estimate to plan against), and the DegradedModeStatus / SafetyState
machinery elsewhere in this repo already treats "some capability
degraded" as a first-class, honestly-reported state rather than a fake
PASS -- this integrator does not itself claim more precision than it has.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from bonbon_base_controller.core.diff_drive_kinematics import DiffDriveConfig


@dataclass(frozen=True)
class Pose2D:
    x_m: float = 0.0
    y_m: float = 0.0
    theta_rad: float = 0.0


@dataclass(frozen=True)
class OdometryEstimate:
    pose: Pose2D
    linear_velocity_mps: float
    angular_velocity_rps: float


class OdometryIntegrator:
    def __init__(self, config: DiffDriveConfig | None = None) -> None:
        self._cfg = config or DiffDriveConfig()
        self._pose = Pose2D()
        self._prev_left_m: float | None = None
        self._prev_right_m: float | None = None

    @property
    def pose(self) -> Pose2D:
        return self._pose

    def reset(self) -> None:
        self._pose = Pose2D()
        self._prev_left_m = None
        self._prev_right_m = None

    def integrate(self, left_distance_m: float, right_distance_m: float) -> OdometryEstimate:
        """Feed the LATEST cumulative distance readings. The first call
        after construction or reset() establishes the baseline (zero
        motion, since there is no prior reading to diff against) rather
        than misinterpreting an absolute encoder value as a delta."""
        if self._prev_left_m is None or self._prev_right_m is None:
            self._prev_left_m = left_distance_m
            self._prev_right_m = right_distance_m
            return OdometryEstimate(self._pose, 0.0, 0.0)

        d_left = left_distance_m - self._prev_left_m
        d_right = right_distance_m - self._prev_right_m
        self._prev_left_m = left_distance_m
        self._prev_right_m = right_distance_m

        d_center = (d_left + d_right) / 2.0
        d_theta = (d_right - d_left) / self._cfg.wheel_base_m

        # Mid-point (2nd-order) integration: use the heading halfway
        # through this step, not the heading at the start of it -- more
        # accurate than naive Euler integration for the same wheel data,
        # at zero extra cost.
        mid_theta = self._pose.theta_rad + d_theta / 2.0
        new_pose = Pose2D(
            x_m=self._pose.x_m + d_center * math.cos(mid_theta),
            y_m=self._pose.y_m + d_center * math.sin(mid_theta),
            theta_rad=_wrap_angle(self._pose.theta_rad + d_theta),
        )
        self._pose = new_pose
        return OdometryEstimate(
            pose=new_pose, linear_velocity_mps=d_center, angular_velocity_rps=d_theta
        )


def _wrap_angle(theta_rad: float) -> float:
    return math.atan2(math.sin(theta_rad), math.cos(theta_rad))
