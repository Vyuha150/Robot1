from __future__ import annotations


def test_list_departments_and_doctors(client):
    depts = client.get("/api/v1/appointments/departments").json()["data"]
    assert any(d["department_id"] == "dept-cardio" for d in depts)

    doctors = client.get("/api/v1/appointments/doctors?department_id=dept-cardio").json()["data"]
    assert len(doctors) == 1
    assert doctors[0]["doctor_id"] == "doc-tan"


def test_book_and_cancel_appointment(client, session_id):
    slots = client.get("/api/v1/appointments/doctors/doc-tan/slots").json()["data"]
    slot_id = slots[0]["slot_id"]

    booked = client.post(
        "/api/v1/appointments",
        json={"session_id": session_id, "doctor_id": "doc-tan", "slot_id": slot_id, "reason": "checkup"},
    )
    assert booked.status_code == 201
    appointment_id = booked.json()["data"]["appointment_id"]

    # Slot should no longer be available
    slots_after = client.get("/api/v1/appointments/doctors/doc-tan/slots").json()["data"]
    assert all(s["slot_id"] != slot_id for s in slots_after)

    cancelled = client.post("/api/v1/appointments/cancel", json={"appointment_id": appointment_id})
    assert cancelled.status_code == 200
    assert cancelled.json()["data"]["status"] == "cancelled"


def test_book_unavailable_slot_conflicts(client, session_id):
    resp = client.post(
        "/api/v1/appointments",
        json={"session_id": session_id, "doctor_id": "doc-tan", "slot_id": "not-a-real-slot"},
    )
    assert resp.status_code == 409


def test_check_in_issues_token_with_position(client, session_id):
    first = client.post(
        "/api/v1/queue/check-in",
        json={"session_id": session_id, "department_id": "dept-gp", "reason": "cough"},
    )
    assert first.status_code == 201
    token = first.json()["data"]["token"]
    assert token["position"] == 1

    status = client.get(f"/api/v1/queue/tokens/{token['token_id']}").json()["data"]
    assert status["department_name"] == "General Practice"


def test_urgent_priority_jumps_queue(client, session_id):
    resp = client.post(
        "/api/v1/queue/check-in",
        json={"session_id": session_id, "department_id": "dept-gp", "priority": "urgent"},
    )
    token = resp.json()["data"]["token"]
    assert token["priority"] == "urgent"
    assert token["estimated_wait_min"] == 0.0


def test_mark_served_requires_staff_auth(client, session_id, staff_token):
    checked_in = client.post(
        "/api/v1/queue/check-in", json={"session_id": session_id, "department_id": "dept-gp"}
    ).json()["data"]["token"]

    unauthorized = client.post(f"/api/v1/queue/tokens/{checked_in['token_id']}/serve")
    assert unauthorized.status_code == 401

    authorized = client.post(
        f"/api/v1/queue/tokens/{checked_in['token_id']}/serve",
        headers={"Authorization": f"Bearer {staff_token}"},
    )
    assert authorized.status_code == 200
    assert authorized.json()["data"]["status"] == "served"
