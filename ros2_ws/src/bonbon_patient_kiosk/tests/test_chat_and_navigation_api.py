from __future__ import annotations

from bonbon_patient_kiosk.models.facility_models import NamedLocationLabelUpsert


def test_chat_query_returns_llm_response(client, session_id, mock_bridge):
    resp = client.post(
        "/api/v1/chat/query", json={"session_id": session_id, "query_text": "Where is Cardiology?"}
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "ok"
    mock_bridge.call_llm_query.assert_called_once()


def test_chat_query_degrades_gracefully_when_bridge_unavailable(client, session_id, mock_bridge):
    mock_bridge.call_llm_query.return_value = {"success": False, "error": "llm/query service unavailable"}
    resp = client.post(
        "/api/v1/chat/query", json={"session_id": session_id, "query_text": "What are your hours?"}
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "fallback"
    assert "staff" in data["response_text"].lower()


def test_chat_emergency_keyword_short_circuits_to_escalation(client, session_id, mock_bridge):
    resp = client.post(
        "/api/v1/chat/query", json={"session_id": session_id, "query_text": "I have severe chest pain"}
    )
    data = resp.json()["data"]
    assert data["is_emergency_escalation"] is True
    mock_bridge.call_llm_query.assert_not_called()  # never sent to the LLM at all
    mock_bridge.publish_speak.assert_called_once()


def test_wayfind_directions_mode_does_not_call_navigate(client, session_id, facility_label_store, mock_bridge):
    facility_label_store.upsert(
        NamedLocationLabelUpsert(name="cardiology_dept", display_label="Cardiology", category="department")
    )
    resp = client.post(
        "/api/v1/navigation/wayfind",
        json={"session_id": session_id, "named_location": "cardiology_dept", "mode": "directions"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["accepted"] is True
    mock_bridge.call_navigate.assert_not_called()


def test_wayfind_escort_mode_calls_navigate_through_safety_gate(client, session_id, mock_bridge):
    resp = client.post(
        "/api/v1/navigation/wayfind",
        json={"session_id": session_id, "named_location": "cardiology_dept", "mode": "escort"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["accepted"] is True
    mock_bridge.call_navigate.assert_called_once()


def test_wayfind_escort_rejects_invalid_location(client, session_id, mock_bridge):
    resp = client.post(
        "/api/v1/navigation/wayfind",
        json={"session_id": session_id, "named_location": "Not A Valid Key!", "mode": "escort"},
    )
    assert resp.status_code == 400
    mock_bridge.call_navigate.assert_not_called()


def test_panic_endpoint_always_accepted(client, session_id, mock_bridge):
    resp = client.post(f"/api/v1/panic?session_id={session_id}&reason=fell%20down")
    assert resp.status_code == 200
    assert resp.json()["data"]["acknowledged"] is True
    mock_bridge.publish_speak.assert_called_once()
