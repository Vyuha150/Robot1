"""Test scenarios 17-19: MemoryPrivacyManager, RetentionPolicyManager, health monitor.

17. MemoryPrivacyManager — do_not_store blocks, audio/face stripping
18. RetentionPolicyManager — sweep purges expired rows, session purge
19. DataStoreHealthMonitor — healthy/degraded/unhealthy classification
"""

from __future__ import annotations

import time

import pytest
from bonbon_data_stores.health.health_monitor import DataStoreHealthMonitor, HealthLevel
from bonbon_data_stores.privacy.privacy_manager import MemoryPrivacyManager
from bonbon_data_stores.privacy.retention_manager import RetentionPolicyManager
from bonbon_data_stores.schema.models import (
    InteractionEvent,
    PrivacyLevel,
    RetentionPolicy,
    UserRecord,
)

# ---------------------------------------------------------------------------
# Scenario 17: MemoryPrivacyManager
# ---------------------------------------------------------------------------


class TestMemoryPrivacyManager:
    def test_do_not_store_interaction_raises(self):
        pm = MemoryPrivacyManager()
        event = InteractionEvent(
            input_text="secret",
            privacy_level=PrivacyLevel.DO_NOT_STORE,
        )
        with pytest.raises(ValueError, match="do_not_store"):
            pm.screen_interaction(event)

    def test_do_not_store_is_not_storable(self):
        pm = MemoryPrivacyManager()
        event = InteractionEvent(privacy_level=PrivacyLevel.DO_NOT_STORE)
        assert pm.is_storable(event) is False

    def test_internal_event_is_storable(self):
        pm = MemoryPrivacyManager()
        event = InteractionEvent(privacy_level=PrivacyLevel.INTERNAL)
        assert pm.is_storable(event) is True

    def test_audio_ref_stripped_when_store_audio_false(self):
        """Default: store_audio=False — audio_ref MUST be stripped."""
        pm = MemoryPrivacyManager(store_audio=False)
        event = InteractionEvent(
            input_text="voice",
            audio_ref="ref_abc123",  # populated (e.g. from sensor node)
        )
        screened = pm.screen_interaction(event)
        assert screened.audio_ref is None

    def test_audio_ref_kept_when_store_audio_true(self):
        pm = MemoryPrivacyManager(store_audio=True)
        event = InteractionEvent(
            input_text="voice",
            audio_ref="ref_abc123",
        )
        screened = pm.screen_interaction(event)
        assert screened.audio_ref == "ref_abc123"

    def test_face_encoding_ref_stripped_when_store_face_false(self):
        """Default: store_face_data=False — face refs MUST be stripped."""
        pm = MemoryPrivacyManager(store_face_data=False)
        user = UserRecord(
            display_name="Eve",
            face_encoding_ref="face_token_xyz",
        )
        screened = pm.screen_user(user)
        assert screened.face_encoding_ref is None

    def test_face_encoding_ref_kept_when_store_face_true(self):
        pm = MemoryPrivacyManager(store_face_data=True)
        user = UserRecord(
            display_name="Eve",
            face_encoding_ref="face_token_xyz",
        )
        screened = pm.screen_user(user)
        assert screened.face_encoding_ref == "face_token_xyz"

    def test_update_config(self):
        pm = MemoryPrivacyManager(store_audio=False)
        assert pm.store_audio is False
        pm.update_config(store_audio=True)
        assert pm.store_audio is True

    def test_build_forget_audit_entry(self):
        pm = MemoryPrivacyManager()
        entry = pm.build_forget_audit_entry(user_id="u123", actor="admin_node")
        assert entry.action == "forget_user"
        assert entry.target_id == "u123"
        assert entry.actor == "admin_node"


# ---------------------------------------------------------------------------
# Scenario 18: RetentionPolicyManager
# ---------------------------------------------------------------------------


class TestRetentionPolicyManager:
    def test_sweep_purges_7day_old_interactions(
        self, interaction_repo, robot_state_repo, nav_repo, safety_repo
    ):
        pm = RetentionPolicyManager(
            interaction_repo=interaction_repo,
            robot_state_repo=robot_state_repo,
            navigation_repo=nav_repo,
            safety_repo=safety_repo,
        )

        # Insert an interaction that is 8 days old with a 7_days policy
        old = InteractionEvent(
            input_text="old message",
            retention_policy=RetentionPolicy.SEVEN_DAYS,
        )
        old = old.model_copy(update={"timestamp": time.time() - 8 * 86400})
        interaction_repo.save(old)

        results = pm.sweep()
        assert results.get("interactions", 0) >= 1

    def test_sweep_does_not_purge_permanent(
        self, interaction_repo, robot_state_repo, nav_repo, safety_repo
    ):
        pm = RetentionPolicyManager(
            interaction_repo=interaction_repo,
            robot_state_repo=robot_state_repo,
            navigation_repo=nav_repo,
            safety_repo=safety_repo,
        )
        perm = InteractionEvent(
            input_text="keep forever",
            retention_policy=RetentionPolicy.PERMANENT_UNTIL_DELETED,
        )
        # Make it "old"
        perm = perm.model_copy(update={"timestamp": time.time() - 1000 * 86400})
        interaction_repo.save(perm)

        pm.sweep()
        fetched = interaction_repo.get_by_id(perm.event_id)
        assert fetched is not None

    def test_ttl_for_policy(self, interaction_repo, robot_state_repo, nav_repo, safety_repo):
        pm = RetentionPolicyManager(interaction_repo, robot_state_repo, nav_repo, safety_repo)
        assert pm.ttl_for_policy("7_days") == 7 * 86400
        assert pm.ttl_for_policy("permanent_until_deleted") is None

    def test_purge_session_data(self, interaction_repo, robot_state_repo, nav_repo, safety_repo):
        pm = RetentionPolicyManager(interaction_repo, robot_state_repo, nav_repo, safety_repo)
        session_id = "sess_test_123"
        event = InteractionEvent(
            input_text="ephemeral message",
            session_id=session_id,
            retention_policy=RetentionPolicy.EPHEMERAL,
        )
        interaction_repo.save(event)
        pm.purge_session_data(session_id)
        fetched = interaction_repo.get_by_id(event.event_id)
        assert fetched is None


# ---------------------------------------------------------------------------
# Scenario 19: DataStoreHealthMonitor
# ---------------------------------------------------------------------------


class TestDataStoreHealthMonitor:
    def test_healthy_with_good_sqlite(self, db_conn):
        monitor = DataStoreHealthMonitor(
            conn=db_conn,
            faiss_store=None,  # not using vector store
            chroma_store=None,
        )
        health = monitor.check()
        # SQLite is available; FAISS/Chroma absent → DEGRADED at worst
        assert health.sqlite.available is True
        assert health.level in (HealthLevel.HEALTHY, HealthLevel.DEGRADED)

    def test_degraded_when_faiss_missing(self, db_conn):
        import tempfile
        from pathlib import Path

        from bonbon_data_stores.vector.faiss_store import FAISSVectorStore

        with tempfile.TemporaryDirectory() as td:
            faiss = FAISSVectorStore(index_dir=Path(td), dim=64, enabled=False)
            monitor = DataStoreHealthMonitor(conn=db_conn, faiss_store=faiss, chroma_store=None)
            health = monitor.check()
            assert health.faiss.available is False
            assert health.level == HealthLevel.DEGRADED

    def test_health_to_dict(self, db_conn):
        monitor = DataStoreHealthMonitor(conn=db_conn)
        health = monitor.check()
        d = health.to_dict()
        assert "level" in d
        assert "stores" in d
        assert "sqlite" in d["stores"]
        assert "faiss" in d["stores"]
        assert "chroma" in d["stores"]

    def test_last_health_cached(self, db_conn):
        monitor = DataStoreHealthMonitor(conn=db_conn)
        assert monitor.last_health is None
        monitor.check()
        assert monitor.last_health is not None
