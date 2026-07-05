"""GestureLibrary — pre-defined expressive gesture keyframe sequences for BonBon.

Each gesture is a sequence of GestureKeyframes that specify which joints to
move, to what position, and at what velocity. The GestureLibrary is a
static registry looked up by gesture name at runtime.

Joint topology (corrected against the real BOM -- see
docs/HARDWARE_SOFTWARE_GAP_REPORT.md and
Humanoid_Robot_Components_Dimensions.xls's "Hand Gestures & Head Pan"
sheet). The robot has a SINGLE right arm (no left arm) and a 2-DOF head
(pan + tilt, no roll) -- this replaces an earlier 7-servo symmetric
two-arm model that never matched the physical hardware:

  HEAD_PAN         NEMA17 closed-loop stepper
  HEAD_TILT        25kgcm PWM servo
  RIGHT_SHOULDER   NEMA17 closed-loop stepper
  RIGHT_ELBOW      25kgcm PWM servo
  RIGHT_WRIST      25kgcm PWM servo

Every joint ID below is unique across BOTH actuator buses (steppers and
servos each have their OWN independent local ID space on
bonbon_hal's stepper_node/servo_node) -- JOINT_ACTUATOR_TYPE and
JOINT_LOCAL_ID translate a gesture's global joint ID into the right
bonbon_hal topic + local ID at dispatch time (see actuation_node.py).
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# Joint IDs for BonBon robot (global, unique across steppers + servos)
# ---------------------------------------------------------------------------
JOINT_HEAD_PAN = 1  # stepper -- horizontal head rotation: -90 to +90 deg (center=0)
JOINT_HEAD_TILT = 2  # servo -- vertical head tilt: -30 down to +20 up deg (center=0)
JOINT_RIGHT_SHOULDER = 3  # stepper -- right arm shoulder: 0-170 deg
JOINT_RIGHT_ELBOW = 4  # servo -- right arm elbow: 0-130 deg
JOINT_RIGHT_WRIST = 5  # servo -- right arm wrist: -90 to +90 deg (center=0)

# Which physical bus each joint is actually driven from (bonbon_hal has a
# SEPARATE stepper_node and servo_node, each with its own local ID space --
# see bonbon_hal/nodes/stepper_node.py and servo_node.py).
JOINT_ACTUATOR_TYPE: Dict[int, str] = {
    JOINT_HEAD_PAN: "stepper",
    JOINT_HEAD_TILT: "servo",
    JOINT_RIGHT_SHOULDER: "stepper",
    JOINT_RIGHT_ELBOW: "servo",
    JOINT_RIGHT_WRIST: "servo",
}

# The joint's ID on ITS OWN bus (bonbon_hal/config/hal_params.yaml's
# stepper_node.stepper_ids=[1,2] and servo_node.servo_ids=[1,2,3] --
# kept in sync manually; both are small, human-reviewed tables).
JOINT_LOCAL_ID: Dict[int, int] = {
    JOINT_HEAD_PAN: 1,  # stepper_node stepper_id 1
    JOINT_RIGHT_SHOULDER: 2,  # stepper_node stepper_id 2
    JOINT_HEAD_TILT: 1,  # servo_node servo_id 1 (== primary_servo_id, the "neck" topic)
    JOINT_RIGHT_ELBOW: 2,  # servo_node servo_id 2 (arm topic)
    JOINT_RIGHT_WRIST: 3,  # servo_node servo_id 3 (arm topic)
}

# Joint safe limits: joint_id -> (min_deg, max_deg). Placeholders inherited
# from the pre-BOM design where plausible (head pan/tilt, right
# shoulder/elbow ranges) -- MUST be verified against the physical
# hardware's actual mechanical stops during Pi-3 bring-up, not assumed
# correct. Wrist range is a new estimate (no prior data existed for it).
JOINT_LIMITS: Dict[int, tuple] = {
    JOINT_HEAD_PAN: (-90.0, 90.0),
    JOINT_HEAD_TILT: (-30.0, 20.0),
    JOINT_RIGHT_SHOULDER: (0.0, 170.0),
    JOINT_RIGHT_ELBOW: (0.0, 130.0),
    JOINT_RIGHT_WRIST: (-90.0, 90.0),
}

# Backwards-compatible alias -- bonbon_actuation.core.servo_validator reads
# this name generically (it doesn't care whether an ID is a stepper or
# servo, only that it's a known joint with limits).
SERVO_LIMITS = JOINT_LIMITS


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class ServoTarget:
    """A single joint position target within a gesture keyframe. The name
    is kept for backward compatibility (servo_validator.py, motion_profile.py
    etc. all key off `.servo_id`) even though the target may resolve to a
    stepper joint -- see JOINT_ACTUATOR_TYPE."""

    servo_id: int
    position_deg: float
    velocity_dps: float = 30.0  # degrees per second


@dataclass
class GestureKeyframe:
    """A set of joint targets to reach at a given time offset into the gesture."""

    time_offset_sec: float
    targets: List[ServoTarget] = field(default_factory=list)


@dataclass
class GestureDefinition:
    """A complete gesture: a named sequence of keyframes with metadata."""

    name: str
    description: str
    keyframes: List[GestureKeyframe]
    duration_sec: float
    interruptible: bool = True
    requires_clear_space: bool = False  # True for gestures that sweep arm space


# ---------------------------------------------------------------------------
# Common pose constants (used as building blocks)
# ---------------------------------------------------------------------------

REST_POSE: List[ServoTarget] = [
    ServoTarget(JOINT_HEAD_PAN, 0.0, 20.0),
    ServoTarget(JOINT_HEAD_TILT, 0.0, 20.0),
    ServoTarget(JOINT_RIGHT_SHOULDER, 10.0, 15.0),
    ServoTarget(JOINT_RIGHT_ELBOW, 10.0, 15.0),
    ServoTarget(JOINT_RIGHT_WRIST, 0.0, 15.0),
]

LISTENING_POSE: List[ServoTarget] = [
    ServoTarget(JOINT_HEAD_PAN, 0.0, 25.0),
    ServoTarget(JOINT_HEAD_TILT, 5.0, 25.0),  # slight upward tilt = attentive
    ServoTarget(JOINT_RIGHT_SHOULDER, 15.0, 15.0),
    ServoTarget(JOINT_RIGHT_ELBOW, 15.0, 15.0),
    ServoTarget(JOINT_RIGHT_WRIST, 0.0, 15.0),
]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

# Minimum duration for a static single-keyframe pose. A pose still needs a
# non-zero settle time so the motion profile and status reporting behave
# sensibly (progress, ETA, completion).
_MIN_POSE_DURATION_SEC = 0.5


def _make_gesture(
    name: str,
    description: str,
    keyframes: List[GestureKeyframe],
    interruptible: bool = True,
    requires_clear_space: bool = False,
) -> GestureDefinition:
    """Build a GestureDefinition, computing duration from the last keyframe.

    Single-keyframe poses (whose last offset is 0.0) are given a minimum settle
    duration so they are never zero-length.
    """
    duration = max(kf.time_offset_sec for kf in keyframes) if keyframes else 1.0
    if duration <= 0.0:
        duration = _MIN_POSE_DURATION_SEC
    return GestureDefinition(
        name=name,
        description=description,
        keyframes=keyframes,
        duration_sec=duration,
        interruptible=interruptible,
        requires_clear_space=requires_clear_space,
    )


_LIBRARY: Dict[str, GestureDefinition] = {}


def _register(g: GestureDefinition) -> None:
    """Add a gesture definition to the module-level registry."""
    _LIBRARY[g.name] = g


# ---------------------------------------------------------------------------
# Gesture definitions
# ---------------------------------------------------------------------------

# rest_pose — neutral resting stance
_register(
    _make_gesture(
        "rest_pose",
        "Neutral resting position with arm lowered",
        [GestureKeyframe(0.0, copy.copy(REST_POSE))],
        interruptible=True,
    )
)

# listening_pose — attentive head tilt with arm relaxed
_register(
    _make_gesture(
        "listening_pose",
        "Attentive listening posture: slight upward head tilt",
        [GestureKeyframe(0.0, copy.copy(LISTENING_POSE))],
        interruptible=True,
    )
)

# safe_folded_pose — compact pose safe for robot navigation
_register(
    _make_gesture(
        "safe_folded_pose",
        "Arm folded safely close to body for navigation",
        [
            GestureKeyframe(
                0.0,
                [
                    ServoTarget(JOINT_HEAD_PAN, 0.0, 20.0),
                    ServoTarget(JOINT_HEAD_TILT, -5.0, 20.0),
                    ServoTarget(JOINT_RIGHT_SHOULDER, 5.0, 10.0),
                    ServoTarget(JOINT_RIGHT_ELBOW, 5.0, 10.0),
                    ServoTarget(JOINT_RIGHT_WRIST, 0.0, 10.0),
                ],
            ),
        ],
        interruptible=False,
    )
)

# nod_yes — two-cycle vertical head nod
_register(
    _make_gesture(
        "nod_yes",
        "Nod head up and down twice to signal agreement",
        [
            GestureKeyframe(0.0, [ServoTarget(JOINT_HEAD_TILT, 0.0, 60.0)]),
            GestureKeyframe(0.3, [ServoTarget(JOINT_HEAD_TILT, 15.0, 80.0)]),
            GestureKeyframe(0.6, [ServoTarget(JOINT_HEAD_TILT, -5.0, 80.0)]),
            GestureKeyframe(0.9, [ServoTarget(JOINT_HEAD_TILT, 15.0, 80.0)]),
            GestureKeyframe(1.2, [ServoTarget(JOINT_HEAD_TILT, 0.0, 60.0)]),
        ],
        interruptible=True,
    )
)

# shake_no — two-cycle horizontal head shake
_register(
    _make_gesture(
        "shake_no",
        "Shake head left and right twice to signal disagreement",
        [
            GestureKeyframe(0.0, [ServoTarget(JOINT_HEAD_PAN, 0.0, 80.0)]),
            GestureKeyframe(0.25, [ServoTarget(JOINT_HEAD_PAN, -25.0, 100.0)]),
            GestureKeyframe(0.5, [ServoTarget(JOINT_HEAD_PAN, 25.0, 100.0)]),
            GestureKeyframe(0.75, [ServoTarget(JOINT_HEAD_PAN, -25.0, 100.0)]),
            GestureKeyframe(1.0, [ServoTarget(JOINT_HEAD_PAN, 0.0, 80.0)]),
        ],
        interruptible=True,
    )
)

# wave — right-arm wave to greet or attract attention
_register(
    _make_gesture(
        "wave",
        "Wave right arm twice to greet or attract attention",
        [
            GestureKeyframe(
                0.0,
                [
                    ServoTarget(JOINT_RIGHT_SHOULDER, 90.0, 40.0),
                    ServoTarget(JOINT_RIGHT_ELBOW, 45.0, 40.0),
                    ServoTarget(JOINT_RIGHT_WRIST, 0.0, 40.0),
                ],
            ),
            GestureKeyframe(0.5, [ServoTarget(JOINT_RIGHT_ELBOW, 90.0, 80.0)]),
            GestureKeyframe(0.9, [ServoTarget(JOINT_RIGHT_ELBOW, 45.0, 80.0)]),
            GestureKeyframe(1.3, [ServoTarget(JOINT_RIGHT_ELBOW, 90.0, 80.0)]),
            GestureKeyframe(1.7, [ServoTarget(JOINT_RIGHT_ELBOW, 45.0, 80.0)]),
            GestureKeyframe(
                2.2,
                [
                    ServoTarget(JOINT_RIGHT_SHOULDER, 10.0, 30.0),
                    ServoTarget(JOINT_RIGHT_ELBOW, 10.0, 30.0),
                ],
            ),
        ],
        interruptible=True,
        requires_clear_space=True,
    )
)

# thinking_pose — head tilted to convey processing (head-roll removed --
# no roll hardware exists; approximated with tilt alone)
_register(
    _make_gesture(
        "thinking_pose",
        "Head tilted slightly to signal active processing or thinking",
        [
            GestureKeyframe(
                0.0,
                [ServoTarget(JOINT_HEAD_TILT, 12.0, 20.0)],
            ),
        ],
        interruptible=True,
    )
)

# greeting_pose — slight bow to acknowledge a person
_register(
    _make_gesture(
        "greeting_pose",
        "Friendly greeting with a slight bow of the head",
        [
            GestureKeyframe(
                0.0,
                [
                    ServoTarget(JOINT_HEAD_PAN, 0.0, 25.0),
                    ServoTarget(JOINT_HEAD_TILT, 0.0, 25.0),
                ],
            ),
            GestureKeyframe(0.5, [ServoTarget(JOINT_HEAD_TILT, -15.0, 40.0)]),  # bow down
            GestureKeyframe(1.0, [ServoTarget(JOINT_HEAD_TILT, 5.0, 40.0)]),  # lift up
            GestureKeyframe(1.5, [ServoTarget(JOINT_HEAD_TILT, 0.0, 25.0)]),  # return
        ],
        interruptible=True,
    )
)

# apology_pose — deeper bow held briefly
_register(
    _make_gesture(
        "apology_pose",
        "Apologetic bow: lower head, hold, return",
        [
            GestureKeyframe(0.0, [ServoTarget(JOINT_HEAD_TILT, 0.0, 20.0)]),
            GestureKeyframe(0.6, [ServoTarget(JOINT_HEAD_TILT, -20.0, 35.0)]),  # bow
            GestureKeyframe(1.8, [ServoTarget(JOINT_HEAD_TILT, -20.0, 5.0)]),  # hold
            GestureKeyframe(2.4, [ServoTarget(JOINT_HEAD_TILT, 0.0, 25.0)]),  # return
        ],
        interruptible=True,
    )
)

# stop_gesture — raised palm STOP signal, not interruptible
_register(
    _make_gesture(
        "stop_gesture",
        "Raise right hand palm-forward to signal STOP",
        [
            GestureKeyframe(
                0.0,
                [
                    ServoTarget(JOINT_RIGHT_SHOULDER, 90.0, 60.0),
                    ServoTarget(JOINT_RIGHT_ELBOW, 0.0, 60.0),
                    ServoTarget(JOINT_RIGHT_WRIST, 0.0, 60.0),
                ],
            ),
            GestureKeyframe(
                1.5,
                [  # hold
                    ServoTarget(JOINT_RIGHT_SHOULDER, 90.0, 5.0),
                    ServoTarget(JOINT_RIGHT_ELBOW, 0.0, 5.0),
                ],
            ),
            GestureKeyframe(
                3.0,
                [
                    ServoTarget(JOINT_RIGHT_SHOULDER, 10.0, 30.0),
                    ServoTarget(JOINT_RIGHT_ELBOW, 10.0, 30.0),
                ],
            ),
        ],
        interruptible=False,
        requires_clear_space=True,
    )
)

# invite_gesture — beckoning motion to invite someone forward
_register(
    _make_gesture(
        "invite_gesture",
        "Beckoning forward gesture to invite a person to approach",
        [
            GestureKeyframe(
                0.0,
                [
                    ServoTarget(JOINT_RIGHT_SHOULDER, 60.0, 30.0),
                    ServoTarget(JOINT_RIGHT_ELBOW, 20.0, 30.0),
                ],
            ),
            GestureKeyframe(
                0.7,
                [
                    ServoTarget(JOINT_RIGHT_SHOULDER, 45.0, 40.0),
                    ServoTarget(JOINT_RIGHT_ELBOW, 60.0, 40.0),
                ],
            ),
            GestureKeyframe(
                1.4,
                [
                    ServoTarget(JOINT_RIGHT_SHOULDER, 60.0, 30.0),
                    ServoTarget(JOINT_RIGHT_ELBOW, 20.0, 30.0),
                ],
            ),
            GestureKeyframe(
                2.1,
                [
                    ServoTarget(JOINT_RIGHT_SHOULDER, 10.0, 20.0),
                    ServoTarget(JOINT_RIGHT_ELBOW, 10.0, 20.0),
                ],
            ),
        ],
        interruptible=True,
        requires_clear_space=True,
    )
)

# point_left — no left arm exists on this robot; approximated as a
# head-pan-only "look/gesture left" cue rather than an arm point. Gesture
# NAME kept for caller compatibility (behavior code may already reference
# it by string name); the PHYSICAL realization is honestly limited to
# what the real hardware can do.
_register(
    _make_gesture(
        "point_left",
        "Approximate left-indication using head pan only (no left arm exists)",
        [
            GestureKeyframe(0.0, [ServoTarget(JOINT_HEAD_PAN, -45.0, 40.0)]),
            GestureKeyframe(1.5, [ServoTarget(JOINT_HEAD_PAN, -45.0, 5.0)]),  # hold
            GestureKeyframe(2.5, [ServoTarget(JOINT_HEAD_PAN, 0.0, 25.0)]),
        ],
        interruptible=True,
        requires_clear_space=False,
    )
)

# point_right — extend right arm and head to point right
_register(
    _make_gesture(
        "point_right",
        "Point to the right with right arm extended",
        [
            GestureKeyframe(
                0.0,
                [
                    ServoTarget(JOINT_HEAD_PAN, 45.0, 40.0),
                    ServoTarget(JOINT_RIGHT_SHOULDER, 90.0, 40.0),
                    ServoTarget(JOINT_RIGHT_ELBOW, 0.0, 40.0),
                ],
            ),
            GestureKeyframe(
                1.5,
                [  # hold while pointing
                    ServoTarget(JOINT_HEAD_PAN, 45.0, 5.0),
                ],
            ),
            GestureKeyframe(
                2.5,
                [
                    ServoTarget(JOINT_HEAD_PAN, 0.0, 25.0),
                    ServoTarget(JOINT_RIGHT_SHOULDER, 10.0, 25.0),
                    ServoTarget(JOINT_RIGHT_ELBOW, 10.0, 25.0),
                ],
            ),
        ],
        interruptible=True,
        requires_clear_space=True,
    )
)

# idle_scan — slow ambient head scan when idle
_register(
    _make_gesture(
        "idle_scan",
        "Slow ambient head scan left and right when idle",
        [
            GestureKeyframe(0.0, [ServoTarget(JOINT_HEAD_PAN, 0.0, 15.0)]),
            GestureKeyframe(2.0, [ServoTarget(JOINT_HEAD_PAN, 40.0, 20.0)]),
            GestureKeyframe(5.0, [ServoTarget(JOINT_HEAD_PAN, -40.0, 20.0)]),
            GestureKeyframe(8.0, [ServoTarget(JOINT_HEAD_PAN, 0.0, 15.0)]),
        ],
        interruptible=True,
    )
)

# emergency_attention_pose — maximum-visibility emergency posture, not interruptible
_register(
    _make_gesture(
        "emergency_attention_pose",
        "High-visibility emergency posture: raised arm, upright head",
        [
            GestureKeyframe(
                0.0,
                [
                    ServoTarget(JOINT_HEAD_PAN, 0.0, 100.0),
                    ServoTarget(JOINT_HEAD_TILT, 10.0, 100.0),
                    ServoTarget(JOINT_RIGHT_SHOULDER, 90.0, 80.0),
                    ServoTarget(JOINT_RIGHT_ELBOW, 0.0, 80.0),
                ],
            ),
        ],
        interruptible=False,
    )
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class GestureLibrary:
    """Read-only registry of all available BonBon gesture definitions."""

    @staticmethod
    def get(name: str) -> Optional[GestureDefinition]:
        """Return the GestureDefinition for *name*, or None if not found."""
        return _LIBRARY.get(name)

    @staticmethod
    def list_names() -> List[str]:
        """Return a list of all registered gesture names."""
        return list(_LIBRARY.keys())

    @staticmethod
    def has(name: str) -> bool:
        """Return True if *name* is a registered gesture."""
        return name in _LIBRARY
