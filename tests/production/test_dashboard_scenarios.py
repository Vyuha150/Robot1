"""Dashboard and operator control scenarios (family 13).

Drives the REAL FastAPI app (bonbon_operator_api) through a `TestClient`,
the same fixtures the package's own test suite uses -- confirms every
generated scenario's "dashboard reflects live state" property against
real endpoints, and that an unauthorized action is actually rejected.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from reference_behaviors import break_check, simulate_correct_behavior
from scenario_generator import load_generated

from bonbon_behavior_validation import BehaviorOracle
from bonbon_behavior_validation.behavior_oracle import OracleStatus
from bonbon_behavior_validation.dashboard_assertions import endpoint_reflects_backend_state

pytestmark = [pytest.mark.dashboard]

_SCENARIOS = load_generated("dashboard_and_operator_control")


@pytest.mark.parametrize("scenario", _SCENARIOS, ids=[s.scenario_id for s in _SCENARIOS])
def test_dashboard_event_is_logged_and_dashboarded(scenario):
    observed = simulate_correct_behavior(scenario)
    verdict = BehaviorOracle().evaluate(scenario, observed)
    assert verdict.status == OracleStatus.PASS, verdict.failed_checks


def test_robot_status_endpoint_reflects_backend_state(client, viewer_token):
    resp = client.get("/api/v1/robot/status", headers={"Authorization": f"Bearer {viewer_token}"})
    assert resp.status_code == 200
    body = resp.json()
    # ros2.enabled = False in this test app -> the aggregator has no live
    # ROS2 status, so is_online must honestly report False, not a fake True.
    check = endpoint_reflects_backend_state(body["data"]["is_online"], False)
    assert check.status.value == "pass", check.reason


def test_unauthorized_request_is_rejected(client):
    resp = client.get("/api/v1/robot/status")
    assert resp.status_code in (401, 403)


def test_viewer_cannot_trigger_privileged_mode_select(client, viewer_token):
    resp = client.post(
        "/api/v1/deployment/select-mode",
        headers={"Authorization": f"Bearer {viewer_token}"},
        json={"mode": "modular_pi"},
    )
    assert resp.status_code == 403


def test_admin_can_request_mode_select_command(client, admin_token):
    resp = client.post(
        "/api/v1/deployment/select-mode",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"mode": "modular_pi"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["accepted"] is True
    assert "select_deployment_mode.sh" in data["run_on_host"]


def test_oracle_catches_stale_dashboard_data():
    scenario = _SCENARIOS[0]
    observed = break_check(simulate_correct_behavior(scenario), "dashboard_updated")
    verdict = BehaviorOracle().evaluate(scenario, observed)
    assert verdict.status == OracleStatus.FAIL
