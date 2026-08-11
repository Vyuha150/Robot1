"""bonbon_edge_ai_runtime.metrics_publisher -- Edge AI Runtime brief
Phase 2/12. Collects a periodic metrics snapshot from every other
module in this package (cache hit rates, queue depths, dropped
requests, resource/thermal state, safety-blocked-action counts) into
one dict.

This module never publishes anything itself -- it has no ROS2 or HTTP
dependency at all. A caller (a ROS2 node, or bonbon_operator_api's
dashboard bridge) pulls snapshot() on whatever cadence/transport it
owns. Publishing here directly would risk a second dashboard data path
competing with bonbon_operator_api's real one (rule 7); this module
only ever produces data, never ships it anywhere.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class MetricsSnapshot:
    timestamp: float
    cache_metrics: dict = field(default_factory=dict)
    scheduler_status: dict = field(default_factory=dict)
    resource_status: dict = field(default_factory=dict)
    safety_summary: dict = field(default_factory=dict)
    degraded_status: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "cache": self.cache_metrics,
            "scheduler": self.scheduler_status,
            "resource": self.resource_status,
            "safety": self.safety_summary,
            "degradedMode": self.degraded_status,
        }


class MetricsPublisher:
    """Pulls a snapshot from each component's own status()/metrics()/
    summary() method -- never recomputes what those already compute.
    Every dependency is optional: a caller that only wants cache metrics
    can pass just cache_manager and get an honestly-empty dict for
    everything else, not a crash."""

    def __init__(
        self,
        *,
        cache_manager=None,
        scheduler=None,
        resource_guard=None,
        safety_guard=None,
        degraded_manager=None,
    ) -> None:
        self._cache_manager = cache_manager
        self._scheduler = scheduler
        self._resource_guard = resource_guard
        self._safety_guard = safety_guard
        self._degraded_manager = degraded_manager
        self._last_resource_status: dict = {}
        self._last_degraded_status: dict = {}

    def snapshot(
        self,
        *,
        temp_c: float | None = None,
        safety_state_name: str = "UNKNOWN",
        safety_caution_or_above: bool = False,
        load_level=None,
        safety_fault_or_above: bool = False,
    ) -> MetricsSnapshot:
        cache_metrics = self._cache_manager.metrics() if self._cache_manager else {}
        scheduler_status = self._scheduler.status() if self._scheduler else {}

        resource_status = self._last_resource_status
        if self._resource_guard is not None and temp_c is not None:
            resource_status = self._resource_guard.evaluate(
                temp_c, safety_state_name, safety_caution_or_above
            ).to_dict()
            self._last_resource_status = resource_status

        safety_summary = self._safety_guard.summary() if self._safety_guard else {}

        degraded_status = self._last_degraded_status
        if self._degraded_manager is not None and load_level is not None:
            degraded_status = self._degraded_manager.update(load_level, safety_fault_or_above).to_dict()
            self._last_degraded_status = degraded_status

        return MetricsSnapshot(
            timestamp=time.monotonic(),
            cache_metrics=cache_metrics,
            scheduler_status=scheduler_status,
            resource_status=resource_status,
            safety_summary=safety_summary,
            degraded_status=degraded_status,
        )
