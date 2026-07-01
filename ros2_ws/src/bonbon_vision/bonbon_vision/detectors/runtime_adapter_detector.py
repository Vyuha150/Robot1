"""ObjectDetectorRuntimeAdapter — wires the live vision pipeline to
`bonbon_ai_runtime`'s Hailo/CPU/TensorRT/Mock runtime abstraction.

This is the fix for the confirmed gap in docs/OBJECT_RECOGNITION_FAILURE_ANALYSIS.md:
`YoloDetector` calls `ultralytics.YOLO` directly and never attempts Hailo.
This adapter is a `BaseDetector` (selectable via `detector.backend: "runtime"`
in vision_params.yaml) that goes through `RuntimeSelector` instead — so on a
Pi 5 + AI HAT, `auto` mode genuinely prefers Hailo, with an honest CPU
fallback and reason exposed for the dashboard, exactly like every other
Hailo integration in this repo. It does not replace `YoloDetector` (still a
valid backend choice); both remain configurable, non-duplicate options.
"""

from __future__ import annotations

import logging
import time

import numpy as np

from ..config.vision_config import DetectorConfig
from .base_detector import COCO_NAMES, BaseDetector, ObjectDetection

logger = logging.getLogger(__name__)

# Optional import — graceful failure, same posture as bonbon_ai_runtime's own
# lazy-imported accelerator SDKs. bonbon_ai_runtime itself has zero required
# deps beyond numpy, so this import only fails if the package isn't installed
# (e.g. workspace not built), not because of missing hardware.
try:
    from bonbon_ai_runtime import RuntimeKind, RuntimeMode, RuntimeSelector, RuntimeSpec

    _HAS_AI_RUNTIME = True
except ImportError:
    _HAS_AI_RUNTIME = False


class ObjectDetectorRuntimeAdapter(BaseDetector):
    """Runs object detection through `bonbon_ai_runtime.RuntimeSelector`.

    Output decoding assumes the (N, 6) `[x1, y1, x2, y2, confidence,
    class_id]` tensor shape every runtime in this repo already targets
    (MockRuntime's `np.zeros((0, 6))`, HailoRuntime's default infer
    factory) — the same contract bonbon_ai_runtime's own tests assume.
    """

    def __init__(self, cfg: DetectorConfig, hfov_deg: float = 60.0) -> None:
        super().__init__(cfg, hfov_deg)
        self._selection = None  # SelectionResult, once load_model() succeeds
        self._selector_factory = None  # injectable for tests

    # ── Model lifecycle ───────────────────────────────────────────────────────

    def load_model(self) -> None:
        if not _HAS_AI_RUNTIME:
            self._enter_degraded("bonbon_ai_runtime not importable")
            return

        try:
            mode = RuntimeMode(self._cfg.runtime_mode or "auto")
        except ValueError:
            logger.warning(
                "detector=runtime_adapter event=bad_runtime_mode value=%r — using auto",
                self._cfg.runtime_mode,
            )
            mode = RuntimeMode.AUTO

        priority = [
            RuntimeKind(k) for k in (self._cfg.runtime_priority or ["hailo", "cpu", "mock"])
        ]
        model_paths: dict = {}
        if self._cfg.hailo_hef_path:
            model_paths[RuntimeKind.HAILO] = self._cfg.hailo_hef_path
        if self._cfg.cpu_onnx_path or (
            self._cfg.model_path and self._cfg.model_path.endswith(".onnx")
        ):
            model_paths[RuntimeKind.CPU] = self._cfg.cpu_onnx_path or self._cfg.model_path

        selector = (self._selector_factory or RuntimeSelector)()
        t0 = time.monotonic()
        self._selection = selector.select(
            RuntimeSpec(mode=mode, runtime_priority=priority, model_paths=model_paths)
        )
        logger.info(
            "detector=runtime_adapter event=model_loaded selected=%s fallback_active=%s "
            "fallback_reason=%r load_ms=%.0f",
            self._selection.selected_kind.value,
            self._selection.fallback_active,
            self._selection.fallback_reason,
            (time.monotonic() - t0) * 1000,
        )
        self._warmup_via_runtime()

    def _warmup_via_runtime(self) -> None:
        if self._selection is None:
            return
        try:
            self._selection.runtime.warmup(
                runs=2, input_shape=(self._cfg.img_size, self._cfg.img_size, 3)
            )
        except Exception as exc:  # noqa: BLE001 — warmup must never break configure()
            logger.warning("detector=runtime_adapter event=warmup_failed error=%r", str(exc))

    # ── Inference ─────────────────────────────────────────────────────────────

    def _detect_impl(self, bgr: np.ndarray) -> list[ObjectDetection]:
        if self._selection is None:
            return []
        runtime = self._selection.runtime
        tensor = runtime.preprocess(bgr)
        out = runtime.infer(tensor, timeout_ms=self._cfg.inference_timeout_sec * 1000.0)
        if not out.ok or not out.outputs:
            return []

        raw = out.outputs[0]
        if raw.size == 0:
            return []

        classes_filter = set(self._cfg.classes) if self._cfg.classes else None
        detections: list[ObjectDetection] = []
        for row in raw:
            x1, y1, x2, y2, conf, cls_id = row[:6]
            conf = float(conf)
            if conf < self._cfg.confidence_threshold:
                continue
            cls_id = int(cls_id)
            if classes_filter is not None and cls_id not in classes_filter:
                continue
            detections.append(
                ObjectDetection(
                    class_id=cls_id,
                    class_name=COCO_NAMES.get(cls_id, str(cls_id)),
                    confidence=conf,
                    bbox=(int(x1), int(y1), int(x2 - x1), int(y2 - y1)),
                )
            )
        return detections

    # ── Dashboard-facing status ─────────────────────────────────────────────────

    @property
    def selected_runtime_kind(self) -> str:
        return self._selection.selected_kind.value if self._selection else "unavailable"

    @property
    def is_real_accelerator(self) -> bool:
        return self._selection is not None and self._selection.selected_kind.value in (
            "hailo",
            "tensorrt",
        )

    @property
    def fallback_active(self) -> bool:
        return bool(self._selection and self._selection.fallback_active)

    @property
    def fallback_reason(self) -> str:
        return self._selection.fallback_reason if self._selection else "not loaded"
