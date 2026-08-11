from __future__ import annotations


def test_facility_map_requires_staff_auth(client):
    resp = client.get("/api/v1/facility-map/labels")
    assert resp.status_code == 401


def test_staff_can_read_but_not_write(client, staff_token, admin_token):
    headers_staff = {"Authorization": f"Bearer {staff_token}"}
    assert client.get("/api/v1/facility-map/labels", headers=headers_staff).status_code == 200

    denied = client.post(
        "/api/v1/facility-map/labels",
        json={"name": "room_204", "display_label": "Dr. Tan's Room", "category": "doctor"},
        headers=headers_staff,
    )
    assert denied.status_code == 403


def test_admin_can_create_update_delete_and_export(client, admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    created = client.post(
        "/api/v1/facility-map/labels",
        json={
            "name": "room_204",
            "display_label": "Dr. Tan's Room",
            "category": "doctor",
            "map_x": 3.5,
            "map_y": 1.2,
        },
        headers=headers,
    )
    assert created.status_code == 201
    label_id = created.json()["data"]["label_id"]

    updated = client.put(
        f"/api/v1/facility-map/labels/{label_id}",
        json={"name": "room_204", "display_label": "Dr. Tan's Cardiology Room", "category": "doctor"},
        headers=headers,
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["display_label"] == "Dr. Tan's Cardiology Room"

    exported = client.get("/api/v1/facility-map/export", headers=headers)
    assert exported.status_code == 200
    yaml_text = exported.json()["data"]["yaml_text"]
    assert "named_locations:" in yaml_text
    assert "room_204" in yaml_text

    deleted = client.delete(f"/api/v1/facility-map/labels/{label_id}", headers=headers)
    assert deleted.status_code == 200
    assert client.delete(f"/api/v1/facility-map/labels/{label_id}", headers=headers).status_code == 404
