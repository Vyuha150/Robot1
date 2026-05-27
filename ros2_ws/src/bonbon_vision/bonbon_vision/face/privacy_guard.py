"""
bonbon_vision.face.privacy_guard
==================================
Privacy-safe image anonymisation.

Applies face anonymisation (Gaussian blur or pixelation) to detected face
ROIs in the annotated image before it is published on the wire.

IMPORTANT: The original BGR frame used for inference is NEVER modified.
Only the *copy* destined for the /bonbon/vision/annotated_image topic is
processed here.  Downstream code that reads detection results (bounding
boxes, depth, track IDs) is never affected by privacy guards.

Blurring strategy
-----------------
  Gaussian blur (default): Fast, visually clear anonymisation.
  Pixelation (optional):   Stronger — downscale ROI to block_size px,
                            then upscale back.  Completely removes all
                            facial features without artefacts.
"""

from __future__ import annotations

import logging

import numpy as np

try:
    import cv2

    _HAS_CV2 = True
except ImportError:
    _HAS_CV2 = False

from ..config.vision_config import PrivacyConfig

logger = logging.getLogger(__name__)

BBox = tuple[int, int, int, int]  # (x, y, w, h)


class PrivacyGuard:
    """
    Applies anonymisation to a BGR image given a list of face bounding boxes.
    """

    def __init__(self, cfg: PrivacyConfig) -> None:
        self._cfg = cfg

    # ── Public API ────────────────────────────────────────────────────────────

    def anonymise(
        self,
        bgr: np.ndarray,
        faces: list[BBox],
    ) -> np.ndarray:
        """
        Return a copy of `bgr` with all `faces` anonymised.

        Args:
            bgr:   H×W×3 uint8 BGR image.
            faces: list of (x, y, w, h) bounding boxes.

        Returns:
            Anonymised copy of bgr (original is not modified).
        """
        if not self._cfg.enabled or not faces:
            return bgr

        out = bgr.copy()
        for bbox in faces:
            out = self._anonymise_roi(out, bbox)
        return out

    # ── Implementation ────────────────────────────────────────────────────────

    def _anonymise_roi(self, bgr: np.ndarray, bbox: BBox) -> np.ndarray:
        x, y, w, h = bbox
        ih, iw = bgr.shape[:2]

        # Clamp to image bounds
        x = max(0, x)
        y = max(0, y)
        w = min(iw - x, w)
        h = min(ih - y, h)
        if w <= 0 or h <= 0:
            return bgr

        roi = bgr[y : y + h, x : x + w]

        if self._cfg.pixelate_faces:
            processed = self._pixelate(roi)
        else:
            processed = self._blur(roi)

        bgr[y : y + h, x : x + w] = processed
        return bgr

    def _blur(self, roi: np.ndarray) -> np.ndarray:
        k = self._cfg.blur_kernel_size
        # Ensure k is odd and ≥ 3
        k = max(3, k | 1)
        if _HAS_CV2:
            return cv2.GaussianBlur(roi, (k, k), 0)
        # NumPy fallback: uniform average box blur
        kernel = np.ones((k, k)) / (k * k)
        result = np.zeros_like(roi, dtype=np.float32)
        for c in range(roi.shape[2]):
            result[:, :, c] = self._convolve2d(roi[:, :, c].astype(np.float32), kernel)
        return np.clip(result, 0, 255).astype(np.uint8)

    def _pixelate(self, roi: np.ndarray) -> np.ndarray:
        b = max(2, self._cfg.pixelate_block_size)
        h, w = roi.shape[:2]
        small_h = max(1, h // b)
        small_w = max(1, w // b)
        if _HAS_CV2:
            small = cv2.resize(roi, (small_w, small_h), interpolation=cv2.INTER_LINEAR)
            pixelated = cv2.resize(small, (w, h), interpolation=cv2.INTER_NEAREST)
        else:
            row_idx = (np.arange(small_h) * h / small_h).astype(int)
            col_idx = (np.arange(small_w) * w / small_w).astype(int)
            small = roi[row_idx[:, None], col_idx[None, :]]
            row_up = (np.arange(h) * small_h / h).astype(int)
            col_up = (np.arange(w) * small_w / w).astype(int)
            pixelated = small[row_up[:, None], col_up[None, :]]
        return pixelated

    @staticmethod
    def _convolve2d(arr: np.ndarray, kernel: np.ndarray) -> np.ndarray:
        """Minimal 2-D separable box convolution (NumPy fallback only)."""
        kh, kw = kernel.shape
        ph, pw = kh // 2, kw // 2
        padded = np.pad(arr, ((ph, ph), (pw, pw)), mode="edge")
        out = np.zeros_like(arr)
        for i in range(arr.shape[0]):
            for j in range(arr.shape[1]):
                out[i, j] = np.sum(padded[i : i + kh, j : j + kw] * kernel)
        return out
