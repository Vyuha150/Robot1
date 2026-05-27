"""
bonbon_perception.detectors.hog_person_detector
================================================
Real person detector using OpenCV's pre-trained HOG + SVM pedestrian detector.

Performance envelope (Jetson Orin Nano 640×480 @ CPU)
------------------------------------------------------
  ~8 Hz with win_stride=(8,8), scale=1.05
  ~15 Hz with win_stride=(16,16), scale=1.1  (reduced recall)

For the BonBon service robot operating at walking pace this gives adequate
latency.  If a GPU is available prefer YoloPersonDetector instead.

Requires: opencv-python (cv2) — standard ROS2 Humble dependency.
"""

from __future__ import annotations

import numpy as np

try:
    import cv2

    _HAS_CV2 = True
except ImportError:
    _HAS_CV2 = False

from .person_detector import Detection, PersonDetector


class HogPersonDetector(PersonDetector):
    """
    OpenCV HOG-based pedestrian detector.

    Parameters
    ----------
    win_stride       (int, int)   HOG window stride; smaller = slower + more recall
    padding          (int, int)   padding around window
    scale            float        pyramid scale factor; smaller = slower + finer
    hit_threshold    float        SVM hit threshold (negative = more detections)
    """

    def __init__(
        self,
        confidence_threshold: float = 0.3,
        hfov_deg: float = 60.0,
        win_stride: tuple = (8, 8),
        padding: tuple = (4, 4),
        scale: float = 1.05,
        hit_threshold: float = 0.0,
    ) -> None:
        if not _HAS_CV2:
            raise ImportError(
                "HogPersonDetector requires opencv-python. "
                "Install with: pip install opencv-python"
            )
        super().__init__(
            confidence_threshold=confidence_threshold,
            hfov_deg=hfov_deg,
        )
        self._win_stride = win_stride
        self._padding = padding
        self._scale = scale
        self._hit_threshold = hit_threshold

        self._hog = cv2.HOGDescriptor()
        self._hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())

    # ── Core implementation ───────────────────────────────────────────────────

    def _detect_impl(self, color_bgr: np.ndarray) -> list[Detection]:
        # HOG runs on grayscale; resize to multiples of 8
        h, w = color_bgr.shape[:2]
        proc_w = (w // 8) * 8
        proc_h = (h // 8) * 8
        if proc_w != w or proc_h != h:
            img = cv2.resize(color_bgr, (proc_w, proc_h))
        else:
            img = color_bgr

        rects, weights = self._hog.detectMultiScale(
            img,
            winStride=self._win_stride,
            padding=self._padding,
            scale=self._scale,
            hitThreshold=self._hit_threshold,
        )

        detections: list[Detection] = []
        scale_x = w / proc_w
        scale_y = h / proc_h

        for i, (rx, ry, rw, rh) in enumerate(rects):
            conf = float(weights[i]) if weights is not None and len(weights) > i else 0.5
            # HOG weights are raw SVM scores — map to ~[0,1] with sigmoid
            conf_norm = 1.0 / (1.0 + np.exp(-conf))
            if conf_norm < self.confidence_threshold:
                continue
            # Scale back to original image coords
            x = int(rx * scale_x)
            y = int(ry * scale_y)
            bw = int(rw * scale_x)
            bh = int(rh * scale_y)
            det = Detection(
                bbox=(x, y, bw, bh),
                confidence=float(conf_norm),
            )
            detections.append(det)

        # Apply NMS to remove overlapping detections
        detections = sorted(detections, key=lambda d: d.confidence, reverse=True)
        return self._nms(detections)
