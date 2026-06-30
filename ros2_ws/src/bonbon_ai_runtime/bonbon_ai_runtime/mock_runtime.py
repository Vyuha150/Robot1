"""MockRuntime — a fully-functional, dependency-free, deterministic runtime.

Always available, never needs hardware or a model file. It is both the
test/dev default and the final fallback in the selection chain, so the
vision stack always has *something* that runs (degraded, but alive) even
with no accelerator and no model.
"""

from __future__ import annotations

import time

from bonbon_ai_runtime.health_monitor import ModelRuntimeHealthMonitor
from bonbon_ai_runtime.interface import (
    AvailabilityResult,
    InferenceOutput,
    RuntimeHealth,
    RuntimeKind,
    VisionModelRuntimeInterface,
)
from bonbon_ai_runtime.metrics_collector import InferenceMetricsCollector


class MockRuntime(VisionModelRuntimeInterface):
    kind = RuntimeKind.MOCK

    def __init__(self, fixed_latency_ms: float = 2.0) -> None:
        self._latency = fixed_latency_ms
        self._metrics = InferenceMetricsCollector()
        self._health = ModelRuntimeHealthMonitor()

    @property
    def name(self) -> str:
        return "mock"

    def is_available(self) -> AvailabilityResult:
        return AvailabilityResult(True, "mock runtime is always available")

    def load_model(self, model_path: str) -> bool:
        self._health.mark_model_loaded(True)
        return True

    def infer(self, input_tensor, timeout_ms: float = 300.0) -> InferenceOutput:
        import numpy as np

        t0 = time.perf_counter()
        # Deterministic, cheap "inference": a single empty detection tensor.
        time.sleep(self._latency / 1000.0)
        latency = (time.perf_counter() - t0) * 1000.0
        out = InferenceOutput(outputs=[np.zeros((0, 6), dtype=np.float32)], latency_ms=latency)
        self._metrics.record(latency)
        self._health.record_inference(True)
        return out

    def health(self) -> RuntimeHealth:
        snap = self._metrics.snapshot()
        return RuntimeHealth(
            runtime=self.name,
            status=self._health.status(available=True),
            model_loaded=self._health.model_loaded,
            detail="mock",
            total_inferences=snap.total,
            total_timeouts=snap.timeouts,
            total_errors=snap.errors,
            last_latency_ms=snap.last_latency_ms,
        )
