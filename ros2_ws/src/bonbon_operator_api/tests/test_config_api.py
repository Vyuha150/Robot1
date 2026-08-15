"""Config API tests.

No dedicated test file existed for this router before this round (found
during the cleanup audit's dead-code pass). Covers the existing read/write/
permission behavior plus the fix for a real bug: `set_config_key` used to
call `bridge.call_set_config(...)` and discard the result entirely, then
unconditionally return `updated: True` even when the ROS2 propagation
failed (e.g. the documented NOT_IMPLEMENTED bridge stub) -- a safety-
critical config write (emergency distance, watchdog timeout) could silently
never reach the live robot while the dashboard reported success.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


class TestGetConfig:
    def test_get_all_config_returns_empty_store(self, client: TestClient, viewer_token: str):
        resp = client.get(
            "/api/v1/config/",
            headers={"Authorization": f"Bearer {viewer_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["data"] == {}

    def test_get_missing_key_returns_404(self, client: TestClient, viewer_token: str):
        resp = client.get(
            "/api/v1/config/tts.default_volume",
            headers={"Authorization": f"Bearer {viewer_token}"},
        )
        assert resp.status_code == 404


class TestSetConfigPermissions:
    def test_engineer_can_write_limited_key(self, client: TestClient, engineer_token: str):
        resp = client.put(
            "/api/v1/config/",
            json={"key": "tts.default_volume", "value": 0.8},
            headers={"Authorization": f"Bearer {engineer_token}"},
        )
        assert resp.status_code == 200

    def test_engineer_forbidden_from_critical_key(self, client: TestClient, engineer_token: str):
        resp = client.put(
            "/api/v1/config/",
            json={"key": "safety.emergency_distance_m", "value": 0.5},
            headers={"Authorization": f"Bearer {engineer_token}"},
        )
        assert resp.status_code == 403

    def test_operator_forbidden_from_any_config_write(
        self, client: TestClient, operator_token: str
    ):
        # operator has no config:write permission at all (config:write:limited
        # starts at engineer per role_permissions.py) -- not just blocked from
        # critical keys.
        resp = client.put(
            "/api/v1/config/",
            json={"key": "tts.default_volume", "value": 0.8},
            headers={"Authorization": f"Bearer {operator_token}"},
        )
        assert resp.status_code == 403

    def test_admin_can_write_critical_key(self, client: TestClient, admin_token: str):
        resp = client.put(
            "/api/v1/config/",
            json={"key": "safety.emergency_distance_m", "value": 0.5},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200

    def test_unwritable_key_returns_400(self, client: TestClient, admin_token: str):
        resp = client.put(
            "/api/v1/config/",
            json={"key": "not_a_real_key", "value": 1},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 400


class TestSetConfigWritesAndPropagates:
    def test_successful_write_is_readable_afterwards(self, client: TestClient, admin_token: str):
        client.put(
            "/api/v1/config/",
            json={"key": "tts.default_volume", "value": 0.6},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        resp = client.get(
            "/api/v1/config/tts.default_volume",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["value"] == 0.6

    def test_bridge_receives_the_write(self, client: TestClient, admin_token: str, mock_bridge):
        client.put(
            "/api/v1/config/",
            json={"key": "tts.default_volume", "value": 0.3},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        mock_bridge.call_set_config.assert_called_once_with("tts.default_volume", 0.3)


class TestSetConfigReportsBridgeFailureHonestly:
    """Pins the fix: a bridge result with success=False must surface as an
    HTTP error, never a fake 200 'updated'. Mirrors the equivalent tests
    for command_api.py's /robot/commands/* routes."""

    def test_set_config_reports_bridge_dispatch_failure(
        self, client: TestClient, admin_token: str, mock_bridge
    ):
        mock_bridge.call_set_config.return_value = {
            "success": False,
            "error": "NOT_IMPLEMENTED",
        }
        resp = client.put(
            "/api/v1/config/",
            json={"key": "safety.watchdog_timeout_sec", "value": 5.0},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 503

    def test_local_store_still_written_even_when_propagation_fails(
        self, client: TestClient, admin_token: str, mock_bridge
    ):
        # The local dashboard config store write happens before the bridge
        # call and is real/durable -- a failed ROS2 propagation must not
        # silently lose the operator's intended change either.
        mock_bridge.call_set_config.return_value = {"success": False}
        client.put(
            "/api/v1/config/",
            json={"key": "tts.default_volume", "value": 0.9},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        resp = client.get(
            "/api/v1/config/tts.default_volume",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.json()["data"]["value"] == 0.9

    def test_successful_propagation_returns_updated_true(
        self, client: TestClient, admin_token: str, mock_bridge
    ):
        mock_bridge.call_set_config.return_value = {"success": True}
        resp = client.put(
            "/api/v1/config/",
            json={"key": "tts.default_volume", "value": 0.4},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["updated"] is True
