"""MotionProfileGenerator — converts gesture keyframes into timed motion steps.

The generator does **not** sub-sample or interpolate between keyframes: the
robot's servo controllers handle in-hardware interpolation.  It simply scales
the keyframe timestamps by the requested speed factor and adjusts servo
velocities proportionally.

Speed scale ``s`` maps raw gesture times linearly::

    step.elapsed_sec = keyframe.time_offset_sec / clamp(s, 0.1, 2.0)

Progress [0, 1] is computed relative to the final keyframe timestamp.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List

from bonbon_actuation.core.gesture_library import (
    GestureDefinition,
    GestureKeyframe,
    ServoTarget,
)

_logger = logging.getLogger(__name__)

_MIN_SPEED: float = 0.1
_MAX_SPEED: float = 2.0


@dataclass
class MotionStep:
    """A single scheduled step in a gesture execution sequence.

    Attributes:
        elapsed_sec: When (relative to gesture start) this step should fire.
        targets: Servo targets to send at this step.
        progress: Completion fraction [0.0, 1.0] at this step.
    """

    elapsed_sec: float
    targets: List[ServoTarget]
    progress: float


class MotionProfileGenerator:
    """Convert a :class:`~bonbon_actuation.core.gesture_library.GestureDefinition`
    into a flat list of :class:`MotionStep` objects ready for sequential dispatch.

    Usage::

        gen = MotionProfileGenerator()
        steps = gen.generate_steps(gesture, speed_scale=1.0)
        for step in steps:
            time.sleep(step.elapsed_sec - prev_elapsed)
            publish(step.targets)
    """

    def generate_steps(
        self,
        gesture: GestureDefinition,
        speed_scale: float = 1.0,
    ) -> List[MotionStep]:
        """Build the execution plan for *gesture* at the given *speed_scale*.

        Args:
            gesture: The gesture definition to expand.
            speed_scale: Execution speed relative to the canonical definition.
                         Clamped to ``[0.1, 2.0]``.

        Returns:
            Ordered list of :class:`MotionStep` objects (one per keyframe).
        """
        speed = max(_MIN_SPEED, min(_MAX_SPEED, speed_scale))

        if not gesture.keyframes:
            _logger.warning("Gesture '%s' has no keyframes.", gesture.name)
            return []

        total_raw_duration = max(kf.time_offset_sec for kf in gesture.keyframes)
        total_scaled_duration = total_raw_duration / speed

        steps: List[MotionStep] = []

        for kf in gesture.keyframes:
            scaled_time = kf.time_offset_sec / speed

            progress = (
                scaled_time / total_scaled_duration
                if total_scaled_duration > 1e-6
                else 1.0
            )

            # Scale servo velocities proportionally to maintain natural motion.
            scaled_targets = [
                ServoTarget(
                    servo_id=t.servo_id,
                    position_deg=t.position_deg,
                    velocity_dps=t.velocity_dps * speed,
                )
                for t in kf.targets
            ]

            steps.append(
                MotionStep(
                    elapsed_sec=scaled_time,
                    targets=scaled_targets,
                    progress=min(1.0, progress),
                )
            )

        _logger.debug(
            "Generated %d steps for gesture '%s' at %.2fx speed "
            "(total=%.2fs).",
            len(steps),
            gesture.name,
            speed,
            total_scaled_duration,
        )
        return steps
