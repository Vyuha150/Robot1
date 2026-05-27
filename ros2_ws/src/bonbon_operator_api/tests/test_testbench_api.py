"""Testbench API tests."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_testbench_status_includes_all_panels(client: TestClient, viewer_token: str):
    resp = client.get(
        "/api/v1/testbench/status",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert {"speech", "vision", "llm", "tts", "system", "safety"} <= set(data)


def test_client_output_is_merged_into_status(client: TestClient, viewer_token: str):
    headers = {"Authorization": f"Bearer {viewer_token}"}
    resp = client.post(
        "/api/v1/testbench/client-output",
        json={
            "module": "speech",
            "status": "ok",
            "payload": {"audio_heard": True, "transcript": "hello bonbon", "api_key": "secret"},
        },
        headers=headers,
    )

    assert resp.status_code == 200
    assert resp.json()["data"]["payload"]["api_key"] == "[redacted]"

    status = client.get("/api/v1/testbench/status", headers=headers).json()["data"]
    assert status["speech"]["audio_heard"] is True
    assert status["speech"]["transcript"] == "hello bonbon"


def test_provider_catalog_documents_secret_policy(client: TestClient, viewer_token: str):
    resp = client.get(
        "/api/v1/testbench/providers",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "never stored" in data["secret_policy"]
    assert {item["id"] for item in data["providers"]} >= {
        "ollama",
        "deepgram",
        "elevenlabs",
        "roboflow",
    }


def test_cloud_provider_check_requires_key(client: TestClient, viewer_token: str):
    resp = client.post(
        "/api/v1/testbench/providers/check",
        json={"provider": "deepgram", "base_url": "https://api.deepgram.com/v1"},
        headers={"Authorization": f"Bearer {viewer_token}"},
    )

    assert resp.status_code == 400
    assert "api_key is required" in resp.json()["detail"]


def test_session_recording_analysis_and_redaction(client: TestClient, viewer_token: str):
    headers = {"Authorization": f"Bearer {viewer_token}"}
    start = client.post(
        "/api/v1/testbench/sessions",
        json={"title": "Regression run", "scenario": "low_light", "operator_notes": "test"},
        headers=headers,
    )
    assert start.status_code == 200
    session_id = start.json()["data"]["session_id"]

    event = client.post(
        f"/api/v1/testbench/sessions/{session_id}/events",
        json={
            "module": "vision",
            "event_type": "low_light_detection",
            "status": "fail",
            "summary": "Object was missed in low light",
            "failure_label": "low_light_false_negative",
            "metrics": {"latency_ms": 42, "token": "should-not-persist"},
            "payload": {"api_key": "secret", "object": "cart"},
        },
        headers=headers,
    )
    assert event.status_code == 200
    saved_event = event.json()["data"]
    assert saved_event["metrics"]["token"] == "[redacted]"
    assert saved_event["payload"]["api_key"] == "[redacted]"

    analysis = client.post(
        f"/api/v1/testbench/sessions/{session_id}/analysis",
        headers=headers,
    )
    assert analysis.status_code == 200
    data = analysis.json()["data"]
    assert data["failures"] == 1
    assert data["deployment_ready"] is False
    assert data["regression_candidates"][0]["failure_label"] == "low_light_false_negative"
