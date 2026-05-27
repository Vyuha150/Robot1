"""
bonbon_vision.models.model_manager
=====================================
Thread-safe model lifecycle manager.

Responsibilities
----------------
1. Load a model from a path (not hardcoded) in a background thread so the
   ROS2 node remains responsive during configure().
2. Track model state: UNLOADED → LOADING → READY | FAILED.
3. Surface load time and warmup duration for health reporting.
4. Support graceful degraded startup: if the model fails to load and
   allow_degraded=True the manager returns FAILED without crashing.

Usage
-----
    mgr = ModelManager(detector, allow_degraded=True)
    mgr.load_async()             # returns immediately
    mgr.wait_ready(timeout=30.0) # block until READY or FAILED
    if mgr.state == ModelState.READY:
        ...
"""

from __future__ import annotations

import logging
import threading
import time
from enum import IntEnum

logger = logging.getLogger(__name__)


class ModelState(IntEnum):
    UNLOADED = 0
    LOADING = 1
    READY = 2
    FAILED = 3


class ModelManager:
    """
    Wraps a detector's load_model() in a background thread and exposes
    a structured view of the loading lifecycle.

    Parameters
    ----------
    detector         object     must have a `load_model()` method
    allow_degraded   bool       if True, FAILED state is acceptable (no crash)
    """

    def __init__(self, detector, allow_degraded: bool = True) -> None:
        self._detector = detector
        self._allow_degraded = allow_degraded
        self._state = ModelState.UNLOADED
        self._lock = threading.Lock()
        self._ready_event = threading.Event()
        self._load_start_t: float | None = None
        self._load_end_t: float | None = None
        self._error: str | None = None

    # ── Public API ────────────────────────────────────────────────────────────

    @property
    def state(self) -> ModelState:
        with self._lock:
            return self._state

    @property
    def is_ready(self) -> bool:
        return self.state == ModelState.READY

    @property
    def load_ms(self) -> float:
        """Wall-clock loading + warmup time in milliseconds.  0 if not done."""
        with self._lock:
            if self._load_start_t is None or self._load_end_t is None:
                return 0.0
            return (self._load_end_t - self._load_start_t) * 1000.0

    @property
    def error(self) -> str | None:
        with self._lock:
            return self._error

    def load_async(self) -> None:
        """Start loading in a background thread.  Non-blocking."""
        with self._lock:
            if self._state not in (ModelState.UNLOADED, ModelState.FAILED):
                logger.debug(
                    "stage=model_manager event=load_skipped state=%s",
                    self._state.name,
                )
                return
            self._state = ModelState.LOADING
            self._ready_event.clear()

        thread = threading.Thread(target=self._load_worker, daemon=True, name="model_loader")
        thread.start()
        logger.info("stage=model_manager event=load_started async=True")

    def load_sync(self) -> bool:
        """
        Load synchronously (blocks until READY or FAILED).
        Returns True on success.
        """
        self.load_async()
        return self.wait_ready(timeout=120.0)

    def wait_ready(self, timeout: float = 30.0) -> bool:
        """
        Block until model is READY or FAILED (or timeout expires).
        Returns True if READY.
        """
        signalled = self._ready_event.wait(timeout=timeout)
        if not signalled:
            logger.warning(
                "stage=model_manager event=wait_timeout timeout_sec=%.1f",
                timeout,
            )
        return self.state == ModelState.READY

    def reload(self) -> None:
        """Reset to UNLOADED and trigger a fresh async load."""
        with self._lock:
            self._state = ModelState.UNLOADED
            self._error = None
        self.load_async()

    def summary(self) -> dict:
        with self._lock:
            return {
                "state": self._state.name,
                "load_ms": self.load_ms,
                "error": self._error,
                "allow_degraded": self._allow_degraded,
            }

    # ── Worker ────────────────────────────────────────────────────────────────

    def _load_worker(self) -> None:
        with self._lock:
            self._load_start_t = time.monotonic()

        try:
            self._detector.load_model()
            is_degraded = getattr(self._detector, "is_degraded", False)
            if is_degraded:
                raise RuntimeError("Detector entered degraded state during load_model()")

            with self._lock:
                self._state = ModelState.READY
                self._load_end_t = time.monotonic()

            logger.info(
                "stage=model_manager event=load_ready load_ms=%.0f",
                self.load_ms,
            )

        except Exception as exc:
            with self._lock:
                self._state = ModelState.FAILED
                self._load_end_t = time.monotonic()
                self._error = str(exc)

            if self._allow_degraded:
                logger.warning(
                    "stage=model_manager event=load_failed error=%r "
                    "degraded_mode=True load_ms=%.0f",
                    str(exc),
                    self.load_ms,
                )
            else:
                logger.error(
                    "stage=model_manager event=load_failed error=%r " "degraded_mode=False",
                    str(exc),
                )
                raise

        finally:
            self._ready_event.set()
