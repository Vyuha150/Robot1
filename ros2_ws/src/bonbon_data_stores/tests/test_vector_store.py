"""Test scenarios 13-14: EmbeddingManager and FAISSVectorStore.

These tests run in all environments — they use the hash-based fallback
embedding so they do NOT require sentence-transformers or faiss-cpu to be
installed.  Tests that do require faiss are marked with @pytest.mark.faiss.
"""

from __future__ import annotations

import numpy as np
import pytest
from bonbon_data_stores.vector.embedding_manager import EmbeddingManager, _hash_embed
from bonbon_data_stores.vector.faiss_store import INDEX_NAMES, FAISSVectorStore

# ---------------------------------------------------------------------------
# Scenario 13: EmbeddingManager
# ---------------------------------------------------------------------------


class TestEmbeddingManager:
    def test_hash_fallback_produces_vector(self):
        vec = _hash_embed("hello world", dim=384)
        assert vec.shape == (384,)
        assert vec.dtype == np.float32

    def test_hash_fallback_deterministic(self):
        v1 = _hash_embed("same text", dim=384)
        v2 = _hash_embed("same text", dim=384)
        np.testing.assert_array_equal(v1, v2)

    def test_hash_fallback_different_texts(self):
        v1 = _hash_embed("text A", dim=384)
        v2 = _hash_embed("text B", dim=384)
        assert not np.allclose(v1, v2)

    def test_embedding_manager_fallback_mode(self):
        em = EmbeddingManager(
            model_name="nonexistent-model",
            dim=384,
            use_hash_fallback=True,
        )
        assert em.is_fallback is True
        vec = em.embed("hello")
        assert vec.shape == (384,)

    def test_embed_batch_returns_correct_shape(self):
        em = EmbeddingManager(
            model_name="nonexistent-model",
            dim=64,
            use_hash_fallback=True,
        )
        batch = em.embed_batch(["a", "b", "c"])
        assert batch.shape == (3, 64)

    def test_embed_empty_batch(self):
        em = EmbeddingManager(model_name="x", dim=64, use_hash_fallback=True)
        result = em.embed_batch([])
        assert result.shape == (0, 64)

    def test_embedding_manager_no_fallback_raises(self):
        with pytest.raises(ImportError):
            EmbeddingManager(
                model_name="nonexistent-model",
                dim=384,
                use_hash_fallback=False,
            )


# ---------------------------------------------------------------------------
# Scenario 14: FAISSVectorStore
# ---------------------------------------------------------------------------


class TestFAISSVectorStoreDegraded:
    """Tests that run even without faiss-cpu installed (degraded mode)."""

    def test_degraded_mode_add_returns_id(self, tmp_path):
        store = FAISSVectorStore(index_dir=tmp_path, dim=64, enabled=False)
        assert store.is_degraded is True
        vid = store.add("interactions", np.zeros(64, dtype=np.float32))
        assert isinstance(vid, str)

    def test_degraded_mode_search_returns_empty(self, tmp_path):
        store = FAISSVectorStore(index_dir=tmp_path, dim=64, enabled=False)
        results = store.search("interactions", np.zeros(64, dtype=np.float32))
        assert results == []

    def test_degraded_mode_count_zero(self, tmp_path):
        store = FAISSVectorStore(index_dir=tmp_path, dim=64, enabled=False)
        assert store.count("interactions") == 0

    def test_invalid_index_name_raises(self, tmp_path):
        store = FAISSVectorStore(index_dir=tmp_path, dim=64, enabled=False)
        with pytest.raises(ValueError):
            store.add("nonexistent_index", np.zeros(64))


@pytest.mark.faiss
class TestFAISSVectorStoreLive:
    """Tests that require faiss-cpu to be installed."""

    def test_add_and_search(self, tmp_path):
        pytest.importorskip("faiss")
        store = FAISSVectorStore(index_dir=tmp_path, dim=64, enabled=True, auto_save=False)
        if store.is_degraded:
            pytest.skip("faiss not available")

        em = EmbeddingManager(model_name="x", dim=64, use_hash_fallback=True)
        v1 = em.embed("hello world")
        v2 = em.embed("goodbye")

        store.add("knowledge", v1, payload={"text": "hello world"})
        store.add("knowledge", v2, payload={"text": "goodbye"})

        results = store.search("knowledge", em.embed("hello world"), top_k=2)
        assert len(results) >= 1
        assert results[0].payload.get("text") is not None

    def test_all_index_names_valid(self, tmp_path):
        pytest.importorskip("faiss")
        store = FAISSVectorStore(index_dir=tmp_path, dim=64, enabled=True, auto_save=False)
        if store.is_degraded:
            pytest.skip("faiss not available")
        for name in INDEX_NAMES:
            assert store.count(name) == 0

    def test_delete_vector(self, tmp_path):
        pytest.importorskip("faiss")
        store = FAISSVectorStore(index_dir=tmp_path, dim=64, enabled=True, auto_save=False)
        if store.is_degraded:
            pytest.skip("faiss not available")

        em = EmbeddingManager(model_name="x", dim=64, use_hash_fallback=True)
        vid = store.add("navigation", em.embed("room A"), payload={"room": "A"})
        assert store.count("navigation") == 1
        removed = store.delete("navigation", vid)
        assert removed is True
        assert store.count("navigation") == 0
