"""Diagnostics API and audit log tests."""

from __future__ import annotations

from fastapi.testclient import TestClient


# Scenario 1: Engineer can get module status
def test_engineer_get_module_status(client: TestClient, engineer_token: str):
    resp = client.get(
        "/api/v1/diagnostics/modules",
        headers={"Authorization": f"Bearer {engineer_token}"},
    )
    assert resp.status_code == 200
    assert "modules" in resp.json()["data"]


# Scenario 2: Viewer can get module status (diagnostics:read required, viewer has it)
def test_viewer_get_module_status(client: TestClient, viewer_token: str):
    resp = client.get(
        "/api/v1/diagnostics/modules",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert resp.status_code == 200


# Scenario 3: Engineer can restart a valid module
def test_engineer_restart_valid_module(client: TestClient, engineer_token: str):
    resp = client.post(
        "/api/v1/diagnostics/modules/bonbon_tts/restart",
        headers={"Authorization": f"Bearer {engineer_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["restart_requested"] is True


# Cleanup-audit fix: a bridge result with success=False must surface as an
# HTTP error, never a fake 200 "restart_requested". Mirrors command_api.py's
# _check_bridge_result tests for the same class of bug.
def test_restart_reports_bridge_dispatch_failure(
    client: TestClient, engineer_token: str, mock_bridge
):
    mock_bridge.call_restart_module.return_value = {
        "success": False,
        "error": "NOT_IMPLEMENTED",
    }
    resp = client.post(
        "/api/v1/diagnostics/modules/bonbon_tts/restart",
        headers={"Authorization": f"Bearer {engineer_token}"},
    )
    assert resp.status_code == 503


# Scenario 4: Restarting unknown module returns 400
def test_restart_unknown_module(client: TestClient, engineer_token: str):
    resp = client.post(
        "/api/v1/diagnostics/modules/unknown_module/restart",
        headers={"Authorization": f"Bearer {engineer_token}"},
    )
    assert resp.status_code == 400


# Scenario 5: Viewer cannot restart module (needs diagnostics:restart_module)
def test_viewer_cannot_restart_module(client: TestClient, viewer_token: str):
    resp = client.post(
        "/api/v1/diagnostics/modules/bonbon_tts/restart",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert resp.status_code == 403


# Scenario 6: Operator cannot restart module
def test_operator_cannot_restart_module(client: TestClient, operator_token: str):
    resp = client.post(
        "/api/v1/diagnostics/modules/bonbon_tts/restart",
        headers={"Authorization": f"Bearer {operator_token}"},
    )
    assert resp.status_code == 403


# Scenario 7: Admin can query audit log
def test_admin_can_query_audit(client: TestClient, admin_token: str):
    resp = client.get(
        "/api/v1/diagnostics/audit",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "events" in data
    assert isinstance(data["events"], list)


# Scenario 8: Engineer cannot read audit log
def test_engineer_cannot_read_audit(client: TestClient, engineer_token: str):
    resp = client.get(
        "/api/v1/diagnostics/audit",
        headers={"Authorization": f"Bearer {engineer_token}"},
    )
    assert resp.status_code == 403


# Scenario 9: Audit log pagination works
def test_audit_pagination(client: TestClient, admin_token: str):
    resp = client.get(
        "/api/v1/diagnostics/audit?limit=5&offset=0",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["limit"] == 5


# Scenario 10: WS connection count endpoint
def test_ws_connections_endpoint(client: TestClient, engineer_token: str):
    resp = client.get(
        "/api/v1/diagnostics/ws-connections",
        headers={"Authorization": f"Bearer {engineer_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "total" in data
    assert "by_channel" in data


# Scenario 11: Robot status health summary
def test_robot_status_health(client: TestClient, viewer_token: str):
    resp = client.get(
        "/api/v1/robot/status/health",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "overall_health" in data
    assert "is_online" in data


# Scenario 12: Robot safety state endpoint
def test_robot_safety_state(client: TestClient, viewer_token: str):
    resp = client.get(
        "/api/v1/robot/status/safety",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert resp.status_code == 200
    assert "state" in resp.json()["data"]


# Scenario 13: Robot battery endpoint
def test_robot_battery(client: TestClient, viewer_token: str):
    resp = client.get(
        "/api/v1/robot/status/battery",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert resp.status_code == 200
    assert "percentage" in resp.json()["data"]


def test_robot_performance(client: TestClient, viewer_token: str):
    resp = client.get(
        "/api/v1/robot/status/performance",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "cpu_percent" in data
    assert "memory_percent" in data
    assert "load_level" in data


# Scenario 14: Full robot status
def test_full_robot_status(client: TestClient, viewer_token: str):
    resp = client.get(
        "/api/v1/robot/status",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "safety" in data
    assert "battery" in data
    assert "navigation" in data


# Scenario 15: Aggregator offline detection
def test_aggregator_offline_by_default(aggregator):
    assert aggregator.is_online() is False


# Scenario 16: Aggregator online after heartbeat
def test_aggregator_online_after_update(aggregator):
    aggregator.mark_heartbeat()
    assert aggregator.is_online() is True


# Scenario 17: Module update reflected in status
def test_module_update_reflected(aggregator):
    aggregator.update_module(
        "bonbon_tts", {"state": "active", "health": "healthy", "message": "OK"}
    )
    status = aggregator.get_status()
    assert "bonbon_tts" in status.modules
    assert status.modules["bonbon_tts"].state == "active"


# Scenario 18: Safety state update reflected
def test_safety_state_update(aggregator):
    aggregator.update_safety({"state": "safety_stop", "active_faults": ["fault_1"]})
    assert aggregator.get_safety_state() == "safety_stop"


# Scenario 19b: Performance update reflected
def test_performance_update(aggregator):
    aggregator.update_performance(
        {
            "cpu_percent": 42.0,
            "memory_percent": 60.0,
            "load_level": "reduced",
            "degraded_mode_active": False,
        }
    )
    status = aggregator.get_status()
    assert status.performance.cpu_percent == 42.0
    assert status.performance.load_level == "reduced"


# Scenario 19: Navigation state update reflected
def test_navigation_update(aggregator):
    aggregator.update_navigation(
        {"state": "navigating", "current_x": 5.0, "current_y": 3.0, "current_yaw": 0.0}
    )
    status = aggregator.get_status()
    assert status.navigation.state == "navigating"
    assert status.navigation.current_x == 5.0


# Scenario 20: Health endpoint unauthenticated (public)
def test_health_endpoint_public(client: TestClient):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert "status" in resp.json()
