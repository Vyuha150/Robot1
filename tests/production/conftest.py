"""Shared fixtures for tests/production/. Currently only the dashboard
family needs a live FastAPI app + auth tokens; mirrors
ros2_ws/src/bonbon_operator_api/tests/conftest.py's fixtures so the same
real app/auth/permission code is exercised here, not a re-implementation.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("BONBON_TEST_MODE", "1")
os.environ.setdefault("BONBON_ADMIN_PASSWORD", "BonBon@dmin2025!")

sys.path.insert(
    0, str(Path(__file__).resolve().parents[2] / "ros2_ws" / "src" / "bonbon_operator_api")
)


@pytest.fixture
def tmp_data_dir(tmp_path) -> Path:
    return tmp_path


@pytest.fixture
def audit_logger(tmp_data_dir):
    from bonbon_operator_api.audit.audit_logger import AuditLogger

    return AuditLogger(db_path=tmp_data_dir / "audit_test.db", max_events=1000)


@pytest.fixture
def auth_manager(tmp_data_dir):
    from bonbon_operator_api.auth.auth_manager import AuthManager

    return AuthManager(
        db_path=tmp_data_dir / "users_test.db",
        jwt_secret="test-secret-key-32-chars-minimum!!",
        algorithm="HS256",
        token_expire_minutes=60,
    )


@pytest.fixture
def role_manager():
    from bonbon_operator_api.auth.role_permissions import RolePermissionManager

    return RolePermissionManager()


@pytest.fixture
def validator():
    from bonbon_operator_api.safety.command_validator import CommandValidator

    return CommandValidator(dedup_window_sec=5.0, dedup_capacity=64)


@pytest.fixture
def aggregator():
    from bonbon_operator_api.ros2.status_aggregator import RobotStatusAggregator

    return RobotStatusAggregator(offline_timeout_sec=15.0)


@pytest.fixture
def mock_bridge():
    bridge = MagicMock()
    bridge.call_emergency_stop.return_value = {"success": True}
    return bridge


@pytest.fixture
def safety_gate(validator, aggregator, audit_logger):
    from bonbon_operator_api.safety.safety_gate import SafetyCommandGate

    return SafetyCommandGate(
        validator=validator, status_aggregator=aggregator, audit_logger=audit_logger
    )


@pytest.fixture
def app(
    tmp_data_dir, auth_manager, role_manager, audit_logger, aggregator, mock_bridge, safety_gate
):
    from bonbon_operator_api.api.config_api import _ConfigStore
    from bonbon_operator_api.api.testbench_api import _TestbenchStore
    from bonbon_operator_api.config.api_config import OperatorAPIConfig
    from bonbon_operator_api.main import _build_app
    from bonbon_operator_api.metrics.metrics_collector import DashboardMetricsCollector
    from bonbon_operator_api.websocket.ws_manager import WebSocketConnectionManager

    cfg = OperatorAPIConfig()
    cfg.ros2.enabled = False

    application = _build_app(cfg)
    application.state.auth_manager = auth_manager
    application.state.role_manager = role_manager
    application.state.audit_logger = audit_logger
    application.state.status_aggregator = aggregator
    application.state.ros2_bridge = mock_bridge
    application.state.safety_gate = safety_gate
    application.state.metrics = DashboardMetricsCollector(enabled=False)
    application.state.ws_manager = WebSocketConnectionManager()
    application.state.config_store = _ConfigStore(tmp_data_dir / "config_test.json")
    application.state.testbench_store = _TestbenchStore(tmp_data_dir / "testbench_test.json")
    return application


@pytest.fixture
def client(app) -> TestClient:
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


def _token_for(auth_manager, username: str, password: str, role: str) -> str:
    from bonbon_operator_api.models.auth_models import UserCreate

    try:
        auth_manager.create_user(UserCreate(username=username, password=password, role=role))
    except ValueError:
        pass
    user = auth_manager.authenticate(username, password)
    token, _ = auth_manager.create_token(user)
    return token


@pytest.fixture
def admin_token(auth_manager):
    return _token_for(auth_manager, "test_admin", "Admin1234!", "admin")


@pytest.fixture
def viewer_token(auth_manager):
    return _token_for(auth_manager, "test_viewer", "Viewer1234!", "viewer")
