"""Test fixtures for bonbon_patient_kiosk.

All fixtures stub out ROS2 entirely — tests run without a live ROS2 installation,
mirroring bonbon_operator_api/tests/conftest.py.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("BONBON_TEST_MODE", "1")
os.environ.setdefault("BONBON_KIOSK_ADMIN_PASSWORD", "BonBonKiosk@dmin2025!")


@pytest.fixture
def tmp_data_dir(tmp_path):
    return tmp_path


@pytest.fixture
def audit_logger(tmp_data_dir):
    from bonbon_patient_kiosk.audit.audit_logger import AuditLogger

    return AuditLogger(db_path=tmp_data_dir / "audit_test.db", max_events=1000)


@pytest.fixture
def auth_manager(tmp_data_dir):
    from bonbon_patient_kiosk.auth.auth_manager import AuthManager

    return AuthManager(
        db_path=tmp_data_dir / "staff_users_test.db",
        jwt_secret="test-secret-key-32-chars-minimum!!",
        algorithm="HS256",
        token_expire_minutes=60,
    )


@pytest.fixture
def role_manager():
    from bonbon_patient_kiosk.auth.role_permissions import RolePermissionManager

    return RolePermissionManager()


@pytest.fixture
def session_store():
    from bonbon_patient_kiosk.data.session_store import SessionStore

    return SessionStore(idle_timeout_sec=90.0, max_session_age_sec=1800.0)


@pytest.fixture
def patient_store(tmp_data_dir):
    from bonbon_patient_kiosk.data.crypto import PHICipher
    from bonbon_patient_kiosk.data.store import PatientDataStore

    cipher = PHICipher(key_hex="00" * 32)
    return PatientDataStore(db_path=tmp_data_dir / "patient_data_test.db", cipher=cipher)


@pytest.fixture
def facility_label_store(tmp_data_dir):
    from bonbon_patient_kiosk.data.facility_store import FacilityLabelStore

    return FacilityLabelStore(path=tmp_data_dir / "facility_labels_test.json")


@pytest.fixture
def emr_adapter():
    from bonbon_patient_kiosk.data.adapters.emr_adapter import MockEMRAdapter

    return MockEMRAdapter()


@pytest.fixture
def scheduling_adapter():
    from bonbon_patient_kiosk.data.adapters.scheduling_adapter import MockSchedulingAdapter

    return MockSchedulingAdapter()


@pytest.fixture
def notifier_adapter():
    from bonbon_patient_kiosk.data.adapters.notifier_adapter import MockNotifierAdapter

    return MockNotifierAdapter()


@pytest.fixture
def kiosk_safety_gate(audit_logger):
    from bonbon_patient_kiosk.safety.command_validator import CommandValidator
    from bonbon_patient_kiosk.safety.kiosk_safety_gate import KioskSafetyGate

    validator = CommandValidator(dedup_window_sec=5.0, dedup_capacity=64)
    return KioskSafetyGate(validator=validator, audit_logger=audit_logger)


@pytest.fixture
def mock_bridge():
    bridge = MagicMock()
    bridge.call_llm_query.return_value = {
        "success": True,
        "response_text": "Cardiology is on Floor 2.",
        "status": "ok",
        "confidence": 0.9,
    }
    bridge.call_navigate.return_value = {"success": True, "message": "arrived"}
    bridge.call_set_privacy_mode.return_value = {"success": True}
    bridge.publish_speak.return_value = {"success": True}
    bridge._ready.return_value = True
    return bridge


@pytest.fixture
def app(
    tmp_data_dir,
    audit_logger,
    auth_manager,
    role_manager,
    session_store,
    patient_store,
    facility_label_store,
    emr_adapter,
    scheduling_adapter,
    notifier_adapter,
    kiosk_safety_gate,
    mock_bridge,
):
    from bonbon_patient_kiosk.config.kiosk_api_config import KioskAPIConfig
    from bonbon_patient_kiosk.main import _build_app

    cfg = KioskAPIConfig()
    cfg.ros2.enabled = False  # no live ROS2 in tests
    # _build_app() unconditionally constructs real services from these paths
    # before the fixtures below override application.state — point them at
    # tmp_data_dir so a test run never seeds/touches the real deployment's
    # default /tmp/bonbon/patient_kiosk/* files (this bit a real manual run:
    # an earlier `pytest` invocation silently seeded the admin account at
    # the default path with this file's test password).
    cfg.staff_users_db_path = tmp_data_dir / "_unused_staff_users.db"
    cfg.patient_data_db_path = tmp_data_dir / "_unused_patient_data.db"
    cfg.facility_labels_path = tmp_data_dir / "_unused_facility_labels.json"
    cfg.audit.db_path = tmp_data_dir / "_unused_audit.db"

    application = _build_app(cfg)

    application.state.audit_logger = audit_logger
    application.state.auth_manager = auth_manager
    application.state.role_manager = role_manager
    application.state.session_store = session_store
    application.state.patient_store = patient_store
    application.state.facility_label_store = facility_label_store
    application.state.emr_adapter = emr_adapter
    application.state.scheduling_adapter = scheduling_adapter
    application.state.notifier_adapter = notifier_adapter
    application.state.kiosk_safety_gate = kiosk_safety_gate
    application.state.ros2_bridge = mock_bridge

    return application


@pytest.fixture
def client(app) -> TestClient:
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture
def admin_token(auth_manager):
    from bonbon_patient_kiosk.models.auth_models import UserCreate

    try:
        auth_manager.create_user(UserCreate(username="test_admin", password="Admin1234!", role="admin"))
    except ValueError:
        pass
    user = auth_manager.authenticate("test_admin", "Admin1234!")
    token, _ = auth_manager.create_token(user)
    return token


@pytest.fixture
def staff_token(auth_manager):
    from bonbon_patient_kiosk.models.auth_models import UserCreate

    try:
        auth_manager.create_user(UserCreate(username="test_staff", password="Staff1234!", role="staff"))
    except ValueError:
        pass
    user = auth_manager.authenticate("test_staff", "Staff1234!")
    token, _ = auth_manager.create_token(user)
    return token


@pytest.fixture
def session_id(client) -> str:
    resp = client.post("/api/v1/session", json={"language": "en", "kiosk_id": "kiosk-1"})
    return resp.json()["data"]["session_id"]


@pytest.fixture
def consented_session_id(client, session_id) -> str:
    client.post(
        "/api/v1/consent",
        json={"session_id": session_id, "consent_given": True, "jurisdiction": "default", "policy_version": "1.0"},
    )
    return session_id
