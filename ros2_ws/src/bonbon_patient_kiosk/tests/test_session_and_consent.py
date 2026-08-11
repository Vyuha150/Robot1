from __future__ import annotations


def test_create_session_engages_privacy_mode(client, mock_bridge):
    resp = client.post("/api/v1/session", json={"language": "en", "kiosk_id": "kiosk-1"})
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["privacy_mode_active"] is True
    mock_bridge.call_set_privacy_mode.assert_called_once()


def test_get_unknown_session_404(client):
    resp = client.get("/api/v1/session/does-not-exist")
    assert resp.status_code == 404


def test_heartbeat_updates_session(client, session_id):
    resp = client.post(f"/api/v1/session/{session_id}/heartbeat")
    assert resp.status_code == 200
    assert resp.json()["data"]["session_id"] == session_id


def test_end_session_wipes_draft(client, session_id):
    client.put(
        f"/api/v1/intake/{session_id}/draft",
        json={
            "session_id": session_id,
            "full_name": "Jane Tan",
            "date_of_birth": "1990-01-01",
            "contact_phone": "+6591112222",
            "visit_reason": "Annual checkup",
        },
    )
    assert client.get(f"/api/v1/intake/{session_id}/draft").status_code == 200

    resp = client.post(f"/api/v1/session/{session_id}/end")
    assert resp.status_code == 200
    assert client.get(f"/api/v1/session/{session_id}").status_code == 404
    assert client.get(f"/api/v1/intake/{session_id}/draft").status_code == 404


def test_consent_required_before_submit(client, session_id):
    client.put(
        f"/api/v1/intake/{session_id}/draft",
        json={
            "session_id": session_id,
            "full_name": "Jane Tan",
            "date_of_birth": "1990-01-01",
            "contact_phone": "+6591112222",
            "visit_reason": "Annual checkup",
        },
    )
    resp = client.post(f"/api/v1/intake/{session_id}/submit")
    assert resp.status_code == 403


def test_consent_disclosure_text_present(client):
    resp = client.get("/api/v1/consent/disclosure")
    assert resp.status_code == 200
    assert "text" in resp.json()["data"]
