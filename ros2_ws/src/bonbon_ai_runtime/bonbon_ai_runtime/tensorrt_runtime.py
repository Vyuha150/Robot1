"""TensorRTRuntime — NVIDIA TensorRT (Jetson / CUDA GPUs). Preserved as an
optional backend so the original Jetson deployment path is not lost; it is
NOT used on a Raspberry Pi (no CUDA). tensorrt is lazy-imported, so this
reports unavailable rather than erroring on a machine without it.

This backend is intentionally thin and cannot be exercised without NVIDIA
hardware; its tested behaviour is the graceful "unavailable" path.
"""

from __future__ import annotations

import importlib.util

from bonbon_ai_runtime.health_monitor import ModelRuntimeHealthMonitor
from bonbon_ai_runtime.interface import (
    AvailabilityResult,
    InferenceOutput,
    RuntimeHealth,
    RuntimeKind,
    VisionModelRuntimeInterface,
)
from bonbon_ai_runtime.metrics_collector import InferenceMetricsCollector
from bonbon_ai_runtime.model_compatibility import ModelCompatibilityChecker


class TensorRTRuntime(VisionModelRuntimeInterface):
    kind = RuntimeKind.TENSORRT

    def __init__(self) -> None:
        self._engine = None
        self._metrics = InferenceMetricsCollector()
        self._health = ModelRuntimeHealthMonitor()

    @property
    def name(self) -> str:
        return "tensorrt"

    def is_available(self) -> AvailabilityResult:
        if importlib.util.find_spec("tensorrt") is None:
            return AvailabilityResult(False, "tensorrt not installed (NVIDIA only — not on a Pi)")
        return AvailabilityResult(True, "tensorrt available")

    def load_model(self, model_path: str) -> bool:
        compat = ModelCompatibilityChecker.check(RuntimeKind.TENSORRT, model_path)
        if not compat.compatible or not self.is_available().available:
            self._health.mark_model_loaded(False)
            return False
        try:
            import tensorrt as trt  # lazy

            logger = trt.Logger(trt.Logger.WARNING)
            with open(model_path, "rb") as f, trt.Runtime(logger) as rt:
                self._engine = rt.deserialize_cuda_engine(f.read())
            ok = self._engine is not None
            self._health.mark_model_loaded(ok)
            return ok
        except Exception:  # noqa: BLE001
            self._engine = None
            self._health.mark_model_loaded(False)
            return False

    def infer(self, input_tensor, timeout_ms: float = 300.0) -> InferenceOutput:
        # Full TensorRT execution context binding requires NVIDIA hardware and
        # is out of scope to exercise here. Report not-loaded so a selector
        # falls back rather than producing a bogus result.
        if self._engine is None:
            self._metrics.record(0.0, error=True)
            self._health.record_inference(False)
            return InferenceOutput(error="tensorrt engine not loaded")
        self._metrics.record(0.0, error=True)
        self._health.record_inference(False)
        return InferenceOutput(error="tensorrt execution not implemented on this build")

    def health(self) -> RuntimeHealth:
        snap = self._metrics.snapshot()
        return RuntimeHealth(
            runtime=self.name,
            status=self._health.status(available=self.is_available().available),
            model_loaded=self._health.model_loaded,
            detail="tensorrt (NVIDIA)",
            total_inferences=snap.total,
            total_timeouts=snap.timeouts,
            total_errors=snap.errors,
            last_latency_ms=snap.last_latency_ms,
        )
