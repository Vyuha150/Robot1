"""DataStoreConfig — central pydantic v2 configuration for bonbon_data_stores.

All paths, limits, retention defaults, and privacy defaults live here so
every sub-system reads from a single authoritative source.
"""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, Field, model_validator

# ---------------------------------------------------------------------------
# Sub-config blocks
# ---------------------------------------------------------------------------


class SQLiteConfig(BaseModel):
    """Configuration for the SQLite memory store."""

    db_path: Path = Field(
        default=Path("/tmp/bonbon/data/bonbon_memory.db"),
        description="Absolute path to the SQLite database file.",
    )
    wal_mode: bool = Field(default=True, description="Enable WAL journal mode.")
    cache_size_kb: int = Field(default=16384, ge=1024, description="Page-cache size in KB.")
    busy_timeout_ms: int = Field(default=5000, ge=0, description="Busy-wait timeout in ms.")
    max_connections: int = Field(default=10, ge=1, le=64)
    # Retention sweeper
    retention_sweep_interval_sec: int = Field(default=3600, ge=60)

    @model_validator(mode="after")
    def _ensure_parent_dir(self) -> SQLiteConfig:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        return self


class FAISSConfig(BaseModel):
    """Configuration for the FAISS vector store."""

    index_dir: Path = Field(
        default=Path("/tmp/bonbon/data/faiss_indexes"),
        description="Directory where FAISS index files are stored.",
    )
    embedding_dim: int = Field(default=384, ge=64, le=4096)
    n_lists: int = Field(
        default=100,
        ge=1,
        description="Number of IVF lists (used when index size > nlist_threshold).",
    )
    nlist_threshold: int = Field(
        default=10_000,
        ge=1,
        description="Switch from Flat to IVF index when vector count exceeds this.",
    )
    n_probe: int = Field(default=10, ge=1, description="Number of IVF clusters to probe.")
    max_vectors_per_index: int = Field(default=100_000, ge=100)
    auto_save: bool = Field(default=True, description="Persist indexes to disk after add/delete.")
    enabled: bool = Field(default=True)

    @model_validator(mode="after")
    def _ensure_index_dir(self) -> FAISSConfig:
        self.index_dir.mkdir(parents=True, exist_ok=True)
        return self


class ChromaConfig(BaseModel):
    """Configuration for the ChromaDB RAG store."""

    persist_dir: Path = Field(
        default=Path("/tmp/bonbon/data/chromadb"),
        description="Persistent storage directory for ChromaDB.",
    )
    collection_prefix: str = Field(
        default="bonbon_", description="Prefix for all collection names."
    )
    max_results: int = Field(default=10, ge=1, le=100, description="Default max results per query.")
    distance_threshold: float = Field(
        default=0.75,
        ge=0.0,
        le=2.0,
        description="Maximum distance for a result to be considered relevant.",
    )
    enabled: bool = Field(default=True)

    @model_validator(mode="after")
    def _ensure_persist_dir(self) -> ChromaConfig:
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        return self


class EmbeddingConfig(BaseModel):
    """Configuration for the sentence-transformer embedding model."""

    model_name: str = Field(
        default="all-MiniLM-L6-v2",
        description="HuggingFace model name. Injected via ROS2 param — never hardcoded.",
    )
    device: str = Field(default="cpu", description="'cpu' or 'cuda'.")
    batch_size: int = Field(default=32, ge=1)
    cache_size: int = Field(
        default=1000,
        ge=0,
        description="Number of embeddings to cache in memory (0 = disabled).",
    )
    # Fallback: use hash-based embeddings when transformers not installed
    use_hash_fallback: bool = Field(
        default=True,
        description="Fall back to deterministic hash embeddings when sentence-transformers is absent.",
    )


class BackupConfig(BaseModel):
    """Configuration for backup and restore operations."""

    backup_dir: Path = Field(
        default=Path("/tmp/bonbon/backups"),
        description="Root directory for backup archives.",
    )
    max_backups: int = Field(default=7, ge=1, description="Number of rolling backups to keep.")
    compress: bool = Field(default=True, description="GZip-compress backup archives.")
    auto_backup_interval_sec: int = Field(
        default=86400,
        ge=3600,
        description="Interval between automatic backups (0 = disabled).",
    )

    @model_validator(mode="after")
    def _ensure_backup_dir(self) -> BackupConfig:
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        return self


class PrivacyConfig(BaseModel):
    """Default privacy-level and behaviour overrides."""

    default_privacy_level: str = Field(
        default="internal",
        description="Default privacy level for events that don't specify one.",
    )
    store_audio: bool = Field(
        default=False,
        description=(
            "Raw audio is NEVER stored unless explicitly enabled. "
            "privacy.store_audio=False is the safe default."
        ),
    )
    store_face_data: bool = Field(
        default=False,
        description="Biometric face data is not stored by default.",
    )
    anonymise_on_export: bool = Field(
        default=True,
        description="Strip PII from exported records.",
    )
    # Retention defaults (in days; 0 = permanent-until-deleted)
    retention_defaults: dict[str, int] = Field(
        default_factory=lambda: {
            "ephemeral": 0,  # purged after session
            "session_only": 0,  # purged at session end
            "7_days": 7,
            "30_days": 30,
            "1_year": 365,
            "permanent_until_deleted": 0,
        }
    )


# ---------------------------------------------------------------------------
# Top-level config
# ---------------------------------------------------------------------------


class DataStoreConfig(BaseModel):
    """Root configuration object for the whole bonbon_data_stores package.

    Usage::

        cfg = DataStoreConfig()               # all defaults
        cfg = DataStoreConfig(sqlite=SQLiteConfig(db_path=Path("/my/path.db")))
        cfg = DataStoreConfig.from_env()      # read BONBON_DATA_DIR env var
    """

    sqlite: SQLiteConfig = Field(default_factory=SQLiteConfig)
    faiss: FAISSConfig = Field(default_factory=FAISSConfig)
    chroma: ChromaConfig = Field(default_factory=ChromaConfig)
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    backup: BackupConfig = Field(default_factory=BackupConfig)
    privacy: PrivacyConfig = Field(default_factory=PrivacyConfig)

    # ROS2-param extras
    node_name: str = Field(default="data_store_node")
    log_level: str = Field(default="INFO")

    @classmethod
    def from_env(cls, base_dir: str | None = None) -> DataStoreConfig:
        """Build config rooted at *base_dir* (or the BONBON_DATA_DIR env var).

        All sub-paths are placed under *base_dir* so the whole store can be
        relocated by setting a single environment variable.
        """
        root = Path(base_dir or os.environ.get("BONBON_DATA_DIR", "/tmp/bonbon/data"))
        return cls(
            sqlite=SQLiteConfig(db_path=root / "bonbon_memory.db"),
            faiss=FAISSConfig(index_dir=root / "faiss_indexes"),
            chroma=ChromaConfig(persist_dir=root / "chromadb"),
            backup=BackupConfig(backup_dir=root.parent / "backups"),
        )
