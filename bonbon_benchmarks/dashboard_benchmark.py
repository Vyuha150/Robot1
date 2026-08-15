"""Dashboard API/WebSocket latency benchmarking. Builds a real
bonbon_operator_api FastAPI app + TestClient (same construction as
ros2_ws/src/bonbon_operator_api/tests/conftest.py's `app`/`client`
fixtures, replicated standalone since this module runs outside pytest) --
real HTTP requests through the real router/auth/permission stack, ROS2
bridge mocked (no live robot needed for endpoint-latency measurement,
same as every existing bonbon_operator_api test).
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock

from bonbon_safety.core.perf_targets import build_targets

import bonbon_benchmarks  # noqa: F401
from bonbon_benchmarks.metrics_collector import (
    BenchmarkCategoryReport,
    BenchmarkMetric,
    MetricSampler,
)

os.environ.setdefault("BONBON_TEST_MODE", "1")
os.environ.setdefault("BONBON_ADMIN_PASSWORD", "BonBon@dmin2025!")

_REPO_ROOT = Path(__file__).resolve().parents[1]
_OPERATOR_API_SRC = _REPO_ROOT / "ros2_ws" / "src" / "bonbon_operator_api"
if str(_OPERATOR_API_SRC) not in sys.path:
    sys.path.insert(0, str(_OPERATOR_API_SRC))


def _build_test_client_and_token():
    from bonbon_operator_api.api.config_api import _ConfigStore
    from bonbon_operator_api.api.testbench_api import _TestbenchStore
    from bonbon_operator_api.audit.audit_logger import AuditLogger
    from bonbon_operator_api.auth.auth_manager import AuthManager
    from bonbon_operator_api.auth.role_permissions import RolePermissionManager
    from bonbon_operator_api.config.api_config import OperatorAPIConfig
    from bonbon_operator_api.main import _build_app
    from bonbon_operator_api.metrics.metrics_collector import DashboardMetricsCollector
    from bonbon_operator_api.models.auth_models import UserCreate
    from bonbon_operator_api.ros2.status_aggregator import RobotStatusAggregator
    from bonbon_operator_api.safety.command_validator import CommandValidator
    from bonbon_operator_api.safety.safety_gate import SafetyCommandGate
    from bonbon_operator_api.websocket.ws_manager import WebSocketConnectionManager
    from fastapi.testclient import TestClient

    tmp_dir = Path(tempfile.mkdtemp(prefix="bonbon_benchmark_dashboard_"))
    audit_logger = AuditLogger(db_path=tmp_dir / "audit.db", max_events=1000)
    auth_manager = AuthManager(
        db_path=tmp_dir / "users.db", jwt_secret="test-secret-key-32-chars-minimum!!",
        algorithm="HS256", token_expire_minutes=60,
    )
    validator = CommandValidator(dedup_window_sec=5.0, dedup_capacity=64)
    aggregator = RobotStatusAggregator(offline_timeout_sec=15.0)
    mock_bridge = MagicMock()
    mock_bridge.get_distributed_snapshot.return_value = {
        "bridge_ready": False, "pi_links": {"pi1": "lost", "pi2": "lost", "pi3": "lost"},
        "last_approval": None, "last_rejection": None, "last_degraded_mode": None,
        "approval_count": 0, "rejection_count": 0,
    }
    safety_gate = SafetyCommandGate(validator=validator, status_aggregator=aggregator, audit_logger=audit_logger)

    cfg = OperatorAPIConfig()
    cfg.ros2.enabled = False
    app = _build_app(cfg)
    app.state.auth_manager = auth_manager
    app.state.role_manager = RolePermissionManager()
    app.state.audit_logger = audit_logger
    app.state.status_aggregator = aggregator
    app.state.ros2_bridge = mock_bridge
    app.state.safety_gate = safety_gate
    app.state.metrics = DashboardMetricsCollector(enabled=False)
    app.state.ws_manager = WebSocketConnectionManager()
    app.state.config_store = _ConfigStore(tmp_dir / "config.json")
    app.state.testbench_store = _TestbenchStore(tmp_dir / "testbench.json")

    auth_manager.create_user(UserCreate(username="bench_viewer", password="Viewer1234!", role="viewer"))
    user = auth_manager.authenticate("bench_viewer", "Viewer1234!")
    token, _ = auth_manager.create_token(user)

    client = TestClient(app, raise_server_exceptions=True)
    return client, token


# Representative endpoints: a plain status read, a data-pipeline read
# (this session's own addition), and the validation-framework rollup --
# all GET, all real router dispatch through the full auth/permission stack.
_ENDPOINTS = (
    "/api/v1/status",
    "/api/v1/data/datasets",
    "/api/v1/validation/scenario-families",
)


def benchmark_endpoint(
    path: str, iterations: int = 50, board: str = "ui_pi"
) -> BenchmarkMetric:
    client, token = _build_test_client_and_token()
    headers = {"Authorization": f"Bearer {token}"}
    sampler = MetricSampler()
    failures = 0
    for _ in range(iterations):
        started = time.perf_counter()
        resp = client.get(path, headers=headers)
        sampler.record((time.perf_counter() - started) * 1000.0)
        if resp.status_code != 200:
            failures += 1

    budget = build_targets()["dashboard_status"]
    return BenchmarkMetric.from_sampler(
        sampler, metric_name="dashboard_api_latency", board=board, module="dashboard",
        scenario=f"GET {path} x{iterations} (in-process TestClient, no network hop)",
        unit="ms", target=budget.budget_ms, target_stat=budget.metric,
        recommendation=(
            f"{failures}/{iterations} requests returned non-200." if failures
            else "In-process TestClient has no real network/TLS overhead -- real UI Pi <-> AI Pi latency will be higher; see three_pi_network_benchmark.py."
        ),
    )


def benchmark_websocket_connect(board: str = "ui_pi") -> BenchmarkMetric:
    """Time to establish the /ws/robot-status connection -- a proxy for
    the "WebSocket health update" latency budget until a real multi-client
    subscribe/broadcast harness exists."""
    client, token = _build_test_client_and_token()
    sampler = MetricSampler()
    for _ in range(10):
        started = time.perf_counter()
        try:
            with client.websocket_connect(f"/ws/robot-status?token={token}") as ws:
                ws.close()
        except Exception:  # noqa: BLE001 -- record as a failed sample, not a crash
            continue
        sampler.record((time.perf_counter() - started) * 1000.0)

    if sampler.count == 0:
        return BenchmarkMetric.blocked(
            metric_name="dashboard_websocket_connect_latency", board=board, module="dashboard",
            scenario="/ws/robot-status connect x10", reason="no successful WebSocket connection in 10 attempts",
        )
    return BenchmarkMetric.from_sampler(
        sampler, metric_name="dashboard_websocket_connect_latency", board=board, module="dashboard",
        scenario=f"/ws/status connect+close x{sampler.count}", unit="ms",
    )


def run_all(iterations: int = 50) -> BenchmarkCategoryReport:
    report = BenchmarkCategoryReport(category="dashboard")
    for path in _ENDPOINTS:
        report.add(benchmark_endpoint(path, iterations=iterations))
    report.add(benchmark_websocket_connect())
    return report
