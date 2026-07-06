"""VisionModelRuntimeInterface and the shared value types every runtime
returns.

A "runtime" here is the thing that executes a vision model on an input
tensor and returns raw output — one level below bonbon_vision's
BaseDetector (which adds ROS2, depth, bearing, COCO labels). Keeping the
runtime that thin is what lets the same CPU/Hailo/TensorRT/mock backends be
swapped purely by config, and lets a Hailo failure fall back to CPU without
touching any detection logic.

Nothing heavy is imported here — numpy only. Each concrete runtime
lazy-imports its accelerator SDK inside is_available()/load_model().
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum


class RuntimeKind(str, Enum):
    CPU = "cpu"
    HAILO = "hailo"
    TENSORRT = "tensorrt"
    MOCK = "mock"


class RuntimeStatus(str, Enum):
    UNINITIALISED = "uninitialised"
    READY = "ready"
    DEGRADED = "degraded"  # loaded but a recent inference failed/timed out
    UNAVAILABLE = "unavailable"  # deps/hardware/model missing
    FAILED = "failed"  # load attempted and errored


@dataclass
class AvailabilityResult:
    available: bool
    reason: str = ""


@dataclass
class InferenceOutput:
    """Raw model output plus timing. `outputs` is a list of numpy arrays
    (one per model output tensor). `timed_out`/`error` signal a failed run
    without raising, so the caller can fall back gracefully."""

    outputs: list = field(default_factory=list)
    latency_ms: float = 0.0
    timed_out: bool = False
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.timed_out and not self.error


@dataclass
class BenchmarkResult:
    runtime: str
    runs: int
    mean_ms: float
    p50_ms: float
    p95_ms: float
    max_ms: float
    fps: float
    failures: int


@dataclass
class RuntimeHealth:
    runtime: str
    status: RuntimeStatus
    model_loaded: bool
    detail: str = ""
    total_inferences: int = 0
    total_timeouts: int = 0
    total_errors: int = 0
    last_latency_ms: float = 0.0


class VisionModelRuntimeInterface(ABC):
    """One vision inference backend. Subclasses must never raise on import or
    construction — availability/load failures are reported, not thrown, so a
    RuntimeSelector can fall back."""

    kind: RuntimeKind = RuntimeKind.MOCK

    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def is_available(self) -> AvailabilityResult:
        """Are this backend's deps + hardware + (if needed) model present?
        Must be cheap and side-effect-free enough to call during selection."""

    @abstractmethod
    def load_model(self, model_path: str) -> bool:
        """Load the model; return True on success. On failure, return False
        and reflect it in health() — never raise."""

    @abstractmethod
    def infer(self, input_tensor, timeout_ms: float = 300.0) -> InferenceOutput:
        """Run one inference. Must honour the timeout and return an
        InferenceOutput with timed_out/error set rather than raising."""

    @abstractmethod
    def health(self) -> RuntimeHealth: ...

    # ── Optional hooks with safe defaults ─────────────────────────────────────

    def preprocess(self, frame):
        """Frame (HxWxC BGR) -> model input tensor. Default: passthrough.
        Detection-specific letterboxing lives in the detector adapter; a
        backend that needs a particular layout overrides this."""
        return frame

    def postprocess(self, output: InferenceOutput):
        """Raw model output -> backend-neutral form. Default: passthrough."""
        return output

    def warmup(self, runs: int = 5, input_shape: tuple = (640, 640, 3)) -> None:
        """Run a few blank inferences to trigger JIT/allocation. Best-effort;
        swallows failures (they'll surface on the first real infer)."""
        import numpy as np

        dummy = np.zeros(input_shape, dtype=np.uint8)
        for _ in range(max(0, runs)):
            try:
                self.infer(self.preprocess(dummy))
            except Exception:  # noqa: BLE001 — warmup must never raise
                return

    def benchmark(self, runs: int = 30, input_shape: tuple = (640, 640, 3)) -> BenchmarkResult:
        import numpy as np

        dummy = np.zeros(input_shape, dtype=np.uint8)
        tensor = self.preprocess(dummy)
        samples: list[float] = []
        failures = 0
        for _ in range(max(1, runs)):
            out = self.infer(tensor)
            if out.ok:
                samples.append(out.latency_ms)
            else:
                failures += 1
        samples.sort()
        if not samples:
            return BenchmarkResult(self.name, runs, 0, 0, 0, 0, 0.0, failures)
        mean = sum(samples) / len(samples)
        p50 = samples[len(samples) // 2]
        p95 = samples[min(len(samples) - 1, int(len(samples) * 0.95))]
        mx = samples[-1]
        fps = 1000.0 / mean if mean > 0 else 0.0
        return BenchmarkResult(self.name, runs, mean, p50, p95, mx, fps, failures)

    def shutdown(self) -> None:
        """Release model/device handles. Default: no-op."""
        return None
