"""DashboardMetricsCollector — Prometheus metrics for the operator API.

Exposed at GET /metrics (prometheus-client text format).

Metrics
-------
bonbon_api_http_requests_total          — counter, labels: method, endpoint, status_code
bonbon_api_http_request_duration_seconds — histogram, labels: method, endpoint
bonbon_api_ws_connections_total          — gauge, labels: channel
bonbon_api_commands_total                — counter, labels: command_type, outcome
bonbon_api_command_duration_seconds      — histogram, labels: command_type
bonbon_api_auth_attempts_total           — counter, labels: outcome (success|failure)
bonbon_api_robot_online                  — gauge (1=online, 0=offline)
bonbon_api_robot_battery_pct             — gauge
bonbon_api_audit_events_total            — counter (total events logged)
"""

from __future__ import annotations

import logging
from contextlib import contextmanager

logger = logging.getLogger(__name__)

try:
    from prometheus_client import (
        CONTENT_TYPE_LATEST,
        REGISTRY,
        CollectorRegistry,
        Counter,
        Gauge,
        Histogram,
        generate_latest,
    )

    _PROMETHEUS_AVAILABLE = True
except (ImportError, AttributeError, Exception):
    # prometheus_client may fail on Windows (resource.getpagesize) or
    # in environments without the package
    _PROMETHEUS_AVAILABLE = False
    logger.warning("prometheus_client not available — metrics disabled")


class DashboardMetricsCollector:
    """Prometheus metrics for the BonBon operator API.

    Parameters
    ----------
    registry:
        Prometheus registry to register metrics with.
        Defaults to the global registry.
    enabled:
        If False (or prometheus_client is missing), all methods are no-ops.
    """

    def __init__(
        self,
        registry=None,
        enabled: bool = True,
    ) -> None:
        self._enabled = enabled and _PROMETHEUS_AVAILABLE
        if not self._enabled:
            return

        reg = registry or REGISTRY

        self.http_requests = Counter(
            "bonbon_api_http_requests_total",
            "Total HTTP requests",
            ["method", "endpoint", "status_code"],
            registry=reg,
        )
        self.http_duration = Histogram(
            "bonbon_api_http_request_duration_seconds",
            "HTTP request duration",
            ["method", "endpoint"],
            buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5],
            registry=reg,
        )
        self.ws_connections = Gauge(
            "bonbon_api_ws_connections_total",
            "Current WebSocket connections by channel",
            ["channel"],
            registry=reg,
        )
        self.commands_total = Counter(
            "bonbon_api_commands_total",
            "Commands issued through the API",
            ["command_type", "outcome"],
            registry=reg,
        )
        self.command_duration = Histogram(
            "bonbon_api_command_duration_seconds",
            "Time from API receipt to ROS2 dispatch",
            ["command_type"],
            buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.5, 1.0],
            registry=reg,
        )
        self.auth_attempts = Counter(
            "bonbon_api_auth_attempts_total",
            "Login attempts",
            ["outcome"],
            registry=reg,
        )
        self.robot_online = Gauge(
            "bonbon_api_robot_online",
            "1 if robot is online, 0 if offline",
            registry=reg,
        )
        self.robot_battery = Gauge(
            "bonbon_api_robot_battery_pct",
            "Robot battery percentage",
            registry=reg,
        )
        self.audit_events = Counter(
            "bonbon_api_audit_events_total",
            "Total audit log entries written",
            registry=reg,
        )
        self._registry = reg

    # ------------------------------------------------------------------
    # HTTP metrics
    # ------------------------------------------------------------------

    def record_request(self, method: str, endpoint: str, status_code: int) -> None:
        if not self._enabled:
            return
        self.http_requests.labels(
            method=method, endpoint=endpoint, status_code=str(status_code)
        ).inc()

    @contextmanager
    def time_request(self, method: str, endpoint: str):
        if not self._enabled:
            yield
            return
        with self.http_duration.labels(method=method, endpoint=endpoint).time():
            yield

    # ------------------------------------------------------------------
    # WebSocket metrics
    # ------------------------------------------------------------------

    def set_ws_connections(self, channel: str, count: int) -> None:
        if not self._enabled:
            return
        self.ws_connections.labels(channel=channel).set(count)

    def update_ws_connections(self, counts: dict) -> None:
        if not self._enabled:
            return
        for channel, count in counts.items():
            self.ws_connections.labels(channel=channel).set(count)

    # ------------------------------------------------------------------
    # Command metrics
    # ------------------------------------------------------------------

    def record_command(self, command_type: str, outcome: str) -> None:
        if not self._enabled:
            return
        self.commands_total.labels(command_type=command_type, outcome=outcome).inc()

    @contextmanager
    def time_command(self, command_type: str):
        if not self._enabled:
            yield
            return
        with self.command_duration.labels(command_type=command_type).time():
            yield

    # ------------------------------------------------------------------
    # Auth metrics
    # ------------------------------------------------------------------

    def record_auth(self, success: bool) -> None:
        if not self._enabled:
            return
        self.auth_attempts.labels(outcome="success" if success else "failure").inc()

    # ------------------------------------------------------------------
    # Robot state metrics
    # ------------------------------------------------------------------

    def update_robot_state(self, is_online: bool, battery_pct: float) -> None:
        if not self._enabled:
            return
        self.robot_online.set(1 if is_online else 0)
        self.robot_battery.set(battery_pct)

    # ------------------------------------------------------------------
    # Audit
    # ------------------------------------------------------------------

    def record_audit_event(self) -> None:
        if not self._enabled:
            return
        self.audit_events.inc()

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def generate_text(self) -> tuple[bytes, str]:
        """Return (content_bytes, content_type) for /metrics endpoint."""
        if not self._enabled:
            return b"# metrics disabled\n", "text/plain"
        return generate_latest(self._registry), CONTENT_TYPE_LATEST
