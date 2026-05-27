"""
bonbon_vision.detectors.mock_detector
=======================================
Simulation-safe, fully controllable mock detector for all test scenarios.

Supported scenarios
-------------------
  Normal         — N synthetic detections per frame (configurable mix of classes)
  Low-light      — same results but marks frame_quality="low_light" in log
  Empty frame    — returns zero detections (simulates no objects)
  Corrupted      — raises RuntimeError on specific call number
  Timeout        — blocks for > timeout duration (tests degraded-mode entry)
  Degraded       — can be pre-set to degraded for test coverage
  Partial result — returns fewer detections than expected (dropped object)

All detections are deterministic: given the same call_count the same bounding
boxes and depths are returned.  Randomised only when randomise=True.
"""

from __future__ import annotations

import logging
import time

import numpy as np

from ..config.vision_config import DetectorConfig
from .base_detector import COCO_NAMES, BaseDetector, ObjectDetection

logger = logging.getLogger(__name__)

# Default synthetic class mix: person, chair, cup, cell phone
_DEFAULT_CLASSES = [0, 56, 41, 67]


class MockDetector(BaseDetector):
    """
    Mock multi-class detector for testing and CI.

    Constructor parameters
    ----------------------
    num_detections   int   total objects synthesised per frame (default 2)
    class_ids        list  which COCO classes to cycle through
    base_depth_m     float depth of nearest object (metres)
    depth_step_m     float additional depth per object
    skip_every_n     int   every N-th call returns [] (0 = never skip)
    corrupt_on_call  int   raise RuntimeError on this exact call (-1 = never)
    block_sec        float sleep for this many seconds per call (timeout test)
    start_degraded   bool  detector starts already in degraded mode
    randomise        bool  add ±5% noise to positions and depths
    """

    def __init__(
        self,
        cfg: DetectorConfig = None,
        hfov_deg: float = 60.0,
        num_detections: int = 2,
        class_ids: list[int] | None = None,
        base_depth_m: float = 2.0,
        depth_step_m: float = 0.6,
        confidence: float = 0.88,
        image_width: int = 640,
        image_height: int = 480,
        skip_every_n: int = 0,
        corrupt_on_call: int = -1,
        block_sec: float = 0.0,
        start_degraded: bool = False,
        randomise: bool = False,
    ) -> None:
        if cfg is None:
            cfg = DetectorConfig(backend="mock")
        super().__init__(cfg, hfov_deg)
        self._n = num_detections
        self._classes = class_ids or _DEFAULT_CLASSES
        self._depth = base_depth_m
        self._depth_step = depth_step_m
        self._conf = confidence
        self._img_w = image_width
        self._img_h = image_height
        self._skip_n = skip_every_n
        self._corrupt_n = corrupt_on_call
        self._block_sec = block_sec
        self._randomise = randomise
        self._call_count = 0

        if start_degraded:
            self._enter_degraded("start_degraded=True")

    # ── Subclass interface ────────────────────────────────────────────────────

    def _detect_impl(self, bgr: np.ndarray) -> list[ObjectDetection]:
        self._call_count += 1

        # Fault: block (simulates long inference for timeout test)
        if self._block_sec > 0:
            time.sleep(self._block_sec)

        # Fault: exception on specific call
        if self._corrupt_n >= 0 and self._call_count == self._corrupt_n:
            raise RuntimeError(
                f"MockDetector: simulated inference error on call {self._call_count}"
            )

        # Fault: skip every N
        if self._skip_n > 0 and self._call_count % self._skip_n == 0:
            return []

        h, w = bgr.shape[:2]
        detections: list[ObjectDetection] = []

        n_classes = len(self._classes)
        n = max(0, self._n)
        hfov_half = self._hfov_deg / 2.0

        for i in range(n):
            cls_id = self._classes[i % n_classes]
            name = COCO_NAMES.get(cls_id, str(cls_id))

            # Spread objects horizontally across FOV
            if n == 1:
                bearing = 0.0
            else:
                frac = i / (n - 1)  # 0 … 1
                bearing = -hfov_half * 0.8 + frac * hfov_half * 1.6

            norm_x = bearing / self._hfov_deg + 0.5
            cx = int(norm_x * w)
            cy = int(h * 0.55)

            # Box size: scales with distance (perspective)
            depth = self._depth + i * self._depth_step
            box_w = max(30, int(w * 0.18 / max(0.3, depth)))
            box_h = max(50, int(box_w * (2.2 if cls_id == 0 else 1.0)))
            bx = max(0, cx - box_w // 2)
            by = max(0, cy - box_h // 2)
            box_w = min(w - bx, box_w)
            box_h = min(h - by, box_h)

            conf = max(0.5, self._conf - i * 0.03)

            if self._randomise:
                noise = 1.0 + (((self._call_count * 7 + i * 13) % 100) - 50) / 1000
                depth *= noise
                conf = min(1.0, conf * (1.0 + (i % 5 - 2) * 0.01))

            det = ObjectDetection(
                class_id=cls_id,
                class_name=name,
                confidence=conf,
                bbox=(bx, by, box_w, box_h),
                depth_m=depth,
                bearing_deg=bearing,
            )
            detections.append(det)

        return detections

    # ── Test helpers ──────────────────────────────────────────────────────────

    def set_num_detections(self, n: int) -> None:
        self._n = n

    def force_degraded(self, reason: str = "forced") -> None:
        self._enter_degraded(reason)

    @property
    def call_count(self) -> int:
        return self._call_count
