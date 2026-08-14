"""bonbon_hardware_telemetry.core.pi_metrics -- per-Pi (ui_supervisor_pi
/ ai_interaction_pi / navigation_safety_pi) CPU/memory/disk, sampled
locally via bonbon_safety.core.resource_monitor.ResourceMonitor
(reused unchanged, not reimplemented) and read directly against that
same module's own cpu_overloaded/memory_pressure/disk_low properties
(ThresholdConfig.pi_resources mirrors them exactly -- see
threshold_config.py).

Deliberately NOT emitted as a bonbon_msgs/HalFault trigger here: CPU/
memory/disk pressure already has its own dedicated, already-acted-on
pipeline -- bonbon_edge_ai_runtime.resource_guard,
bonbon_perception_efficiency.LoadSheddingController/
DegradedModeManager, and bonbon_llm.Pi2LLMGuard all consume
ResourceMonitor snapshots (via /bonbon/system/resource_usage,
safety_supervisor_node) and take real load-shedding action on the exact
same thresholds used here. Also forwarding these numbers into
fault_manager's HAL-device-fault taxonomy would give the same reading
two independent, potentially-diverging meanings -- exactly the
duplicate-pipeline problem this workstream has repeatedly avoided
elsewhere (docs/DUPLICATE_PIPELINE_AUDIT.md). This module exposes
cpu/memory/disk pressure purely as a dashboard-visibility snapshot.

What IS a genuinely new trigger here (nothing else already reports it):
- `available=False` -- ResourceMonitor degraded to safe zero readings
  (psutil missing), meaning every number in this snapshot is a
  placeholder, not a real reading. Surfaced as INFO so operators don't
  mistake a degraded monitor for an idle Pi.
- Staleness of a remote Pi's aggregated snapshot on the dashboard's
  cross-Pi view (this node's own topic, not a duplicate of
  heartbeat_monitor's process-liveness topic).
"""

from __future__ import annotations

from dataclasses import dataclass

from .threshold_config import ThresholdConfig
from .trigger import Severity, TelemetryTrigger

_DEVICE = "pi_resource"


@dataclass(frozen=True)
class PiResourceMetrics:
    pi_role: str
    cpu_percent: float
    memory_percent: float
    memory_mb: float
    disk_free_percent: float
    available: bool
    cpu_elevated: bool
    cpu_overloaded: bool
    memory_pressure: bool
    disk_low: bool
    age_sec: float
    stale: bool


def compute_pi_resource_metrics(
    pi_role: str,
    cpu_percent: float,
    memory_percent: float,
    memory_mb: float,
    disk_free_percent: float,
    available: bool,
    age_sec: float,
    thresholds: ThresholdConfig,
) -> PiResourceMetrics:
    t = thresholds.pi_resources
    return PiResourceMetrics(
        pi_role=pi_role,
        cpu_percent=cpu_percent,
        memory_percent=memory_percent,
        memory_mb=memory_mb,
        disk_free_percent=disk_free_percent,
        available=available,
        cpu_elevated=cpu_percent >= t.cpu_elevated_percent,
        cpu_overloaded=cpu_percent >= t.cpu_overloaded_percent,
        memory_pressure=memory_percent >= t.memory_pressure_percent,
        disk_low=available and disk_free_percent <= t.disk_low_percent,
        age_sec=age_sec,
        stale=age_sec > t.heartbeat_stale_after_sec,
    )


def pi_resource_triggers(metrics: PiResourceMetrics) -> list[TelemetryTrigger]:
    triggers: list[TelemetryTrigger] = []

    if not metrics.available:
        triggers.append(
            TelemetryTrigger(
                device=_DEVICE,
                severity=Severity.INFO,
                code="PI_RESOURCE_MONITOR_DEGRADED",
                message=f"{metrics.pi_role}: resource monitor unavailable (psutil missing) -- readings are placeholders",
            )
        )

    if metrics.stale:
        triggers.append(
            TelemetryTrigger(
                device=_DEVICE,
                severity=Severity.WARN,
                code="PI_RESOURCE_SNAPSHOT_STALE",
                message=f"{metrics.pi_role}: no resource snapshot in {metrics.age_sec:.1f}s",
            )
        )

    return triggers
