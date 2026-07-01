"""DiffDriveKinematics — converts between a robot-frame Twist
(linear.x, angular.z) and per-wheel speeds for a differential-drive base
(Rhino 24V wheel motors via the Cytron MDDS30, see bonbon_hal's
motor_node/CytronMDDS30Driver).

wheel_base_m is the distance between the two wheel contact points --
NOT yet measured on the physical robot as of this session; the default
below is a placeholder that MUST be corrected during Pi-3 hardware
bring-up (see docs/HARDWARE_SOFTWARE_GAP_REPORT.md). Getting this wrong
doesn't just cost precision, it makes commanded turns physically wrong
in both this direction (Twist -> wheel speeds) and the reverse
(wheel speeds -> odometry).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DiffDriveConfig:
    wheel_base_m: float = 0.40  # PLACEHOLDER — verify against physical robot
    max_wheel_speed_mps: float = 1.0

    def __post_init__(self) -> None:
        if self.wheel_base_m <= 0:
            raise ValueError("wheel_base_m must be > 0")
        if self.max_wheel_speed_mps <= 0:
            raise ValueError("max_wheel_speed_mps must be > 0")


@dataclass(frozen=True)
class WheelSpeeds:
    left_mps: float
    right_mps: float


@dataclass(frozen=True)
class Twist2D:
    linear_x_mps: float
    angular_z_rps: float


class DiffDriveKinematics:
    def __init__(self, config: DiffDriveConfig | None = None) -> None:
        self._cfg = config or DiffDriveConfig()

    @property
    def config(self) -> DiffDriveConfig:
        return self._cfg

    def twist_to_wheel_speeds(self, twist: Twist2D) -> WheelSpeeds:
        half_base = self._cfg.wheel_base_m / 2.0
        left = twist.linear_x_mps - twist.angular_z_rps * half_base
        right = twist.linear_x_mps + twist.angular_z_rps * half_base

        # If either wheel exceeds the physical max, scale BOTH down by the
        # same factor rather than independently clamping each -- clamping
        # only the faster wheel would silently distort the commanded
        # turning radius (e.g. a tight in-place turn could become a wide
        # arc), which is worse than a slightly slower version of the same
        # requested motion.
        max_abs = max(abs(left), abs(right))
        if max_abs > self._cfg.max_wheel_speed_mps and max_abs > 0:
            scale = self._cfg.max_wheel_speed_mps / max_abs
            left *= scale
            right *= scale

        return WheelSpeeds(left_mps=left, right_mps=right)

    def wheel_speeds_to_twist(self, wheels: WheelSpeeds) -> Twist2D:
        linear_x = (wheels.left_mps + wheels.right_mps) / 2.0
        angular_z = (wheels.right_mps - wheels.left_mps) / self._cfg.wheel_base_m
        return Twist2D(linear_x_mps=linear_x, angular_z_rps=angular_z)
