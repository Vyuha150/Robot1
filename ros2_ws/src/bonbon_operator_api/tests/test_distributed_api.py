"""Tests for the three-Pi distributed status/API endpoints.

Real backend data: reads config/distributed/*.yaml and the ROS2 bridge's
DistributedStatusTracker snapshot (mocked here the same way every other
command test mocks the bridge) -- never a fabricated PASS.
"""

from __future__ import annotations

import yaml
from fastapi.testclient import TestClient


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _write_distributed_config(tmp_path, cfg_app):
    repo_root = tmp_path
    dist_dir = repo_root / "config" / "distributed"
    dist_dir.mkdir(parents=True)
    (dist_dir / "robot_network.yaml").write_text(
        yaml.safe_dump(
            {
                "deployment_mode": "three_pi",
                "pis": {
                    "pi1": {"role": "ui_api", "static_ip": "192.168.10.11"},
                    "pi2": {"role": "human_ai", "static_ip": "192.168.10.12"},
                    "pi3": {"role": "navigation_safety", "static_ip": "192.168.10.13"},
                },
            }
        )
    )
    (dist_dir / "pi_ui_api.yaml").write_text(
        yaml.safe_dump({"pi_role": "ui_api", "packages": ["bonbon_operator_dashboard"]})
    )
    (dist_dir / "pi_human_ai.yaml").write_text(
        yaml.safe_dump({"pi_role": "human_ai", "packages": ["bonbon_asr"]})
    )
    (dist_dir / "pi_navigation_safety.yaml").write_text(
        yaml.safe_dump({"pi_role": "navigation_safety", "packages": ["bonbon_safety_supervisor"]})
    )
    (dist_dir / "topic_contracts.yaml").write_text(yaml.safe_dump({"inter_pi_topics": []}))
    (dist_dir / "failure_policy.yaml").write_text(yaml.safe_dump({"policies": {}}))
    cfg_app.app.state.cfg.project_status_dir = repo_root / "devops"


# ── /distributed/status ──────────────────────────────────────────────────────


def test_distributed_status_honest_when_config_missing(
    client: TestClient, viewer_token: str, tmp_path
):
    client.app.state.cfg.project_status_dir = tmp_path / "devops"
    resp = client.get("/api/v1/distributed/status", headers=_auth(viewer_token))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["available"] is False


def test_distributed_status_reports_deployment_mode_when_present(
    client: TestClient, viewer_token: str, tmp_path
):
    _write_distributed_config(tmp_path, client)
    resp = client.get("/api/v1/distributed/status", headers=_auth(viewer_token))
    data = resp.json()["data"]
    assert data["available"] is True
    assert data["deployment_mode"] == "three_pi"
    assert set(data["pi_links"].keys()) == {"pi2", "pi3"}  # pi1 excluded, see snapshot builder


def test_distributed_status_reflects_bridge_snapshot(
    client: TestClient, viewer_token: str, tmp_path
):
    _write_distributed_config(tmp_path, client)
    client.app.state.ros2_bridge.get_distributed_snapshot.return_value = {
        "bridge_ready": True,
        "pi_links": {"pi1": "online", "pi2": "online", "pi3": "lost"},
        "last_approval": None,
        "last_rejection": None,
        "last_degraded_mode": None,
        "approval_count": 0,
        "rejection_count": 0,
    }
    resp = client.get("/api/v1/distributed/status", headers=_auth(viewer_token))
    data = resp.json()["data"]
    assert data["bridge_ready"] is True
    assert data["pi_links"]["pi3"] == "lost"


# ── /distributed/pi/{pi_id} ──────────────────────────────────────────────────


def test_distributed_pi_detail_unknown_pi_404s(client: TestClient, viewer_token: str):
    resp = client.get("/api/v1/distributed/pi/pi9", headers=_auth(viewer_token))
    assert resp.status_code == 404


def test_distributed_pi_detail_honest_when_profile_missing(
    client: TestClient, viewer_token: str, tmp_path
):
    client.app.state.cfg.project_status_dir = tmp_path / "devops"
    resp = client.get("/api/v1/distributed/pi/pi2", headers=_auth(viewer_token))
    data = resp.json()["data"]
    assert data["available"] is False
    assert data["pi_id"] == "pi2"


def test_distributed_pi_detail_returns_profile_when_present(
    client: TestClient, viewer_token: str, tmp_path
):
    _write_distributed_config(tmp_path, client)
    resp = client.get("/api/v1/distributed/pi/pi3", headers=_auth(viewer_token))
    data = resp.json()["data"]
    assert data["available"] is True
    assert data["pi_role"] == "navigation_safety"
    assert "bonbon_safety_supervisor" in data["packages"]


def test_distributed_pi1_link_state_is_always_online(
    client: TestClient, viewer_token: str, tmp_path
):
    _write_distributed_config(tmp_path, client)
    resp = client.get("/api/v1/distributed/pi/pi1", headers=_auth(viewer_token))
    data = resp.json()["data"]
    assert data["link_state"] == "online"


# ── /distributed/safety/approvals + /distributed/degraded-mode ──────────────


def test_safety_approvals_honest_when_no_data(client: TestClient, viewer_token: str):
    resp = client.get("/api/v1/distributed/safety/approvals", headers=_auth(viewer_token))
    data = resp.json()["data"]
    assert data["last_approval"] is None
    assert data["approval_count"] == 0


def test_safety_approvals_reflects_latest_decision(client: TestClient, viewer_token: str):
    client.app.state.ros2_bridge.get_distributed_snapshot.return_value = {
        "bridge_ready": True,
        "pi_links": {},
        "last_approval": {"decision": "approved", "event_id": "e1"},
        "last_rejection": None,
        "last_degraded_mode": None,
        "approval_count": 1,
        "rejection_count": 0,
    }
    resp = client.get("/api/v1/distributed/safety/approvals", headers=_auth(viewer_token))
    data = resp.json()["data"]
    assert data["last_approval"]["event_id"] == "e1"
    assert data["approval_count"] == 1


def test_degraded_mode_defaults_to_not_degraded_when_no_data(client: TestClient, viewer_token: str):
    resp = client.get("/api/v1/distributed/degraded-mode", headers=_auth(viewer_token))
    data = resp.json()["data"]
    assert data["is_degraded"] is False


# ── /distributed/topology, /topics, /failure-policy ─────────────────────────


def test_topology_honest_when_missing(client: TestClient, viewer_token: str, tmp_path):
    client.app.state.cfg.project_status_dir = tmp_path / "devops"
    resp = client.get("/api/v1/distributed/topology", headers=_auth(viewer_token))
    assert resp.json()["data"]["available"] is False


def test_topology_returns_full_network_config(client: TestClient, viewer_token: str, tmp_path):
    _write_distributed_config(tmp_path, client)
    resp = client.get("/api/v1/distributed/topology", headers=_auth(viewer_token))
    data = resp.json()["data"]
    assert data["available"] is True
    assert data["pis"]["pi3"]["static_ip"] == "192.168.10.13"


def test_topics_returns_contract_table(client: TestClient, viewer_token: str, tmp_path):
    _write_distributed_config(tmp_path, client)
    resp = client.get("/api/v1/distributed/topics", headers=_auth(viewer_token))
    data = resp.json()["data"]
    assert data["available"] is True
    assert "inter_pi_topics" in data


def test_failure_policy_returns_policy_document(client: TestClient, viewer_token: str, tmp_path):
    _write_distributed_config(tmp_path, client)
    resp = client.get("/api/v1/distributed/failure-policy", headers=_auth(viewer_token))
    data = resp.json()["data"]
    assert data["available"] is True
    assert "policies" in data


# ── POST /distributed/operator-proposal ──────────────────────────────────────


def test_operator_proposal_requires_navigate_permission(client: TestClient, viewer_token: str):
    resp = client.post(
        "/api/v1/distributed/operator-proposal",
        json={"proposal_type": "speak", "proposal_content": "hello"},
        headers=_auth(viewer_token),
    )
    assert resp.status_code == 403


def test_operator_proposal_accepted_publishes_via_bridge(client: TestClient, operator_token: str):
    resp = client.post(
        "/api/v1/distributed/operator-proposal",
        json={"proposal_type": "speak", "proposal_content": "hello", "urgency": 0.1},
        headers=_auth(operator_token),
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["accepted"] is True
    client.app.state.ros2_bridge.call_operator_proposal.assert_called_once()


def test_operator_proposal_rejects_unknown_type(client: TestClient, operator_token: str):
    resp = client.post(
        "/api/v1/distributed/operator-proposal",
        json={"proposal_type": "do_a_backflip"},
        headers=_auth(operator_token),
    )
    assert resp.status_code == 422  # pydantic pattern validation


def test_operator_proposal_reports_bridge_dispatch_failure(client: TestClient, operator_token: str):
    client.app.state.ros2_bridge.call_operator_proposal.return_value = {
        "success": False,
        "error": "bridge not ready",
    }
    resp = client.post(
        "/api/v1/distributed/operator-proposal",
        json={"proposal_type": "navigate", "proposal_content": "goal_a"},
        headers=_auth(operator_token),
    )
    assert resp.status_code == 503
