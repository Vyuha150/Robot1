"""Test scenario 20: BackupRestoreManager — create, list, prune, restore.

Also covers the SQLiteMemoryStore facade open/close/context-manager.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from bonbon_data_stores.backup.backup_manager import BackupRestoreManager
from bonbon_data_stores.schema.models import InteractionEvent
from bonbon_data_stores.store import SQLiteMemoryStore

# ---------------------------------------------------------------------------
# Scenario 20: BackupRestoreManager
# ---------------------------------------------------------------------------


class TestBackupRestoreManager:
    def _make_manager(self, tmp_path: Path) -> BackupRestoreManager:
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "faiss_indexes").mkdir()
        (data_dir / "chromadb").mkdir()
        # Create an empty SQLite file so backup() has something to copy
        import sqlite3

        db_path = data_dir / "bonbon_memory.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE IF NOT EXISTS _test (id INTEGER PRIMARY KEY);")
        conn.commit()
        conn.close()

        return BackupRestoreManager(
            db_path=db_path,
            faiss_index_dir=data_dir / "faiss_indexes",
            chroma_persist_dir=data_dir / "chromadb",
            backup_dir=tmp_path / "backups",
            max_backups=3,
            compress=True,
        )

    def test_create_backup_produces_archive(self, tmp_path):
        mgr = self._make_manager(tmp_path)
        archive = mgr.create_backup(label="test")
        assert archive.exists()
        assert archive.suffix == ".gz" or str(archive).endswith(".tar.gz")

    def test_list_backups_returns_entry(self, tmp_path):
        mgr = self._make_manager(tmp_path)
        mgr.create_backup(label="a")
        entries = mgr.list_backups()
        assert len(entries) >= 1
        path, mtime, size = entries[0]
        assert path.exists()
        assert size > 0

    def test_latest_backup(self, tmp_path):
        mgr = self._make_manager(tmp_path)
        mgr.create_backup(label="first")
        time.sleep(0.01)
        mgr.create_backup(label="second")
        latest = mgr.latest_backup()
        assert latest is not None
        assert "second" in str(latest)

    def test_prune_old_backups(self, tmp_path):
        mgr = self._make_manager(tmp_path)
        for i in range(5):
            mgr.create_backup(label=f"backup_{i}")
            time.sleep(0.01)
        entries = mgr.list_backups()
        assert len(entries) <= 3  # max_backups=3

    def test_restore_sqlite(self, tmp_path):
        mgr = self._make_manager(tmp_path)
        archive = mgr.create_backup(label="restore_test")
        results = mgr.restore_backup(archive)
        assert results["sqlite"] is True

    def test_restore_nonexistent_raises(self, tmp_path):
        mgr = self._make_manager(tmp_path)
        with pytest.raises(FileNotFoundError):
            mgr.restore_backup(Path("/nonexistent/backup.tar.gz"))


# ---------------------------------------------------------------------------
# SQLiteMemoryStore facade
# ---------------------------------------------------------------------------


class TestSQLiteMemoryStoreFacade:
    def test_open_close(self, db_config):
        store = SQLiteMemoryStore(db_config)
        store.open()
        assert store.is_open is True
        store.close()
        assert store.is_open is False

    def test_context_manager(self, db_config):
        with SQLiteMemoryStore(db_config) as store:
            assert store.is_open is True
        assert store.is_open is False

    def test_double_open_safe(self, db_config):
        store = SQLiteMemoryStore(db_config)
        store.open()
        store.open()  # should not raise
        assert store.is_open is True
        store.close()

    def test_save_interaction_via_store(self, store):
        event = InteractionEvent(input_text="test via facade")
        screened = store.privacy.screen_interaction(event)
        eid = store.interactions.save(screened)
        fetched = store.interactions.get_by_id(eid)
        assert fetched is not None
        assert fetched.input_text == "test via facade"

    def test_health_check_via_store(self, store):
        from bonbon_data_stores.health.health_monitor import HealthLevel

        health = store.check_health()
        assert health.level in list(HealthLevel)

    def test_store_exposes_all_repos(self, store):
        """Verify the facade exposes all required sub-systems."""
        assert store.users is not None
        assert store.interactions is not None
        assert store.robot_states is not None
        assert store.safety_events is not None
        assert store.navigation_events is not None
        assert store.audit_log is not None
        assert store.maps is not None
        assert store.vectors is not None
        assert store.chroma is not None
        assert store.rag is not None
        assert store.privacy is not None
        assert store.retention is not None
        assert store.backup is not None
        assert store.health is not None
