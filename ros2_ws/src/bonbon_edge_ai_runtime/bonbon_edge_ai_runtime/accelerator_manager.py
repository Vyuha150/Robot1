"""bonbon_edge_ai_runtime.accelerator_manager -- Edge AI Runtime brief
Phase 5. A thin, capability-aware facade over
bonbon_ai_runtime.RuntimeSelector, which already implements real
Hailo/CPU/TensorRT/mock detection, selection, and fallback -- see
docs/DUPLICATE_PIPELINE_AUDIT.md. This module does not reimplement that
selection algorithm. It adds the two things that didn't already exist:

1. One call surface spanning object detection, person detection,
   gesture recognition, and pose estimation -- today each picks its own
   runtime independently across bonbon_vision/bonbon_perception/
   bonbon_gesture.
2. The per-output envelope (timestamp, frame_id, runtime_source,
   model_id, confidence, latency_ms, stale_result) this brief's Phase 5
   requires every vision output to carry, which
   bonbon_ai_runtime.interface.InferenceOutput does not (it's one level
   lower -- raw tensors + timing, not a labeled detection result).
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from bonbon_ai_runtime.interface import RuntimeKind
from bonbon_ai_runtime.runtime_selector import RuntimeSelector, RuntimeSpec, SelectionResult

# Matches bonbon_vision's own frame-throttling cadence rather than
# inventing a new number -- see docs/THREE_PI_RUNTIME_AUDIT.md's
# FrameThrottler finding.
DEFAULT_STALE_AFTER_SEC = 0.5

VISION_CAPABILITIES = (
    "object_detection",
    "person_detection",
    "gesture_recognition",
    "pose_estimation",
)


@dataclass
class VisionOutputEnvelope:
    """Wraps a single inference result with the fields this brief's
    Phase 5 requires every vision output to carry."""

    timestamp: float
    frame_id: str
    runtime_source: str  # "hailo" | "cpu" | "tensorrt" | "mock"
    model_id: str
    confidence: float
    latency_ms: float
    stale_result: bool

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "frameId": self.frame_id,
            "runtimeSource": self.runtime_source,
            "modelId": self.model_id,
            "confidence": self.confidence,
            "latencyMs": self.latency_ms,
            "staleResult": self.stale_result,
        }


class AcceleratorManager:
    """One call surface for every vision capability's runtime selection.
    Delegates the actual hailo/cpu/tensorrt/mock decision to
    bonbon_ai_runtime.RuntimeSelector; adds unification across
    capabilities and the output envelope, not a new selection
    algorithm."""

    def __init__(self, stale_after_sec: float = DEFAULT_STALE_AFTER_SEC) -> None:
        self._selector = RuntimeSelector()
        self._stale_after_sec = stale_after_sec
        self._last_result_by_capability: dict[str, tuple[SelectionResult, float]] = {}

    def select(self, capability: str, spec: RuntimeSpec) -> SelectionResult:
        if capability not in VISION_CAPABILITIES:
            raise ValueError(
                f"{capability!r} is not a vision capability -- accelerator_manager only "
                f"handles {VISION_CAPABILITIES}; non-vision capabilities go through "
                "bonbon_edge_ai_runtime.runtime_selector.ModelRuntimeSelector instead"
            )
        result = self._selector.select(spec)
        self._last_result_by_capability[capability] = (result, time.monotonic())
        return result

    def wrap_output(
        self,
        capability: str,
        model_id: str,
        frame_id: str,
        confidence: float,
        latency_ms: float,
        produced_at: float | None = None,
    ) -> VisionOutputEnvelope:
        """Builds the required output envelope for one detection result.
        `produced_at` should be the monotonic time the frame was
        captured/inferred, not now -- staleness is measured against
        that, not against when this wrapper happens to be called."""
        produced_at = produced_at if produced_at is not None else time.monotonic()
        stale = (time.monotonic() - produced_at) > self._stale_after_sec
        cached = self._last_result_by_capability.get(capability)
        runtime_source = cached[0].selected_kind.value if cached else RuntimeKind.MOCK.value
        return VisionOutputEnvelope(
            timestamp=produced_at,
            frame_id=frame_id,
            runtime_source=runtime_source,
            model_id=model_id,
            confidence=confidence,
            latency_ms=latency_ms,
            stale_result=stale,
        )

    def status(self) -> dict:
        """Dashboard-facing snapshot: last selection result per vision
        capability, or absent if select() was never called for it (not
        fabricated as 'unavailable' -- genuinely unknown yet)."""
        return {
            capability: {**result.to_dict(), "selectedAtMonotonic": selected_at}
            for capability, (result, selected_at) in self._last_result_by_capability.items()
        }
