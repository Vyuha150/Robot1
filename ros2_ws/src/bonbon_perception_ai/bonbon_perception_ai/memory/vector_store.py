"""
bonbon_perception_ai.memory.vector_store
=========================================
FAISS-backed episodic memory for scene snapshots.

Falls back to a NumPy cosine-similarity implementation when the faiss-cpu
package is not installed, so tests and CI work without any special deps.

Privacy
-------
Embeddings are computed from SceneSnapshot fields only (counts, distances,
activity labels) — no face data, no raw audio, no PII is embedded.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

import numpy as np

from bonbon_perception_ai.config.perception_config import MemoryConfig
from bonbon_perception_ai.understanding.scene_analyzer import SceneSnapshot

# ── Embedding ─────────────────────────────────────────────────────────────────


class SceneEmbedding:
    """
    Encodes a SceneSnapshot as a fixed-length float32 vector.

    Vector layout (32 dimensions):
    ┌──────┬────────────────────────────────────────────────┐
    │ [0]  │ person count / 5  (clamped to [0,1])           │
    │ [1]  │ object count / 10 (clamped to [0,1])           │
    │ [2]  │ human proximity (1 − d/5, 0 if none)           │
    │ [3]  │ is_crowded                                      │
    │ 4-8  │ one-hot: activity (idle/interacting/nav/srv/cwd)│
    │ 9-12 │ one-hot: spatial (open/crowded/near/station)    │
    │ [13] │ uncertainty (0=LOW, 0.5=MED, 1=HIGH)           │
    │ [14] │ confidence                                      │
    │ [15] │ stale_count / 5                                 │
    │16-31 │ object-class presence bits (hashed into 16 bins)│
    └──────┴────────────────────────────────────────────────┘
    """

    DIM = 32

    _ACTIVITY_IDX = {
        "idle": 0,
        "interacting": 1,
        "navigating": 2,
        "serving": 3,
        "crowded": 4,
    }
    _SPATIAL_IDX = {
        "open_space": 0,
        "crowded": 1,
        "near_person": 2,
        "at_station": 3,
    }
    _UNCERTAINTY = {"LOW": 0.0, "MEDIUM": 0.5, "HIGH": 1.0}

    @classmethod
    def encode(cls, snap: SceneSnapshot) -> np.ndarray:
        v = np.zeros(cls.DIM, dtype=np.float32)

        # Dense features
        v[0] = min(len(snap.present_person_ids) / 5.0, 1.0)
        v[1] = min(len(snap.present_object_classes) / 10.0, 1.0)
        prox = snap.human_proximity_m
        v[2] = max(0.0, 1.0 - prox / 5.0) if prox != float("inf") else 0.0
        v[3] = 1.0 if snap.is_crowded else 0.0

        # Activity one-hot
        a_idx = cls._ACTIVITY_IDX.get(snap.dominant_activity, 0)
        v[4 + a_idx] = 1.0

        # Spatial one-hot
        s_idx = cls._SPATIAL_IDX.get(snap.spatial_context, 0)
        v[9 + s_idx] = 1.0

        # Scalars
        v[13] = cls._UNCERTAINTY.get(snap.uncertainty_level, 0.5)
        v[14] = float(snap.confidence)
        v[15] = min(len(snap.stale_modalities) / 5.0, 1.0)

        # Object class hash bins (16 bins, index 16-31)
        for cls_name in snap.present_object_classes:
            bin_idx = hash(cls_name) % 16
            v[16 + bin_idx] = 1.0

        return v

    @classmethod
    def normalise(cls, v: np.ndarray) -> np.ndarray:
        n = float(np.linalg.norm(v))
        if n < 1e-8:
            return v.copy()
        return v / n


# ── Episode record ────────────────────────────────────────────────────────────


@dataclass
class EpisodeRecord:
    episode_id: str
    timestamp: float
    snapshot: SceneSnapshot
    embedding: np.ndarray = field(repr=False)

    @property
    def age_sec(self) -> float:
        return time.monotonic() - self.timestamp


# ── Vector store ──────────────────────────────────────────────────────────────


class FAISSVectorStore:
    """
    Stores scene embeddings and supports k-nearest-neighbour retrieval.

    Backend selection (automatic):
    * faiss-cpu present → IndexFlatIP (inner product on normalised vectors = cosine)
    * otherwise         → pure NumPy cosine similarity (O(N) scan)
    """

    def __init__(self, cfg: MemoryConfig) -> None:
        self.cfg = cfg
        self._episodes: list[EpisodeRecord] = []
        self._index = None  # faiss.Index or None
        self._use_faiss = False
        self._lock = threading.Lock()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def load(self) -> None:
        try:
            import faiss  # type: ignore

            self._index = faiss.IndexFlatIP(SceneEmbedding.DIM)
            self._use_faiss = True
        except ImportError:
            self._use_faiss = False  # NumPy fallback

    def clear(self) -> None:
        with self._lock:
            self._episodes.clear()
            if self._use_faiss and self._index is not None:
                import faiss  # type: ignore

                self._index = faiss.IndexFlatIP(SceneEmbedding.DIM)

    # ── Write ─────────────────────────────────────────────────────────────────

    def add(self, snap: SceneSnapshot) -> EpisodeRecord:
        raw = SceneEmbedding.encode(snap)
        norm = SceneEmbedding.normalise(raw)
        rec = EpisodeRecord(
            episode_id=snap.scene_id,
            timestamp=snap.timestamp,
            snapshot=snap,
            embedding=norm,
        )
        with self._lock:
            self._episodes.append(rec)
            if self._use_faiss:
                self._index.add(norm.reshape(1, -1))  # type: ignore[union-attr]
            if len(self._episodes) > self.cfg.max_episodes:
                self._evict_oldest()
        return rec

    def _evict_oldest(self) -> None:
        """Remove the 10 % oldest episodes."""
        n_evict = max(1, self.cfg.max_episodes // 10)
        self._episodes = self._episodes[n_evict:]
        if self._use_faiss:
            # Rebuild index from remaining embeddings (FAISS flat has no delete)
            import faiss  # type: ignore

            self._index = faiss.IndexFlatIP(SceneEmbedding.DIM)
            if self._episodes:
                mat = np.vstack([r.embedding for r in self._episodes])
                self._index.add(mat)

    # ── Query ─────────────────────────────────────────────────────────────────

    def search(self, query_snap: SceneSnapshot, k: int = 5) -> list[EpisodeRecord]:
        """Return up to k most-similar past episodes."""
        raw = SceneEmbedding.encode(query_snap)
        norm = SceneEmbedding.normalise(raw)

        with self._lock:
            if not self._episodes:
                return []
            k_actual = min(k, len(self._episodes))
            if self._use_faiss:
                _D, indices = self._index.search(norm.reshape(1, -1), k_actual)  # type: ignore
                return [self._episodes[i] for i in indices[0] if 0 <= i < len(self._episodes)]
            else:
                # NumPy cosine similarity
                mat = np.vstack([r.embedding for r in self._episodes])
                scores = mat @ norm  # dot product of normalised = cosine
                top_idx = np.argsort(scores)[::-1][:k_actual]
                return [self._episodes[int(i)] for i in top_idx]

    # ── Stats ─────────────────────────────────────────────────────────────────

    @property
    def episode_count(self) -> int:
        with self._lock:
            return len(self._episodes)

    @property
    def backend(self) -> str:
        return "faiss" if self._use_faiss else "numpy"
