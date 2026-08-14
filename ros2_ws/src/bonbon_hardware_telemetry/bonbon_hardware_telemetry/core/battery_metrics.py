"""bonbon_hardware_telemetry.core.battery_metrics -- INA226 power monitor
(bonbon_hal.nodes.battery_node.BatteryNode, sensor_msgs/BatteryState on
/bonbon/battery/state). percent/voltage thresholds are read from
ThresholdConfig.battery, which is grounded in this pack's own 3S-LiPo
voltage table (bonbon_hal.drivers.battery.battery_driver
._VOLTAGE_TABLE) -- see threshold_config.py's docstring for the exact
row mapping. current_overcurrent_a is compared against abs(current_a):
the driver documents "negative = discharging" but sensor_msgs/
BatteryState does not itself mandate a sign convention, so this module
does not assume one beyond magnitude.
"""

from __future__ import annotations

from dataclasses import dataclass

from .threshold_config import ThresholdConfig
from .trigger import Severity, TelemetryTrigger

_DEVICE = "battery"


@dataclass(frozen=True)
class BatteryMetrics:
    voltage_v: float
    current_a: float
    percent: float
    is_charging: bool
    age_sec: float
    stale: bool
    low_warn: bool
    low_error: bool
    undervoltage: bool
    overcurrent: bool


def compute_battery_metrics(
    voltage_v: float,
    current_a: float,
    percent: float,
    is_charging: bool,
    age_sec: float,
    thresholds: ThresholdConfig,
) -> BatteryMetrics:
    b = thresholds.battery
    return BatteryMetrics(
        voltage_v=voltage_v,
        current_a=current_a,
        percent=percent,
        is_charging=is_charging,
        age_sec=age_sec,
        stale=age_sec > thresholds.liveness.stale_after_sec,
        low_warn=percent <= b.percent_warn,
        low_error=percent <= b.percent_error,
        undervoltage=voltage_v <= b.voltage_error_v,
        overcurrent=(not is_charging) and abs(current_a) >= b.current_overcurrent_a,
    )


def battery_triggers(metrics: BatteryMetrics) -> list[TelemetryTrigger]:
    triggers: list[TelemetryTrigger] = []

    if metrics.low_error:
        triggers.append(
            TelemetryTrigger(
                device=_DEVICE,
                severity=Severity.ERROR,
                code="BATTERY_CRITICALLY_LOW",
                message=f"Battery at {metrics.percent:.1f}% ({metrics.voltage_v:.2f}V)",
            )
        )
    elif metrics.low_warn:
        triggers.append(
            TelemetryTrigger(
                device=_DEVICE,
                severity=Severity.WARN,
                code="BATTERY_LOW",
                message=f"Battery at {metrics.percent:.1f}% ({metrics.voltage_v:.2f}V)",
            )
        )

    if metrics.undervoltage:
        triggers.append(
            TelemetryTrigger(
                device=_DEVICE,
                severity=Severity.ERROR,
                code="BATTERY_UNDERVOLTAGE",
                message=f"Battery voltage {metrics.voltage_v:.2f}V at/below cutoff",
            )
        )

    if metrics.overcurrent:
        triggers.append(
            TelemetryTrigger(
                device=_DEVICE,
                severity=Severity.WARN,
                code="BATTERY_OVERCURRENT",
                message=f"Battery discharge current {metrics.current_a:.2f}A exceeds threshold",
            )
        )

    if metrics.stale:
        triggers.append(
            TelemetryTrigger(
                device=_DEVICE,
                severity=Severity.WARN,
                code="BATTERY_STATE_STALE",
                message=f"No /bonbon/battery/state update in {metrics.age_sec:.1f}s",
            )
        )

    return triggers
