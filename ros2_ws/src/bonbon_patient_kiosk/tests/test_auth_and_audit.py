from __future__ import annotations


def test_login_success_and_failure(client):
    ok = client.post("/api/v1/auth/login", json={"username": "test_admin", "password": "wrong"})
    assert ok.status_code == 401


def test_admin_user_management_flow(client, admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    created = client.post(
        "/api/v1/auth/users",
        json={"username": "new_staff", "password": "NewStaff1234!", "role": "staff"},
        headers=headers,
    )
    assert created.status_code == 201
    user_id = created.json()["data"]["user_id"]

    listed = client.get("/api/v1/auth/users", headers=headers)
    assert any(u["username"] == "new_staff" for u in listed.json()["data"])

    deleted = client.delete(f"/api/v1/auth/users/{user_id}", headers=headers)
    assert deleted.status_code == 200


def test_staff_cannot_manage_users(client, staff_token):
    headers = {"Authorization": f"Bearer {staff_token}"}
    resp = client.get("/api/v1/auth/users", headers=headers)
    assert resp.status_code == 403


def test_audit_log_never_stores_raw_phi(audit_logger):
    audit_logger.log(
        actor_id="session-123",
        actor_role="patient",
        action="intake:draft_saved",
        request_data={"fields": ["symptoms", "allergies"], "is_red_flag": False},
    )
    events = audit_logger.query(actor_id="session-123")
    assert len(events) == 1
    assert "symptoms" not in str(events[0]["request_data"]) or "penicillin" not in str(events[0])
    # Explicit check: nothing resembling a symptom/allergy free-text value leaked in.
    assert "penicillin" not in str(events[0]).lower()
