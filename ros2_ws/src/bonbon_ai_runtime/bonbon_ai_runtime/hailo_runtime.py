"""HailoRuntime — vision inference on the Raspberry Pi AI HAT (Hailo-8 /
Hailo-8L) via HailoRT.

Supports the full required surface: (1) Hailo device detection, (2) HailoRT
availability check, (3) HEF model-path validation, (4) input-tensor
preprocessing hook, (5) output-tensor postprocessing hook, (6) inference
timeout, (7) model warmup, (8) benchmark, (9) health status, (10) graceful
fallback.

Hailo is OPTIONAL. `hailort` is lazy-imported and the device is probed via
an injectable HailoDeviceDetector, so on a machine with no HAT this runtime
simply reports `is_available() == False` and a RuntimeSelector falls back to
CPU — without this module ever importing hailort or touching hardware. That
is exactly what makes the package's tests pass with mocked detection.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout

from bonbon_ai_runtime.hailo_device_detector import HailoDeviceDetector
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


class HailoRuntime(VisionModelRuntimeInterface):
    kind = RuntimeKind.HAILO

    def __init__(
        self,
        detector: HailoDeviceDetector | None = None,
        preprocess_fn: Callable | None = None,
        postprocess_fn: Callable | None = None,
        # Injection seam: build the real HailoRT inference handle from an HEF
        # path. Defaults to the lazy real loader; tests inject a fake.
        infer_factory: Callable[[str], "Callable | None"] | None = None,
    ) -> None:
        self._detector = detector or HailoDeviceDetector()
        self._preprocess_fn = preprocess_fn
        self._postprocess_fn = postprocess_fn
        self._infer_factory = infer_factory or _default_hailo_infer_factory
        self._infer_handle: Callable | None = None
        self._metrics = InferenceMetricsCollector()
        self._health = ModelRuntimeHealthMonitor()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="hailo_infer")
        self._last_availability = AvailabilityResult(False, "not checked")

    @property
    def name(self) -> str:
        return "hailo"

    # (1)+(2) device detection + HailoRT availability
    def is_available(self) -> AvailabilityResult:
        det = self._detector.detect()
        self._last_availability = AvailabilityResult(det.usable, det.detail)
        return self._last_availability

    # (3) HEF model-path validation
    def validate_model_path(self, model_path: str):
        return ModelCompatibilityChecker.check(RuntimeKind.HAILO, model_path)

    def load_model(self, model_path: str) -> bool:
        compat = self.validate_model_path(model_path)
        if not compat.compatible:
            self._health.mark_model_loaded(False)
            return False
        if not self.is_available().available:
            self._health.mark_model_loaded(False)
            return False
        try:
            self._infer_handle = self._infer_factory(model_path)
            ok = self._infer_handle is not None
            self._health.mark_model_loaded(ok)
            return ok
        except Exception:  # noqa: BLE001 — load failure reported, not raised
            self._infer_handle = None
            self._health.mark_model_loaded(False)
            return False

    # (4) input preprocessing hook
    def preprocess(self, frame):
        if self._preprocess_fn is not None:
            return self._preprocess_fn(frame)
        return frame

    # (5) output postprocessing hook
    def postprocess(self, output: InferenceOutput):
        if self._postprocess_fn is not None and output.ok:
            return self._postprocess_fn(output)
        return output

    # (6) inference with timeout, (10) graceful fallback (never raises)
    def infer(self, input_tensor, timeout_ms: float = 300.0) -> InferenceOutput:
        if self._infer_handle is None:
            self._metrics.record(0.0, error=True)
            self._health.record_inference(False)
            return InferenceOutput(error="hailo model not loaded")
        t0 = time.perf_counter()
        future = self._executor.submit(self._infer_handle, input_tensor)
        try:
            raw = future.result(timeout=timeout_ms / 1000.0)
            latency = (time.perf_counter() - t0) * 1000.0
            self._metrics.record(latency)
            self._health.record_inference(True)
            outputs = raw if isinstance(raw, list) else [raw]
            return InferenceOutput(outputs=outputs, latency_ms=latency)
        except FutureTimeout:
            latency = (time.perf_counter() - t0) * 1000.0
            self._metrics.record(latency, timed_out=True)
            self._health.record_inference(False)
            return InferenceOutput(
                latency_ms=latency, timed_out=True, error="hailo inference timeout"
            )
        except Exception as exc:  # noqa: BLE001
            self._metrics.record(0.0, error=True)
            self._health.record_inference(False)
            return InferenceOutput(error=str(exc))

    # (7) warmup and (8) benchmark are inherited from the interface.

    # (9) health status
    def health(self) -> RuntimeHealth:
        snap = self._metrics.snapshot()
        return RuntimeHealth(
            runtime=self.name,
            status=self._health.status(available=self._last_availability.available),
            model_loaded=self._health.model_loaded,
            detail=self._last_availability.reason or "hailo",
            total_inferences=snap.total,
            total_timeouts=snap.timeouts,
            total_errors=snap.errors,
            last_latency_ms=snap.last_latency_ms,
        )

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False)
        self._infer_handle = None


def _default_hailo_infer_factory(hef_path: str):
    """Build a real HailoRT inference callable from an .hef. Lazy-imports
    hailort; returns None if the SDK is absent (so load_model fails cleanly
    and the selector falls back). The full HailoRT VDevice/InferModel wiring
    is only constructible on a real Hailo device and is intentionally minimal
    here — it is exercised by the hardware-gated tests, not unit tests."""
    import importlib

    try:
        hailort = importlib.import_module("hailort")
    except ImportError:
        return None

    # Real construction happens on-device; this is the integration seam.
    vdevice = hailort.VDevice()
    infer_model = vdevice.create_infer_model(hef_path)
    configured = infer_model.configure()

    def _run(input_tensor):
        with configured.run([input_tensor]) as result:
            return list(result)

    return _run
