"""
bonbon_perception.detectors.person_detector
=============================================
Abstract base class for all person detectors.

All detectors return a list of Detection objects from a single call to
detect(color_bgr, depth_m).  They are pure Python — no ROS2 dependency —
so they can be unit tested in isolation.

Detection fields
----------------
  bbox            (x, y, w, h)  — bounding box in image pixels
  confidence      float          — detector confidence 0.0–1.0
  label           str            — always "person"
  centre_px       (cx, cy)       — bbox centre in image pixels
  depth_m         float          — median depth within bbox (NaN if unknown)
  bearing_deg     float          — horizontal bearing from camera optical axis
  distance_m      float          — same as depth_m for forward-facing camera

Depth convention
----------------
depth_m is measured along the optical Z axis.  For a forward-facing camera
this equals horizontal ground-plane distance to the person's torso centre.
NaN is used when depth is unavailable (color-only mode).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np

# ── Detection dataclass ───────────────────────────────────────────────────────


@dataclass
class Detection:
    """Single person detection in image space."""

    # Bounding box [x, y, w, h] in pixels (top-left origin)
    bbox: tuple[int, int, int, int]
    confidence: float = 0.0
    label: str = "person"
    depth_m: float = float("nan")
    bearing_deg: float = 0.0

    # Camera intrinsics at detection time (optional)
    fx: float = 0.0  # focal length x (pixels)
    fy: float = 0.0  # focal length y (pixels)
    cx: float = 0.0  # principal point x
    cy: float = 0.0  # principal point y

    @property
    def centre_px(self) -> tuple[float, float]:
        x, y, w, h = self.bbox
        return x + w / 2.0, y + h / 2.0

    @property
    def distance_m(self) -> float:
        """Alias for depth_m for semantic clarity."""
        return self.depth_m

    @property
    def area_px2(self) -> int:
        return self.bbox[2] * self.bbox[3]

    @staticmethod
    def iou(a: Detection, b: Detection) -> float:
        """Intersection-over-Union between two bounding boxes."""
        ax, ay, aw, ah = a.bbox
        bx, by, bw, bh = b.bbox
        ix = max(ax, bx)
        iy = max(ay, by)
        iw = max(0, min(ax + aw, bx + bw) - ix)
        ih = max(0, min(ay + ah, by + bh) - iy)
        inter = iw * ih
        union = aw * ah + bw * bh - inter
        return inter / union if union > 0 else 0.0

    def compute_bearing(self, image_width: int, hfov_deg: float = 60.0) -> None:
        """
        Set bearing_deg from bbox centre and camera horizontal FOV.
        Positive = right of camera forward axis.
        """
        cx_img, _ = self.centre_px
        # Normalised position: -0.5 (left edge) to +0.5 (right edge)
        norm = (cx_img / image_width) - 0.5
        self.bearing_deg = norm * hfov_deg


# ── Abstract detector ─────────────────────────────────────────────────────────


class PersonDetector(ABC):
    """
    Abstract person detector.

    Implementations must fill Detection.depth_m using the supplied depth array
    when available, and call compute_bearing() before returning.
    """

    def __init__(
        self,
        confidence_threshold: float = 0.5,
        hfov_deg: float = 60.0,
        nms_iou_threshold: float = 0.45,
    ) -> None:
        self.confidence_threshold = confidence_threshold
        self.hfov_deg = hfov_deg
        self.nms_iou_threshold = nms_iou_threshold

    def detect(
        self,
        color_bgr: np.ndarray,
        depth_m: np.ndarray | None = None,
    ) -> list[Detection]:
        """
        Run person detection on a BGR image.

        Args:
            color_bgr:  HxWx3 uint8 BGR image.
            depth_m:    HxW float32 depth in metres (aligned to color).
                        Pass None for color-only mode; depth_m will be NaN.

        Returns:
            List of Detection objects sorted by confidence descending.
        """
        detections = self._detect_impl(color_bgr)

        h, w = color_bgr.shape[:2]
        for det in detections:
            det.compute_bearing(w, self.hfov_deg)
            if depth_m is not None:
                det.depth_m = self._sample_depth(det, depth_m)

        return sorted(detections, key=lambda d: d.confidence, reverse=True)

    @abstractmethod
    def _detect_impl(self, color_bgr: np.ndarray) -> list[Detection]:
        """Override: return raw detections (bearing and depth not yet set)."""

    # ── Shared depth sampling ─────────────────────────────────────────────────

    @staticmethod
    def _sample_depth(det: Detection, depth_m: np.ndarray) -> float:
        """
        Median depth inside the inner 50% of the bounding box (avoids edges
        which are often on background / occlusion boundaries).
        """
        x, y, w, h = det.bbox
        ih, iw = depth_m.shape[:2]

        # Shrink to inner 50%
        margin_x = max(1, w // 4)
        margin_y = max(1, h // 4)
        x0 = max(0, x + margin_x)
        y0 = max(0, y + margin_y)
        x1 = min(iw, x + w - margin_x)
        y1 = min(ih, y + h - margin_y)

        if x0 >= x1 or y0 >= y1:
            return float("nan")

        roi = depth_m[y0:y1, x0:x1]
        valid = roi[np.isfinite(roi) & (roi > 0.1) & (roi < 10.0)]
        if valid.size == 0:
            return float("nan")
        return float(np.median(valid))

    # ── NMS utility (optional use by subclasses) ──────────────────────────────

    def _nms(self, detections: list[Detection]) -> list[Detection]:
        """
        Greedy non-maximum suppression by IoU.
        Assumes detections are sorted by confidence (highest first).
        """
        kept: list[Detection] = []
        for det in detections:
            suppress = any(Detection.iou(det, k) > self.nms_iou_threshold for k in kept)
            if not suppress:
                kept.append(det)
        return kept
