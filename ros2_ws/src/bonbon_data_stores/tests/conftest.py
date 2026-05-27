"""Shared pytest fixtures for bonbon_data_stores tests."""

from __future__ import annotations

import pytest
from bonbon_data_stores.config.store_config import DataStoreConfig
from bonbon_data_stores.schema.models import (
    InteractionEvent,
    NavigationEvent,
    NavigationOutcome,
    RobotMode,
    RobotState,
    SafetyEvent,
    SafetyEventType,
    UserRecord,
)
from bonbon_data_stores.sqlite.connection import SQLiteConnection
from bonbon_data_stores.sqlite.migrations import SchemaMigrator
from bonbon_data_stores.sqlite.repositories.audit_log_repo import AuditLogRepository
from bonbon_data_stores.sqlite.repositories.interaction_repo import InteractionHistoryRepository
from bonbon_data_stores.sqlite.repositories.map_metadata_repo import MapMetadataRepository
from bonbon_data_stores.sqlite.repositories.navigation_event_repo import NavigationEventRepository
from bonbon_data_stores.sqlite.repositories.robot_state_repo import RobotStateRepository
from bonbon_data_stores.sqlite.repositories.safety_event_repo import SafetyEventRepository
from bonbon_data_stores.sqlite.repositories.user_repo import UserProfileRepository
from bonbon_data_stores.store import SQLiteMemoryStore

# ---------------------------------------------------------------------------
# Core fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_dir(tmp_path):
    """A temporary directory scoped to the test."""
    return tmp_path


@pytest.fixture()
def db_config(tmp_path):
    """DataStoreConfig pointing entirely to a tmp directory."""
    return DataStoreConfig.from_env(base_dir=str(tmp_path / "data"))


@pytest.fixture()
def db_conn(db_config):
    """Migrated SQLiteConnection in a temp directory."""
    conn = SQLiteConnection(db_path=db_config.sqlite.db_path)
    SchemaMigrator(conn).migrate()
    yield conn
    conn.close()


@pytest.fixture()
def store(db_config):
    """Open SQLiteMemoryStore backed by a tmp directory."""
    s = SQLiteMemoryStore(db_config)
    s.open()
    yield s
    s.close()


# ---------------------------------------------------------------------------
# Repository fixtures (all share the same migrated connection)
# ---------------------------------------------------------------------------


@pytest.fixture()
def user_repo(db_conn):
    return UserProfileRepository(db_conn)


@pytest.fixture()
def interaction_repo(db_conn):
    return InteractionHistoryRepository(db_conn)


@pytest.fixture()
def robot_state_repo(db_conn):
    return RobotStateRepository(db_conn)


@pytest.fixture()
def safety_repo(db_conn):
    return SafetyEventRepository(db_conn)


@pytest.fixture()
def nav_repo(db_conn):
    return NavigationEventRepository(db_conn)


@pytest.fixture()
def audit_repo(db_conn):
    return AuditLogRepository(db_conn)


@pytest.fixture()
def map_repo(db_conn):
    return MapMetadataRepository(db_conn)


# ---------------------------------------------------------------------------
# Sample domain objects
# ---------------------------------------------------------------------------


@pytest.fixture()
def sample_user():
    return UserRecord(
        display_name="Alice",
        language="en",
        preferred_interaction_style="friendly",
    )


@pytest.fixture()
def sample_interaction():
    """A standalone interaction with no FK user dependency (user_id=None)."""
    return InteractionEvent(
        user_id=None,
        input_text="Hello, robot!",
        response_text="Hello, Alice!",
        intent="greeting",
        intent_confidence=0.95,
    )


@pytest.fixture()
def sample_robot_state():
    return RobotState(
        mode=RobotMode.ACTIVE,
        battery_level=0.85,
        position_x=1.0,
        position_y=2.0,
    )


@pytest.fixture()
def sample_safety_event():
    return SafetyEvent(
        event_type=SafetyEventType.COLLISION_RISK,
        severity=3,
        source_node="bonbon_safety",
        description="Obstacle detected at 0.3 m",
    )


@pytest.fixture()
def sample_nav_event():
    return NavigationEvent(
        goal_x=5.0,
        goal_y=3.0,
        outcome=NavigationOutcome.SUCCESS,
        distance_m=4.5,
        duration_sec=12.3,
    )
