"""Tests for the perception dashboard endpoints (bonbon_operator_api.api.perception_api)
-- Dashboard Perception Gap Report Phase 8. Verifies both the honest
"unavailable" path (no message received yet) and the "available" path
using data shaped exactly like ros2_bridge.py's real snapshot dicts.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


# ── Objects ──────────────────────────────────────────────────────────────────


def test_objects_status_honest_when_no_message_received(client: TestClient, viewer_token: str):
    client.app.state.ros2_bridge.get_perception_objects.return_value = ({}, None)
    resp = client.get("/api/v1/perception/objects/status", headers=_auth(viewer_token))
    assert resp.status_code == 200
    assert resp.json()["data"]["available"] is False


def test_objects_status_reports_real_data(client: TestClient, viewer_token: str):
    objects = {
        "obj_1": {"track_id": "obj_1", "class_name": "chair", "confidence": 0.9},
        "obj_2": {"track_id": "obj_2", "class_name": "wheelchair", "confidence": 0.8},
    }
    meta = {
        "total_count": 2,
        "is_degraded": False,
        "privacy_mode_active": False,
        "inference_ms": 12.5,
        "detector_backend": "yolo",
        "received_at": 123.0,
    }
    client.app.state.ros2_bridge.get_perception_objects.return_value = (objects, meta)
    resp = client.get("/api/v1/perception/objects/status", headers=_auth(viewer_token))
    data = resp.json()["data"]
    assert data["available"] is True
    assert data["count"] == 2
    assert data["detector_backend"] == "yolo"


def test_objects_classes_deduplicated(client: TestClient, viewer_token: str):
    objects = {
        "obj_1": {"track_id": "obj_1", "class_name": "chair", "confidence": 0.9},
        "obj_2": {"track_id": "obj_2", "class_name": "chair", "confidence": 0.7},
        "obj_3": {"track_id": "obj_3", "class_name": "table", "confidence": 0.6},
    }
    meta = {"total_count": 3, "is_degraded": False, "privacy_mode_active": False,
             "inference_ms": 10.0, "detector_backend": "yolo", "received_at": 1.0}
    client.app.state.ros2_bridge.get_perception_objects.return_value = (objects, meta)
    resp = client.get("/api/v1/perception/objects/classes", headers=_auth(viewer_token))
    assert resp.json()["data"]["classes"] == ["chair", "table"]


def test_objects_active_returns_object_list(client: TestClient, viewer_token: str):
    objects = {"obj_1": {"track_id": "obj_1", "class_name": "chair", "confidence": 0.9}}
    meta = {"total_count": 1, "is_degraded": False, "privacy_mode_active": False,
             "inference_ms": 10.0, "detector_backend": "yolo", "received_at": 1.0}
    client.app.state.ros2_bridge.get_perception_objects.return_value = (objects, meta)
    resp = client.get("/api/v1/perception/objects/active", headers=_auth(viewer_token))
    data = resp.json()["data"]
    assert data["available"] is True
    assert len(data["objects"]) == 1


# ── People ───────────────────────────────────────────────────────────────────


def test_people_status_honest_when_nobody_present(client: TestClient, viewer_token: str):
    client.app.state.ros2_bridge.get_perception_people.return_value = {}
    resp = client.get("/api/v1/perception/people/status", headers=_auth(viewer_token))
    data = resp.json()["data"]
    assert data["available"] is False
    assert data["active_count"] == 0


def test_people_status_splits_known_and_unknown(client: TestClient, viewer_token: str):
    people = {
        "ptrk_1": {"person_track_id": "ptrk_1", "known_person_id": "staff_42"},
        "ptrk_2": {"person_track_id": "ptrk_2", "known_person_id": ""},
    }
    client.app.state.ros2_bridge.get_perception_people.return_value = people
    resp = client.get("/api/v1/perception/people/status", headers=_auth(viewer_token))
    data = resp.json()["data"]
    assert data["available"] is True
    assert data["active_count"] == 2
    assert data["known_count"] == 1
    assert data["unknown_count"] == 1


def test_people_active_returns_list(client: TestClient, viewer_token: str):
    people = {"ptrk_1": {"person_track_id": "ptrk_1", "known_person_id": ""}}
    client.app.state.ros2_bridge.get_perception_people.return_value = people
    resp = client.get("/api/v1/perception/people/active", headers=_auth(viewer_token))
    data = resp.json()["data"]
    assert data["available"] is True
    assert data["people"][0]["person_track_id"] == "ptrk_1"


# ── Affective ────────────────────────────────────────────────────────────────


def test_affective_status_honest_when_no_data(client: TestClient, viewer_token: str):
    client.app.state.ros2_bridge.get_perception_affective.return_value = {}
    resp = client.get("/api/v1/perception/affective/status", headers=_auth(viewer_token))
    assert resp.json()["data"]["available"] is False


def test_affective_human_states_returns_per_person_data(client: TestClient, viewer_token: str):
    affective = {
        "p1": {"face": {"dominant_emotion": "happy"}, "fused": {"dominant_state": "engaged"}},
    }
    client.app.state.ros2_bridge.get_perception_affective.return_value = affective
    resp = client.get("/api/v1/perception/affective/human-states", headers=_auth(viewer_token))
    data = resp.json()["data"]
    assert data["available"] is True
    assert data["people"]["p1"]["fused"]["dominant_state"] == "engaged"


# ── Gestures ─────────────────────────────────────────────────────────────────


def test_gestures_status_honest_when_none_received(client: TestClient, viewer_token: str):
    client.app.state.ros2_bridge.get_perception_gestures.return_value = []
    resp = client.get("/api/v1/perception/gestures/status", headers=_auth(viewer_token))
    data = resp.json()["data"]
    assert data["available"] is False
    assert data["recent_count"] == 0


def test_gestures_status_reports_last_gesture_type(client: TestClient, viewer_token: str):
    gestures = [
        {"gesture_type": "wave", "person_track_id": "ptrk_1"},
        {"gesture_type": "pointing_at_object", "person_track_id": "ptrk_2"},
    ]
    client.app.state.ros2_bridge.get_perception_gestures.return_value = gestures
    resp = client.get("/api/v1/perception/gestures/status", headers=_auth(viewer_token))
    data = resp.json()["data"]
    assert data["available"] is True
    assert data["recent_count"] == 2
    assert data["last_gesture_type"] == "pointing_at_object"


def test_gestures_active_returns_list(client: TestClient, viewer_token: str):
    gestures = [{"gesture_type": "stop_palm", "safety_relevant": True}]
    client.app.state.ros2_bridge.get_perception_gestures.return_value = gestures
    resp = client.get("/api/v1/perception/gestures/active", headers=_auth(viewer_token))
    data = resp.json()["data"]
    assert data["available"] is True
    assert data["gestures"][0]["safety_relevant"] is True


# ── Human state ──────────────────────────────────────────────────────────────


def test_human_state_active_honest_when_none(client: TestClient, viewer_token: str):
    client.app.state.ros2_bridge.get_perception_human_state.return_value = {}
    resp = client.get("/api/v1/perception/human-state/active", headers=_auth(viewer_token))
    assert resp.json()["data"]["available"] is False


def test_human_state_active_returns_urgency(client: TestClient, viewer_token: str):
    states = {"ptrk_1": {"person_track_id": "ptrk_1", "urgency_level": 0.9}}
    client.app.state.ros2_bridge.get_perception_human_state.return_value = states
    resp = client.get("/api/v1/perception/human-state/active", headers=_auth(viewer_token))
    data = resp.json()["data"]
    assert data["available"] is True
    assert data["people"][0]["urgency_level"] == 0.9


# ── Efficiency ───────────────────────────────────────────────────────────────


def test_efficiency_status_honest_when_none_received(client: TestClient, viewer_token: str):
    client.app.state.ros2_bridge.get_perception_efficiency.return_value = None
    resp = client.get("/api/v1/perception/efficiency/status", headers=_auth(viewer_token))
    assert resp.json()["data"]["available"] is False


def test_efficiency_status_reports_real_metrics(client: TestClient, viewer_token: str):
    metrics = {"cpu_percent": 42.0, "load_level": "normal", "degraded_mode_active": False}
    client.app.state.ros2_bridge.get_perception_efficiency.return_value = metrics
    resp = client.get("/api/v1/perception/efficiency/status", headers=_auth(viewer_token))
    data = resp.json()["data"]
    assert data["available"] is True
    assert data["cpu_percent"] == 42.0


# ── Auth ─────────────────────────────────────────────────────────────────────


def test_perception_endpoint_requires_auth(client: TestClient):
    resp = client.get("/api/v1/perception/objects/status")
    assert resp.status_code in (401, 403)
