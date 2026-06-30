"""ModelRuntimeHealthMonitor — decides when a runtime should be considered
DEGRADED based on consecutive failures, mirroring the same
escalate-immediately / recover-on-clean-run discipline used elsewhere in
BonBon (bonbon_vision's BaseDetector, the LoadSheddingController)."""

from __future__ import annotations

from bonbon_ai_runtime.interface import RuntimeStatus


class ModelRuntimeHealthMonitor:
    def __init__(self, degrade_after_consecutive: int = 3) -> None:
        self._threshold = max(1, degrade_after_consecutive)
        self._consecutive_failures = 0
        self._load_attempted = False
        self._load_succeeded = False

    def mark_model_loaded(self, ok: bool) -> None:
        self._load_attempted = True
        self._load_succeeded = ok
        if ok:
            self._consecutive_failures = 0

    def record_inference(self, ok: bool) -> None:
        if ok:
            self._consecutive_failures = 0
        else:
            self._consecutive_failures += 1

    @property
    def consecutive_failures(self) -> int:
        return self._consecutive_failures

    @property
    def model_loaded(self) -> bool:
        return self._load_succeeded

    def status(self, available: bool) -> RuntimeStatus:
        if not available:
            return RuntimeStatus.UNAVAILABLE
        if not self._load_attempted:
            return RuntimeStatus.UNINITIALISED
        if not self._load_succeeded:
            return RuntimeStatus.FAILED
        if self._consecutive_failures >= self._threshold:
            return RuntimeStatus.DEGRADED
        return RuntimeStatus.READY
