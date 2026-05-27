"""
bonbon_vision.preprocessing.frame_processor
=============================================
OpenCV-based image preprocessing pipeline.

Processing stages (each is individually togglable via PreprocessConfig)
-----------------------------------------------------------------------
1. **Quality gate** — reject empty, all-black, or obviously corrupted frames.
2. **Resize** — scale to (resize_width × resize_height) before detection.
3. **Low-light detection** — compare mean brightness against threshold.
4. **CLAHE** — apply Contrast Limited Adaptive Histogram Equalisation to the
   Y channel of YCrCb when low-light is detected (or always if force_clahe).
5. **Gaussian denoise** — optional mild blur to reduce sensor noise.

All methods are pure Python + NumPy/OpenCV — no ROS2 dependency.

Structured log format used throughout:
    logger.debug("stage=%s latency_ms=%.1f key=value …", …)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from enum import IntEnum

import numpy as np

try:
    import cv2

    _HAS_CV2 = True
except ImportError:
    _HAS_CV2 = False

from ..config.vision_config import PreprocessConfig

logger = logging.getLogger(__name__)


# ── Frame quality classification ──────────────────────────────────────────────


class FrameQuality(IntEnum):
    OK = 0  # suitable for inference
    LOW_LIGHT = 1  # dark, CLAHE applied
    EMPTY = 2  # all-black / no data
    CORRUPTED = 3  # NaN / inf pixels detected
    WRONG_SHAPE = 4  # unexpected H×W×C


@dataclass
class ProcessedFrame:
    """Output of FrameProcessor.process()."""

    bgr: np.ndarray  # H×W×3 uint8, ready for detector
    depth_m: np.ndarray | None  # H×W float32 metres, or None
    quality: FrameQuality
    original_shape: tuple[int, int]  # (H, W) before resize
    mean_brightness: float  # 0–255
    is_low_light: bool
    clahe_applied: bool
    denoise_applied: bool
    preprocess_ms: float  # wall-clock time for this frame
    depth_valid_frac: float  # fraction of depth pixels that are finite >0

    @property
    def is_usable(self) -> bool:
        return self.quality in (FrameQuality.OK, FrameQuality.LOW_LIGHT)


# ── Processor ─────────────────────────────────────────────────────────────────


class FrameProcessor:
    """
    Stateless (except for the CLAHE object) OpenCV preprocessing pipeline.

    Thread-safe: CLAHE object is created per-instance but only called from
    one thread (the detection timer thread in VisionNode).
    """

    def __init__(self, cfg: PreprocessConfig) -> None:
        self._cfg = cfg
        self._clahe = None
        if _HAS_CV2 and cfg.enable_clahe:
            self._clahe = cv2.createCLAHE(
                clipLimit=cfg.clahe_clip_limit,
                tileGridSize=(cfg.clahe_tile_grid_size, cfg.clahe_tile_grid_size),
            )
        elif cfg.enable_clahe and not _HAS_CV2:
            logger.warning("stage=init msg='CLAHE requested but opencv-python not installed'")

    # ── Public API ────────────────────────────────────────────────────────────

    def process(
        self,
        bgr: np.ndarray,
        depth_m: np.ndarray | None = None,
    ) -> ProcessedFrame:
        """
        Run the full preprocessing pipeline on a raw camera frame.

        Args:
            bgr:     H×W×3 uint8 BGR image from the HAL camera node.
            depth_m: H×W float32 depth in metres (aligned to BGR).  May be None.

        Returns:
            ProcessedFrame with the processed bgr and metadata.
        """
        t0 = time.monotonic()

        # Stage 0: shape / dtype sanity
        quality, err = self._check_shape(bgr)
        if quality != FrameQuality.OK:
            logger.debug("stage=quality_gate quality=%s reason=%s", quality.name, err)
            return self._bad_frame(bgr, depth_m, quality, t0)

        original_h, original_w = bgr.shape[:2]

        # Stage 1: corruption check (NaN / Inf in float frames passed as bgr)
        if bgr.dtype in (np.float32, np.float64):
            if not np.all(np.isfinite(bgr)):
                logger.debug("stage=quality_gate quality=CORRUPTED reason=nan_in_float_bgr")
                return self._bad_frame(bgr, depth_m, FrameQuality.CORRUPTED, t0)
            # Normalise to uint8 for downstream
            bgr = np.clip(bgr * 255, 0, 255).astype(np.uint8)

        # Stage 2: empty frame (camera off or all-black)
        mean_brightness = float(np.mean(bgr))
        if mean_brightness < self._cfg.min_mean_brightness:
            logger.debug(
                "stage=quality_gate quality=EMPTY brightness=%.1f threshold=%.1f",
                mean_brightness,
                self._cfg.min_mean_brightness,
            )
            return self._bad_frame(bgr, depth_m, FrameQuality.EMPTY, t0)

        # Stage 3: resize
        target_w = self._cfg.resize_width
        target_h = self._cfg.resize_height
        if bgr.shape[1] != target_w or bgr.shape[0] != target_h:
            if _HAS_CV2:
                bgr = cv2.resize(bgr, (target_w, target_h), interpolation=cv2.INTER_LINEAR)
            else:
                bgr = self._numpy_resize(bgr, target_h, target_w)

        # Stage 4: low-light detection + CLAHE
        is_low_light = mean_brightness < self._cfg.brightness_threshold
        clahe_applied = False
        if self._cfg.enable_clahe and is_low_light and _HAS_CV2:
            bgr, clahe_applied = self._apply_clahe(bgr)

        # Stage 5: denoise
        denoise_applied = False
        if self._cfg.enable_denoise and _HAS_CV2:
            k = self._cfg.denoise_kernel_size
            bgr = cv2.GaussianBlur(bgr, (k, k), 0)
            denoise_applied = True

        # Stage 6: depth quality
        depth_valid_frac = self._depth_valid_fraction(depth_m)
        if depth_m is not None and depth_valid_frac < (1.0 - self._cfg.max_nan_fraction):
            logger.debug(
                "stage=depth_check valid_frac=%.2f depth_set_to_none=True",
                depth_valid_frac,
            )
            depth_m = None  # too many invalid pixels — discard depth

        quality = FrameQuality.LOW_LIGHT if is_low_light else FrameQuality.OK
        elapsed_ms = (time.monotonic() - t0) * 1000.0

        logger.debug(
            "stage=preprocess quality=%s brightness=%.1f low_light=%s "
            "clahe=%s denoise=%s depth_valid=%.2f latency_ms=%.1f",
            quality.name,
            mean_brightness,
            is_low_light,
            clahe_applied,
            denoise_applied,
            depth_valid_frac,
            elapsed_ms,
        )

        return ProcessedFrame(
            bgr=bgr,
            depth_m=depth_m,
            quality=quality,
            original_shape=(original_h, original_w),
            mean_brightness=mean_brightness,
            is_low_light=is_low_light,
            clahe_applied=clahe_applied,
            denoise_applied=denoise_applied,
            preprocess_ms=elapsed_ms,
            depth_valid_frac=depth_valid_frac,
        )

    # ── CLAHE ─────────────────────────────────────────────────────────────────

    def _apply_clahe(self, bgr: np.ndarray) -> tuple[np.ndarray, bool]:
        """
        Apply CLAHE to the luminance (Y) channel of YCrCb.
        Returns (enhanced_bgr, was_applied).
        """
        try:
            ycrcb = cv2.cvtColor(bgr, cv2.COLOR_BGR2YCrCb)
            y, cr, cb = cv2.split(ycrcb)
            y_eq = self._clahe.apply(y)
            ycrcb_eq = cv2.merge([y_eq, cr, cb])
            enhanced = cv2.cvtColor(ycrcb_eq, cv2.COLOR_YCrCb2BGR)
            return enhanced, True
        except Exception as exc:
            logger.warning("stage=clahe error=%r", str(exc))
            return bgr, False

    # ── Quality gate helpers ──────────────────────────────────────────────────

    @staticmethod
    def _check_shape(bgr: np.ndarray) -> tuple[FrameQuality, str]:
        if bgr is None or bgr.size == 0:
            return FrameQuality.EMPTY, "empty_array"
        if bgr.ndim not in (2, 3):
            return FrameQuality.WRONG_SHAPE, f"ndim={bgr.ndim}"
        if bgr.ndim == 3 and bgr.shape[2] not in (1, 3, 4):
            return FrameQuality.WRONG_SHAPE, f"channels={bgr.shape[2]}"
        return FrameQuality.OK, ""

    @staticmethod
    def _depth_valid_fraction(depth_m: np.ndarray | None) -> float:
        if depth_m is None:
            return 0.0
        total = depth_m.size
        if total == 0:
            return 0.0
        valid = np.sum(np.isfinite(depth_m) & (depth_m > 0.05) & (depth_m < 15.0))
        return float(valid) / total

    @staticmethod
    def _numpy_resize(arr: np.ndarray, target_h: int, target_w: int) -> np.ndarray:
        """Pure-NumPy nearest-neighbour resize (fallback when cv2 absent)."""
        src_h, src_w = arr.shape[:2]
        row_idx = (np.arange(target_h) * src_h / target_h).astype(int)
        col_idx = (np.arange(target_w) * src_w / target_w).astype(int)
        return arr[row_idx[:, None], col_idx[None, :]]

    def _bad_frame(
        self,
        bgr: np.ndarray,
        depth_m: np.ndarray | None,
        quality: FrameQuality,
        t0: float,
    ) -> ProcessedFrame:
        blank = np.zeros((self._cfg.resize_height, self._cfg.resize_width, 3), dtype=np.uint8)
        return ProcessedFrame(
            bgr=blank,
            depth_m=None,
            quality=quality,
            original_shape=(bgr.shape[0], bgr.shape[1]) if bgr.ndim >= 2 else (0, 0),
            mean_brightness=0.0,
            is_low_light=False,
            clahe_applied=False,
            denoise_applied=False,
            preprocess_ms=(time.monotonic() - t0) * 1000.0,
            depth_valid_frac=0.0,
        )

    # ── Config hot-reload ─────────────────────────────────────────────────────

    def update_config(self, cfg: PreprocessConfig) -> None:
        """Replace config at runtime (e.g., toggled from ROS2 param event)."""
        self._cfg = cfg
        if _HAS_CV2 and cfg.enable_clahe:
            self._clahe = cv2.createCLAHE(
                clipLimit=cfg.clahe_clip_limit,
                tileGridSize=(cfg.clahe_tile_grid_size, cfg.clahe_tile_grid_size),
            )
        else:
            self._clahe = None
        logger.info(
            "stage=config_reload clahe=%s denoise=%s brightness_threshold=%.1f",
            cfg.enable_clahe,
            cfg.enable_denoise,
            cfg.brightness_threshold,
        )
