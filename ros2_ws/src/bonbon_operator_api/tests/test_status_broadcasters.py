"""Unit tests for the 5 finalization-mode WebSocket snapshot builders.
Each is exercised directly against a minimal fake `app` (just needs
`.state.cfg.project_status_dir` and, for pi-efficiency/deployment-
readiness, `.state.status_aggregator`) so these don't need a full
TestClient/lifespan just to prove the snapshot shape is real, not fabricated.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from bonbon_operator_api.ros2.status_aggregator import RobotStatusAggregator
from bonbon_operator_api.websocket.status_broadcasters import (
    CHANNEL_SNAPSHOTS,
    ai_runtime_snapshot,
    boot_topology_snapshot,
    degraded_mode_snapshot,
    deployment_readiness_snapshot,
    distributed_status_snapshot,
    pi1_status_snapshot,
    pi_efficiency_snapshot,
    pi_status_snapshot,
    safety_approvals_snapshot,
    validation_snapshot,
)

_EMPTY_DISTRIBUTED_SNAPSHOT = {
    "bridge_ready": False,
    "pi_links": {"pi1": "lost", "pi2": "lost", "pi3": "lost"},
    "last_approval": None,
    "last_rejection": None,
    "last_degraded_mode": None,
    "approval_count": 0,
    "rejection_count": 0,
}


@pytest.fixture
def fake_app(tmp_path):
    aggregator = RobotStatusAggregator(offline_timeout_sec=15.0)
    cfg = SimpleNamespace(project_status_dir=tmp_path)
    bridge = MagicMock()
    bridge.get_distributed_snapshot.return_value = dict(_EMPTY_DISTRIBUTED_SNAPSHOT)
    return SimpleNamespace(
        state=SimpleNamespace(cfg=cfg, status_aggregator=aggregator, ros2_bridge=bridge)
    )


def test_all_channel_snapshots_registered():
    assert set(CHANNEL_SNAPSHOTS) == {
        "boot-topology",
        "ai-runtime",
        "pi-efficiency",
        "validation",
        "deployment-readiness",
        # Three-Pi distributed channels (docs/DISTRIBUTED_TOPIC_SERVICE_CONTRACT.md)
        "distributed-status",
        "pi1-status",
        "pi2-status",
        "pi3-status",
        "safety-approvals",
        "safety-rejections",
        "degraded-mode",
        "component-health",
        # AI model registry / speech / Sarvam / perception / affective status
        # -- see websocket/ai_model_snapshots.py and docs/AI_MODEL_GAP_ANALYSIS.md
        "ai-models",
        "speech-ai",
        "sarvam",
        "perception-ai",
        "affective-ai",
        # Edge AI Runtime brief Phase 12 -- see websocket/edge_ai_snapshots.py
        "edge-ai-status",
        "edge-ai-models",
        "edge-ai-routes",
        "edge-ai-resources",
        "edge-ai-safety",
        "edge-ai-cache",
        # bonbon_hardware_telemetry -- see websocket/hardware_telemetry_snapshots.py
        "hardware-telemetry",
    }


def test_boot_topology_snapshot_honest_when_missing(fake_app):
    snap = boot_topology_snapshot(fake_app)
    assert snap["available"] is False


def test_boot_topology_snapshot_reads_real_file(fake_app):
    pdir = fake_app.state.cfg.project_status_dir / "project-status"
    pdir.mkdir()
    (pdir / "boot_topology.json").write_text(
        '{"mode": "modular_pi", "valid": true}', encoding="utf-8"
    )
    snap = boot_topology_snapshot(fake_app)
    assert snap["available"] is True
    assert snap["valid"] is True


def test_ai_runtime_snapshot_is_never_a_fake_hailo_pass(fake_app):
    snap = ai_runtime_snapshot(fake_app)
    assert snap["available"] is True
    # No real accelerator on this dev machine -- must not claim hailo.
    assert snap["selected_kind"] != "hailo"
    assert snap["fallback_active"] is True


def test_pi_efficiency_snapshot_includes_live_perf(fake_app):
    snap = pi_efficiency_snapshot(fake_app)
    assert "live" in snap
    assert isinstance(snap["live"], dict)


def test_validation_snapshot_reflects_real_catalog(fake_app):
    snap = validation_snapshot(fake_app)
    assert snap["available"] is True
    assert snap["total_scenarios"] > 0
    assert "gesture_understanding" in snap["scenarios_per_family"]


def test_deployment_readiness_snapshot_honest_with_no_issues_file(fake_app):
    snap = deployment_readiness_snapshot(fake_app)
    assert snap["blocking_issue_count"] == 0
    assert isinstance(snap["ready"], bool)


def test_deployment_readiness_snapshot_reflects_blocking_issues(fake_app):
    pdir = fake_app.state.cfg.project_status_dir / "project-status"
    pdir.mkdir()
    (pdir / "known_issues.json").write_text(
        '{"issues": [{"id": "x", "blocking_deployment": true}]}', encoding="utf-8"
    )
    snap = deployment_readiness_snapshot(fake_app)
    assert snap["blocking_issue_count"] == 1
    assert snap["ready"] is False
    assert "blocking issue" in snap["reasons"][0]


# ── Three-Pi distributed channels ────────────────────────────────────────────
# These read the REAL config/distributed/*.yaml (via status_broadcasters'
# module-level _REPO_ROOT), same as ai_runtime_snapshot/pi_efficiency_snapshot
# above read the real config/ directory rather than fake_app's tmp_path --
# only the bridge (peer liveness/approvals) is mocked, per fake_app fixture.


def test_distributed_status_snapshot_reads_real_network_config(fake_app):
    snap = distributed_status_snapshot(fake_app)
    assert snap["available"] is True
    assert snap["deployment_mode"] == "three_pi"
    assert set(snap["pi_links"].keys()) == {"pi2", "pi3"}


def test_pi1_status_snapshot_is_trivially_online(fake_app):
    snap = pi1_status_snapshot(fake_app)
    assert snap["pi_id"] == "pi1"
    assert snap["link_state"] == "online"


def test_pi_status_snapshot_reflects_bridge_link_state(fake_app):
    fake_app.state.ros2_bridge.get_distributed_snapshot.return_value = {
        **_EMPTY_DISTRIBUTED_SNAPSHOT,
        "bridge_ready": True,
        "pi_links": {"pi1": "online", "pi2": "online", "pi3": "stale"},
    }
    snap = pi_status_snapshot("pi3")(fake_app)
    assert snap["pi_id"] == "pi3"
    assert snap["link_state"] == "stale"
    assert snap["bridge_ready"] is True


def test_safety_approvals_snapshot_honest_when_no_data(fake_app):
    snap = safety_approvals_snapshot(fake_app)
    assert snap["last_approval"] is None
    assert snap["approval_count"] == 0


def test_degraded_mode_snapshot_defaults_to_not_degraded(fake_app):
    snap = degraded_mode_snapshot(fake_app)
    assert snap["is_degraded"] is False
