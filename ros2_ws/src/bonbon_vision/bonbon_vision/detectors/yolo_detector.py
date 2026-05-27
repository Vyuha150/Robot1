"""
bonbon_vision.detectors.yolo_detector
=======================================
YOLOv8 multi-class object detector (ultralytics backend).

Model loading strategy
----------------------
1. load_model() is called once from VisionNode.on_configure().
2. If the model file is missing or ultralytics is not installed the detector
   enters degraded mode immediately (VisionConfig.allow_degraded_startup must
   be True, otherwise configure() fails).
3. A warm-up inference is run on a blank frame so JIT compilation and GPU
   memory allocation happen before the first real frame arrives.

Model path
----------
NEVER hardcoded.  Must be passed via DetectorConfig.model_path which
comes from the ROS2 parameter 'detector_model_path'.

Recommended models for the Jetson Orin Nano
-------------------------------------------
  yolov8n.pt  — 3.2 MB, ~15 Hz CPU / ~30 Hz TRT
  yolov8s.pt  — 11 MB, ~10 Hz CPU / ~20 Hz TRT
  yolov8n-seg.pt — instance segmentation (heavier)

TensorRT export (one-time, done offline on Jetson):
  yolo export model=yolov8n.pt format=engine device=0 half=True
  → produces yolov8n.engine; pass its path as detector_model_path
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

import numpy as np

from ..config.vision_config import DetectorConfig
from .base_detector import COCO_NAMES, BaseDetector, ObjectDetection

logger = logging.getLogger(__name__)

# Optional import — graceful failure
try:
    from ultralytics import YOLO as _YOLO

    _HAS_ULTRALYTICS = True
except ImportError:
    _HAS_ULTRALYTICS = False

# COCO person class ID
_PERSON_CLASS = 0


class YoloDetector(BaseDetector):
    """
    YOLOv8 (ultralytics) multi-class object detector.

    Supports: .pt (PyTorch), .engine (TensorRT), .onnx (ONNX Runtime).
    """

    def __init__(self, cfg: DetectorConfig, hfov_deg: float = 60.0) -> None:
        super().__init__(cfg, hfov_deg)
        self._model = None
        self._warmup_done = False

    # ── Model lifecycle ───────────────────────────────────────────────────────

    def load_model(self) -> None:
        """
        Load the YOLO model from cfg.model_path and run a warmup inference.
        Enters degraded mode on failure (if allowed by config).
        """
        if not _HAS_ULTRALYTICS:
            msg = "ultralytics not installed. " "Install with: pip install ultralytics"
            logger.error("detector=yolo event=load_failed reason=%r", msg)
            self._enter_degraded("ultralytics not installed")
            return

        model_path = Path(self._cfg.model_path)
        if not model_path.exists():
            msg = f"model file not found: {model_path}"
            logger.error("detector=yolo event=load_failed reason=%r", msg)
            self._enter_degraded(msg)
            return

        t0 = time.monotonic()
        try:
            self._model = _YOLO(str(model_path))
            logger.info(
                "detector=yolo event=model_loaded path=%r " "load_ms=%.0f",
                str(model_path),
                (time.monotonic() - t0) * 1000,
            )
            self._warmup()
        except Exception as exc:
            logger.error("detector=yolo event=load_exception error=%r", str(exc))
            self._enter_degraded(str(exc))

    def _warmup(self) -> None:
        """Run one blank-frame inference to trigger JIT / GPU alloc."""
        try:
            dummy = np.zeros((self._cfg.img_size, self._cfg.img_size, 3), dtype=np.uint8)
            t0 = time.monotonic()
            self._model(
                dummy,
                verbose=False,
                half=self._cfg.half_precision,
                device=self._cfg.device or None,
            )
            warmup_ms = (time.monotonic() - t0) * 1000
            self._warmup_done = True
            logger.info("detector=yolo event=warmup_done warmup_ms=%.0f", warmup_ms)
        except Exception as exc:
            logger.warning("detector=yolo event=warmup_failed error=%r", str(exc))

    # ── Inference ─────────────────────────────────────────────────────────────

    def _detect_impl(self, bgr: np.ndarray) -> list[ObjectDetection]:
        if self._model is None:
            return []

        classes_arg = self._cfg.classes if self._cfg.classes else None
        results = self._model(
            bgr,
            conf=self._cfg.confidence_threshold,
            iou=self._cfg.nms_iou_threshold,
            classes=classes_arg,
            imgsz=self._cfg.img_size,
            verbose=False,
            half=self._cfg.half_precision,
            device=self._cfg.device or None,
        )

        detections: list[ObjectDetection] = []
        for result in results:
            boxes = result.boxes
            if boxes is None:
                continue
            for box in boxes:
                cls_id = int(box.cls[0])
                conf = float(box.conf[0])
                xyxy = box.xyxy[0].cpu().numpy()
                x1, y1, x2, y2 = map(int, xyxy)
                det = ObjectDetection(
                    class_id=cls_id,
                    class_name=COCO_NAMES.get(cls_id, str(cls_id)),
                    confidence=conf,
                    bbox=(x1, y1, x2 - x1, y2 - y1),
                )
                detections.append(det)

        return detections
