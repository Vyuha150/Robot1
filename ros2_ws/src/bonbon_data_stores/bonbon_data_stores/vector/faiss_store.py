"""FAISSVectorStore — four semantic indexes with graceful degraded mode.

Indexes
-------
interactions   — user interaction embeddings
knowledge      — robot knowledge-base fragments
navigation     — place / route descriptions
ai_context     — LLM context window fragments

When ``faiss-cpu`` is not installed the store runs in degraded mode:
``search()`` always returns an empty list and ``add()`` is a no-op.
A warning is emitted once on startup.
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from bonbon_data_stores.schema.models import VectorSearchResult

logger = logging.getLogger(__name__)

# Optional FAISS import
try:
    import faiss  # type: ignore

    _HAS_FAISS = True
except ImportError:
    faiss = None  # type: ignore
    _HAS_FAISS = False

# Known index names
INDEX_NAMES = ("interactions", "knowledge", "navigation", "ai_context")


# ---------------------------------------------------------------------------
# Internal index state
# ---------------------------------------------------------------------------


@dataclass
class _IndexState:
    name: str
    dim: int
    index: Any = None  # faiss.Index | None
    id_map: dict[int, str] = field(default_factory=dict)  # int faiss id → str vector_id
    payload_map: dict[str, dict] = field(default_factory=dict)  # vector_id → payload
    _next_id: int = 0

    def next_int_id(self) -> int:
        self._next_id += 1
        return self._next_id

    @property
    def count(self) -> int:
        return self.index.ntotal if self.index is not None else 0


# ---------------------------------------------------------------------------
# FAISSVectorStore
# ---------------------------------------------------------------------------


class FAISSVectorStore:
    """Manage four FAISS indexes for BonBon.

    Parameters
    ----------
    index_dir:
        Directory where ``.index`` and ``.json`` sidecar files are stored.
    dim:
        Embedding dimension.  Must match the ``EmbeddingManager`` dimension.
    auto_save:
        Persist indexes after every ``add`` / ``delete`` call.
    enabled:
        Hard-disable the store (returns empty results without touching FAISS).
    """

    def __init__(
        self,
        index_dir: Path,
        dim: int = 384,
        auto_save: bool = True,
        enabled: bool = True,
    ) -> None:
        self._dir = Path(index_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._dim = dim
        self._auto_save = auto_save
        self._enabled = enabled and _HAS_FAISS
        self._lock = threading.RLock()
        self._indexes: dict[str, _IndexState] = {}

        if not _HAS_FAISS:
            logger.warning(
                "faiss-cpu not installed; FAISSVectorStore running in degraded mode. "
                "Run: pip install faiss-cpu"
            )
        elif not enabled:
            logger.info("FAISSVectorStore disabled by configuration.")
        else:
            self._init_indexes()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_degraded(self) -> bool:
        return not self._enabled

    @property
    def dim(self) -> int:
        return self._dim

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add(
        self,
        index_name: str,
        vector: np.ndarray,
        payload: dict[str, Any] | None = None,
        vector_id: str | None = None,
    ) -> str:
        """Add a vector to *index_name*.

        Returns the ``vector_id`` string assigned to this entry.
        """
        self._validate_index_name(index_name)
        if not self._enabled:
            return vector_id or str(uuid.uuid4())

        self._validate_index_name(index_name)
        vid = vector_id or str(uuid.uuid4())
        vec32 = np.array(vector, dtype=np.float32).reshape(1, -1)

        with self._lock:
            state = self._indexes[index_name]
            int_id = state.next_int_id()
            # FAISS IndexIDMap requires explicit int IDs
            state.index.add_with_ids(vec32, np.array([int_id], dtype=np.int64))
            state.id_map[int_id] = vid
            state.payload_map[vid] = payload or {}

        if self._auto_save:
            self._save_index(index_name)

        return vid

    def search(
        self,
        index_name: str,
        query_vector: np.ndarray,
        top_k: int = 5,
    ) -> list[VectorSearchResult]:
        """Return the *top_k* nearest neighbours from *index_name*."""
        self._validate_index_name(index_name)
        if not self._enabled:
            return []
        q = np.array(query_vector, dtype=np.float32).reshape(1, -1)

        with self._lock:
            state = self._indexes[index_name]
            if state.count == 0:
                return []
            k = min(top_k, state.count)
            distances, indices = state.index.search(q, k)

        results = []
        for dist, idx in zip(distances[0], indices[0]):
            if idx < 0:
                continue
            vid = state.id_map.get(int(idx))
            if vid is None:
                continue
            results.append(
                VectorSearchResult(
                    vector_id=vid,
                    score=float(dist),
                    payload=state.payload_map.get(vid, {}),
                    source_index=index_name,
                )
            )
        return results

    def delete(self, index_name: str, vector_id: str) -> bool:
        """Remove the vector with *vector_id* from *index_name*.

        FAISS does not support direct ID removal on all index types.
        We rebuild the index from the remaining vectors (O(n) but safe).
        """
        self._validate_index_name(index_name)
        if not self._enabled:
            return False

        with self._lock:
            state = self._indexes[index_name]
            # Find the int id for this vector_id
            int_id_to_remove = None
            for int_id, vid in state.id_map.items():
                if vid == vector_id:
                    int_id_to_remove = int_id
                    break

            if int_id_to_remove is None:
                return False

            # Collect all remaining vectors
            remaining_ids = [i for i, v in state.id_map.items() if v != vector_id]
            if remaining_ids:
                remaining_vecs = np.zeros((len(remaining_ids), self._dim), dtype=np.float32)
                state.index.reconstruct_batch(
                    np.array(remaining_ids, dtype=np.int64), remaining_vecs
                )
            else:
                remaining_vecs = np.empty((0, self._dim), dtype=np.float32)

            # Rebuild
            new_index = self._make_flat_index()
            if len(remaining_ids) > 0:
                new_index.add_with_ids(remaining_vecs, np.array(remaining_ids, dtype=np.int64))
            state.index = new_index
            del state.id_map[int_id_to_remove]
            state.payload_map.pop(vector_id, None)

        if self._auto_save:
            self._save_index(index_name)

        return True

    def count(self, index_name: str) -> int:
        if not self._enabled:
            return 0
        self._validate_index_name(index_name)
        with self._lock:
            return self._indexes[index_name].count

    def save_all(self) -> None:
        """Persist all indexes to disk."""
        if not self._enabled:
            return
        for name in INDEX_NAMES:
            self._save_index(name)

    def load_all(self) -> None:
        """Load indexes from disk (called during restore)."""
        if not self._enabled:
            return
        for name in INDEX_NAMES:
            self._load_index(name)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _init_indexes(self) -> None:
        for name in INDEX_NAMES:
            state = _IndexState(name=name, dim=self._dim)
            idx_path = self._dir / f"{name}.index"
            if idx_path.exists():
                try:
                    state.index = faiss.read_index(str(idx_path))
                    sidecar = self._dir / f"{name}.json"
                    if sidecar.exists():
                        data = json.loads(sidecar.read_text())
                        state.id_map = {int(k): v for k, v in data.get("id_map", {}).items()}
                        state.payload_map = data.get("payload_map", {})
                        state._next_id = data.get("next_id", 0)
                    logger.info("Loaded FAISS index %r (%d vectors)", name, state.count)
                except Exception as exc:
                    logger.error("Failed to load FAISS index %r: %s — creating fresh.", name, exc)
                    state.index = self._make_flat_index()
            else:
                state.index = self._make_flat_index()
            self._indexes[name] = state

    def _make_flat_index(self):
        """Create an IndexIDMap wrapping an IndexFlatIP (inner-product / cosine)."""
        inner = faiss.IndexFlatIP(self._dim)
        return faiss.IndexIDMap(inner)

    def _save_index(self, name: str) -> None:
        try:
            state = self._indexes[name]
            idx_path = self._dir / f"{name}.index"
            faiss.write_index(state.index, str(idx_path))
            sidecar = self._dir / f"{name}.json"
            sidecar.write_text(
                json.dumps(
                    {
                        "id_map": {str(k): v for k, v in state.id_map.items()},
                        "payload_map": state.payload_map,
                        "next_id": state._next_id,
                    }
                )
            )
        except Exception as exc:
            logger.error("Failed to save FAISS index %r: %s", name, exc)

    def _load_index(self, name: str) -> None:
        self._validate_index_name(name)
        idx_path = self._dir / f"{name}.index"
        if not idx_path.exists():
            return
        with self._lock:
            state = self._indexes[name]
            state.index = faiss.read_index(str(idx_path))
            sidecar = self._dir / f"{name}.json"
            if sidecar.exists():
                data = json.loads(sidecar.read_text())
                state.id_map = {int(k): v for k, v in data.get("id_map", {}).items()}
                state.payload_map = data.get("payload_map", {})
                state._next_id = data.get("next_id", 0)

    @staticmethod
    def _validate_index_name(name: str) -> None:
        if name not in INDEX_NAMES:
            raise ValueError(f"Unknown FAISS index {name!r}. Valid indexes: {INDEX_NAMES}")
