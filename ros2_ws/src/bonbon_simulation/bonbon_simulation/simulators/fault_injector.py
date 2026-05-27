from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict


@dataclass
class SensorHealth:
    publishing: bool = True
    drift: float = 0.0
    noise: float = 0.0
    failed_at_sec: float | None = None
    detected_at_sec: float | None = None


class SensorFaultInjector:
    """Tracks simulated sensor health and detection latency."""

    def __init__(self, detection_timeout_sec: float = 1.0) -> None:
        self.detection_timeout_sec = detection_timeout_sec
        self._health: Dict[str, SensorHealth] = {
            "lidar": SensorHealth(),
            "imu": SensorHealth(),
            "camera": SensorHealth(),
            "microphone": SensorHealth(),
            "servo": SensorHealth(),
            "wifi": SensorHealth(),
        }

    def fail(self, sensor: str, now_sec: float) -> None:
        health = self._health.setdefault(sensor, SensorHealth())
        health.publishing = False
        health.failed_at_sec = now_sec
        health.detected_at_sec = now_sec + self.detection_timeout_sec

    def recover(self, sensor: str) -> None:
        health = self._health.setdefault(sensor, SensorHealth())
        health.publishing = True
        health.failed_at_sec = None
        health.detected_at_sec = None
        health.drift = 0.0
        health.noise = 0.0

    def add_drift(self, sensor: str, amount: float) -> None:
        self._health.setdefault(sensor, SensorHealth()).drift += float(amount)

    def add_noise(self, sensor: str, amount: float) -> None:
        self._health.setdefault(sensor, SensorHealth()).noise += float(amount)

    def is_publishing(self, sensor: str) -> bool:
        return self._health.setdefault(sensor, SensorHealth()).publishing

    def detection_latency_ms(self, sensor: str) -> float | None:
        health = self._health.get(sensor)
        if not health or health.failed_at_sec is None or health.detected_at_sec is None:
            return None
        return (health.detected_at_sec - health.failed_at_sec) * 1000.0

    def snapshot(self) -> Dict[str, SensorHealth]:
        return dict(self._health)
