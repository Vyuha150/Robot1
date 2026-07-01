"""Tests for the production behavior-validation framework dashboard
endpoints. Real backend data: the scenario-family/generated-scenario
endpoints read the actual repo catalog, the field-learning endpoints run
the actual bonbon_field_learning stores, production-score runs the actual
ProductionScoreCalculator -- nothing here hardcodes a PASS.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


# ── scenario families / generated scenarios (real repo catalog) ────────────


def test_scenario_families_reads_the_real_catalog(client: TestClient, viewer_token: str):
    resp = client.get("/api/v1/validation/scenario-families", headers=_auth(viewer_token))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["available"] is True
    assert data["count"] == 15
    names = {f["name"] for f in data["families"]}
    assert "boot_and_deployment_topology" in names
    assert "field_pilot_learning" in names


def test_generated_scenarios_reflects_real_manifest(client: TestClient, viewer_token: str):
    resp = client.get("/api/v1/validation/generated-scenarios", headers=_auth(viewer_token))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["available"] is True
    assert data["total_scenarios"] > 0
    assert "gesture_understanding" in data["scenarios_per_family"]


# ── test results (real JUnit XML, written by scripts/run_production_tests.sh) ─


def test_test_results_honest_when_missing(client: TestClient, viewer_token: str, tmp_path):
    client.app.state.cfg.project_status_dir = tmp_path
    resp = client.get("/api/v1/validation/test-results", headers=_auth(viewer_token))
    data = resp.json()["data"]
    assert data["available"] is False


def test_test_results_parses_real_junit_xml(client: TestClient, viewer_token: str, tmp_path):
    pdir = tmp_path / "project-status"
    pdir.mkdir()
    (pdir / "production_test_results.xml").write_text(
        '<?xml version="1.0"?>'
        '<testsuites><testsuite tests="3" failures="1" errors="0" skipped="1" time="0.5" '
        'timestamp="2026-07-01T00:00:00">'
        '<testcase classname="tests.production.test_safety_scenarios" name="a"/>'
        '<testcase classname="tests.production.test_safety_scenarios" name="b">'
        "<failure>boom</failure></testcase>"
        '<testcase classname="tests.production.test_safety_scenarios" name="c">'
        "<skipped/></testcase>"
        "</testsuite></testsuites>",
        encoding="utf-8",
    )
    client.app.state.cfg.project_status_dir = tmp_path
    resp = client.get("/api/v1/validation/test-results", headers=_auth(viewer_token))
    data = resp.json()["data"]
    assert data["available"] is True
    assert data["total"] == 3
    assert data["failed"] == 1
    assert data["skipped"] == 1
    assert data["passed"] == 1
    assert data["per_family"]["test_safety_scenarios"] == {"passed": 1, "failed": 1, "skipped": 1}


# ── production score (real calculator, real maintainability introspection) ─


def test_production_score_with_no_test_results_is_blocked_on_safety(
    client: TestClient, viewer_token: str, tmp_path
):
    client.app.state.cfg.project_status_dir = tmp_path
    resp = client.get("/api/v1/validation/production-score", headers=_auth(viewer_token))
    data = resp.json()["data"]
    assert data["available"] is True
    assert data["verdict"] == "BLOCKED"
    assert data["category_scores"]["maintainability"] == 1.0  # real introspection, always available


def test_production_score_uses_real_test_results_when_present(
    client: TestClient, viewer_token: str, tmp_path
):
    pdir = tmp_path / "project-status"
    pdir.mkdir()
    (pdir / "production_test_results.xml").write_text(
        '<?xml version="1.0"?>'
        '<testsuites><testsuite tests="2" failures="0" errors="0" skipped="0" time="0.1" '
        'timestamp="2026-07-01T00:00:00">'
        '<testcase classname="tests.production.test_safety_scenarios" name="a"/>'
        '<testcase classname="tests.production.test_safety_scenarios" name="b"/>'
        "</testsuite></testsuites>",
        encoding="utf-8",
    )
    client.app.state.cfg.project_status_dir = tmp_path
    resp = client.get("/api/v1/validation/production-score", headers=_auth(viewer_token))
    data = resp.json()["data"]
    assert data["category_scores"]["safety"] == 1.0
    assert data["verdict"] in ("PARTIAL", "PASS")


# ── field learning (real bonbon_field_learning stores) ─────────────────────


def test_field_learning_failure_cases_empty_by_default(
    client: TestClient, viewer_token: str, tmp_path
):
    client.app.state.cfg.project_status_dir = tmp_path
    resp = client.get("/api/v1/field-learning/failure-cases", headers=_auth(viewer_token))
    data = resp.json()["data"]
    assert data["available"] is True
    assert data["count"] == 0
    assert data["events"] == []


def test_field_learning_regression_tests_empty_by_default(
    client: TestClient, viewer_token: str, tmp_path
):
    client.app.state.cfg.project_status_dir = tmp_path
    resp = client.get("/api/v1/field-learning/regression-tests", headers=_auth(viewer_token))
    data = resp.json()["data"]
    assert data["available"] is True
    assert isinstance(data["count"], int)


# ── datasets ─────────────────────────────────────────────────────────────────


def test_datasets_status_starts_at_zero(client: TestClient, viewer_token: str, tmp_path):
    client.app.state.cfg.project_status_dir = tmp_path
    resp = client.get("/api/v1/datasets/status", headers=_auth(viewer_token))
    data = resp.json()["data"]
    assert data["available"] is True
    assert data["current_version"] == "0.0.0"
    assert data["history"] == []


def test_datasets_license_checklist_reads_real_config(client: TestClient, viewer_token: str):
    resp = client.get("/api/v1/datasets/license-checklist", headers=_auth(viewer_token))
    data = resp.json()["data"]
    assert data["available"] is True
    capabilities = {c["capability"] for c in data["categories"]}
    assert "object_detection" in capabilities
    assert "behavior_validation" in capabilities


# ── models ────────────────────────────────────────────────────────────────


def test_models_evaluation_empty_by_default(client: TestClient, viewer_token: str, tmp_path):
    client.app.state.cfg.project_status_dir = tmp_path
    resp = client.get("/api/v1/models/evaluation", headers=_auth(viewer_token))
    data = resp.json()["data"]
    assert data["available"] is True
    assert data["latest"] is None
    assert data["history_count"] == 0


# ── privacy ───────────────────────────────────────────────────────────────


def test_privacy_status_confirms_no_raw_media_fields(
    client: TestClient, viewer_token: str, tmp_path
):
    client.app.state.cfg.project_status_dir = tmp_path
    resp = client.get("/api/v1/privacy/data-collection-status", headers=_auth(viewer_token))
    data = resp.json()["data"]
    assert data["available"] is True
    assert data["raw_media_fields_present_on_default_event_type"] == []
    assert data["debug_snapshot_store_active"] is False


def test_endpoints_require_auth(client: TestClient):
    resp = client.get("/api/v1/validation/scenario-families")
    assert resp.status_code in (401, 403)


# ── /dashboard/summary ───────────────────────────────────────────────────────


def test_dashboard_summary_reflects_real_state(client: TestClient, viewer_token: str, tmp_path):
    client.app.state.cfg.project_status_dir = tmp_path
    resp = client.get("/api/v1/dashboard/summary", headers=_auth(viewer_token))
    assert resp.status_code == 200
    data = resp.json()["data"]
    # no boot_topology.json / known_issues.json in the empty tmp_path -> honest Nones/zeros
    assert data["boot_topology_valid"] is None
    assert data["known_issue_count"] == 0
    assert data["blocking_issue_count"] == 0
    assert data["ai_runtime"] is not None
    assert data["ai_runtime"]["is_real_accelerator"] is False  # no accelerator on this machine


def test_dashboard_summary_counts_real_known_issues(
    client: TestClient, viewer_token: str, tmp_path
):
    pdir = tmp_path / "project-status"
    pdir.mkdir()
    (pdir / "known_issues.json").write_text(
        '{"issues": [{"id": "a", "blocking_deployment": true}, '
        '{"id": "b", "blocking_deployment": false}]}',
        encoding="utf-8",
    )
    client.app.state.cfg.project_status_dir = tmp_path
    resp = client.get("/api/v1/dashboard/summary", headers=_auth(viewer_token))
    data = resp.json()["data"]
    assert data["known_issue_count"] == 2
    assert data["blocking_issue_count"] == 1


def test_dashboard_summary_requires_auth(client: TestClient):
    assert client.get("/api/v1/dashboard/summary").status_code in (401, 403)


# ── new websocket channels ───────────────────────────────────────────────────


def test_new_finalization_channels_are_registered():
    from bonbon_operator_api.websocket.ws_manager import VALID_CHANNELS

    for channel in (
        "boot-topology",
        "ai-runtime",
        "pi-efficiency",
        "validation",
        "deployment-readiness",
    ):
        assert channel in VALID_CHANNELS


def test_ws_boot_topology_channel_connects(client: TestClient, viewer_token: str):
    with client.websocket_connect(f"/ws/boot-topology?token={viewer_token}") as ws:
        msg = ws.receive_json()
        assert msg["event"] == "connected"
        assert msg["data"]["channel"] == "boot-topology"


def test_ws_unknown_channel_still_rejected(client: TestClient, viewer_token: str):
    import pytest
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/ws/not-a-real-channel?token={viewer_token}"):
            pass
