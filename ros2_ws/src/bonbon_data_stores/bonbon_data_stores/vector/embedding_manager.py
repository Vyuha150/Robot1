"""EmbeddingManager — sentence-transformers primary; hash-based fallback.

When ``sentence-transformers`` is not installed the manager silently falls
back to a deterministic hash embedding so the rest of the system can
operate in degraded mode without crashing.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from functools import lru_cache

import numpy as np

logger = logging.getLogger(__name__)

# Attempt to import sentence-transformers
try:
    from sentence_transformers import SentenceTransformer  # type: ignore

    _HAS_ST = True
except ImportError:
    _HAS_ST = False
    SentenceTransformer = None  # type: ignore


# ---------------------------------------------------------------------------
# Hash-based fallback embedding
# ---------------------------------------------------------------------------


def _hash_embed(text: str, dim: int = 384) -> np.ndarray:
    """Produce a deterministic pseudo-embedding from an MD5 hash.

    This is NOT semantically meaningful.  It exists only so that the
    vector-search pipeline can function without sentence-transformers installed.
    The resulting "similarity" scores are meaningless but the API shape is
    identical.
    """
    seed = int(hashlib.md5(text.encode()).hexdigest(), 16) % (2**32)
    rng = np.random.default_rng(seed)
    vec = rng.standard_normal(dim).astype(np.float32)
    norm = np.linalg.norm(vec)
    if norm > 0:
        vec /= norm
    return vec


# ---------------------------------------------------------------------------
# EmbeddingManager
# ---------------------------------------------------------------------------


class EmbeddingManager:
    """Produce fixed-dimension embeddings for text strings.

    Parameters
    ----------
    model_name:
        HuggingFace model identifier.  Not hardcoded — injected via config.
    dim:
        Expected embedding dimension.  Must match the FAISS index dimension.
    device:
        ``'cpu'`` or ``'cuda'``.
    batch_size:
        Number of texts to encode in one forward pass.
    cache_size:
        LRU cache size for single-string embeddings (0 = disabled).
    use_hash_fallback:
        When True (default), fall back to hash embeddings if the model
        cannot be loaded.
    """

    def __init__(
        self,
        model_name: str = "all-MiniLM-L6-v2",
        dim: int = 384,
        device: str = "cpu",
        batch_size: int = 32,
        cache_size: int = 1000,
        use_hash_fallback: bool = True,
    ) -> None:
        self._model_name = model_name
        self._dim = dim
        self._device = device
        self._batch_size = batch_size
        self._use_hash_fallback = use_hash_fallback
        self._model: SentenceTransformer | None = None
        self._lock = threading.Lock()
        self._is_fallback = False

        # Build the cached single-embed function (size=0 means no cache)
        if cache_size > 0:
            self._cached_embed = lru_cache(maxsize=cache_size)(self._embed_one)
        else:
            self._cached_embed = self._embed_one

        self._load_model()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def dim(self) -> int:
        return self._dim

    @property
    def is_fallback(self) -> bool:
        """True when using hash embeddings instead of the real model."""
        return self._is_fallback

    @property
    def model_name(self) -> str:
        return self._model_name

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def embed(self, text: str) -> np.ndarray:
        """Return a (dim,) float32 L2-normalised embedding for *text*."""
        return np.array(self._cached_embed(text), dtype=np.float32)

    def embed_batch(self, texts: list[str]) -> np.ndarray:
        """Return an (N, dim) float32 matrix for a list of strings.

        Uses the model's batched encode path when available.
        """
        if not texts:
            return np.empty((0, self._dim), dtype=np.float32)

        if self._is_fallback or self._model is None:
            return np.array([_hash_embed(t, self._dim) for t in texts], dtype=np.float32)

        with self._lock:
            vecs = self._model.encode(
                texts,
                batch_size=self._batch_size,
                normalize_embeddings=True,
                convert_to_numpy=True,
                device=self._device,
                show_progress_bar=False,
            )
        return vecs.astype(np.float32)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_model(self) -> None:
        if not _HAS_ST:
            if self._use_hash_fallback:
                logger.warning(
                    "sentence-transformers not installed; using hash-based fallback embeddings. "
                    "Vector search results will NOT be semantically meaningful."
                )
                self._is_fallback = True
                return
            raise ImportError(
                "sentence-transformers is required but not installed. "
                "Run: pip install sentence-transformers"
            )

        try:
            logger.info("Loading embedding model: %s", self._model_name)
            self._model = SentenceTransformer(self._model_name, device=self._device)
            actual_dim = self._model.get_sentence_embedding_dimension()
            if actual_dim != self._dim:
                logger.warning(
                    "Model %r has dim=%d but configured dim=%d; " "updating dim to match model.",
                    self._model_name,
                    actual_dim,
                    self._dim,
                )
                self._dim = actual_dim
            self._is_fallback = False
            logger.info("Embedding model loaded (dim=%d)", self._dim)
        except Exception as exc:
            if self._use_hash_fallback:
                logger.error(
                    "Failed to load embedding model %r: %s. " "Falling back to hash embeddings.",
                    self._model_name,
                    exc,
                )
                self._is_fallback = True
            else:
                raise

    def _embed_one(self, text: str) -> tuple:
        """Return embedding as a plain tuple (hashable, so lru_cache works)."""
        if self._is_fallback or self._model is None:
            return tuple(_hash_embed(text, self._dim).tolist())

        with self._lock:
            vec = self._model.encode(
                text,
                normalize_embeddings=True,
                convert_to_numpy=True,
                device=self._device,
                show_progress_bar=False,
            )
        return tuple(vec.astype(np.float32).tolist())
