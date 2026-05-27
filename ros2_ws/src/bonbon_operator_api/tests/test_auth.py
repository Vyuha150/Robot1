"""Auth API tests — login, JWT, RBAC, user management."""

from __future__ import annotations

from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Scenario 1: Successful login returns JWT
# ---------------------------------------------------------------------------
def test_login_success(client: TestClient):
    resp = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "BonBon@dmin2025!"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "access_token" in data["data"]
    assert data["data"]["token_type"] == "bearer"
    assert data["data"]["role"] == "admin"


# ---------------------------------------------------------------------------
# Scenario 2: Wrong password returns 401
# ---------------------------------------------------------------------------
def test_login_wrong_password(client: TestClient):
    resp = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "WrongPassword!"}
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Scenario 3: Unknown user returns 401
# ---------------------------------------------------------------------------
def test_login_unknown_user(client: TestClient):
    resp = client.post("/api/v1/auth/login", json={"username": "nobody", "password": "Whatever1!"})
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Scenario 4: /me returns own user info
# ---------------------------------------------------------------------------
def test_get_me(client: TestClient, admin_token: str):
    resp = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["username"] == "test_admin"


# ---------------------------------------------------------------------------
# Scenario 5: No token → 401
# ---------------------------------------------------------------------------
def test_no_token_returns_401(client: TestClient):
    resp = client.get("/api/v1/auth/me")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Scenario 6: Admin can list users
# ---------------------------------------------------------------------------
def test_admin_list_users(client: TestClient, admin_token: str):
    resp = client.get(
        "/api/v1/auth/users",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    assert isinstance(resp.json()["data"], list)


# ---------------------------------------------------------------------------
# Scenario 7: Viewer cannot list users (403)
# ---------------------------------------------------------------------------
def test_viewer_cannot_list_users(client: TestClient, viewer_token: str):
    resp = client.get(
        "/api/v1/auth/users",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Scenario 8: Admin creates a new user
# ---------------------------------------------------------------------------
def test_admin_create_user(client: TestClient, admin_token: str):
    resp = client.post(
        "/api/v1/auth/users",
        json={"username": "new_operator", "password": "Pass1234!", "role": "operator"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 201
    assert resp.json()["data"]["role"] == "operator"


# ---------------------------------------------------------------------------
# Scenario 9: Duplicate username → 409
# ---------------------------------------------------------------------------
def test_duplicate_username_rejected(client: TestClient, admin_token: str):
    payload = {"username": "dup_user", "password": "Pass1234!", "role": "viewer"}
    client.post(
        "/api/v1/auth/users", json=payload, headers={"Authorization": f"Bearer {admin_token}"}
    )
    resp = client.post(
        "/api/v1/auth/users", json=payload, headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# Scenario 10: Weak password pattern (min 8 chars)
# ---------------------------------------------------------------------------
def test_weak_password_rejected(client: TestClient, admin_token: str):
    resp = client.post(
        "/api/v1/auth/users",
        json={"username": "weakpw_user", "password": "abc", "role": "viewer"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 422  # pydantic validation


# ---------------------------------------------------------------------------
# Scenario 11: Admin updates user role
# ---------------------------------------------------------------------------
def test_admin_update_user_role(client: TestClient, admin_token: str, auth_manager):
    from bonbon_operator_api.models.auth_models import UserCreate

    try:
        auth_manager.create_user(
            UserCreate(username="role_target", password="Pass1234!", role="viewer")
        )
    except ValueError:
        pass
    user = auth_manager.get_user_by_username("role_target")
    resp = client.patch(
        f"/api/v1/auth/users/{user['user_id']}",
        json={"role": "operator"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["role"] == "operator"


# ---------------------------------------------------------------------------
# Scenario 12: Invalid role rejected
# ---------------------------------------------------------------------------
def test_invalid_role_rejected(client: TestClient, admin_token: str):
    resp = client.post(
        "/api/v1/auth/users",
        json={"username": "bad_role", "password": "Pass1234!", "role": "superadmin"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Scenario 13: Admin deletes a user
# ---------------------------------------------------------------------------
def test_admin_delete_user(client: TestClient, admin_token: str, auth_manager):
    from bonbon_operator_api.models.auth_models import UserCreate

    try:
        auth_manager.create_user(
            UserCreate(username="to_delete", password="Pass1234!", role="viewer")
        )
    except ValueError:
        pass
    user = auth_manager.get_user_by_username("to_delete")
    resp = client.delete(
        f"/api/v1/auth/users/{user['user_id']}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["deleted"] is True


# ---------------------------------------------------------------------------
# Scenario 14: Cannot delete own account
# ---------------------------------------------------------------------------
def test_cannot_delete_own_account(client: TestClient, admin_token: str, auth_manager):
    user = auth_manager.get_user_by_username("test_admin")
    resp = client.delete(
        f"/api/v1/auth/users/{user['user_id']}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Scenario 15: Expired token returns 401
# ---------------------------------------------------------------------------
def test_expired_token_rejected(client: TestClient):
    import time

    import jwt

    expired_payload = {
        "sub": "fake-id",
        "username": "expired_user",
        "role": "viewer",
        "iat": int(time.time()) - 7200,
        "exp": int(time.time()) - 3600,  # expired 1h ago
    }
    token = jwt.encode(
        expired_payload,
        "test-secret-key-32-chars-minimum!!",
        algorithm="HS256",
    )
    resp = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Scenario 16: Tampered token rejected
# ---------------------------------------------------------------------------
def test_tampered_token_rejected(client: TestClient, admin_token: str):
    tampered = admin_token[:-5] + "AAAAA"
    resp = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {tampered}"},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Scenario 17: RBAC — operator cannot access audit log
# ---------------------------------------------------------------------------
def test_operator_cannot_read_audit(client: TestClient, operator_token: str):
    resp = client.get(
        "/api/v1/diagnostics/audit",
        headers={"Authorization": f"Bearer {operator_token}"},
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Scenario 18: Login records audit event
# ---------------------------------------------------------------------------
def test_login_creates_audit_event(client: TestClient, audit_logger):
    before = audit_logger.count()
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "BonBon@dmin2025!"})
    after = audit_logger.count()
    assert after > before


# ---------------------------------------------------------------------------
# Scenario 19: Deactivated user cannot log in
# ---------------------------------------------------------------------------
def test_deactivated_user_rejected(client: TestClient, admin_token: str, auth_manager):
    from bonbon_operator_api.models.auth_models import UserCreate, UserUpdate

    try:
        auth_manager.create_user(
            UserCreate(username="soon_inactive", password="Pass1234!", role="viewer")
        )
    except ValueError:
        pass
    user = auth_manager.get_user_by_username("soon_inactive")
    auth_manager.update_user(user["user_id"], UserUpdate(is_active=False))
    resp = client.post(
        "/api/v1/auth/login", json={"username": "soon_inactive", "password": "Pass1234!"}
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Scenario 20: Username with special chars rejected by pattern
# ---------------------------------------------------------------------------
def test_username_invalid_chars_rejected(client: TestClient, admin_token: str):
    resp = client.post(
        "/api/v1/auth/users",
        json={"username": "bad user!", "password": "Pass1234!", "role": "viewer"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 422
