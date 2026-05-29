"""GestureLibrary — pre-defined expressive gesture keyframe sequences for BonBon.

Each gesture is a sequence of GestureKeyframes that specify which servos to move,
to what position, and at what velocity. The GestureLibrary is a static registry
looked up by gesture name at runtime.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# Servo IDs for BonBon robot
# ---------------------------------------------------------------------------
SERVO_HEAD_PAN       = 1   # Horizontal head rotation: -90° to +90° (center=0)
SERVO_HEAD_TILT      = 2   # Vertical head tilt: -30° down to +20° up (center=0)
SERVO_HEAD_ROLL      = 3   # Head roll: -15° to +15° (center=0)
SERVO_LEFT_SHOULDER  = 4   # Left arm shoulder: 0°–180°
SERVO_LEFT_ELBOW     = 5   # Left arm elbow: 0°–135°
SERVO_RIGHT_SHOULDER = 6   # Right arm shoulder: 0°–180°
SERVO_RIGHT_ELBOW    = 7   # Right arm elbow: 0°–135°

# Servo safe limits: servo_id -> (min_deg, max_deg)
SERVO_LIMITS: Dict[int, tuple] = {
    SERVO_HEAD_PAN:       (-90.0,  90.0),
    SERVO_HEAD_TILT:      (-30.0,  20.0),
    SERVO_HEAD_ROLL:      (-15.0,  15.0),
    SERVO_LEFT_SHOULDER:  (  0.0, 170.0),
    SERVO_LEFT_ELBOW:     (  0.0, 130.0),
    SERVO_RIGHT_SHOULDER: (  0.0, 170.0),
    SERVO_RIGHT_ELBOW:    (  0.0, 130.0),
}


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ServoTarget:
    """A single servo position target within a gesture keyframe."""

    servo_id: int
    position_deg: float
    velocity_dps: float = 30.0  # degrees per second


@dataclass
class GestureKeyframe:
    """A set of servo targets to reach at a given time offset into the gesture."""

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
    ServoTarget(SERVO_HEAD_PAN,       0.0, 20.0),
    ServoTarget(SERVO_HEAD_TILT,      0.0, 20.0),
    ServoTarget(SERVO_HEAD_ROLL,      0.0, 20.0),
    ServoTarget(SERVO_LEFT_SHOULDER,  10.0, 15.0),
    ServoTarget(SERVO_LEFT_ELBOW,     10.0, 15.0),
    ServoTarget(SERVO_RIGHT_SHOULDER, 10.0, 15.0),
    ServoTarget(SERVO_RIGHT_ELBOW,    10.0, 15.0),
]

LISTENING_POSE: List[ServoTarget] = [
    ServoTarget(SERVO_HEAD_PAN,       0.0, 25.0),
    ServoTarget(SERVO_HEAD_TILT,      5.0, 25.0),  # slight upward tilt = attentive
    ServoTarget(SERVO_HEAD_ROLL,      0.0, 25.0),
    ServoTarget(SERVO_LEFT_SHOULDER,  15.0, 15.0),
    ServoTarget(SERVO_LEFT_ELBOW,     15.0, 15.0),
    ServoTarget(SERVO_RIGHT_SHOULDER, 15.0, 15.0),
    ServoTarget(SERVO_RIGHT_ELBOW,    15.0, 15.0),
]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _make_gesture(
    name: str,
    description: str,
    keyframes: List[GestureKeyframe],
    interruptible: bool = True,
    requires_clear_space: bool = False,
) -> GestureDefinition:
    """Build a GestureDefinition, computing duration from the last keyframe."""
    duration = max(kf.time_offset_sec for kf in keyframes) if keyframes else 1.0
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
_register(_make_gesture(
    "rest_pose",
    "Neutral resting position with arms lowered",
    [GestureKeyframe(0.0, copy.copy(REST_POSE))],
    interruptible=True,
))

# listening_pose — attentive head tilt with arms relaxed
_register(_make_gesture(
    "listening_pose",
    "Attentive listening posture: slight upward head tilt",
    [GestureKeyframe(0.0, copy.copy(LISTENING_POSE))],
    interruptible=True,
))

# safe_folded_pose — compact pose safe for robot navigation
_register(_make_gesture(
    "safe_folded_pose",
    "Arms folded safely close to body for navigation",
    [
        GestureKeyframe(0.0, [
            ServoTarget(SERVO_HEAD_PAN,       0.0, 20.0),
            ServoTarget(SERVO_HEAD_TILT,     -5.0, 20.0),
            ServoTarget(SERVO_HEAD_ROLL,      0.0, 20.0),
            ServoTarget(SERVO_LEFT_SHOULDER,  5.0, 10.0),
            ServoTarget(SERVO_LEFT_ELBOW,     5.0, 10.0),
            ServoTarget(SERVO_RIGHT_SHOULDER, 5.0, 10.0),
            ServoTarget(SERVO_RIGHT_ELBOW,    5.0, 10.0),
        ]),
    ],
    interruptible=False,
))

# nod_yes — two-cycle vertical head nod
_register(_make_gesture(
    "nod_yes",
    "Nod head up and down twice to signal agreement",
    [
        GestureKeyframe(0.0,  [ServoTarget(SERVO_HEAD_TILT,  0.0, 60.0)]),
        GestureKeyframe(0.3,  [ServoTarget(SERVO_HEAD_TILT, 15.0, 80.0)]),
        GestureKeyframe(0.6,  [ServoTarget(SERVO_HEAD_TILT, -5.0, 80.0)]),
        GestureKeyframe(0.9,  [ServoTarget(SERVO_HEAD_TILT, 15.0, 80.0)]),
        GestureKeyframe(1.2,  [ServoTarget(SERVO_HEAD_TILT,  0.0, 60.0)]),
    ],
    interruptible=True,
))

# shake_no — two-cycle horizontal head shake
_register(_make_gesture(
    "shake_no",
    "Shake head left and right twice to signal disagreement",
    [
        GestureKeyframe(0.0,  [ServoTarget(SERVO_HEAD_PAN,   0.0,  80.0)]),
        GestureKeyframe(0.25, [ServoTarget(SERVO_HEAD_PAN, -25.0, 100.0)]),
        GestureKeyframe(0.5,  [ServoTarget(SERVO_HEAD_PAN,  25.0, 100.0)]),
        GestureKeyframe(0.75, [ServoTarget(SERVO_HEAD_PAN, -25.0, 100.0)]),
        GestureKeyframe(1.0,  [ServoTarget(SERVO_HEAD_PAN,   0.0,  80.0)]),
    ],
    interruptible=True,
))

# wave — right-arm wave to greet or attract attention
_register(_make_gesture(
    "wave",
    "Wave right arm twice to greet or attract attention",
    [
        GestureKeyframe(0.0, [
            ServoTarget(SERVO_RIGHT_SHOULDER, 90.0, 40.0),
            ServoTarget(SERVO_RIGHT_ELBOW,    45.0, 40.0),
        ]),
        GestureKeyframe(0.5,  [ServoTarget(SERVO_RIGHT_ELBOW, 90.0, 80.0)]),
        GestureKeyframe(0.9,  [ServoTarget(SERVO_RIGHT_ELBOW, 45.0, 80.0)]),
        GestureKeyframe(1.3,  [ServoTarget(SERVO_RIGHT_ELBOW, 90.0, 80.0)]),
        GestureKeyframe(1.7,  [ServoTarget(SERVO_RIGHT_ELBOW, 45.0, 80.0)]),
        GestureKeyframe(2.2, [
            ServoTarget(SERVO_RIGHT_SHOULDER, 10.0, 30.0),
            ServoTarget(SERVO_RIGHT_ELBOW,    10.0, 30.0),
        ]),
    ],
    interruptible=True,
    requires_clear_space=True,
))

# thinking_pose — head tilted to convey processing
_register(_make_gesture(
    "thinking_pose",
    "Head tilted slightly to signal active processing or thinking",
    [
        GestureKeyframe(0.0, [
            ServoTarget(SERVO_HEAD_TILT, 10.0, 20.0),
            ServoTarget(SERVO_HEAD_ROLL,  8.0, 20.0),
        ]),
    ],
    interruptible=True,
))

# greeting_pose — slight bow to acknowledge a person
_register(_make_gesture(
    "greeting_pose",
    "Friendly greeting with a slight bow of the head",
    [
        GestureKeyframe(0.0, [
            ServoTarget(SERVO_HEAD_PAN,  0.0, 25.0),
            ServoTarget(SERVO_HEAD_TILT, 0.0, 25.0),
        ]),
        GestureKeyframe(0.5, [ServoTarget(SERVO_HEAD_TILT, -15.0, 40.0)]),  # bow down
        GestureKeyframe(1.0, [ServoTarget(SERVO_HEAD_TILT,   5.0, 40.0)]),  # lift up
        GestureKeyframe(1.5, [ServoTarget(SERVO_HEAD_TILT,   0.0, 25.0)]),  # return
    ],
    interruptible=True,
))

# apology_pose — deeper bow held briefly
_register(_make_gesture(
    "apology_pose",
    "Apologetic bow: lower head, hold, return",
    [
        GestureKeyframe(0.0, [ServoTarget(SERVO_HEAD_TILT,   0.0, 20.0)]),
        GestureKeyframe(0.6, [ServoTarget(SERVO_HEAD_TILT, -20.0, 35.0)]),  # bow
        GestureKeyframe(1.8, [ServoTarget(SERVO_HEAD_TILT, -20.0,  5.0)]),  # hold
        GestureKeyframe(2.4, [ServoTarget(SERVO_HEAD_TILT,   0.0, 25.0)]),  # return
    ],
    interruptible=True,
))

# stop_gesture — raised palm STOP signal, not interruptible
_register(_make_gesture(
    "stop_gesture",
    "Raise right hand palm-forward to signal STOP",
    [
        GestureKeyframe(0.0, [
            ServoTarget(SERVO_RIGHT_SHOULDER, 90.0, 60.0),
            ServoTarget(SERVO_RIGHT_ELBOW,     0.0, 60.0),
        ]),
        GestureKeyframe(1.5, [  # hold
            ServoTarget(SERVO_RIGHT_SHOULDER, 90.0, 5.0),
            ServoTarget(SERVO_RIGHT_ELBOW,     0.0, 5.0),
        ]),
        GestureKeyframe(3.0, [
            ServoTarget(SERVO_RIGHT_SHOULDER, 10.0, 30.0),
            ServoTarget(SERVO_RIGHT_ELBOW,    10.0, 30.0),
        ]),
    ],
    interruptible=False,
    requires_clear_space=True,
))

# invite_gesture — beckoning motion to invite someone forward
_register(_make_gesture(
    "invite_gesture",
    "Beckoning forward gesture to invite a person to approach",
    [
        GestureKeyframe(0.0, [
            ServoTarget(SERVO_RIGHT_SHOULDER, 60.0, 30.0),
            ServoTarget(SERVO_RIGHT_ELBOW,    20.0, 30.0),
        ]),
        GestureKeyframe(0.7, [
            ServoTarget(SERVO_RIGHT_SHOULDER, 45.0, 40.0),
            ServoTarget(SERVO_RIGHT_ELBOW,    60.0, 40.0),
        ]),
        GestureKeyframe(1.4, [
            ServoTarget(SERVO_RIGHT_SHOULDER, 60.0, 30.0),
            ServoTarget(SERVO_RIGHT_ELBOW,    20.0, 30.0),
        ]),
        GestureKeyframe(2.1, [
            ServoTarget(SERVO_RIGHT_SHOULDER, 10.0, 20.0),
            ServoTarget(SERVO_RIGHT_ELBOW,    10.0, 20.0),
        ]),
    ],
    interruptible=True,
    requires_clear_space=True,
))

# point_left — extend left arm and head to point left
_register(_make_gesture(
    "point_left",
    "Point to the left with left arm extended",
    [
        GestureKeyframe(0.0, [
            ServoTarget(SERVO_HEAD_PAN,      -45.0, 40.0),
            ServoTarget(SERVO_LEFT_SHOULDER,  90.0, 40.0),
            ServoTarget(SERVO_LEFT_ELBOW,      0.0, 40.0),
        ]),
        GestureKeyframe(1.5, [  # hold while pointing
            ServoTarget(SERVO_HEAD_PAN, -45.0, 5.0),
        ]),
        GestureKeyframe(2.5, [
            ServoTarget(SERVO_HEAD_PAN,      0.0, 25.0),
            ServoTarget(SERVO_LEFT_SHOULDER, 10.0, 25.0),
            ServoTarget(SERVO_LEFT_ELBOW,    10.0, 25.0),
        ]),
    ],
    interruptible=True,
    requires_clear_space=True,
))

# point_right — extend right arm and head to point right
_register(_make_gesture(
    "point_right",
    "Point to the right with right arm extended",
    [
        GestureKeyframe(0.0, [
            ServoTarget(SERVO_HEAD_PAN,       45.0, 40.0),
            ServoTarget(SERVO_RIGHT_SHOULDER, 90.0, 40.0),
            ServoTarget(SERVO_RIGHT_ELBOW,     0.0, 40.0),
        ]),
        GestureKeyframe(1.5, [  # hold while pointing
            ServoTarget(SERVO_HEAD_PAN, 45.0, 5.0),
        ]),
        GestureKeyframe(2.5, [
            ServoTarget(SERVO_HEAD_PAN,       0.0, 25.0),
            ServoTarget(SERVO_RIGHT_SHOULDER, 10.0, 25.0),
            ServoTarget(SERVO_RIGHT_ELBOW,    10.0, 25.0),
        ]),
    ],
    interruptible=True,
    requires_clear_space=True,
))

# idle_scan — slow ambient head scan when idle
_register(_make_gesture(
    "idle_scan",
    "Slow ambient head scan left and right when idle",
    [
        GestureKeyframe(0.0, [ServoTarget(SERVO_HEAD_PAN,   0.0, 15.0)]),
        GestureKeyframe(2.0, [ServoTarget(SERVO_HEAD_PAN,  40.0, 20.0)]),
        GestureKeyframe(5.0, [ServoTarget(SERVO_HEAD_PAN, -40.0, 20.0)]),
        GestureKeyframe(8.0, [ServoTarget(SERVO_HEAD_PAN,   0.0, 15.0)]),
    ],
    interruptible=True,
))

# emergency_attention_pose — maximum-visibility emergency posture, not interruptible
_register(_make_gesture(
    "emergency_attention_pose",
    "High-visibility emergency posture: raised arm, upright head",
    [
        GestureKeyframe(0.0, [
            ServoTarget(SERVO_HEAD_PAN,        0.0, 100.0),
            ServoTarget(SERVO_HEAD_TILT,       10.0, 100.0),
            ServoTarget(SERVO_RIGHT_SHOULDER,  90.0,  80.0),
            ServoTarget(SERVO_RIGHT_ELBOW,      0.0,  80.0),
        ]),
    ],
    interruptible=False,
))


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
