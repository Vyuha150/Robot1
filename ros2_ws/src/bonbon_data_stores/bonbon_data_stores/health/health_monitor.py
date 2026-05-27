"""DataStoreHealthMonitor — aggregated health check for all data stores.

Health levels
-------------
HEALTHY   — all stores reachable; write latency < 100 ms
DEGRADED  — one or more optional stores unavailable (FAISS / ChromaDB)
UNHEALTHY — SQLite unavailable or write latency > 500 ms
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import StrEnum

logger = logging.getLogger(__name__)


class HealthLevel(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


@dataclass
class StoreHealth:
    name: str
    available: bool
    latency_ms: float = 0.0
    error: str | None = None
    record_count: int = 0


@dataclass
class DataStoreHealth:
    level: HealthLevel
    sqlite: StoreHealth = field(default_factory=lambda: StoreHealth("sqlite", False))
    faiss: StoreHealth = field(default_factory=lambda: StoreHealth("faiss", False))
    chroma: StoreHealth = field(default_factory=lambda: StoreHealth("chroma", False))
    checked_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "level": self.level.value,
            "checked_at": self.checked_at,
            "stores": {
                "sqlite": {
                    "available": self.sqlite.available,
                    "latency_ms": self.sqlite.latency_ms,
                    "error": self.sqlite.error,
                    "record_count": self.sqlite.record_count,
                },
                "faiss": {
                    "available": self.faiss.available,
                    "latency_ms": self.faiss.latency_ms,
                    "error": self.faiss.error,
                    "record_count": self.faiss.record_count,
                },
                "chroma": {
                    "available": self.chroma.available,
                    "latency_ms": self.chroma.latency_ms,
                    "error": self.chroma.error,
                    "record_count": self.chroma.record_count,
                },
            },
        }


class DataStoreHealthMonitor:
    """Perform liveness and latency checks against all data stores.

    Parameters
    ----------
    conn:
        SQLiteConnection used for the write-latency probe.
    faiss_store:
        FAISSVectorStore instance (may be None or degraded).
    chroma_store:
        ChromaRAGStore instance (may be None or degraded).
    write_latency_warn_ms:
        Log a warning when SQLite write latency exceeds this threshold.
    write_latency_fail_ms:
        Mark SQLite UNHEALTHY when write latency exceeds this threshold.
    """

    def __init__(
        self,
        conn,
        faiss_store=None,
        chroma_store=None,
        write_latency_warn_ms: float = 100.0,
        write_latency_fail_ms: float = 500.0,
    ) -> None:
        self._conn = conn
        self._faiss = faiss_store
        self._chroma = chroma_store
        self._warn_ms = write_latency_warn_ms
        self._fail_ms = write_latency_fail_ms
        self._last_health: DataStoreHealth | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check(self) -> DataStoreHealth:
        """Run a full health check and return a ``DataStoreHealth`` snapshot."""
        sqlite_health = self._check_sqlite()
        faiss_health = self._check_faiss()
        chroma_health = self._check_chroma()

        # Determine overall level
        if not sqlite_health.available or sqlite_health.latency_ms > self._fail_ms:
            level = HealthLevel.UNHEALTHY
        elif not faiss_health.available or not chroma_health.available:
            level = HealthLevel.DEGRADED
        else:
            level = HealthLevel.HEALTHY

        health = DataStoreHealth(
            level=level,
            sqlite=sqlite_health,
            faiss=faiss_health,
            chroma=chroma_health,
        )
        self._last_health = health

        if level == HealthLevel.UNHEALTHY:
            logger.error("DataStore health: UNHEALTHY — %s", health.to_dict())
        elif level == HealthLevel.DEGRADED:
            logger.warning("DataStore health: DEGRADED — %s", health.to_dict())
        else:
            logger.debug("DataStore health: HEALTHY")

        return health

    @property
    def last_health(self) -> DataStoreHealth | None:
        return self._last_health

    # ------------------------------------------------------------------
    # Internal probes
    # ------------------------------------------------------------------

    def _check_sqlite(self) -> StoreHealth:
        try:
            t0 = time.monotonic()
            db = self._conn.get()
            # Lightweight write: create a temp table, insert, drop
            db.execute("CREATE TABLE IF NOT EXISTS _health_probe (ts REAL);")
            db.execute("INSERT INTO _health_probe (ts) VALUES (?);", (time.time(),))
            db.execute("DELETE FROM _health_probe;")
            db.commit()
            latency_ms = (time.monotonic() - t0) * 1000

            if latency_ms > self._warn_ms:
                logger.warning(
                    "SQLite write latency %.1f ms exceeds %.1f ms threshold",
                    latency_ms,
                    self._warn_ms,
                )

            # Count a real table for the record_count field
            row = db.execute("SELECT COUNT(*) FROM interactions;").fetchone()
            count = int(row[0]) if row else 0

            return StoreHealth("sqlite", available=True, latency_ms=latency_ms, record_count=count)

        except Exception as exc:
            logger.error("SQLite health probe failed: %s", exc)
            return StoreHealth("sqlite", available=False, error=str(exc))

    def _check_faiss(self) -> StoreHealth:
        if self._faiss is None:
            return StoreHealth("faiss", available=False, error="not initialised")
        if self._faiss.is_degraded:
            return StoreHealth("faiss", available=False, error="faiss-cpu not installed")
        try:
            t0 = time.monotonic()
            count = self._faiss.count("interactions")
            latency_ms = (time.monotonic() - t0) * 1000
            return StoreHealth("faiss", available=True, latency_ms=latency_ms, record_count=count)
        except Exception as exc:
            return StoreHealth("faiss", available=False, error=str(exc))

    def _check_chroma(self) -> StoreHealth:
        if self._chroma is None:
            return StoreHealth("chroma", available=False, error="not initialised")
        if self._chroma.is_degraded:
            return StoreHealth("chroma", available=False, error="chromadb not installed")
        try:
            t0 = time.monotonic()
            count = self._chroma.count("knowledge")
            latency_ms = (time.monotonic() - t0) * 1000
            return StoreHealth("chroma", available=True, latency_ms=latency_ms, record_count=count)
        except Exception as exc:
            return StoreHealth("chroma", available=False, error=str(exc))
