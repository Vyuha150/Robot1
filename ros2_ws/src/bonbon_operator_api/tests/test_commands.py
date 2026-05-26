"""Command API tests — speak, navigate, pause, resume, dock, cancel, e-stop."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Scenario 1: Operator issues emergency stop
# ---------------------------------------------------------------------------
def test_emergency_stop_accepted(client: TestClient, operator_token: str):
    resp = client.post(
        "/api/v1/robot/commands/emergency_stop",
        json={"reason": "Safety test"},
        headers={"Authorization": f"Bearer {operator_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["data"]["accepted"] is True


# ---------------------------------------------------------------------------
# Scenario 2: Emergency stop with empty reason rejected (validation)
# ---------------------------------------------------------------------------
def test_emergency_stop_empty_reason_rejected(client: TestClient, operator_token: str):
    resp = client.post(
        "/api/v1/robot/commands/emergency_stop",
        json={"reason": "   "},
        headers={"Authorization": f"Bearer {operator_token}"},
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Scenario 3: Speak command accepted
# ---------------------------------------------------------------------------
def test_speak_accepted(client: TestClient, operator_token: str):
    resp = client.post(
        "/api/v1/robot/commands/speak",
        json={"text": "Hello, welcome to BonBon!"},
        headers={"Authorization": f"Bearer {operator_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["accepted"] is True


# ---------------------------------------------------------------------------
# Scenario 4: Speak with blocked content rejected
# ---------------------------------------------------------------------------
def test_speak_blocked_content(client: TestClient, operator_token: str):
    resp = client.post(
        "/api/v1/robot/commands/speak",
        json={"text": "My password is secret123"},
        headers={"Authorization": f"Bearer {operator_token}"},
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Scenario 5: Speak text too long rejected
# ---------------------------------------------------------------------------
def test_speak_text_too_long(client: TestClient, operator_token: str):
    resp = client.post(
        "/api/v1/robot/commands/speak",
        json={"text": "x" * 501},
        headers={"Authorization": f"Bearer {operator_token}"},
    )
    assert resp.status_code == 422  # pydantic length validation


# ---------------------------------------------------------------------------
# Scenario 6: Navigate accepted with valid coords
# ---------------------------------------------------------------------------
def test_navigate_accepted(client: TestClient, operator_token: str):
    resp = client.post(
        "/api/v1/robot/commands/navigate",
        json={"goal_x": 5.0, "goal_y": 3.0},
        headers={"Authorization": f"Bearer {operator_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["accepted"] is True


# ---------------------------------------------------------------------------
# Scenario 7: Navigate with out-of-bounds coords rejected
# (500.0 passes pydantic ±1000 limit but fails CommandValidator ±200 limit → 400)
# ---------------------------------------------------------------------------
def test_navigate_out_of_bounds(client: TestClient, operator_token: str):
    resp = client.post(
        "/api/v1/robot/commands/navigate",
        json={"goal_x": 500.0, "goal_y": 0.0},
        headers={"Authorization": f"Bearer {operator_token}"},
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Scenario 8: Navigate with invalid speed rejected
# (pydantic catches out-of-range speed with 422 before CommandValidator)
# ---------------------------------------------------------------------------
def test_navigate_invalid_speed(client: TestClient, operator_token: str):
    resp = client.post(
        "/api/v1/robot/commands/navigate",
        json={"goal_x": 1.0, "goal_y": 1.0, "speed_limit_mps": 99.0},
        headers={"Authorization": f"Bearer {operator_token}"},
    )
    assert resp.status_code == 422  # pydantic le=1.5 catches it first


# ---------------------------------------------------------------------------
# Scenario 9: Navigate blocked during emergency stop
# ---------------------------------------------------------------------------
def test_navigate_blocked_during_emergency_stop(
    client: TestClient, operator_token: str, aggregator
):
    aggregator.update_safety({"state": "emergency_stop"})
    resp = client.post(
        "/api/v1/robot/commands/navigate",
        json={"goal_x": 1.0, "goal_y": 1.0},
        headers={"Authorization": f"Bearer {operator_token}"},
    )
    assert resp.status_code == 503
    # Restore
    aggregator.update_safety({"state": "normal"})


# ---------------------------------------------------------------------------
# Scenario 10: Emergency stop passes even during e-stop state
# ---------------------------------------------------------------------------
def test_emergency_stop_always_accepted_during_estop(
    client: TestClient, operator_token: str, aggregator
):
    aggregator.update_safety({"state": "emergency_stop"})
    resp = client.post(
        "/api/v1/robot/commands/emergency_stop",
        json={"reason": "Confirm stop"},
        headers={"Authorization": f"Bearer {operator_token}"},
    )
    assert resp.status_code == 200
    aggregator.update_safety({"state": "normal"})


# ---------------------------------------------------------------------------
# Scenario 11: Viewer cannot issue commands
# ---------------------------------------------------------------------------
def test_viewer_cannot_speak(client: TestClient, viewer_token: str):
    resp = client.post(
        "/api/v1/robot/commands/speak",
        json={"text": "Hello!"},
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Scenario 12: Pause accepted
# ---------------------------------------------------------------------------
def test_pause_accepted(client: TestClient, operator_token: str):
    resp = client.post(
        "/api/v1/robot/commands/pause",
        json={},
        headers={"Authorization": f"Bearer {operator_token}"},
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Scenario 13: Dock accepted
# ---------------------------------------------------------------------------
def test_dock_accepted(client: TestClient, operator_token: str):
    resp = client.post(
        "/api/v1/robot/commands/dock",
        json={"station_id": "dock_1"},
        headers={"Authorization": f"Bearer {operator_token}"},
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Scenario 14: Cancel task accepted
# ---------------------------------------------------------------------------
def test_cancel_task_accepted(client: TestClient, operator_token: str):
    resp = client.post(
        "/api/v1/robot/commands/cancel_task",
        json={},
        headers={"Authorization": f"Bearer {operator_token}"},
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Scenario 15: Duplicate command rejected
# ---------------------------------------------------------------------------
def test_duplicate_command_rejected(client: TestClient, operator_token: str, safety_gate):
    import uuid
    cmd_id = str(uuid.uuid4())
    # Manually register the command_id in the validator's dedup buffer
    safety_gate._validator.check_duplicate(cmd_id)

    # Now issue a command — it won't have the same ID since uuid4() is different,
    # but we can test by calling check_duplicate directly
    assert safety_gate._validator.check_duplicate(cmd_id) is True


# ---------------------------------------------------------------------------
# Scenario 16: Resume blocked during safety_stop
# ---------------------------------------------------------------------------
def test_resume_blocked_during_safety_stop(
    client: TestClient, operator_token: str, aggregator
):
    aggregator.update_safety({"state": "safety_stop"})
    resp = client.post(
        "/api/v1/robot/commands/resume",
        json={},
        headers={"Authorization": f"Bearer {operator_token}"},
    )
    assert resp.status_code == 503
    aggregator.update_safety({"state": "normal"})


# ---------------------------------------------------------------------------
# Scenario 17: Command without auth returns 401
# ---------------------------------------------------------------------------
def test_command_no_auth(client: TestClient):
    resp = client.post(
        "/api/v1/robot/commands/speak",
        json={"text": "Hello!"},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Scenario 18: ROS2 bridge is called on accepted command
# ---------------------------------------------------------------------------
def test_bridge_called_on_navigate(
    client: TestClient, operator_token: str, mock_bridge
):
    mock_bridge.call_navigate.reset_mock()
    client.post(
        "/api/v1/robot/commands/navigate",
        json={"goal_x": 2.0, "goal_y": 3.0},
        headers={"Authorization": f"Bearer {operator_token}"},
    )
    mock_bridge.call_navigate.assert_called_once()


# ---------------------------------------------------------------------------
# Scenario 19: Command response includes command_id
# ---------------------------------------------------------------------------
def test_command_response_has_command_id(client: TestClient, operator_token: str):
    resp = client.post(
        "/api/v1/robot/commands/speak",
        json={"text": "Test speech"},
        headers={"Authorization": f"Bearer {operator_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "command_id" in data
    assert len(data["command_id"]) == 36  # UUID format


# ---------------------------------------------------------------------------
# Scenario 20: Speak blocked when robot in unknown safety state passes
# ---------------------------------------------------------------------------
def test_speak_passes_in_unknown_safety_state(
    client: TestClient, operator_token: str, aggregator
):
    """Speak should not be blocked in 'unknown' state (only navigate/dock/resume are)."""
    aggregator.update_safety({"state": "unknown"})
    resp = client.post(
        "/api/v1/robot/commands/speak",
        json={"text": "This should work"},
        headers={"Authorization": f"Bearer {operator_token}"},
    )
    assert resp.status_code == 200
    aggregator.update_safety({"state": "normal"})
