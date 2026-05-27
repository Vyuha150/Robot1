"""
bonbon_vision.detectors.base_detector
=======================================
Abstract base class for all object detectors.

Key responsibilities handled at this layer
------------------------------------------
1. **Inference timeout** — wraps _detect_impl() in a ThreadPoolExecutor
   future with a configurable deadline. On timeout the detector enters
   degraded mode.
2. **Degraded mode** — after max_consecutive_timeouts the detector marks
   itself as degraded and returns empty DetectionResults until recover() is
   called.  This prevents a hung GPU process from blocking the ROS2 timer.
3. **Structured logging** — every public call emits a structured debug line.
4. **Depth association** — calls _sample_depth (same logic as bonbon_hal
   DriverBase) to fill ObjectDetection.depth_m from the aligned depth map.
5. **Bearing computation** — fills ObjectDetection.bearing_deg from bbox
   centre and camera HFOV.

All implementations inherit BaseDetector and only override _detect_impl().
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from dataclasses import dataclass, field

import numpy as np

from ..config.vision_config import DetectorConfig

logger = logging.getLogger(__name__)

# COCO class names (80-class YOLO default)
COCO_NAMES: dict[int, str] = {
    0: "person",
    1: "bicycle",
    2: "car",
    3: "motorcycle",
    4: "airplane",
    5: "bus",
    6: "train",
    7: "truck",
    8: "boat",
    9: "traffic light",
    10: "fire hydrant",
    11: "stop sign",
    12: "parking meter",
    13: "bench",
    14: "bird",
    15: "cat",
    16: "dog",
    17: "horse",
    18: "sheep",
    19: "cow",
    20: "elephant",
    21: "bear",
    22: "zebra",
    23: "giraffe",
    24: "backpack",
    25: "umbrella",
    26: "handbag",
    27: "tie",
    28: "suitcase",
    29: "frisbee",
    30: "skis",
    31: "snowboard",
    32: "sports ball",
    33: "kite",
    34: "baseball bat",
    35: "baseball glove",
    36: "skateboard",
    37: "surfboard",
    38: "tennis racket",
    39: "bottle",
    40: "wine glass",
    41: "cup",
    42: "fork",
    43: "knife",
    44: "spoon",
    45: "bowl",
    46: "banana",
    47: "apple",
    48: "sandwich",
    49: "orange",
    50: "broccoli",
    51: "carrot",
    52: "hot dog",
    53: "pizza",
    54: "donut",
    55: "cake",
    56: "chair",
    57: "couch",
    58: "potted plant",
    59: "bed",
    60: "dining table",
    61: "toilet",
    62: "tv",
    63: "laptop",
    64: "mouse",
    65: "remote",
    66: "keyboard",
    67: "cell phone",
    68: "microwave",
    69: "oven",
    70: "toaster",
    71: "sink",
    72: "refrigerator",
    73: "book",
    74: "clock",
    75: "vase",
    76: "scissors",
    77: "teddy bear",
    78: "hair drier",
    79: "toothbrush",
}


# ── Detection data classes ────────────────────────────────────────────────────


@dataclass
class ObjectDetection:
    """Single detected object."""

    class_id: int
    class_name: str
    confidence: float
    bbox: tuple[int, int, int, int]  # (x, y, w, h) pixels, top-left
    depth_m: float = float("nan")
    bearing_deg: float = 0.0
    track_id: str = ""
    is_anonymized: bool = False

    @property
    def centre_px(self) -> tuple[float, float]:
        x, y, w, h = self.bbox
        return x + w / 2.0, y + h / 2.0

    @property
    def is_person(self) -> bool:
        return self.class_id == 0


@dataclass
class DetectionResult:
    """Result of one detector run."""

    detections: list[ObjectDetection] = field(default_factory=list)
    is_degraded: bool = False
    timed_out: bool = False
    inference_ms: float = 0.0
    error: str | None = None
    backend: str = "unknown"
    frame_quality: str = "ok"


# ── Abstract base detector ────────────────────────────────────────────────────


class BaseDetector(ABC):
    """
    Abstract detector with built-in timeout and degraded-mode management.

    Subclasses implement only _detect_impl() and optionally load_model().
    """

    def __init__(self, cfg: DetectorConfig, hfov_deg: float = 60.0) -> None:
        self._cfg = cfg
        self._hfov_deg = hfov_deg
        self._consecutive_timeouts: int = 0
        self._is_degraded: bool = False
        self._total_inferences: int = 0
        self._total_timeouts: int = 0
        self._total_errors: int = 0
        # Single-worker pool for timeout isolation
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="detector")

    # ── Public API ────────────────────────────────────────────────────────────

    @property
    def is_degraded(self) -> bool:
        return self._is_degraded

    @property
    def backend_name(self) -> str:
        return self._cfg.backend

    def detect(
        self,
        bgr: np.ndarray,
        depth_m: np.ndarray | None = None,
    ) -> DetectionResult:
        """
        Run detection with timeout.  Returns DetectionResult.
        If degraded, immediately returns an empty degraded result.
        """
        if self._is_degraded:
            logger.debug(
                "detector=degraded inference_skipped=True " "consecutive_timeouts=%d",
                self._consecutive_timeouts,
            )
            return DetectionResult(is_degraded=True, backend=self.backend_name)

        t0 = time.monotonic()
        timeout = self._cfg.inference_timeout_sec
        result: DetectionResult

        try:
            if timeout > 0:
                future = self._executor.submit(self._detect_impl, bgr)
                detections = future.result(timeout=timeout)
            else:
                detections = self._detect_impl(bgr)

            # Post-process: depth + bearing
            h, w = bgr.shape[:2]
            for det in detections:
                self._fill_depth(det, depth_m)
                self._fill_bearing(det, w)

            elapsed_ms = (time.monotonic() - t0) * 1000.0
            self._consecutive_timeouts = 0
            self._total_inferences += 1

            result = DetectionResult(
                detections=detections,
                inference_ms=elapsed_ms,
                backend=self.backend_name,
            )
            logger.debug(
                "detector=%s n_detections=%d inference_ms=%.1f",
                self.backend_name,
                len(detections),
                elapsed_ms,
            )

        except FuturesTimeout:
            elapsed_ms = (time.monotonic() - t0) * 1000.0
            self._consecutive_timeouts += 1
            self._total_timeouts += 1
            logger.warning(
                "detector=%s event=inference_timeout " "consecutive=%d max=%d elapsed_ms=%.1f",
                self.backend_name,
                self._consecutive_timeouts,
                self._cfg.max_consecutive_timeouts,
                elapsed_ms,
            )
            if self._consecutive_timeouts >= self._cfg.max_consecutive_timeouts:
                self._enter_degraded("too many consecutive timeouts")
            result = DetectionResult(
                timed_out=True, inference_ms=elapsed_ms, backend=self.backend_name
            )

        except Exception as exc:
            elapsed_ms = (time.monotonic() - t0) * 1000.0
            self._total_errors += 1
            logger.error(
                "detector=%s event=inference_error error=%r elapsed_ms=%.1f",
                self.backend_name,
                str(exc),
                elapsed_ms,
            )
            result = DetectionResult(
                error=str(exc), inference_ms=elapsed_ms, backend=self.backend_name
            )

        return result

    def recover(self) -> None:
        """Exit degraded mode (called by VisionNode on external instruction)."""
        if self._is_degraded:
            logger.info("detector=%s event=recover", self.backend_name)
        self._is_degraded = False
        self._consecutive_timeouts = 0

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False)

    # ── Subclass interface ────────────────────────────────────────────────────

    @abstractmethod
    def _detect_impl(self, bgr: np.ndarray) -> list[ObjectDetection]:
        """
        Run inference and return raw ObjectDetections.
        depth_m and bearing_deg are filled by the base class after this returns.
        Called inside the ThreadPoolExecutor.
        """

    def load_model(self) -> None:
        """
        Optional override: load and warm up the model.
        Called once from VisionNode.on_configure().
        """

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _enter_degraded(self, reason: str) -> None:
        self._is_degraded = True
        logger.error(
            "detector=%s event=degraded reason=%r " "total_timeouts=%d total_errors=%d",
            self.backend_name,
            reason,
            self._total_timeouts,
            self._total_errors,
        )

    @staticmethod
    def _fill_depth(det: ObjectDetection, depth_m: np.ndarray | None) -> None:
        """Sample the median depth inside the inner 50% of the bounding box."""
        if depth_m is None:
            return
        x, y, w, h = det.bbox
        ih, iw = depth_m.shape[:2]
        mx = max(1, w // 4)
        my = max(1, h // 4)
        x0 = max(0, x + mx)
        x1 = min(iw, x + w - mx)
        y0 = max(0, y + my)
        y1 = min(ih, y + h - my)
        if x0 >= x1 or y0 >= y1:
            return
        roi = depth_m[y0:y1, x0:x1]
        valid = roi[np.isfinite(roi) & (roi > 0.05) & (roi < 15.0)]
        if valid.size > 0:
            det.depth_m = float(np.median(valid))

    def _fill_bearing(self, det: ObjectDetection, image_width: int) -> None:
        """Compute horizontal bearing from bbox centre and HFOV."""
        cx, _ = det.centre_px
        norm = (cx / max(1, image_width)) - 0.5  # -0.5 … +0.5
        det.bearing_deg = norm * self._hfov_deg

    def stats(self) -> dict:
        return {
            "backend": self.backend_name,
            "is_degraded": self._is_degraded,
            "total_inferences": self._total_inferences,
            "total_timeouts": self._total_timeouts,
            "total_errors": self._total_errors,
            "consecutive_timeouts": self._consecutive_timeouts,
        }
