"""
tests.test_rag_retriever
=========================
Unit tests for bonbon_llm.core.rag_retriever.RAGRetriever.

Uses the NumPy backend (always available, no external deps required).
Tests cover
-----------
* Default knowledge seeding (8 documents)
* add_document / retrieve round-trip
* retrieve_with_scores returns score between 0 and 1
* top_k limit respected
* similarity threshold filters low-score results
* build_context_string produces non-empty output
* Thread-safety: concurrent retrieval does not raise
* Empty query returns results without error
"""

import threading

import pytest
from bonbon_llm.config.llm_config import RAGConfig
from bonbon_llm.core.rag_retriever import RAGDocument, RAGRetriever, RetrievalResult

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def rag() -> RAGRetriever:
    """RAGRetriever with NumPy backend, loaded with default documents."""
    cfg = RAGConfig(backend="numpy", top_k=5, similarity_threshold=0.0)
    r = RAGRetriever(cfg)
    r.load()
    return r


@pytest.fixture()
def rag_strict() -> RAGRetriever:
    """RAGRetriever with strict similarity threshold."""
    cfg = RAGConfig(backend="numpy", top_k=5, similarity_threshold=0.50)
    r = RAGRetriever(cfg)
    r.load()
    return r


# ── Default knowledge seeding ──────────────────────────────────────────────────


class TestDefaultKnowledge:

    def test_docs_seeded_after_load(self, rag):
        results = rag.retrieve("robot capabilities")
        assert len(results) > 0, "Should return results from default knowledge"

    def test_menu_retrievable(self, rag):
        results = rag.retrieve("latte price espresso menu")
        texts = [r.document.text for r in results]
        assert any(
            "menu" in t.lower() or "latte" in t.lower() or "espresso" in t.lower() for t in texts
        )

    def test_safety_retrievable(self, rag):
        results = rag.retrieve("safety rules stop navigation danger")
        texts = [r.document.text for r in results]
        assert any("safety" in t.lower() for t in texts)

    def test_emergency_retrievable(self, rag):
        results = rag.retrieve("emergency ambulance 995")
        texts = [r.document.text for r in results]
        assert any("emergency" in t.lower() or "995" in t for t in texts)


# ── add_document / retrieve round-trip ───────────────────────────────────────


class TestAddAndRetrieve:

    def test_added_document_is_retrievable(self, rag):
        rag.add_document(
            "We have a new seasonal drink: Pandan Latte at S$6.00.",
            metadata={"category": "seasonal_menu"},
            doc_id="pandan_latte_001",
        )
        results = rag.retrieve("pandan latte")
        found = any("pandan" in r.document.text.lower() for r in results)
        assert found, "Newly added document should be retrievable"

    def test_added_doc_has_correct_text(self, rag):
        text = "The robot's charging station is at the north wall."
        doc = rag.add_document(text)
        assert doc.text == text

    def test_added_doc_returns_rag_document(self, rag):
        doc = rag.add_document("test document for unit test")
        assert isinstance(doc, RAGDocument)
        assert doc.doc_id is not None

    def test_custom_doc_id_preserved(self, rag):
        doc = rag.add_document("Some content.", doc_id="my_custom_id_42")
        assert doc.doc_id == "my_custom_id_42"

    def test_metadata_preserved(self, rag):
        meta = {"source": "operator_config", "version": "1.0"}
        doc = rag.add_document("Operator note: always greet by name.", metadata=meta)
        assert doc.metadata == meta


# ── retrieve_with_scores ──────────────────────────────────────────────────────


class TestRetrieveWithScores:

    def test_scores_in_range(self, rag):
        results = rag.retrieve_with_scores("latte menu price")
        for r in results:
            assert 0.0 <= r.score <= 1.0, f"Score {r.score} out of [0,1] range"

    def test_returns_retrieval_result_objects(self, rag):
        results = rag.retrieve_with_scores("robot navigation")
        assert all(isinstance(r, RetrievalResult) for r in results)

    def test_results_sorted_by_score_descending(self, rag):
        results = rag.retrieve_with_scores("safety danger stop")
        scores = [r.score for r in results]
        assert scores == sorted(scores, reverse=True), "Results should be ranked by score"


# ── top_k enforcement ─────────────────────────────────────────────────────────


class TestTopK:

    def test_top_k_respected(self):
        cfg = RAGConfig(backend="numpy", top_k=3, similarity_threshold=0.0)
        rag = RAGRetriever(cfg)
        rag.load()
        results = rag.retrieve("café robot menu navigation")
        assert len(results) <= 3

    def test_top_k_1(self):
        cfg = RAGConfig(backend="numpy", top_k=1, similarity_threshold=0.0)
        rag = RAGRetriever(cfg)
        rag.load()
        results = rag.retrieve("espresso price")
        assert len(results) == 1


# ── Similarity threshold ──────────────────────────────────────────────────────


class TestSimilarityThreshold:

    def test_threshold_filters_low_scores(self, rag_strict):
        # With threshold 0.50, very dissimilar queries return few/no results
        results = rag_strict.retrieve("xkzqw nonsense gibberish")
        # All returned results must meet the threshold
        for r in results:
            assert r.score >= 0.50, f"Result with score {r.score:.3f} below threshold 0.50"

    def test_zero_threshold_allows_all(self, rag):
        # With threshold=0.0, even an empty/nonsense query returns results
        results = rag.retrieve("zzz")
        assert isinstance(results, list)  # no crash


# ── build_context_string ──────────────────────────────────────────────────────


class TestBuildContextString:

    def test_context_string_non_empty_on_hit(self, rag):
        ctx = rag.build_context_string("latte menu price")
        assert isinstance(ctx, str)
        assert len(ctx) > 0

    def test_context_string_contains_retrieved_text(self, rag):
        rag.add_document("Our special token ZZTESTTOKEN appears in the menu today.")
        ctx = rag.build_context_string("ZZTESTTOKEN special menu")
        assert "ZZTESTTOKEN" in ctx


# ── Thread safety ─────────────────────────────────────────────────────────────


class TestThreadSafety:

    def test_concurrent_retrieve_no_exception(self, rag):
        errors = []

        def _retrieve():
            try:
                rag.retrieve("coffee menu safety robot")
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=_retrieve) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Concurrent retrieval raised: {errors}"

    def test_concurrent_add_and_retrieve(self, rag):
        errors = []

        def _add(i):
            try:
                rag.add_document(f"Thread-safe test document number {i}.")
            except Exception as exc:
                errors.append(exc)

        def _read():
            try:
                rag.retrieve("thread safe document test")
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=_add, args=(i,)) for i in range(5)]
        threads += [threading.Thread(target=_read) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Concurrent add/retrieve raised: {errors}"


# ── Edge cases ────────────────────────────────────────────────────────────────


class TestEdgeCases:

    def test_empty_query_does_not_crash(self, rag):
        results = rag.retrieve("")
        assert isinstance(results, list)

    def test_very_long_query(self, rag):
        long_query = "latte " * 100
        results = rag.retrieve(long_query)
        assert isinstance(results, list)

    def test_unicode_query(self, rag):
        results = rag.retrieve("咖啡 价格 菜单")
        assert isinstance(results, list)

    def test_load_idempotent(self, rag):
        # Calling load() twice should not raise or double-seed
        count_before = len(rag.retrieve("robot"))
        rag.load()
        count_after = len(rag.retrieve("robot"))
        assert count_before == count_after
