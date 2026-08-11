from __future__ import annotations


def _draft_payload(session_id: str, visit_reason: str = "Annual checkup", symptoms=None):
    return {
        "session_id": session_id,
        "full_name": "Jane Tan",
        "date_of_birth": "1990-01-01",
        "contact_phone": "+6591112222",
        "visit_reason": visit_reason,
        "symptoms": symptoms or [],
    }


def test_save_and_get_draft(client, consented_session_id):
    resp = client.put(
        f"/api/v1/intake/{consented_session_id}/draft", json=_draft_payload(consented_session_id)
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["is_red_flag"] is False

    got = client.get(f"/api/v1/intake/{consented_session_id}/draft")
    assert got.status_code == 200
    assert got.json()["data"]["full_name"] == "Jane Tan"


def test_submit_intake_persists_encrypted_record(client, consented_session_id, patient_store):
    client.put(
        f"/api/v1/intake/{consented_session_id}/draft", json=_draft_payload(consented_session_id)
    )
    resp = client.post(f"/api/v1/intake/{consented_session_id}/submit")
    assert resp.status_code == 201
    intake_id = resp.json()["data"]["intake_id"]

    stored = patient_store.get_intake(intake_id)
    assert stored is not None
    assert stored["form"]["full_name"] == "Jane Tan"

    with open(patient_store._db_path, "rb") as fh:
        raw = fh.read()
    assert b"Jane Tan" not in raw  # never stored in plaintext on disk


def test_red_flag_symptom_forces_escalation(client, consented_session_id, mock_bridge):
    resp = client.put(
        f"/api/v1/intake/{consented_session_id}/draft",
        json=_draft_payload(consented_session_id, visit_reason="I have severe chest pain"),
    )
    assert resp.json()["data"]["is_red_flag"] is True

    submit = client.post(f"/api/v1/intake/{consented_session_id}/submit")
    assert submit.status_code == 201
    assert submit.json()["data"]["is_red_flag"] is True
    mock_bridge.publish_speak.assert_any_call(
        "I've alerted a staff member — someone will be with you right away.", priority="high"
    )


def test_submit_without_draft_400(client, consented_session_id):
    resp = client.post(f"/api/v1/intake/{consented_session_id}/submit")
    assert resp.status_code == 400
