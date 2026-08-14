"""bonbon_hardware_telemetry.core.threshold_config -- Tier 1 trigger
thresholds for every physical hardware component this robot has a real,
already-wired sensor for.

Deliberately NOT here (see docs/HARDWARE_TELEMETRY_METRICS_PLAN.md, Tier
2): per-motor current draw, motor/servo temperature, wheel encoders, Pi
CPU temperature -- the hardware cannot measure these today, so no
threshold is defined for them. Adding a threshold here without a real
sensor behind it would be exactly the kind of fabricated reading this
package's docstring promises never to produce.

What IS here, and why each number is what it is:

- Battery: bonbon_hal.drivers.battery.battery_driver's own 3S-LiPo
  voltage table (11.1V nominal, 12.6V=100%, 9.9V=0%) is the ONE
  authoritative source for this pack's chemistry -- percent_warn/error
  and voltage_warn_v/error_v below are chosen to land on that table's
  20%/5% rows (10.8V, 10.2V) rather than inventing independent numbers.
  current_overcurrent_a leaves headroom under Ina226Driver's own
  max_a=20.0 calibration ceiling.
- Pi resources: mirrors bonbon_safety.core.resource_monitor
  .ResourceSnapshot's own cpu_overloaded (>=90%), memory_pressure
  (>=85%), and disk_low (<=10%) properties exactly, plus
  ResourceMonitor.recommended_load_shed's 75% "elevated" second tier --
  reused, not reinvented, so a Pi is never "fine" by this package's
  threshold and "overloaded" by resource_monitor's at the same reading.
- Heartbeat/topic staleness: mirrors
  bonbon_distributed_safety.core.heartbeat_monitor.HeartbeatConfig's own
  stale_after_sec=1.5 default for the same reason.

Steppers (shoulder=id2, head_pan=id1) and PCA9685 servos (elbow, wrist,
head_tilt) need no numeric threshold here: their only real fault signals
are already booleans straight off the hardware --
ServoState.error_code==1 (stepper lost_sync/stall, ALM-pin-backed) and
ServoState.torque_enabled (PCA9685 PWM-pulse-train state) -- read
directly by core/joint_metrics.py, not thresholded.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[5]
DEFAULT_CONFIG_PATH = _REPO_ROOT / "config" / "hardware_telemetry" / "thresholds.yaml"


@dataclass(frozen=True)
class LivenessThresholds:
    """Applies uniformly to every HAL topic this package watches (wheel,
    stepper, servo, battery state) -- all publish at >=1Hz, so one
    conservative staleness window covers all of them without per-topic
    tuning that isn't backed by a real, distinct requirement."""

    stale_after_sec: float = 2.0


@dataclass(frozen=True)
class BatteryThresholds:
    percent_warn: float = 20.0
    percent_error: float = 5.0
    voltage_warn_v: float = 10.8
    voltage_error_v: float = 10.2
    current_overcurrent_a: float = 18.0


@dataclass(frozen=True)
class PiResourceThresholds:
    cpu_elevated_percent: float = 75.0
    cpu_overloaded_percent: float = 90.0
    memory_pressure_percent: float = 85.0
    disk_low_percent: float = 10.0
    heartbeat_stale_after_sec: float = 1.5


@dataclass(frozen=True)
class ThresholdConfig:
    liveness: LivenessThresholds
    battery: BatteryThresholds
    pi_resources: PiResourceThresholds

    @classmethod
    def defaults(cls) -> "ThresholdConfig":
        return cls(
            liveness=LivenessThresholds(),
            battery=BatteryThresholds(),
            pi_resources=PiResourceThresholds(),
        )

    @classmethod
    def load(cls, path: str | Path | None = None) -> "ThresholdConfig":
        p = Path(path) if path is not None else DEFAULT_CONFIG_PATH
        if not p.exists():
            return cls.defaults()
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        return cls(
            liveness=LivenessThresholds(**(raw.get("liveness") or {})),
            battery=BatteryThresholds(**(raw.get("battery") or {})),
            pi_resources=PiResourceThresholds(**(raw.get("pi_resources") or {})),
        )
