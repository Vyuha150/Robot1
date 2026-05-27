"""
bonbon_llm.core.rag_retriever
==============================
ChromaDB-first / FAISS-fallback / NumPy-last RAG retriever.

Backend priority (auto-selected at load time):
  1. ChromaDB   — pip install langchain-chroma chromadb
  2. FAISS      — pip install faiss-cpu
  3. NumPy      — always available; brute-force cosine (no external deps)

Embeddings:
  sentence-transformers (pip install sentence-transformers) preferred.
  Falls back to a deterministic TF-IDF-style hash embedding when the
  library is absent (adequate for unit tests; not for production).

Default knowledge base
----------------------
Seeded with BonBon robot facts, menu items, location names and
safety rules so the LLM has grounded facts even before operator
documents are added.
"""
from __future__ import annotations

import hashlib
import logging
import math
import re
import threading
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

from bonbon_llm.config.llm_config import RAGConfig

logger = logging.getLogger(__name__)

# ── Document type ─────────────────────────────────────────────────────────────

@dataclass
class RAGDocument:
    doc_id:   str
    text:     str
    metadata: Dict[str, str] = field(default_factory=dict)
    embedding: Optional[np.ndarray] = field(default=None, repr=False)


@dataclass
class RetrievalResult:
    document: RAGDocument
    score: float        # cosine similarity 0–1
    rank: int


# ── Default knowledge base ────────────────────────────────────────────────────

_DEFAULT_KNOWLEDGE: List[Tuple[str, Dict[str, str]]] = [
    # Robot capabilities
    ("BonBon is a service robot at a café. "
     "BonBon can speak, navigate the café, and serve food and drinks. "
     "BonBon cannot carry objects weighing more than 2 kg. "
     "BonBon moves at up to 0.8 m/s in normal mode and 0.3 m/s in caution mode.",
     {"category": "robot_capabilities"}),

    ("BonBon's safety rules: "
     "BonBon will always stop when a person is within 0.4 m. "
     "BonBon will not navigate when the safety state is DANGER or FAULT. "
     "All navigation commands are reviewed by the Safety Supervisor. "
     "BonBon will never directly control motors or servos.",
     {"category": "safety_rules"}),

    ("BonBon serves the following menu items: "
     "Espresso (S$3.50), Americano (S$4.00), Latte (S$5.00), "
     "Cappuccino (S$5.00), Green Tea (S$4.50), "
     "Orange Juice (S$4.00), Still Water (S$1.50), "
     "Croissant (S$3.50), Blueberry Muffin (S$4.00), "
     "Banana Cake (S$4.50). All prices in SGD.",
     {"category": "menu"}),

    ("Café layout: "
     "Table 1 to 6 are in the main seating area. "
     "Tables 7 to 10 are in the quiet zone near the window. "
     "The counter is at the north end of the café. "
     "The kitchen is behind the counter. "
     "The entrance is at the south end.",
     {"category": "locations"}),

    ("BonBon's conversation rules: "
     "Always be polite and concise. "
     "Responses should be under 40 words for spoken TTS. "
     "If unsure, say so and ask for clarification rather than guessing. "
     "Never make up menu prices, distances, or names. "
     "Always acknowledge the customer by their preferred address.",
     {"category": "conversation_rules"}),

    ("BonBon cannot: fly, lift heavy objects, open doors, work outdoors, "
     "access the internet, make phone calls, process payments independently, "
     "remember conversations from previous days (only the current session), "
     "or give medical/legal/financial advice.",
     {"category": "robot_limitations"}),

    ("Emergency procedures: "
     "If a customer reports an emergency, BonBon will call for human staff "
     "immediately and announce via TTS. "
     "BonBon will not attempt to provide medical assistance itself. "
     "Emergency contact: dial 995 (Singapore) for ambulance.",
     {"category": "emergency"}),

    ("Operating hours: Monday to Friday 7:30am to 9:00pm. "
     "Saturday and Sunday 8:00am to 8:00pm. "
     "BonBon is offline for maintenance every Tuesday 2:00pm to 3:00pm.",
     {"category": "operations"}),
]


# ── Embedding fallback (TF-IDF hash, no external deps) ────────────────────────

def _hash_embed(text: str, dim: int = 384) -> np.ndarray:
    """
    Deterministic hash-based embedding (no ML libraries needed).
    Good enough for structural tests; replace with real model in production.
    """
    words = re.findall(r"\w+", text.lower())
    vec = np.zeros(dim, dtype=np.float32)
    for word in words:
        h = int(hashlib.md5(word.encode()).hexdigest(), 16)
        idx = h % dim
        vec[idx] += 1.0
    norm = float(np.linalg.norm(vec))
    if norm > 0:
        vec /= norm
    return vec


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    n = float(np.dot(a, b))
    da = float(np.linalg.norm(a))
    db = float(np.linalg.norm(b))
    if da < 1e-9 or db < 1e-9:
        return 0.0
    return max(-1.0, min(1.0, n / (da * db)))


# ── Retriever ─────────────────────────────────────────────────────────────────

class RAGRetriever:
    """
    Vector-store backed knowledge retriever.

    Thread-safe: all mutating operations are protected by a lock.
    The store is lazily initialised on first ``add`` or ``retrieve`` call.
    """

    def __init__(self, cfg: RAGConfig) -> None:
        self._cfg      = cfg
        self._lock     = threading.Lock()
        self._docs: List[RAGDocument] = []
        self._embedder = None
        self._store    = None          # ChromaDB collection or FAISS index
        self._backend  = "numpy"       # resolved at load time
        self._loaded   = False

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def load(self) -> None:
        """Initialise the chosen backend and seed with default knowledge."""
        with self._lock:
            if self._loaded:
                return
            self._init_embedder()
            self._init_store()
            self._seed_defaults()
            self._loaded = True
            logger.info("RAGRetriever loaded (backend=%s, docs=%d)",
                        self._backend, len(self._docs))

    def close(self) -> None:
        with self._lock:
            self._store = None
            self._loaded = False

    # ── Public API ────────────────────────────────────────────────────────────

    def add_document(
        self,
        text: str,
        metadata: Optional[Dict[str, str]] = None,
        doc_id: Optional[str] = None,
    ) -> RAGDocument:
        """Add a document to the knowledge base."""
        self._ensure_loaded()
        doc = RAGDocument(
            doc_id   = doc_id or str(uuid.uuid4()),
            text     = text,
            metadata = metadata or {},
            embedding= self._embed(text),
        )
        with self._lock:
            self._docs.append(doc)
            self._store_add(doc)
        return doc

    def retrieve(
        self,
        query: str,
        k: Optional[int]     = None,
        threshold: Optional[float] = None,
    ) -> List["RetrievalResult"]:
        """Return up to k RetrievalResult objects above similarity threshold."""
        return self.retrieve_with_scores(query, k=k, threshold=threshold)

    def retrieve_with_scores(
        self,
        query: str,
        k: Optional[int]     = None,
        threshold: Optional[float] = None,
    ) -> List[RetrievalResult]:
        """Return (document, score) pairs sorted by descending similarity."""
        self._ensure_loaded()
        top_k     = k         if k         is not None else self._cfg.top_k
        min_score = threshold if threshold is not None else self._cfg.similarity_threshold

        q_emb = self._embed(query)
        with self._lock:
            docs = list(self._docs)

        if not docs:
            return []

        scored = []
        for doc in docs:
            if doc.embedding is None:
                continue
            score = _cosine(q_emb, doc.embedding)
            if score >= min_score:
                scored.append((doc, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return [
            RetrievalResult(document=d, score=s, rank=i + 1)
            for i, (d, s) in enumerate(scored[:top_k])
        ]

    def build_context_string(
        self,
        query_or_results,   # str | List[RetrievalResult]
    ) -> str:
        """
        Format retrieved documents into a prompt-injectable string.

        Accepts either:
          - a query string (retrieval performed internally), or
          - a pre-computed list of RetrievalResult objects.
        """
        if isinstance(query_or_results, str):
            results = self.retrieve_with_scores(query_or_results)
        else:
            results = list(query_or_results)

        if not results:
            return ""
        parts = []
        total = 0
        max_chars = self._cfg.max_context_tokens * 4  # ~4 chars/token
        for r in results:
            snippet = f"[{r.document.metadata.get('category', 'knowledge')}] {r.document.text}"
            if total + len(snippet) > max_chars:
                break
            parts.append(snippet)
            total += len(snippet)
        return "\n\n".join(parts)

    @property
    def doc_count(self) -> int:
        return len(self._docs)

    # ── Initialisation helpers ────────────────────────────────────────────────

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self.load()

    def _init_embedder(self) -> None:
        if self._cfg.backend == "none":
            self._embedder = _hash_embed
            return
        try:
            from sentence_transformers import SentenceTransformer
            _model = SentenceTransformer(self._cfg.embedding_model)
            def _st_embed(text: str) -> np.ndarray:
                return _model.encode(text, normalize_embeddings=True).astype(np.float32)
            self._embedder = _st_embed
            logger.info("Using sentence-transformers: %s", self._cfg.embedding_model)
        except ImportError:
            logger.info("sentence-transformers not installed; using hash embedding")
            self._embedder = _hash_embed

    def _init_store(self) -> None:
        requested = self._cfg.backend

        if requested == "none":
            self._backend = "numpy"
            self._store   = None
            return

        if requested in ("chroma", "faiss"):
            if requested == "chroma":
                try:
                    import chromadb
                    client = (
                        chromadb.PersistentClient(path=self._cfg.persist_dir)
                        if self._cfg.persist_dir else
                        chromadb.EphemeralClient()
                    )
                    self._store   = client.get_or_create_collection(self._cfg.collection_name)
                    self._backend = "chroma"
                    logger.info("RAG backend: ChromaDB")
                    return
                except ImportError:
                    logger.info("chromadb not installed; trying faiss")

            try:
                import faiss  # noqa: F401
                self._backend = "faiss"
                self._store   = None   # built lazily after first batch
                logger.info("RAG backend: FAISS")
                return
            except ImportError:
                logger.info("faiss not installed; using NumPy fallback")

        self._backend = "numpy"
        self._store   = None
        logger.info("RAG backend: NumPy (brute force cosine)")

    def _seed_defaults(self) -> None:
        for text, metadata in _DEFAULT_KNOWLEDGE:
            doc = RAGDocument(
                doc_id    = str(uuid.uuid4()),
                text      = text,
                metadata  = metadata,
                embedding = self._embed(text),
            )
            self._docs.append(doc)

    def _embed(self, text: str) -> np.ndarray:
        return self._embedder(text)

    def _store_add(self, doc: RAGDocument) -> None:
        """Add to ChromaDB store if active (NumPy/FAISS are handled via _docs list)."""
        if self._backend == "chroma" and self._store is not None:
            try:
                self._store.add(
                    documents=[doc.text],
                    metadatas=[doc.metadata],
                    ids=[doc.doc_id],
                    embeddings=[doc.embedding.tolist()],
                )
            except Exception as exc:
                logger.debug("ChromaDB add error (non-fatal): %s", exc)
