"""CPUONNXRuntime — ONNX Runtime on the CPU. The universal fallback on a
Raspberry Pi (no CUDA, no Hailo needed). onnxruntime is lazy-imported so the
package installs and tests run without it.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout

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


class CPUONNXRuntime(VisionModelRuntimeInterface):
    kind = RuntimeKind.CPU

    def __init__(self) -> None:
        self._session = None
        self._input_name: str | None = None
        self._metrics = InferenceMetricsCollector()
        self._health = ModelRuntimeHealthMonitor()
        # Single worker → real per-call timeout without cancelling in-flight
        # native inference (same trade-off as bonbon_vision's BaseDetector).
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="onnx_infer")

    @property
    def name(self) -> str:
        return "cpu_onnx"

    def is_available(self) -> AvailabilityResult:
        import importlib.util

        if importlib.util.find_spec("onnxruntime") is None:
            return AvailabilityResult(False, "onnxruntime not installed (pip install onnxruntime)")
        return AvailabilityResult(True, "onnxruntime available")

    def load_model(self, model_path: str) -> bool:
        compat = ModelCompatibilityChecker.check(RuntimeKind.CPU, model_path)
        if not compat.compatible:
            self._health.mark_model_loaded(False)
            return False
        try:
            import onnxruntime as ort  # lazy

            self._session = ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])
            self._input_name = self._session.get_inputs()[0].name
            self._health.mark_model_loaded(True)
            return True
        except Exception:  # noqa: BLE001 — load failures are reported, not raised
            self._session = None
            self._health.mark_model_loaded(False)
            return False

    def infer(self, input_tensor, timeout_ms: float = 300.0) -> InferenceOutput:
        if self._session is None:
            out = InferenceOutput(error="model not loaded")
            self._metrics.record(0.0, error=True)
            self._health.record_inference(False)
            return out

        def _run():
            return self._session.run(None, {self._input_name: input_tensor})

        t0 = time.perf_counter()
        future = self._executor.submit(_run)
        try:
            outputs = future.result(timeout=timeout_ms / 1000.0)
            latency = (time.perf_counter() - t0) * 1000.0
            self._metrics.record(latency)
            self._health.record_inference(True)
            return InferenceOutput(outputs=list(outputs), latency_ms=latency)
        except FutureTimeout:
            latency = (time.perf_counter() - t0) * 1000.0
            self._metrics.record(latency, timed_out=True)
            self._health.record_inference(False)
            return InferenceOutput(latency_ms=latency, timed_out=True, error="inference timeout")
        except Exception as exc:  # noqa: BLE001
            self._metrics.record(0.0, error=True)
            self._health.record_inference(False)
            return InferenceOutput(error=str(exc))

    def health(self) -> RuntimeHealth:
        snap = self._metrics.snapshot()
        return RuntimeHealth(
            runtime=self.name,
            status=self._health.status(available=self.is_available().available),
            model_loaded=self._health.model_loaded,
            detail="onnxruntime CPU",
            total_inferences=snap.total,
            total_timeouts=snap.timeouts,
            total_errors=snap.errors,
            last_latency_ms=snap.last_latency_ms,
        )

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False)
        self._session = None
