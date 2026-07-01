"""Tests for the deployment / AI-runtime / Pi-efficiency dashboard endpoints.

Real backend data, no fabricated PASS: the AI-runtime endpoints run the
actual RuntimeSelector (which on this no-accelerator machine reports a
mock/cpu fallback, never a fake Hailo PASS), and the deployment endpoints
read the real config/boot-topology files.
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


# ── Boot topology ────────────────────────────────────────────────────────────
def test_boot_topology_reports_when_file_present(client: TestClient, viewer_token: str, tmp_path):
    # Write a verdict file into a temp project-status dir.
    pdir = tmp_path / "project-status"
    pdir.mkdir()
    (pdir / "boot_topology.json").write_text(
        json.dumps(
            {
                "mode": "invalid",
                "valid": False,
                "duplicate_safety_detected": True,
                "remediation": "bash scripts/enable_modular_pi_mode.sh",
            }
        )
    )
    client.app.state.cfg.project_status_dir = tmp_path
    resp = client.get("/api/v1/deployment/boot-topology", headers=_auth(viewer_token))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["available"] is True
    assert data["duplicate_safety_detected"] is True


def test_boot_topology_honest_when_missing(client: TestClient, viewer_token: str, tmp_path):
    client.app.state.cfg.project_status_dir = tmp_path
    resp = client.get("/api/v1/deployment/boot-topology", headers=_auth(viewer_token))
    data = resp.json()["data"]
    assert data["available"] is False
    assert "validate_boot_topology" in data["message"]


def test_duplicate_node_check(client: TestClient, viewer_token: str, tmp_path):
    pdir = tmp_path / "project-status"
    pdir.mkdir()
    (pdir / "boot_topology.json").write_text(
        json.dumps({"duplicate_safety_detected": False, "observed_safety_supervisors": 1})
    )
    client.app.state.cfg.project_status_dir = tmp_path
    resp = client.get("/api/v1/deployment/duplicate-node-check", headers=_auth(viewer_token))
    data = resp.json()["data"]
    assert data["available"] is True
    assert data["duplicate_safety_detected"] is False


# ── Select mode ──────────────────────────────────────────────────────────────
def test_select_mode_returns_host_command(client: TestClient, admin_token: str):
    resp = client.post(
        "/api/v1/deployment/select-mode",
        json={"mode": "modular_pi"},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["accepted"] is True
    assert "select_deployment_mode.sh modular_pi" in data["run_on_host"]


def test_select_mode_rejects_invalid(client: TestClient, admin_token: str):
    resp = client.post(
        "/api/v1/deployment/select-mode",
        json={"mode": "bogus"},
        headers=_auth(admin_token),
    )
    data = resp.json()["data"]
    assert data["accepted"] is False


# ── AI runtime (real selection, honest fallback) ─────────────────────────────
def test_ai_runtime_status_is_honest(client: TestClient, viewer_token: str):
    resp = client.get("/api/v1/ai-runtime/status", headers=_auth(viewer_token))
    assert resp.status_code == 200
    data = resp.json()["data"]
    # bonbon_ai_runtime is on the test path; with no accelerator it must
    # report a fallback, never a fake hailo PASS.
    if data.get("available"):
        assert data["selected_kind"] in ("mock", "cpu")
        assert "chain" in data


def test_ai_runtime_models_mapping(client: TestClient, viewer_token: str):
    resp = client.get("/api/v1/ai-runtime/models", headers=_auth(viewer_token))
    data = resp.json()["data"]
    if data.get("available"):
        assert "object_detection" in data["models"]


def test_ai_runtime_benchmark_flags_non_accelerator(client: TestClient, viewer_token: str):
    resp = client.get("/api/v1/ai-runtime/benchmark", headers=_auth(viewer_token))
    data = resp.json()["data"]
    if data.get("available"):
        # On dev: selected mock/cpu → is_real_accelerator must be False.
        assert data["is_real_accelerator"] is False
        assert data["fps"] >= 0


# ── Pi efficiency ────────────────────────────────────────────────────────────
def test_pi_efficiency_includes_live_perf(client: TestClient, viewer_token: str):
    resp = client.get("/api/v1/pi/efficiency", headers=_auth(viewer_token))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "live" in data
    assert "cpu_percent" in data["live"]
    if data.get("available"):
        assert "fps_limits" in data


def test_pi_degraded_mode(client: TestClient, viewer_token: str):
    resp = client.get("/api/v1/pi/degraded-mode", headers=_auth(viewer_token))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "degraded_mode_active" in data
    if data.get("available"):
        # safety must never be in the shed order
        assert "safety_supervisor" in data["never_disable"]
        assert "safety_supervisor" not in data["shed_order"]


def test_endpoints_require_auth(client: TestClient):
    for path in (
        "/api/v1/deployment/boot-topology",
        "/api/v1/ai-runtime/status",
        "/api/v1/pi/efficiency",
    ):
        assert client.get(path).status_code in (401, 403)


# ── Finalization-mode aliases ───────────────────────────────────────────────


def test_deployment_known_issues_matches_diagnostics_alias(client: TestClient, viewer_token: str):
    direct = client.get("/api/v1/diagnostics/known-issues", headers=_auth(viewer_token))
    alias = client.get("/api/v1/deployment/known-issues", headers=_auth(viewer_token))
    assert alias.status_code == 200
    assert alias.json()["data"] == direct.json()["data"]


def test_deployment_readiness_matches_diagnostics_alias(client: TestClient, viewer_token: str):
    direct = client.get("/api/v1/diagnostics/deployment-readiness", headers=_auth(viewer_token))
    alias = client.get("/api/v1/deployment/readiness", headers=_auth(viewer_token))
    assert alias.status_code == 200
    assert alias.json()["data"] == direct.json()["data"]


def test_finalization_aliases_require_auth(client: TestClient):
    for path in ("/api/v1/deployment/known-issues", "/api/v1/deployment/readiness"):
        assert client.get(path).status_code in (401, 403)
