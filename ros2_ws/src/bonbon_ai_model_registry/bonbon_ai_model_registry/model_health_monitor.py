"""ModelHealthMonitor — periodic per-model health snapshot for the
dashboard (Phase 11) and for model_dashboard_publisher.py to serialize.
Pure-Python core (HealthMonitor) is fully unit-testable without rclpy;
the optional ROS2 node wrapper at the bottom follows this repo's
established pattern of lazy-importing rclpy so the module stays
importable in environments (like this dev sandbox) where rclpy isn't
installed -- see bonbon_hal's driver modules for the same convention.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from bonbon_ai_model_registry.model_registry import ModelRegistry
from bonbon_ai_model_registry.model_runtime_selector import ModelRuntimeSelector, RuntimeStatus


@dataclass
class ModelHealth:
    model_id: str
    capability: str
    installed: bool
    active: bool
    fallback_active: bool
    last_checked: float
    last_latency_ms: float | None = None
    last_error: str | None = None


class ModelHealthMonitor:
    def __init__(self, registry: ModelRegistry, selector: ModelRuntimeSelector) -> None:
        self._registry = registry
        self._selector = selector
        self._latency_samples: dict[str, float] = {}
        self._last_errors: dict[str, str] = {}

    def record_latency(self, model_id: str, latency_ms: float) -> None:
        self._latency_samples[model_id] = latency_ms
        self._last_errors.pop(model_id, None)

    def record_error(self, model_id: str, error: str) -> None:
        self._last_errors[model_id] = error

    def snapshot(self) -> dict[str, list[ModelHealth]]:
        """capability -> list[ModelHealth] for every registered model in
        that capability, not just the active one -- the dashboard needs
        to show installed-but-not-active models too (rule 11: real
        active/fallback/status)."""
        result: dict[str, list[ModelHealth]] = {}
        statuses = self._selector.select_all()
        for capability, status in statuses.items():
            entries = self._registry.by_capability(capability)
            result[capability] = [
                ModelHealth(
                    model_id=entry.model_id,
                    capability=capability,
                    installed=status.availability.get(entry.model_id, False),
                    active=(status.decision.active_model_id == entry.model_id),
                    fallback_active=status.decision.fallback_active and status.decision.active_model_id == entry.model_id,
                    last_checked=status.checked_at,
                    last_latency_ms=self._latency_samples.get(entry.model_id),
                    last_error=self._last_errors.get(entry.model_id),
                )
                for entry in entries
            ]
        return result

    def capability_status(self, capability: str) -> RuntimeStatus:
        return self._selector.select(capability)


def main(args: list[str] | None = None) -> None:  # pragma: no cover -- exercised only with rclpy present
    """ROS2 node entry point: periodically republishes the health
    snapshot as a JSON string on /bonbon/ai_models/health so
    bonbon_operator_api's ROS2 bridge (or any other subscriber) can pick
    it up without importing this package directly. Lazy rclpy import so
    `python -m py_compile` / plain `import` of this module never requires
    rclpy to be installed -- consistent with every other node in this
    repo (see docs/HARDWARE_GATED_TESTS.md)."""
    try:
        import json

        import rclpy
        from rclpy.node import Node
        from std_msgs.msg import String
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "model_health_monitor_node requires rclpy + std_msgs -- run inside a ROS2 environment, "
            "not this dev sandbox (see docs/AI_MODEL_CURRENT_AUDIT.md's environment note)"
        ) from exc

    from pathlib import Path

    from bonbon_ai_model_registry.model_registry import ModelRegistry

    class ModelHealthMonitorNode(Node):  # type: ignore[misc]
        def __init__(self) -> None:
            super().__init__("model_health_monitor_node")
            self.declare_parameter("registry_path", "config/models/model_registry.yaml")
            self.declare_parameter("publish_interval_sec", 5.0)
            registry_path = self.get_parameter("registry_path").get_parameter_value().string_value
            registry = ModelRegistry.load(Path(registry_path))
            selector = ModelRuntimeSelector(registry)
            self._monitor = ModelHealthMonitor(registry, selector)
            self._pub = self.create_publisher(String, "/bonbon/ai_models/health", 10)
            interval = self.get_parameter("publish_interval_sec").get_parameter_value().double_value
            self.create_timer(interval, self._tick)

        def _tick(self) -> None:
            snapshot = self._monitor.snapshot()
            payload = {
                cap: [
                    {
                        "modelId": h.model_id, "installed": h.installed, "active": h.active,
                        "fallbackActive": h.fallback_active, "lastLatencyMs": h.last_latency_ms,
                        "lastError": h.last_error,
                    }
                    for h in items
                ]
                for cap, items in snapshot.items()
            }
            msg = String()
            msg.data = json.dumps(payload)
            self._pub.publish(msg)

    rclpy.init(args=args)
    node = ModelHealthMonitorNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":  # pragma: no cover
    main()
