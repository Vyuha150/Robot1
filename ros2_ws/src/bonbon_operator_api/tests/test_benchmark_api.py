"""Tests for the efficiency-benchmarking dashboard endpoints
(bonbon_operator_api.api.benchmark_api). Every assertion reads data
produced by an actual bonbon_benchmarks run, not a mock.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_status_honest_when_no_run_has_happened(client: TestClient, viewer_token: str, tmp_path):
    client.app.state.cfg.project_status_dir = tmp_path
    resp = client.get("/api/v1/benchmarks/status", headers=_auth(viewer_token))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["available"] is False


def test_latest_honest_when_no_run_has_happened(client: TestClient, viewer_token: str, tmp_path):
    client.app.state.cfg.project_status_dir = tmp_path
    resp = client.get("/api/v1/benchmarks/latest", headers=_auth(viewer_token))
    assert resp.json()["data"]["available"] is False


def test_history_is_empty_list_not_error_when_no_run_has_happened(client: TestClient, viewer_token: str, tmp_path):
    client.app.state.cfg.project_status_dir = tmp_path
    resp = client.get("/api/v1/benchmarks/history", headers=_auth(viewer_token))
    data = resp.json()["data"]
    assert data["available"] is True
    assert data["count"] == 0
    assert data["runs"] == []


def test_run_requires_diagnostics_write_permission(client: TestClient, viewer_token: str, tmp_path):
    client.app.state.cfg.project_status_dir = tmp_path
    resp = client.post("/api/v1/benchmarks/run", headers=_auth(viewer_token), json={"categories": ["resource"]})
    assert resp.status_code == 403


def test_run_rejects_unknown_category(client: TestClient, engineer_token: str, tmp_path):
    client.app.state.cfg.project_status_dir = tmp_path
    resp = client.post(
        "/api/v1/benchmarks/run", headers=_auth(engineer_token), json={"categories": ["not_a_real_category"]}
    )
    assert resp.status_code == 400


def test_run_executes_a_real_benchmark_and_persists_it(client: TestClient, viewer_token: str, engineer_token: str, tmp_path):
    client.app.state.cfg.project_status_dir = tmp_path

    run_resp = client.post(
        "/api/v1/benchmarks/run", headers=_auth(engineer_token),
        json={"categories": ["resource", "cache_efficiency"]},
    )
    assert run_resp.status_code == 200
    assert run_resp.json()["data"]["triggered"] is True
    assert "summary" in run_resp.json()["data"]

    status_resp = client.get("/api/v1/benchmarks/status", headers=_auth(viewer_token))
    status = status_resp.json()["data"]
    assert status["available"] is True
    assert set(status["categoriesRun"]) == {"resource", "cache_efficiency"}

    latest_resp = client.get("/api/v1/benchmarks/latest", headers=_auth(viewer_token))
    latest = latest_resp.json()["data"]
    assert latest["available"] is True
    assert len(latest["categories"]) == 2

    history_resp = client.get("/api/v1/benchmarks/history", headers=_auth(viewer_token))
    assert history_resp.json()["data"]["count"] == 1


def test_compare_needs_at_least_two_runs(client: TestClient, viewer_token: str, engineer_token: str, tmp_path):
    client.app.state.cfg.project_status_dir = tmp_path
    client.post("/api/v1/benchmarks/run", headers=_auth(engineer_token), json={"categories": ["resource"]})

    resp = client.get("/api/v1/benchmarks/compare", headers=_auth(viewer_token))
    assert resp.json()["data"]["available"] is False

    client.post("/api/v1/benchmarks/run", headers=_auth(engineer_token), json={"categories": ["resource"]})
    resp2 = client.get("/api/v1/benchmarks/compare", headers=_auth(viewer_token))
    assert resp2.json()["data"]["available"] is True


def test_production_score_reflects_a_real_run(client: TestClient, viewer_token: str, engineer_token: str, tmp_path):
    client.app.state.cfg.project_status_dir = tmp_path
    client.post(
        "/api/v1/benchmarks/run", headers=_auth(engineer_token),
        json={"categories": ["safety_under_load", "cache_efficiency"]},
    )
    resp = client.get("/api/v1/benchmarks/production-score", headers=_auth(viewer_token))
    data = resp.json()["data"]
    assert data["available"] is True
    assert data["verdict"] in ("PASS", "PARTIAL", "FAIL", "BLOCKED")
    assert "counts" in data


def test_safety_under_load_endpoint_reflects_a_real_run(client: TestClient, viewer_token: str, engineer_token: str, tmp_path):
    client.app.state.cfg.project_status_dir = tmp_path
    client.post("/api/v1/benchmarks/run", headers=_auth(engineer_token), json={"categories": ["safety_under_load"]})
    resp = client.get("/api/v1/benchmarks/safety-under-load", headers=_auth(viewer_token))
    data = resp.json()["data"]
    assert data["available"] is True
    assert data["category"] == "safety_under_load"
    assert len(data["metrics"]) > 0


def test_three_pi_endpoint_reflects_a_real_run(client: TestClient, viewer_token: str, engineer_token: str, tmp_path):
    client.app.state.cfg.project_status_dir = tmp_path
    client.post("/api/v1/benchmarks/run", headers=_auth(engineer_token), json={"categories": ["three_pi_network"]})
    resp = client.get("/api/v1/benchmarks/three-pi", headers=_auth(viewer_token))
    data = resp.json()["data"]
    assert data["available"] is True
    assert data["category"] == "three_pi_network"


def test_edge_ai_endpoint_honest_when_no_edge_ai_benchmark_has_run(client: TestClient, viewer_token: str, monkeypatch):
    import bonbon_operator_api.api.benchmark_api as mod

    monkeypatch.setattr(mod, "_EDGE_AI_RESULTS_PATH", mod._REPO_ROOT / "does" / "not" / "exist.json")
    resp = client.get("/api/v1/benchmarks/edge-ai", headers=_auth(viewer_token))
    assert resp.json()["data"]["available"] is False


def test_benchmarks_is_a_valid_websocket_channel():
    from bonbon_operator_api.websocket.ws_manager import VALID_CHANNELS
    from bonbon_operator_api.websocket.ws_router import _CHANNEL_MIN_PERMISSION

    assert "benchmarks" in VALID_CHANNELS
    assert _CHANNEL_MIN_PERMISSION["benchmarks"] == "diagnostics:read"
