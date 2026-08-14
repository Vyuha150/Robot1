"""bonbon_hardware_telemetry.core.wheel_metrics -- base-mobility wheel
motors (Cytron MDDS30, Rhino 24V 60RPM wheel motors, bonbon_hal
.nodes.motor_node.MotorNode).

Honest limitation, not a gap: these motors have NO feedback sensor
(open-loop, see docs/HARDWARE_SOFTWARE_GAP_REPORT.md and
CytronMDDS30Driver's has_encoders=False) -- left_mps/right_mps/
*_distance_m below are the driver's own commanded/estimated readings,
not measured ones, and this module does not infer a stall or fault from
them (comparing commanded-vs-actual would fabricate a signal no sensor
backs). The one real Tier-1 trigger available for this component is
topic liveness: /bonbon/motor/wheel_state going stale means motor_node
itself (or its I2C/serial link) has stopped reporting, which IS a real,
already-observable condition.
"""

from __future__ import annotations

from dataclasses import dataclass

from .threshold_config import ThresholdConfig
from .trigger import Severity, TelemetryTrigger

_DEVICE = "motor"


@dataclass(frozen=True)
class WheelMetrics:
    left_mps: float
    right_mps: float
    left_distance_m: float
    right_distance_m: float
    age_sec: float
    stale: bool


def compute_wheel_metrics(
    left_mps: float,
    right_mps: float,
    left_distance_m: float,
    right_distance_m: float,
    age_sec: float,
    thresholds: ThresholdConfig,
) -> WheelMetrics:
    return WheelMetrics(
        left_mps=left_mps,
        right_mps=right_mps,
        left_distance_m=left_distance_m,
        right_distance_m=right_distance_m,
        age_sec=age_sec,
        stale=age_sec > thresholds.liveness.stale_after_sec,
    )


def wheel_triggers(metrics: WheelMetrics) -> list[TelemetryTrigger]:
    if not metrics.stale:
        return []
    return [
        TelemetryTrigger(
            device=_DEVICE,
            severity=Severity.WARN,
            code="WHEEL_STATE_STALE",
            message=f"No /bonbon/motor/wheel_state update in {metrics.age_sec:.1f}s",
        )
    ]
