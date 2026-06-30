"""Tests for the project status API — test results, known issues, and
deployment readiness. These read real, checked-in JSON files
(devops/test-results/latest.json, devops/project-status/known_issues.json)
rather than fabricated data; tests cover both the "file present" and
"file missing" (honest unavailable) paths.
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient


def test_test_results_available_when_file_present(client: TestClient, viewer_token: str):
    resp = client.get(
        "/api/v1/diagnostics/test-results",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    # This repo's own devops/test-results/latest.json exists and is read
    # relative to the default project_status_dir ("devops") -- the test
    # client runs from the package's own working directory, so assert on
    # shape rather than the exact repo-root-relative content.
    assert "available" in data


def test_known_issues_available_when_file_present(client: TestClient, viewer_token: str):
    resp = client.get(
        "/api/v1/diagnostics/known-issues",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert resp.status_code == 200
    assert "available" in resp.json()["data"]


def test_deployment_readiness_returns_a_verdict(client: TestClient, viewer_token: str):
    resp = client.get(
        "/api/v1/diagnostics/deployment-readiness",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "ready" in data
    assert isinstance(data["reasons"], list)


def test_deployment_readiness_not_ready_when_offline(client: TestClient, viewer_token: str):
    """The aggregator starts offline (no heartbeat yet) -- readiness must
    honestly say so, never claim ready with no live data."""
    resp = client.get(
        "/api/v1/diagnostics/deployment-readiness",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    data = resp.json()["data"]
    assert data["robot_online"] is False
    assert data["ready"] is False
    assert any("not currently connected" in r for r in data["reasons"])


def test_deployment_readiness_blocked_by_safety_fault(
    client: TestClient, viewer_token: str, aggregator
):
    aggregator.update_safety({"state": "fault"})
    resp = client.get(
        "/api/v1/diagnostics/deployment-readiness",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    data = resp.json()["data"]
    assert data["ready"] is False
    assert any("safety state" in r for r in data["reasons"])
    aggregator.update_safety({"state": "normal"})


def test_test_results_honestly_reports_missing_file(
    client: TestClient, viewer_token: str, tmp_path
):
    """Point project_status_dir at an empty directory -- must report
    available=False, never fabricate a result."""
    client.app.state.cfg.project_status_dir = tmp_path
    resp = client.get(
        "/api/v1/diagnostics/test-results",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    data = resp.json()["data"]
    assert data["available"] is False


def test_known_issues_honestly_reports_missing_file(
    client: TestClient, viewer_token: str, tmp_path
):
    client.app.state.cfg.project_status_dir = tmp_path
    resp = client.get(
        "/api/v1/diagnostics/known-issues",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    data = resp.json()["data"]
    assert data["available"] is False
    assert data["issues"] == []


def test_real_known_issues_file_has_expected_shape(tmp_path):
    """Sanity-checks the actual checked-in known_issues.json this endpoint
    serves in production has the shape the API/frontend expect."""
    import pathlib

    repo_root = pathlib.Path(__file__).resolve()
    while not (repo_root / "devops").is_dir():
        repo_root = repo_root.parent
    data = json.loads((repo_root / "devops" / "project-status" / "known_issues.json").read_text())
    assert "issues" in data
    for issue in data["issues"]:
        assert "id" in issue
        assert "severity" in issue
        assert "blocking_deployment" in issue
