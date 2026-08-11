"""ChromaRAGStore — five ChromaDB collections with graceful degraded mode.

Collections
-----------
bonbon_knowledge          — general robot knowledge
bonbon_menu               — venue / menu information
bonbon_faqs               — frequently asked questions
bonbon_procedures         — operational procedures
bonbon_conversations      — conversation templates / examples

When ``chromadb`` is not installed the store operates in degraded mode:
``query()`` returns empty results; ``add()`` is a no-op.

DEPRECATED (GAP-E9, see docs/EDGE_AI_GAP_ANALYSIS.md): this class is
constructed by SQLiteMemoryStore.__init__ but is not wired to any live
ROS2 topic/service anywhere in this repo -- ``data_store_node.py`` only
exposes ``health_check``/``create_backup`` services, neither of which
touches ``store.chroma``/``store.rag``. Confirmed via repo-wide grep: no
production caller queries it. The real, live RAG implementation every
production caller actually uses is
``bonbon_llm.core.rag_retriever.RAGRetriever``
(ros2_ws/src/bonbon_llm/bonbon_llm/core/rag_retriever.py). Do not build
new RAG-consuming code (including bonbon_edge_ai_runtime.task_router's
FAQ routing) against this class -- it will silently return nothing
useful. Kept in place (not deleted) because tests/test_backup.py and
tests/test_rag_store.py still exercise it directly and deleting it would
require an unrelated refactor of SQLiteMemoryStore's storage-facade
contract, out of scope for the pass that identified this gap.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from bonbon_data_stores.schema.models import RAGSearchResult

logger = logging.getLogger(__name__)

# Optional ChromaDB import
try:
    import chromadb  # type: ignore
    from chromadb.config import Settings  # type: ignore

    _HAS_CHROMA = True
except ImportError:
    chromadb = None  # type: ignore
    Settings = None  # type: ignore
    _HAS_CHROMA = False

COLLECTION_NAMES = (
    "knowledge",
    "menu",
    "faqs",
    "procedures",
    "conversations",
)


class ChromaRAGStore:
    """Thin wrapper around ChromaDB that exposes add / query / delete.

    Parameters
    ----------
    persist_dir:
        Directory where ChromaDB persists its data.
    collection_prefix:
        Prefix prepended to every collection name (default: ``bonbon_``).
    max_results:
        Default number of results returned per query.
    distance_threshold:
        Results with distance > threshold are filtered out.
    enabled:
        Hard-disable (useful for testing without ChromaDB installed).
    """

    def __init__(
        self,
        persist_dir,
        collection_prefix: str = "bonbon_",
        max_results: int = 10,
        distance_threshold: float = 0.75,
        enabled: bool = True,
    ) -> None:
        self._prefix = collection_prefix
        self._max_results = max_results
        self._threshold = distance_threshold
        self._enabled = enabled and _HAS_CHROMA
        self._client = None
        self._collections: dict[str, Any] = {}

        if not _HAS_CHROMA:
            logger.warning(
                "chromadb not installed; ChromaRAGStore running in degraded mode. "
                "Run: pip install chromadb"
            )
        elif not enabled:
            logger.info("ChromaRAGStore disabled by configuration.")
        else:
            self._init_client(persist_dir)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_degraded(self) -> bool:
        return not self._enabled

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add(
        self,
        collection: str,
        document: str,
        metadata: dict[str, Any] | None = None,
        doc_id: str | None = None,
    ) -> str:
        """Add a document to *collection*.  Returns the doc_id."""
        self._validate_collection(collection)
        if not self._enabled:
            return doc_id or str(uuid.uuid4())
        did = doc_id or str(uuid.uuid4())
        col = self._get_collection(collection)
        col.add(
            documents=[document],
            metadatas=[metadata or {}],
            ids=[did],
        )
        return did

    def add_batch(
        self,
        collection: str,
        documents: list[str],
        metadatas: list[dict[str, Any]] | None = None,
        ids: list[str] | None = None,
    ) -> list[str]:
        """Add a batch of documents to *collection*."""
        self._validate_collection(collection)
        if not self._enabled:
            return ids or [str(uuid.uuid4()) for _ in documents]
        dids = ids or [str(uuid.uuid4()) for _ in documents]
        metas = metadatas or [{} for _ in documents]
        col = self._get_collection(collection)
        col.add(documents=documents, metadatas=metas, ids=dids)
        return dids

    def query(
        self,
        collection: str,
        query_text: str,
        n_results: int | None = None,
    ) -> list[RAGSearchResult]:
        """Semantic search in *collection*."""
        self._validate_collection(collection)
        if not self._enabled:
            return []
        k = n_results or self._max_results
        col = self._get_collection(collection)

        try:
            results = col.query(
                query_texts=[query_text],
                n_results=min(k, max(col.count(), 1)),
                include=["documents", "metadatas", "distances"],
            )
        except Exception as exc:
            logger.error("ChromaDB query failed for collection %r: %s", collection, exc)
            return []

        out: list[RAGSearchResult] = []
        for doc_id, doc, meta, dist in zip(
            results["ids"][0],
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        ):
            if dist <= self._threshold:
                out.append(
                    RAGSearchResult(
                        doc_id=doc_id,
                        collection=collection,
                        score=float(1.0 - dist),  # convert distance to similarity
                        document=doc,
                        metadata=meta or {},
                    )
                )
        return out

    def delete(self, collection: str, doc_id: str) -> bool:
        """Delete document by ID from *collection*."""
        self._validate_collection(collection)
        if not self._enabled:
            return False
        try:
            col = self._get_collection(collection)
            col.delete(ids=[doc_id])
            return True
        except Exception as exc:
            logger.error("ChromaDB delete failed: %s", exc)
            return False

    def count(self, collection: str) -> int:
        self._validate_collection(collection)
        if not self._enabled:
            return 0
        return self._get_collection(collection).count()

    def collection_names(self) -> list[str]:
        return list(COLLECTION_NAMES)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _init_client(self, persist_dir) -> None:
        try:
            self._client = chromadb.PersistentClient(
                path=str(persist_dir),
            )
            # Pre-warm all collections
            for name in COLLECTION_NAMES:
                self._get_collection(name)
            logger.info("ChromaDB client initialised at %s", persist_dir)
        except Exception as exc:
            logger.error("Failed to initialise ChromaDB: %s — running in degraded mode.", exc)
            self._enabled = False

    def _get_collection(self, name: str):
        full_name = f"{self._prefix}{name}"
        if full_name not in self._collections:
            self._collections[full_name] = self._client.get_or_create_collection(full_name)
        return self._collections[full_name]

    @staticmethod
    def _validate_collection(name: str) -> None:
        if name not in COLLECTION_NAMES:
            raise ValueError(f"Unknown ChromaDB collection {name!r}. Valid: {COLLECTION_NAMES}")
