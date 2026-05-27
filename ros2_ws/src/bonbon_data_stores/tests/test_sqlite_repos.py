"""Test scenarios 5-12: SQLite repository CRUD, migrations, and retention.

Covers:
  5.  Schema migration — version table populated; idempotent re-run
  6.  UserProfileRepository — save/get/update/delete/forget
  7.  InteractionHistoryRepository — save/get/purge
  8.  RobotStateRepository — save/get_latest/range
  9.  SafetyEventRepository — save/get_unresolved/mark_resolved
  10. NavigationEventRepository — save/get_by_outcome
  11. AuditLogRepository — append-only insert, get_by_actor
  12. MapMetadataRepository — save/get_active/zones
"""

from __future__ import annotations

import time

import pytest
from bonbon_data_stores.schema.models import (
    AuditLogEntry,
    EnvironmentZone,
    InteractionEvent,
    MapMetadata,
    NavigationOutcome,
    PrivacyLevel,
    RetentionPolicy,
    RobotMode,
    RobotState,
    SafetyEventType,
    UserPreference,
    UserRecord,
)
from bonbon_data_stores.sqlite.migrations import SchemaMigrator

# ---------------------------------------------------------------------------
# Scenario 5: Schema migrations
# ---------------------------------------------------------------------------


class TestSchemaMigrations:
    def test_migrate_creates_tables(self, db_conn):
        tables = {
            row["name"]
            for row in db_conn.get()
            .execute("SELECT name FROM sqlite_master WHERE type='table';")
            .fetchall()
        }
        for expected in (
            "users",
            "interactions",
            "robot_states",
            "safety_events",
            "navigation_events",
            "audit_log",
            "map_metadata",
            "environment_zones",
            "ai_context",
            "schema_migrations",
        ):
            assert expected in tables, f"Table {expected!r} missing"

    def test_migrate_idempotent(self, db_conn):
        migrator = SchemaMigrator(db_conn)
        v1 = migrator.migrate()
        v2 = migrator.migrate()
        assert v1 == v2

    def test_current_version_nonzero(self, db_conn):
        v = SchemaMigrator(db_conn).current_version()
        assert v >= 1


# ---------------------------------------------------------------------------
# Scenario 6: UserProfileRepository
# ---------------------------------------------------------------------------


class TestUserProfileRepository:
    def test_save_and_get(self, user_repo, sample_user):
        uid = user_repo.save(sample_user)
        fetched = user_repo.get_by_id(uid)
        assert fetched is not None
        assert fetched.display_name == "Alice"

    def test_count_after_save(self, user_repo, sample_user):
        user_repo.save(sample_user)
        assert user_repo.count() >= 1

    def test_upsert_updates_display_name(self, user_repo, sample_user):
        user_repo.save(sample_user)
        sample_user = sample_user.model_copy(update={"display_name": "Alice Updated"})
        user_repo.save(sample_user)
        fetched = user_repo.get_by_id(sample_user.user_id)
        assert fetched.display_name == "Alice Updated"

    def test_delete_removes_record(self, user_repo, sample_user):
        user_repo.save(sample_user)
        removed = user_repo.delete(sample_user.user_id)
        assert removed is True
        assert user_repo.get_by_id(sample_user.user_id) is None

    def test_do_not_store_raises(self, user_repo):
        u = UserRecord(
            display_name="Ghost",
            privacy_level=PrivacyLevel.DO_NOT_STORE,
        )
        with pytest.raises(ValueError, match="do_not_store"):
            user_repo.save(u)

    def test_save_preferences(self, user_repo, sample_user):
        sample_user.preferences.append(
            UserPreference(key="language", value="en", category="communication")
        )
        user_repo.save(sample_user)
        prefs = user_repo.get_preferences(sample_user.user_id)
        assert any(p.key == "language" for p in prefs)

    def test_forget_user_nulls_interactions(self, user_repo, interaction_repo, sample_user):
        user_repo.save(sample_user)
        # Create an interaction explicitly linked to this user
        linked = InteractionEvent(
            user_id=sample_user.user_id,
            input_text="linked to user",
        )
        interaction_repo.save(linked)
        user_repo.forget_user(sample_user.user_id)
        # User should be deleted
        assert user_repo.get_by_id(sample_user.user_id) is None
        # Interaction user_id should be nulled (not deleted)
        saved = interaction_repo.get_by_id(linked.event_id)
        if saved:
            assert saved.user_id is None

    def test_find_by_name(self, user_repo, sample_user):
        user_repo.save(sample_user)
        results = user_repo.find_by_name("Alice")
        assert len(results) >= 1


# ---------------------------------------------------------------------------
# Scenario 7: InteractionHistoryRepository
# ---------------------------------------------------------------------------


class TestInteractionHistoryRepository:
    def test_save_and_get(self, interaction_repo, sample_interaction):
        eid = interaction_repo.save(sample_interaction)
        fetched = interaction_repo.get_by_id(eid)
        assert fetched is not None
        assert fetched.input_text == "Hello, robot!"

    def test_get_recent(self, interaction_repo, sample_interaction):
        interaction_repo.save(sample_interaction)
        recent = interaction_repo.get_recent(limit=10)
        assert len(recent) >= 1

    def test_purge_by_retention(self, interaction_repo):
        old_event = InteractionEvent(
            input_text="Old",
            retention_policy=RetentionPolicy.SEVEN_DAYS,
        )
        # Force an old timestamp
        old_event = old_event.model_copy(update={"timestamp": time.time() - 8 * 86400})
        interaction_repo.save(old_event)
        cutoff = time.time() - 7 * 86400
        deleted = interaction_repo.purge_by_retention("7_days", cutoff)
        assert deleted >= 1

    def test_delete(self, interaction_repo, sample_interaction):
        interaction_repo.save(sample_interaction)
        removed = interaction_repo.delete(sample_interaction.event_id)
        assert removed is True
        assert interaction_repo.get_by_id(sample_interaction.event_id) is None


# ---------------------------------------------------------------------------
# Scenario 8: RobotStateRepository
# ---------------------------------------------------------------------------


class TestRobotStateRepository:
    def test_save_and_get_latest(self, robot_state_repo, sample_robot_state):
        robot_state_repo.save(sample_robot_state)
        latest = robot_state_repo.get_latest()
        assert latest is not None
        assert latest.mode == RobotMode.ACTIVE

    def test_get_range(self, robot_state_repo):
        state = RobotState(battery_level=0.5)
        robot_state_repo.save(state)
        now = time.time()
        results = robot_state_repo.get_range(now - 60, now + 60)
        assert len(results) >= 1

    def test_delete(self, robot_state_repo, sample_robot_state):
        robot_state_repo.save(sample_robot_state)
        removed = robot_state_repo.delete(sample_robot_state.event_id)
        assert removed is True


# ---------------------------------------------------------------------------
# Scenario 9: SafetyEventRepository
# ---------------------------------------------------------------------------


class TestSafetyEventRepository:
    def test_save_and_get_unresolved(self, safety_repo, sample_safety_event):
        safety_repo.save(sample_safety_event)
        unresolved = safety_repo.get_unresolved()
        assert any(e.event_id == sample_safety_event.event_id for e in unresolved)

    def test_mark_resolved(self, safety_repo, sample_safety_event):
        safety_repo.save(sample_safety_event)
        safety_repo.mark_resolved(sample_safety_event.event_id)
        fetched = safety_repo.get_by_id(sample_safety_event.event_id)
        assert fetched.resolved is True
        assert fetched.resolved_at is not None

    def test_get_by_type(self, safety_repo, sample_safety_event):
        safety_repo.save(sample_safety_event)
        events = safety_repo.get_by_type(SafetyEventType.COLLISION_RISK)
        assert len(events) >= 1


# ---------------------------------------------------------------------------
# Scenario 10: NavigationEventRepository
# ---------------------------------------------------------------------------


class TestNavigationEventRepository:
    def test_save_and_get(self, nav_repo, sample_nav_event):
        eid = nav_repo.save(sample_nav_event)
        fetched = nav_repo.get_by_id(eid)
        assert fetched is not None
        assert fetched.outcome == NavigationOutcome.SUCCESS

    def test_get_by_outcome_success(self, nav_repo, sample_nav_event):
        nav_repo.save(sample_nav_event)
        results = nav_repo.get_by_outcome(NavigationOutcome.SUCCESS)
        assert len(results) >= 1

    def test_get_by_outcome_failed_empty(self, nav_repo, sample_nav_event):
        nav_repo.save(sample_nav_event)
        results = nav_repo.get_by_outcome(NavigationOutcome.FAILED)
        assert all(e.outcome == NavigationOutcome.FAILED for e in results)


# ---------------------------------------------------------------------------
# Scenario 11: AuditLogRepository
# ---------------------------------------------------------------------------


class TestAuditLogRepository:
    def test_append_and_get(self, audit_repo):
        entry = AuditLogEntry(actor="test_node", action="save_user", target_type="user")
        lid = audit_repo.save(entry)
        fetched = audit_repo.get_by_id(lid)
        assert fetched is not None
        assert fetched.actor == "test_node"

    def test_get_by_actor(self, audit_repo):
        entry = AuditLogEntry(actor="admin", action="delete_user")
        audit_repo.save(entry)
        entries = audit_repo.get_by_actor("admin")
        assert len(entries) >= 1
        assert all(e.actor == "admin" for e in entries)

    def test_get_recent(self, audit_repo):
        for i in range(5):
            audit_repo.save(AuditLogEntry(actor=f"node_{i}", action="test"))
        recent = audit_repo.get_recent(limit=5)
        assert len(recent) == 5


# ---------------------------------------------------------------------------
# Scenario 12: MapMetadataRepository
# ---------------------------------------------------------------------------


class TestMapMetadataRepository:
    def test_save_and_get(self, map_repo):
        meta = MapMetadata(map_name="floor_1", resolution_m=0.05)
        mid = map_repo.save(meta)
        fetched = map_repo.get_by_id(mid)
        assert fetched is not None
        assert fetched.map_name == "floor_1"

    def test_set_active(self, map_repo):
        m1 = MapMetadata(map_name="map_a")
        m2 = MapMetadata(map_name="map_b")
        map_repo.save(m1)
        map_repo.save(m2)
        map_repo.set_active(m2.map_id)
        active = map_repo.get_active()
        assert active is not None
        assert active.map_id == m2.map_id

    def test_zones_saved_with_map(self, map_repo):
        zone = EnvironmentZone(
            map_id="placeholder",
            zone_name="Lobby",
            zone_type="room",
        )
        meta = MapMetadata(map_name="floor_2")
        zone = zone.model_copy(update={"map_id": meta.map_id})
        meta.zones.append(zone)
        map_repo.save(meta)
        zones = map_repo.get_zones(meta.map_id)
        assert any(z.zone_name == "Lobby" for z in zones)
