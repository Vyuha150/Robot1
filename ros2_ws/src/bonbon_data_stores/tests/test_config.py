"""Test scenario 1: DataStoreConfig — defaults, env-based init, path creation."""

from __future__ import annotations

import pytest
from bonbon_data_stores.config.store_config import (
    DataStoreConfig,
    FAISSConfig,
    PrivacyConfig,
    SQLiteConfig,
)


class TestSQLiteConfig:
    def test_defaults(self, tmp_path):
        cfg = SQLiteConfig(db_path=tmp_path / "test.db")
        assert cfg.wal_mode is True
        assert cfg.cache_size_kb == 16384
        assert cfg.busy_timeout_ms == 5000

    def test_parent_dir_created(self, tmp_path):
        deep = tmp_path / "a" / "b" / "c" / "test.db"
        SQLiteConfig(db_path=deep)
        assert deep.parent.exists()

    def test_cache_size_minimum_enforced(self):
        with pytest.raises(Exception):
            SQLiteConfig(cache_size_kb=0)


class TestFAISSConfig:
    def test_index_dir_created(self, tmp_path):
        idir = tmp_path / "indexes"
        FAISSConfig(index_dir=idir)
        assert idir.exists()

    def test_enabled_default_true(self, tmp_path):
        cfg = FAISSConfig(index_dir=tmp_path)
        assert cfg.enabled is True


class TestPrivacyConfig:
    def test_store_audio_default_false(self):
        """CRITICAL: raw audio must NOT be stored by default."""
        cfg = PrivacyConfig()
        assert cfg.store_audio is False

    def test_store_face_data_default_false(self):
        """Biometric data must NOT be stored by default."""
        cfg = PrivacyConfig()
        assert cfg.store_face_data is False

    def test_anonymise_on_export_default_true(self):
        cfg = PrivacyConfig()
        assert cfg.anonymise_on_export is True


class TestDataStoreConfig:
    def test_all_defaults_construct(self):
        cfg = DataStoreConfig()
        assert cfg.sqlite is not None
        assert cfg.faiss is not None
        assert cfg.chroma is not None
        assert cfg.embedding is not None
        assert cfg.backup is not None
        assert cfg.privacy is not None

    def test_from_env_uses_base_dir(self, tmp_path):
        cfg = DataStoreConfig.from_env(base_dir=str(tmp_path))
        assert str(tmp_path) in str(cfg.sqlite.db_path)
        assert str(tmp_path) in str(cfg.faiss.index_dir)
        assert str(tmp_path) in str(cfg.chroma.persist_dir)

    def test_from_env_var(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BONBON_DATA_DIR", str(tmp_path))
        cfg = DataStoreConfig.from_env()
        assert str(tmp_path) in str(cfg.sqlite.db_path)
