"""RAGQueryEngine — multi-collection semantic search with re-ranking.

Provides a single ``query()`` method that searches one or all ChromaDB
collections and returns merged, de-duplicated, score-sorted results.
"""

from __future__ import annotations

import logging

from bonbon_data_stores.rag.chroma_store import COLLECTION_NAMES, ChromaRAGStore
from bonbon_data_stores.schema.models import RAGSearchResult

logger = logging.getLogger(__name__)


class RAGQueryEngine:
    """High-level query interface over the ChromaRAGStore.

    Parameters
    ----------
    store:
        An initialised ``ChromaRAGStore`` instance.
    default_collections:
        Collections to search when no explicit list is given.
        Defaults to all five collections.
    default_n_results:
        Number of results to return per collection.
    """

    def __init__(
        self,
        store: ChromaRAGStore,
        default_collections: list[str] | None = None,
        default_n_results: int = 5,
    ) -> None:
        self._store = store
        self._default_collections = default_collections or list(COLLECTION_NAMES)
        self._default_n = default_n_results

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def query(
        self,
        query_text: str,
        collections: list[str] | None = None,
        n_results: int | None = None,
        min_score: float = 0.0,
    ) -> list[RAGSearchResult]:
        """Search *collections* and return merged, score-sorted results.

        Parameters
        ----------
        query_text:
            The natural-language query string.
        collections:
            List of collection names to search.  ``None`` → all defaults.
        n_results:
            Max results per collection.
        min_score:
            Filter out results with score < min_score.

        Returns
        -------
        List of ``RAGSearchResult`` sorted by score descending.
        """
        if not query_text or not query_text.strip():
            return []

        target_collections = collections or self._default_collections
        k = n_results or self._default_n

        merged: list[RAGSearchResult] = []
        seen_ids: set = set()

        for coll in target_collections:
            try:
                results = self._store.query(coll, query_text, n_results=k)
                for r in results:
                    if r.doc_id not in seen_ids and r.score >= min_score:
                        seen_ids.add(r.doc_id)
                        merged.append(r)
            except Exception as exc:
                logger.warning("RAG query failed for collection %r: %s", coll, exc)

        merged.sort(key=lambda r: r.score, reverse=True)
        return merged[: k * len(target_collections)]

    def query_single(
        self,
        query_text: str,
        collection: str,
        n_results: int | None = None,
    ) -> list[RAGSearchResult]:
        """Query a single named collection."""
        return self._store.query(collection, query_text, n_results=n_results or self._default_n)

    def add_knowledge(self, document: str, metadata=None, doc_id=None) -> str:
        """Convenience: add to the ``knowledge`` collection."""
        return self._store.add("knowledge", document, metadata, doc_id)

    def add_faq(self, document: str, metadata=None, doc_id=None) -> str:
        """Convenience: add to the ``faqs`` collection."""
        return self._store.add("faqs", document, metadata, doc_id)

    def add_procedure(self, document: str, metadata=None, doc_id=None) -> str:
        """Convenience: add to the ``procedures`` collection."""
        return self._store.add("procedures", document, metadata, doc_id)

    @property
    def is_degraded(self) -> bool:
        return self._store.is_degraded
