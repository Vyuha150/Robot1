from __future__ import annotations


def test_dashboard_requires_staff_auth(client):
    resp = client.get("/api/v1/staff/dashboard/overview")
    assert resp.status_code == 401


def test_dashboard_shows_queue_appointments_and_feedback(client, session_id, staff_token):
    headers = {"Authorization": f"Bearer {staff_token}"}

    slots = client.get("/api/v1/appointments/doctors/doc-tan/slots").json()["data"]
    client.post(
        "/api/v1/appointments",
        json={"session_id": session_id, "doctor_id": "doc-tan", "slot_id": slots[0]["slot_id"], "reason": "checkup"},
    )
    client.post("/api/v1/queue/check-in", json={"session_id": session_id, "department_id": "dept-gp"})
    client.post("/api/v1/feedback", json={"session_id": session_id, "rating": 5, "comment": "Great service"})

    overview = client.get("/api/v1/staff/dashboard/overview", headers=headers).json()["data"]

    assert overview["appointments_today"][0]["doctor_name"] == "Dr. Tan Wei Ling"
    assert overview["appointments_today"][0]["start_ts"] is not None

    gp_dept = next(d for d in overview["queue"] if d["department_id"] == "dept-gp")
    assert gp_dept["department_name"] == "General Practice"
    assert len(gp_dept["tokens"]) == 1

    assert overview["feedback"]["count"] == 1
    assert overview["feedback"]["average_rating"] == 5.0
    assert overview["feedback"]["recent"][0]["comment"] == "Great service"


def test_dashboard_surfaces_red_flag_intake_and_panic_escalation(client, consented_session_id, staff_token):
    headers = {"Authorization": f"Bearer {staff_token}"}

    client.put(
        f"/api/v1/intake/{consented_session_id}/draft",
        json={
            "session_id": consented_session_id,
            "full_name": "Alex Lim",
            "date_of_birth": "1985-05-05",
            "contact_phone": "+6598887777",
            "visit_reason": "severe chest pain",
        },
    )
    client.post(f"/api/v1/intake/{consented_session_id}/submit")
    client.post(f"/api/v1/panic?session_id={consented_session_id}&reason=fell%20down")

    overview = client.get("/api/v1/staff/dashboard/overview", headers=headers).json()["data"]

    assert any(i["full_name"] == "Alex Lim" and i["is_red_flag"] for i in overview["recent_intake"])
    actions = {e["action"] for e in overview["recent_escalations"]}
    assert "intake:emergency_escalation" in actions
    assert "command:panic" in actions
    panic_event = next(e for e in overview["recent_escalations"] if e["action"] == "command:panic")
    assert panic_event["detail"] == "fell down"


def test_dashboard_mark_served_removes_token_from_queue(client, session_id, staff_token):
    headers = {"Authorization": f"Bearer {staff_token}"}
    token = client.post(
        "/api/v1/queue/check-in", json={"session_id": session_id, "department_id": "dept-gp"}
    ).json()["data"]["token"]

    before = client.get("/api/v1/staff/dashboard/overview", headers=headers).json()["data"]
    gp_before = next(d for d in before["queue"] if d["department_id"] == "dept-gp")
    assert len(gp_before["tokens"]) == 1

    client.post(f"/api/v1/queue/tokens/{token['token_id']}/serve", headers=headers)

    after = client.get("/api/v1/staff/dashboard/overview", headers=headers).json()["data"]
    gp_after = next((d for d in after["queue"] if d["department_id"] == "dept-gp"), None)
    assert gp_after is None  # no waiting tokens left for this department
