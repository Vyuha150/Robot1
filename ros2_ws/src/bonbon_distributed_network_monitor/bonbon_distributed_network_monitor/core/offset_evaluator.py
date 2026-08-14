"""bonbon_distributed_network_monitor.core.offset_evaluator -- combines
a parsed ChronyTrackingResult with TimeSyncThresholds into a metrics
snapshot plus any triggered TelemetryTrigger, exactly mirroring
bonbon_hardware_telemetry.core.*_metrics.py's shape (pure function,
metrics dataclass + trigger list, no rclpy).

Two-tier severity mirrors ResourceSnapshot's cpu_elevated/cpu_overloaded
convention: max_offset_ms is the "designed-for" ceiling
(config/distributed/robot_network.yaml's own value, 50ms) and
alert_offset_ms is the harder breach that Rule 9 explicitly requires
alerting on (200ms) -- crossing the first is a WARN worth watching,
crossing the second is an ERROR because cross-Pi event ordering and
heartbeat-staleness math (both time-based) start actively degrading.
"""

from __future__ import annotations

from dataclasses import dataclass

from .chrony_offset import ChronyTrackingResult
from .network_thresholds import TimeSyncThresholds
from .trigger import Severity, TelemetryTrigger

_DEVICE = "network_time_sync"


@dataclass(frozen=True)
class OffsetMetrics:
    pi_role: str
    raw_available: bool
    synchronised: bool
    offset_ms: float | None
    leap_status: str | None
    max_offset_exceeded: bool
    alert_offset_exceeded: bool


def compute_offset_metrics(
    pi_role: str, result: ChronyTrackingResult, thresholds: TimeSyncThresholds
) -> OffsetMetrics:
    offset_ms = result.offset_ms
    max_exceeded = offset_ms is not None and abs(offset_ms) > thresholds.max_offset_ms
    alert_exceeded = offset_ms is not None and abs(offset_ms) > thresholds.alert_offset_ms
    return OffsetMetrics(
        pi_role=pi_role,
        raw_available=result.parsed,
        synchronised=result.synchronised,
        offset_ms=offset_ms,
        leap_status=result.leap_status,
        max_offset_exceeded=max_exceeded,
        alert_offset_exceeded=alert_exceeded,
    )


def offset_triggers(metrics: OffsetMetrics) -> list[TelemetryTrigger]:
    if not metrics.raw_available:
        return [
            TelemetryTrigger(
                device=_DEVICE,
                severity=Severity.WARN,
                code="CHRONY_UNAVAILABLE",
                message=f"{metrics.pi_role}: chronyc tracking could not be read -- time-sync status unknown",
            )
        ]

    if not metrics.synchronised:
        return [
            TelemetryTrigger(
                device=_DEVICE,
                severity=Severity.WARN,
                code="CLOCK_NOT_SYNCHRONISED",
                message=f"{metrics.pi_role}: chronyd reports 'Not synchronised' -- no valid offset reading yet",
            )
        ]

    if metrics.alert_offset_exceeded:
        return [
            TelemetryTrigger(
                device=_DEVICE,
                severity=Severity.ERROR,
                code="CLOCK_OFFSET_ALERT",
                message=f"{metrics.pi_role}: clock offset {metrics.offset_ms:.1f}ms exceeds alert threshold",
            )
        ]

    if metrics.max_offset_exceeded:
        return [
            TelemetryTrigger(
                device=_DEVICE,
                severity=Severity.WARN,
                code="CLOCK_OFFSET_ELEVATED",
                message=f"{metrics.pi_role}: clock offset {metrics.offset_ms:.1f}ms exceeds designed-for max_offset_ms",
            )
        ]

    return []
