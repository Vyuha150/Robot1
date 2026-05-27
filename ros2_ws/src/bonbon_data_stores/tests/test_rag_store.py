"""Test scenarios 15-16: ChromaRAGStore and RAGQueryEngine.

All tests work in degraded mode (chromadb not required).
Tests requiring the live ChromaDB are marked @pytest.mark.chroma.
"""

from __future__ import annotations

import pytest
from bonbon_data_stores.rag.chroma_store import COLLECTION_NAMES, ChromaRAGStore
from bonbon_data_stores.rag.rag_query_engine import RAGQueryEngine

# ---------------------------------------------------------------------------
# Scenario 15: ChromaRAGStore
# ---------------------------------------------------------------------------


class TestChromaRAGStoreDegraded:
    """Degraded-mode tests (no chromadb required)."""

    def test_degraded_add_returns_id(self, tmp_path):
        store = ChromaRAGStore(persist_dir=tmp_path, enabled=False)
        assert store.is_degraded is True
        did = store.add("knowledge", "Some fact about BonBon.")
        assert isinstance(did, str)

    def test_degraded_query_returns_empty(self, tmp_path):
        store = ChromaRAGStore(persist_dir=tmp_path, enabled=False)
        results = store.query("knowledge", "BonBon")
        assert results == []

    def test_degraded_count_zero(self, tmp_path):
        store = ChromaRAGStore(persist_dir=tmp_path, enabled=False)
        assert store.count("knowledge") == 0

    def test_invalid_collection_raises(self, tmp_path):
        store = ChromaRAGStore(persist_dir=tmp_path, enabled=False)
        with pytest.raises(ValueError):
            store.add("nonexistent_collection", "doc")

    def test_all_collection_names_valid(self, tmp_path):
        store = ChromaRAGStore(persist_dir=tmp_path, enabled=False)
        names = store.collection_names()
        assert set(names) == set(COLLECTION_NAMES)


@pytest.mark.chroma
class TestChromaRAGStoreLive:
    """Live ChromaDB tests."""

    def test_add_and_query(self, tmp_path):
        pytest.importorskip("chromadb")
        store = ChromaRAGStore(persist_dir=tmp_path, enabled=True)
        if store.is_degraded:
            pytest.skip("chromadb not available")

        store.add("knowledge", "BonBon is a service robot.", metadata={"source": "manual"})
        results = store.query("knowledge", "service robot", n_results=3)
        assert len(results) >= 1
        assert "BonBon" in results[0].document

    def test_count_after_add(self, tmp_path):
        pytest.importorskip("chromadb")
        store = ChromaRAGStore(persist_dir=tmp_path, enabled=True)
        if store.is_degraded:
            pytest.skip("chromadb not available")

        store.add("faqs", "How do I order?", metadata={})
        assert store.count("faqs") >= 1

    def test_delete(self, tmp_path):
        pytest.importorskip("chromadb")
        store = ChromaRAGStore(persist_dir=tmp_path, enabled=True)
        if store.is_degraded:
            pytest.skip("chromadb not available")

        did = store.add("procedures", "Cleaning procedure A")
        removed = store.delete("procedures", did)
        assert removed is True


# ---------------------------------------------------------------------------
# Scenario 16: RAGQueryEngine
# ---------------------------------------------------------------------------


class TestRAGQueryEngine:
    def test_empty_query_returns_empty(self, tmp_path):
        store = ChromaRAGStore(persist_dir=tmp_path, enabled=False)
        engine = RAGQueryEngine(store)
        assert engine.query("") == []
        assert engine.query("   ") == []

    def test_degraded_query_returns_empty(self, tmp_path):
        store = ChromaRAGStore(persist_dir=tmp_path, enabled=False)
        engine = RAGQueryEngine(store)
        results = engine.query("tell me about BonBon")
        assert results == []
        assert engine.is_degraded is True

    def test_convenience_add_knowledge(self, tmp_path):
        store = ChromaRAGStore(persist_dir=tmp_path, enabled=False)
        engine = RAGQueryEngine(store)
        did = engine.add_knowledge("Robots are helpful.")
        assert isinstance(did, str)

    @pytest.mark.chroma
    def test_multi_collection_search(self, tmp_path):
        pytest.importorskip("chromadb")
        store = ChromaRAGStore(persist_dir=tmp_path, enabled=True)
        if store.is_degraded:
            pytest.skip("chromadb not available")

        engine = RAGQueryEngine(store, default_n_results=3)
        engine.add_knowledge("BonBon serves coffee.", metadata={"type": "menu"})
        engine.add_faq("What drinks are available?", metadata={})

        results = engine.query("coffee drinks", collections=["knowledge", "faqs"])
        assert isinstance(results, list)
        # Results sorted by score descending
        if len(results) >= 2:
            assert results[0].score >= results[1].score
