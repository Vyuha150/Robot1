"""Reusable test-kit for BonBon real-world scenario tests.

Provides deterministic, hardware-free builders for the signals the AI/safety
cores consume — tracked people, hand landmarks, sensor snapshots (with injected
faults) — plus assertion helpers tied to the fallback-level model and the
failure catalogue. This is the shared fixture layer the scenario suite (and any
future behavioural test) builds on, so no scenario re-invents signal fakes.

Everything is pure Python with no ROS2/hardware dependency. Use a fixed seed
(``seed()``) for reproducibility.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import List, Tuple

from bonbon_safety.core.fault_levels import FallbackLevel

# Deterministic seed for any randomised builder.
DEFAULT_SEED = 1337


def seed(value: int = DEFAULT_SEED) -> None:
    """Seed the module RNG so scenario inputs are reproducible."""
    random.seed(value)


# ── Person / entity signal ────────────────────────────────────────────────────

@dataclass
class Person:
    """A tracked person in robot-frame coordinates, consumed by spatial cores."""

    entity_id: str = "p1"
    person_id: str = "p1"
    x: float = 2.0
    y: float = 0.0
    vx: float = 0.0
    vy: float = 0.0
    entity_type: str = "person"
    person_category: str = "adult"   # adult|child|elderly|wheelchair|staff
    is_approaching_robot: bool = False
    is_moving_away: bool = False
    approach_speed_mps: float = 0.0

    @property
    def distance_to_robot(self) -> float:
        return math.hypot(self.x, self.y)


def person(distance_m: float = 2.0, *, category: str = "adult",
           approaching: bool = False, lateral_m: float = 0.0,
           entity_id: str = "p1") -> Person:
    """Build a Person at ``distance_m`` ahead (optionally approaching)."""
    vx = -0.6 if approaching else 0.0
    return Person(
        entity_id=entity_id, person_id=entity_id,
        x=distance_m, y=lateral_m, vx=vx,
        person_category=category, is_approaching_robot=approaching,
        approach_speed_mps=0.6 if approaching else 0.0,
    )


# ── Hand-landmark builders (21-pt, image coords) ──────────────────────────────

def _fist(cx=320.0, cy=240.0) -> List[Tuple[float, float, float]]:
    pts = []
    for i in range(21):
        ang = (i / 21) * 2 * math.pi
        r = 10 + (i % 4) * 3
        pts.append((cx + r * math.cos(ang), cy + r * math.sin(ang), 0.0))
    for tip, pip in [(8, 6), (12, 10), (16, 14), (20, 18)]:
        pts[tip] = (pts[tip][0], pts[pip][1] + 15, 0.0)
    return pts


def hand(gesture: str, cx=320.0, cy=240.0) -> List[Tuple[float, float, float]]:
    """Build 21 hand landmarks for a named gesture.

    Supported: 'stop_palm', 'open_palm', 'pointing', 'thumbs_up', 'wave', 'fist'.
    """
    pts = _fist(cx, cy)
    if gesture in ("stop_palm", "open_palm", "wave"):
        # all five fingers extended upward
        pts[0] = (cx, cy, 0.0)
        offs = [-25, -12, 0, 12, 25]
        for fi in range(5):
            fx = cx + offs[fi]
            start = 1 + fi * 4
            for joint in range(4):
                pts[start + joint] = (fx, cy - 10 - joint * 15, 0.0)
        return pts
    if gesture == "pointing":
        pts[6] = (cx - 12, cy - 5, 0.0)
        pts[8] = (cx - 12, cy - 40, 0.0)
        return pts
    if gesture == "thumbs_up":
        pts[0] = (cx, cy, 0.0)
        pts[9] = (cx, cy - 18, 0.0)
        pts[3] = (cx - 12, cy - 20, 0.0)
        pts[4] = (cx - 20, cy - 50, 0.0)
        for tip, pip in [(8, 6), (12, 10), (16, 14), (20, 18)]:
            pts[tip] = (pts[tip][0], pts[pip][1] + 12, 0.0)
        return pts
    return pts  # 'fist'


# ── Sensor snapshot with injectable faults ────────────────────────────────────

def sensor_snapshot(**overrides):
    """Build a :class:`SensorSnapshot` for the safety state machine.

    Defaults represent a calm, safe world. Pass overrides to inject faults, e.g.
    ``sensor_snapshot(estop_hardware=True)`` or
    ``sensor_snapshot(lidar_stale=True, nearest_human_m=0.3)``.
    """
    from bonbon_safety.core.safety_state_machine import SensorSnapshot
    base = dict(
        nearest_obstacle_m=3.0, nearest_human_m=3.0,
        cliff_detected_left=False, cliff_detected_right=False,
        bumper_front=False, bumper_rear=False,
        lidar_stale=False, camera_stale=False, imu_stale=False,
        imu_drift_detected=False, battery_percent=80.0,
        cpu_temp_c=45.0, motor_temp_c=40.0, servo_fault=False,
        odrive_fault=False, estop_hardware=False,
        unsafe_command_detected=False, navigation_timeout=False,
        critical_node_crashed=False, important_node_crashed=False,
    )
    base.update(overrides)
    # SensorSnapshot may require timestamp; provide if the field exists.
    try:
        return SensorSnapshot(**base)
    except TypeError:
        import time as _t
        base["timestamp"] = _t.monotonic()
        return SensorSnapshot(**base)


# ── Assertion helpers ──────────────────────────────────────────────────────────

def assert_at_least(level: FallbackLevel, minimum: FallbackLevel, msg: str = "") -> None:
    """Assert a fallback level is at least as severe as ``minimum``."""
    assert int(level) >= int(minimum), (
        f"{msg}: expected ≥ {minimum.name}, got {FallbackLevel(level).name}"
    )


def assert_safe_response(response, *, must_pause: bool = False,
                         must_escalate: bool = False) -> None:
    """Assert a SpatialResponse is appropriately conservative."""
    if must_pause:
        assert response.pause_navigation, "expected navigation to pause"
    if must_escalate:
        assert response.escalate_to_operator, "expected operator escalation"
