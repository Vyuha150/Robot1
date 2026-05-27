"""SQLiteMemoryStore — unified facade over all BonBon data stores.

This is the single entry point for all storage operations.  All sub-systems
(SQLite repos, FAISS, ChromaDB, privacy, retention, backup, health) are
assembled here.

Usage::

    from bonbon_data_stores.store import SQLiteMemoryStore
    from bonbon_data_stores.config.store_config import DataStoreConfig

    store = SQLiteMemoryStore(DataStoreConfig.from_env())
    store.open()

    event = InteractionEvent(user_id="u1", input_text="Hello!")
    store.interactions.save(store.privacy.screen_interaction(event))

    store.close()
"""

from __future__ import annotations

import logging

from bonbon_data_stores.backup.backup_manager import BackupRestoreManager
from bonbon_data_stores.config.store_config import DataStoreConfig
from bonbon_data_stores.health.health_monitor import DataStoreHealth, DataStoreHealthMonitor
from bonbon_data_stores.privacy.privacy_manager import MemoryPrivacyManager
from bonbon_data_stores.privacy.retention_manager import RetentionPolicyManager
from bonbon_data_stores.rag.chroma_store import ChromaRAGStore
from bonbon_data_stores.rag.rag_query_engine import RAGQueryEngine
from bonbon_data_stores.sqlite.connection import SQLiteConnection
from bonbon_data_stores.sqlite.migrations import SchemaMigrator
from bonbon_data_stores.sqlite.repositories.audit_log_repo import AuditLogRepository
from bonbon_data_stores.sqlite.repositories.interaction_repo import InteractionHistoryRepository
from bonbon_data_stores.sqlite.repositories.map_metadata_repo import MapMetadataRepository
from bonbon_data_stores.sqlite.repositories.navigation_event_repo import NavigationEventRepository
from bonbon_data_stores.sqlite.repositories.robot_state_repo import RobotStateRepository
from bonbon_data_stores.sqlite.repositories.safety_event_repo import SafetyEventRepository
from bonbon_data_stores.sqlite.repositories.user_repo import UserProfileRepository
from bonbon_data_stores.vector.embedding_manager import EmbeddingManager
from bonbon_data_stores.vector.faiss_store import FAISSVectorStore

logger = logging.getLogger(__name__)


class SQLiteMemoryStore:
    """Assemble and expose all data-store subsystems.

    Lifecycle: ``open()`` → use → ``close()``

    The store is also a context manager::

        with SQLiteMemoryStore(cfg) as store:
            store.users.save(user)
    """

    def __init__(self, config: DataStoreConfig | None = None) -> None:
        self._cfg = config or DataStoreConfig()

        # Core connection
        self._conn = SQLiteConnection(
            db_path=self._cfg.sqlite.db_path,
            wal_mode=self._cfg.sqlite.wal_mode,
            cache_size_kb=self._cfg.sqlite.cache_size_kb,
            busy_timeout_ms=self._cfg.sqlite.busy_timeout_ms,
        )

        # Repositories
        self.users = UserProfileRepository(self._conn)
        self.interactions = InteractionHistoryRepository(self._conn)
        self.robot_states = RobotStateRepository(self._conn)
        self.safety_events = SafetyEventRepository(self._conn)
        self.navigation_events = NavigationEventRepository(self._conn)
        self.audit_log = AuditLogRepository(self._conn)
        self.maps = MapMetadataRepository(self._conn)

        # Optional vector store
        self.embeddings = EmbeddingManager(
            model_name=self._cfg.embedding.model_name,
            dim=self._cfg.faiss.embedding_dim,
            device=self._cfg.embedding.device,
            batch_size=self._cfg.embedding.batch_size,
            cache_size=self._cfg.embedding.cache_size,
            use_hash_fallback=self._cfg.embedding.use_hash_fallback,
        )
        self.vectors = FAISSVectorStore(
            index_dir=self._cfg.faiss.index_dir,
            dim=self._cfg.faiss.embedding_dim,
            auto_save=self._cfg.faiss.auto_save,
            enabled=self._cfg.faiss.enabled,
        )

        # RAG
        self.chroma = ChromaRAGStore(
            persist_dir=self._cfg.chroma.persist_dir,
            collection_prefix=self._cfg.chroma.collection_prefix,
            max_results=self._cfg.chroma.max_results,
            distance_threshold=self._cfg.chroma.distance_threshold,
            enabled=self._cfg.chroma.enabled,
        )
        self.rag = RAGQueryEngine(self.chroma)

        # Privacy / retention
        self.privacy = MemoryPrivacyManager(
            store_audio=self._cfg.privacy.store_audio,
            store_face_data=self._cfg.privacy.store_face_data,
        )
        self.retention = RetentionPolicyManager(
            interaction_repo=self.interactions,
            robot_state_repo=self.robot_states,
            navigation_repo=self.navigation_events,
            safety_repo=self.safety_events,
        )

        # Backup
        self.backup = BackupRestoreManager(
            db_path=self._cfg.sqlite.db_path,
            faiss_index_dir=self._cfg.faiss.index_dir,
            chroma_persist_dir=self._cfg.chroma.persist_dir,
            backup_dir=self._cfg.backup.backup_dir,
            max_backups=self._cfg.backup.max_backups,
            compress=self._cfg.backup.compress,
        )

        # Health monitor
        self.health = DataStoreHealthMonitor(
            conn=self._conn,
            faiss_store=self.vectors,
            chroma_store=self.chroma,
        )

        self._is_open = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def open(self) -> None:
        """Initialise the database schema (run migrations)."""
        if self._is_open:
            return
        migrator = SchemaMigrator(self._conn)
        version = migrator.migrate()
        logger.info("bonbon_data_stores opened (schema v%d)", version)
        self._is_open = True

    def close(self) -> None:
        """Persist FAISS indexes and close the SQLite connection."""
        if not self._is_open:
            return
        try:
            self.vectors.save_all()
        except Exception as exc:
            logger.warning("Failed to persist FAISS indexes on close: %s", exc)
        self._conn.close()
        self._is_open = False
        logger.info("bonbon_data_stores closed")

    def __enter__(self) -> SQLiteMemoryStore:
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    @property
    def is_open(self) -> bool:
        return self._is_open

    @property
    def config(self) -> DataStoreConfig:
        return self._cfg

    def check_health(self) -> DataStoreHealth:
        return self.health.check()
