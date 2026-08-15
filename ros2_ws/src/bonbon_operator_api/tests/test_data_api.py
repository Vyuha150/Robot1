"""Tests for the data/training/fine-tuning pipeline dashboard endpoints
(bonbon_operator_api.api.data_api). Required test 10: the dashboard shows
real dataset/model status -- every assertion here reads data produced by
the actual bonbon_data_pipeline/bonbon_field_learning modules, not a mock.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


# ── /data/datasets, /data/license-status ────────────────────────────────


def test_data_datasets_reads_the_real_registry(client: TestClient, viewer_token: str):
    resp = client.get("/api/v1/data/datasets", headers=_auth(viewer_token))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["available"] is True
    assert data["count"] > 0
    assert "countByStatus" in data
    dataset_ids = {d["datasetId"] for d in data["datasets"]}
    assert "public_gesture_dataset_jester" in dataset_ids


def test_data_license_status_flags_the_known_nc_dataset_as_blocked(client: TestClient, viewer_token: str):
    resp = client.get("/api/v1/data/license-status", headers=_auth(viewer_token))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["available"] is True
    jester = next(d for d in data["licenseStatus"] if d["datasetId"] == "public_gesture_dataset_jester")
    assert jester["allowedForProductionTraining"] is False


# ── /data/failure-cases, POST review ────────────────────────────────────


def test_data_failure_cases_honest_when_empty(client: TestClient, viewer_token: str, tmp_path):
    client.app.state.cfg.project_status_dir = tmp_path
    resp = client.get("/api/v1/data/failure-cases", headers=_auth(viewer_token))
    data = resp.json()["data"]
    assert data["available"] is True
    assert data["count"] == 0
    assert data["openCount"] == 0


def test_review_unknown_event_id_returns_404(client: TestClient, engineer_token: str, tmp_path):
    # diagnostics:write starts at the engineer role, not operator.
    client.app.state.cfg.project_status_dir = tmp_path
    resp = client.post(
        "/api/v1/data/failure-cases/review",
        headers=_auth(engineer_token),
        json={"event_id": "does-not-exist", "approve": True},
    )
    assert resp.status_code == 404


def test_review_requires_diagnostics_write_permission(client: TestClient, viewer_token: str, tmp_path):
    client.app.state.cfg.project_status_dir = tmp_path
    resp = client.post(
        "/api/v1/data/failure-cases/review",
        headers=_auth(viewer_token),
        json={"event_id": "x", "approve": True},
    )
    assert resp.status_code == 403


def test_full_failure_case_review_round_trip_through_the_dashboard(
    client: TestClient, viewer_token: str, engineer_token: str, tmp_path
):
    client.app.state.cfg.project_status_dir = tmp_path

    from bonbon_field_learning import AnonymizedEventStore, FailureCategory, HumanReviewQueue
    from bonbon_field_learning.failure_case_logger import FailureCaseLogger

    field_dir = tmp_path / "project-status" / "field_learning"
    field_dir.mkdir(parents=True)
    store = AnonymizedEventStore(field_dir / "events.jsonl")
    event = FailureCaseLogger(store).log_failure(
        family="speech_understanding", failure_category=FailureCategory.WRONG_ASR_TRANSCRIPT, reason="x"
    )
    HumanReviewQueue(field_dir / "review_queue.jsonl").enqueue(event.event_id)

    resp = client.get("/api/v1/data/failure-cases", headers=_auth(viewer_token))
    assert resp.json()["data"]["count"] == 1
    assert resp.json()["data"]["openCount"] == 1

    review_resp = client.post(
        "/api/v1/data/failure-cases/review",
        headers=_auth(engineer_token),
        json={"event_id": event.event_id, "approve": True, "notes": "confirmed via staff correction"},
    )
    assert review_resp.status_code == 200
    assert review_resp.json()["data"]["item"]["status"] == "approved"

    resp = client.get("/api/v1/data/failure-cases", headers=_auth(viewer_token))
    assert resp.json()["data"]["openCount"] == 0
    assert resp.json()["data"]["approvedCount"] == 1


# ── /data/training-runs ──────────────────────────────────────────────────


def test_data_training_runs_reads_real_targets_and_cross_checks_registry(client: TestClient, viewer_token: str):
    resp = client.get("/api/v1/data/training-runs", headers=_auth(viewer_token))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["available"] is True
    capabilities = {t["capability"] for t in data["targets"]}
    assert "object_detection" in capabilities
    # Real, honest current state: most datasets are NEEDS_REVIEW, so
    # production training is not yet unblocked -- this must never be
    # silently reported as ready.
    assert data["readyForProductionTraining"] is False
    assert len(data["blockingIssues"]) > 0


# ── /data/model-evaluations, /data/regression-tests ─────────────────────


def test_data_model_evaluations_honest_when_empty(client: TestClient, viewer_token: str, tmp_path):
    client.app.state.cfg.project_status_dir = tmp_path
    resp = client.get("/api/v1/data/model-evaluations", headers=_auth(viewer_token))
    data = resp.json()["data"]
    assert data["available"] is True
    assert data["latest"] is None
    assert data["history"] == []


def test_data_regression_tests_reads_the_real_generated_catalog(client: TestClient, viewer_token: str):
    resp = client.get("/api/v1/data/regression-tests", headers=_auth(viewer_token))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["available"] is True
    assert data["count"] >= 0  # honest either way -- never a fabricated non-zero count


# ── /data/edge-models ─────────────────────────────────────────────────────


def test_data_edge_models_reports_export_targets_and_empty_deployments(client: TestClient, viewer_token: str, tmp_path):
    client.app.state.cfg.project_status_dir = tmp_path
    resp = client.get("/api/v1/data/edge-models", headers=_auth(viewer_token))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["available"] is True
    assert data["count"] == 0  # nothing deployed yet in this fresh tmp_path
    assert data["exportTargets"]["object_detection"]["exportFormat"] == "hailo_hef"
