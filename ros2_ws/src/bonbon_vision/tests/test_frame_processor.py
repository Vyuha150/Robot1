"""
tests/test_frame_processor.py
==============================
Unit tests for bonbon_vision.preprocessing.frame_processor.

Covers
------
* OK frame path — normal bright frame passes through
* Low-light detection — mean < brightness_threshold triggers LOW_LIGHT
* CLAHE application — confirms clahe_applied flag is set in low-light
* Empty frame — all-zero frame rejected with EMPTY quality
* Corrupted frame — NaN float frame rejected with CORRUPTED quality
* Wrong shape — 1-D / bad channel count rejected with WRONG_SHAPE
* Resize — output shape matches configured target
* Depth validity fraction — all valid / partial / all-NaN / None
* Depth discard — depth is set to None when valid fraction < threshold
* Config hot-reload — update_config() picks up new settings
* is_usable property — OK and LOW_LIGHT are usable; others are not
"""

import math
import sys
import types
import unittest

import numpy as np

# ---------------------------------------------------------------------------
# Provide a minimal cv2 stub so the module loads without opencv installed.
# The tests that explicitly need CLAHE are skipped when cv2 is truly absent;
# all other tests run with the NumPy code path.
# ---------------------------------------------------------------------------
_real_cv2_available = False
try:
    import cv2 as _cv2

    _real_cv2_available = True
except ImportError:
    pass

# Build a lightweight stub only when real cv2 is absent
if not _real_cv2_available:
    _cv2_stub = types.ModuleType("cv2")
    _cv2_stub.INTER_LINEAR = 1
    _cv2_stub.INTER_NEAREST = 0
    _cv2_stub.COLOR_BGR2YCrCb = 36
    _cv2_stub.COLOR_YCrCb2BGR = 38

    def _resize(src, dsize, interpolation=1):
        h, w = dsize[1], dsize[0]
        src_h, src_w = src.shape[:2]
        ri = (np.arange(h) * src_h / h).astype(int)
        ci = (np.arange(w) * src_w / w).astype(int)
        return src[ri[:, None], ci[None, :]]

    _cv2_stub.resize = _resize
    _cv2_stub.GaussianBlur = lambda src, ksize, sig: src  # identity

    class _CLAHE:
        def apply(self, ch):
            return ch

    _cv2_stub.createCLAHE = lambda clipLimit=2.0, tileGridSize=(8, 8): _CLAHE()

    def _cvt(src, code):
        return src  # identity — enough for non-CLAHE tests

    _cv2_stub.cvtColor = _cvt
    _cv2_stub.split = lambda src: (src[:, :, 0], src[:, :, 1], src[:, :, 2])
    _cv2_stub.merge = lambda chs: np.stack(chs, axis=2)
    sys.modules.setdefault("cv2", _cv2_stub)

# Import under test AFTER cv2 stub is in place
from bonbon_vision.config.vision_config import PreprocessConfig  # noqa: E402
from bonbon_vision.preprocessing.frame_processor import (  # noqa: E402
    FrameProcessor,
    FrameQuality,
    ProcessedFrame,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────


def _cfg(**overrides) -> PreprocessConfig:
    """Return a PreprocessConfig with test-friendly defaults."""
    defaults = dict(
        resize_width=64,
        resize_height=48,
        enable_clahe=True,
        clahe_clip_limit=2.0,
        clahe_tile_grid_size=8,
        enable_denoise=False,
        denoise_kernel_size=3,
        brightness_threshold=50.0,
        min_mean_brightness=2.0,
        max_nan_fraction=0.50,
    )
    defaults.update(overrides)
    return PreprocessConfig(**defaults)


def _bright_frame(h=120, w=160, brightness=120) -> np.ndarray:
    """Solid-colour frame well above threshold."""
    return np.full((h, w, 3), brightness, dtype=np.uint8)


def _dark_frame(h=120, w=160, brightness=20) -> np.ndarray:
    """Frame below brightness_threshold but above min_mean_brightness."""
    return np.full((h, w, 3), brightness, dtype=np.uint8)


def _black_frame(h=120, w=160) -> np.ndarray:
    """All-zero frame: mean brightness = 0 → EMPTY."""
    return np.zeros((h, w, 3), dtype=np.uint8)


def _nan_float_frame(h=120, w=160) -> np.ndarray:
    """Float32 frame containing NaN → CORRUPTED."""
    arr = np.ones((h, w, 3), dtype=np.float32)
    arr[0, 0, 0] = math.nan
    return arr


def _valid_depth(h=120, w=160, val=1.5) -> np.ndarray:
    return np.full((h, w), val, dtype=np.float32)


def _nan_depth(h=120, w=160) -> np.ndarray:
    return np.full((h, w), math.nan, dtype=np.float32)


# ── Test Classes ──────────────────────────────────────────────────────────────


class TestOKFrame(unittest.TestCase):
    def setUp(self):
        self.proc = FrameProcessor(_cfg())

    def test_quality_is_ok(self):
        pf = self.proc.process(_bright_frame())
        self.assertEqual(pf.quality, FrameQuality.OK)

    def test_is_usable(self):
        pf = self.proc.process(_bright_frame())
        self.assertTrue(pf.is_usable)

    def test_output_is_uint8(self):
        pf = self.proc.process(_bright_frame())
        self.assertEqual(pf.bgr.dtype, np.uint8)

    def test_output_shape_matches_config(self):
        cfg = _cfg(resize_width=64, resize_height=48)
        proc = FrameProcessor(cfg)
        pf = proc.process(_bright_frame(h=120, w=160))
        self.assertEqual(pf.bgr.shape[:2], (48, 64))

    def test_clahe_not_applied_bright(self):
        pf = self.proc.process(_bright_frame(brightness=100))
        self.assertFalse(pf.clahe_applied)

    def test_preprocess_ms_positive(self):
        pf = self.proc.process(_bright_frame())
        self.assertGreater(pf.preprocess_ms, 0.0)

    def test_original_shape_preserved(self):
        pf = self.proc.process(_bright_frame(h=120, w=160))
        self.assertEqual(pf.original_shape, (120, 160))


class TestLowLight(unittest.TestCase):
    """Frames with mean brightness below brightness_threshold."""

    def test_quality_is_low_light(self):
        proc = FrameProcessor(_cfg(brightness_threshold=50.0))
        pf = proc.process(_dark_frame(brightness=20))
        self.assertEqual(pf.quality, FrameQuality.LOW_LIGHT)

    def test_low_light_is_usable(self):
        proc = FrameProcessor(_cfg(brightness_threshold=50.0))
        pf = proc.process(_dark_frame(brightness=20))
        self.assertTrue(pf.is_usable)

    def test_is_low_light_flag(self):
        proc = FrameProcessor(_cfg(brightness_threshold=50.0))
        pf = proc.process(_dark_frame(brightness=20))
        self.assertTrue(pf.is_low_light)

    def test_mean_brightness_recorded(self):
        proc = FrameProcessor(_cfg(brightness_threshold=50.0))
        pf = proc.process(_dark_frame(brightness=20))
        # Mean of 20 in all channels ≈ 20
        self.assertAlmostEqual(pf.mean_brightness, 20.0, delta=1.0)

    @unittest.skipUnless(_real_cv2_available, "requires real cv2 for CLAHE")
    def test_clahe_applied_when_low_light(self):
        proc = FrameProcessor(_cfg(brightness_threshold=50.0, enable_clahe=True))
        pf = proc.process(_dark_frame(brightness=20))
        self.assertTrue(pf.clahe_applied)

    def test_clahe_not_applied_when_disabled(self):
        proc = FrameProcessor(_cfg(brightness_threshold=50.0, enable_clahe=False))
        pf = proc.process(_dark_frame(brightness=20))
        self.assertFalse(pf.clahe_applied)


class TestEmptyFrame(unittest.TestCase):
    """All-black frames (camera off, lens cap, etc.)."""

    def setUp(self):
        self.proc = FrameProcessor(_cfg(min_mean_brightness=2.0))

    def test_quality_is_empty(self):
        pf = self.proc.process(_black_frame())
        self.assertEqual(pf.quality, FrameQuality.EMPTY)

    def test_empty_not_usable(self):
        pf = self.proc.process(_black_frame())
        self.assertFalse(pf.is_usable)

    def test_empty_returns_blank_bgr(self):
        pf = self.proc.process(_black_frame())
        self.assertEqual(pf.bgr.dtype, np.uint8)
        self.assertEqual(pf.bgr.shape[2], 3)

    def test_empty_depth_is_none(self):
        pf = self.proc.process(_black_frame(), _valid_depth())
        self.assertIsNone(pf.depth_m)

    def test_near_zero_brightness_empty(self):
        """1-brightness frame is just above 0 but below 2.0 threshold."""
        frame = np.full((120, 160, 3), 1, dtype=np.uint8)
        pf = self.proc.process(frame)
        self.assertEqual(pf.quality, FrameQuality.EMPTY)

    def test_exactly_at_min_brightness_not_empty(self):
        """Frame whose mean is exactly equal to min_mean_brightness should NOT be EMPTY."""
        cfg = _cfg(min_mean_brightness=5.0)
        proc = FrameProcessor(cfg)
        # mean = 5 → not empty (strictly less than threshold is empty)
        frame = np.full((120, 160, 3), 5, dtype=np.uint8)
        pf = proc.process(frame)
        self.assertNotEqual(pf.quality, FrameQuality.EMPTY)

    def test_empty_none_input_handled(self):
        """Passing a zero-size array is handled gracefully."""
        frame = np.zeros((0, 0, 3), dtype=np.uint8)
        pf = self.proc.process(frame)
        self.assertFalse(pf.is_usable)


class TestCorruptedFrame(unittest.TestCase):
    """Frames containing NaN / Inf values."""

    def setUp(self):
        self.proc = FrameProcessor(_cfg())

    def test_nan_frame_quality_corrupted(self):
        pf = self.proc.process(_nan_float_frame())
        self.assertEqual(pf.quality, FrameQuality.CORRUPTED)

    def test_nan_frame_not_usable(self):
        pf = self.proc.process(_nan_float_frame())
        self.assertFalse(pf.is_usable)

    def test_inf_frame_corrupted(self):
        arr = np.ones((60, 80, 3), dtype=np.float32) * np.inf
        pf = self.proc.process(arr)
        self.assertEqual(pf.quality, FrameQuality.CORRUPTED)

    def test_mixed_nan_inf_corrupted(self):
        arr = np.ones((60, 80, 3), dtype=np.float32)
        arr[5, 5, :] = math.nan
        arr[6, 6, :] = np.inf
        pf = self.proc.process(arr)
        self.assertEqual(pf.quality, FrameQuality.CORRUPTED)

    def test_valid_float_frame_normalised(self):
        """A clean float32 frame in [0,1] should be normalised to uint8 OK."""
        arr = np.full((120, 160, 3), 0.5, dtype=np.float32)
        pf = self.proc.process(arr)
        self.assertEqual(pf.bgr.dtype, np.uint8)
        self.assertIn(pf.quality, (FrameQuality.OK, FrameQuality.LOW_LIGHT))


class TestWrongShape(unittest.TestCase):
    def setUp(self):
        self.proc = FrameProcessor(_cfg())

    def test_1d_array_wrong_shape(self):
        pf = self.proc.process(np.zeros(100, dtype=np.uint8))
        self.assertEqual(pf.quality, FrameQuality.WRONG_SHAPE)

    def test_4d_array_wrong_shape(self):
        arr = np.zeros((4, 60, 80, 3), dtype=np.uint8)
        pf = self.proc.process(arr)
        self.assertEqual(pf.quality, FrameQuality.WRONG_SHAPE)

    def test_wrong_channels_wrong_shape(self):
        arr = np.zeros((60, 80, 2), dtype=np.uint8)
        pf = self.proc.process(arr)
        self.assertEqual(pf.quality, FrameQuality.WRONG_SHAPE)

    def test_wrong_shape_not_usable(self):
        pf = self.proc.process(np.zeros(100, dtype=np.uint8))
        self.assertFalse(pf.is_usable)


class TestDepthHandling(unittest.TestCase):
    def setUp(self):
        self.proc = FrameProcessor(_cfg(max_nan_fraction=0.50))

    def test_valid_depth_preserved(self):
        pf = self.proc.process(_bright_frame(), _valid_depth())
        self.assertIsNotNone(pf.depth_m)
        self.assertGreater(pf.depth_valid_frac, 0.9)

    def test_all_nan_depth_discarded(self):
        pf = self.proc.process(_bright_frame(), _nan_depth())
        # Valid fraction is 0 → depth discarded
        self.assertIsNone(pf.depth_m)
        self.assertAlmostEqual(pf.depth_valid_frac, 0.0)

    def test_none_depth_produces_zero_frac(self):
        pf = self.proc.process(_bright_frame(), None)
        self.assertIsNone(pf.depth_m)
        self.assertAlmostEqual(pf.depth_valid_frac, 0.0)

    def test_partial_nan_depth_above_threshold(self):
        """60% valid → kept (max_nan_fraction=0.50 means require >50% valid)."""
        depth = np.full((120, 160), 1.5, dtype=np.float32)
        depth[:48, :] = math.nan  # 40% NaN → 60% valid
        pf = self.proc.process(_bright_frame(), depth)
        self.assertIsNotNone(pf.depth_m)

    def test_out_of_range_depth_not_valid(self):
        """Depth > 15 m is marked invalid."""
        depth = np.full((120, 160), 20.0, dtype=np.float32)
        pf = self.proc.process(_bright_frame(), depth)
        self.assertAlmostEqual(pf.depth_valid_frac, 0.0)

    def test_negative_depth_not_valid(self):
        depth = np.full((120, 160), -1.0, dtype=np.float32)
        pf = self.proc.process(_bright_frame(), depth)
        self.assertAlmostEqual(pf.depth_valid_frac, 0.0)


class TestResize(unittest.TestCase):
    def test_frame_smaller_than_target_upscaled(self):
        cfg = _cfg(resize_width=128, resize_height=96)
        proc = FrameProcessor(cfg)
        pf = proc.process(_bright_frame(h=48, w=64))
        self.assertEqual(pf.bgr.shape[:2], (96, 128))

    def test_frame_already_target_size_unchanged(self):
        cfg = _cfg(resize_width=64, resize_height=48)
        proc = FrameProcessor(cfg)
        pf = proc.process(_bright_frame(h=48, w=64))
        self.assertEqual(pf.bgr.shape[:2], (48, 64))

    def test_original_shape_reflects_input(self):
        cfg = _cfg(resize_width=64, resize_height=48)
        proc = FrameProcessor(cfg)
        pf = proc.process(_bright_frame(h=480, w=640))
        self.assertEqual(pf.original_shape, (480, 640))


class TestConfigHotReload(unittest.TestCase):
    def test_brightness_threshold_updated(self):
        proc = FrameProcessor(_cfg(brightness_threshold=50.0))
        frame = _dark_frame(brightness=30)
        pf_before = proc.process(frame)
        self.assertEqual(pf_before.quality, FrameQuality.LOW_LIGHT)

        # Raise threshold so 30-brightness frame is now "bright enough"
        new_cfg = _cfg(brightness_threshold=10.0)
        proc.update_config(new_cfg)
        pf_after = proc.process(frame)
        self.assertEqual(pf_after.quality, FrameQuality.OK)

    def test_clahe_toggle_respected(self):
        proc = FrameProcessor(_cfg(enable_clahe=True, brightness_threshold=50.0))
        proc.update_config(_cfg(enable_clahe=False, brightness_threshold=50.0))
        self.assertIsNone(proc._clahe)


class TestIsUsableProperty(unittest.TestCase):
    def test_ok_is_usable(self):
        pf = ProcessedFrame(
            bgr=np.zeros((10, 10, 3), dtype=np.uint8),
            depth_m=None,
            quality=FrameQuality.OK,
            original_shape=(10, 10),
            mean_brightness=100.0,
            is_low_light=False,
            clahe_applied=False,
            denoise_applied=False,
            preprocess_ms=0.5,
            depth_valid_frac=0.0,
        )
        self.assertTrue(pf.is_usable)

    def test_low_light_is_usable(self):
        pf = ProcessedFrame(
            bgr=np.zeros((10, 10, 3), dtype=np.uint8),
            depth_m=None,
            quality=FrameQuality.LOW_LIGHT,
            original_shape=(10, 10),
            mean_brightness=20.0,
            is_low_light=True,
            clahe_applied=True,
            denoise_applied=False,
            preprocess_ms=0.5,
            depth_valid_frac=0.0,
        )
        self.assertTrue(pf.is_usable)

    def test_empty_not_usable(self):
        pf = ProcessedFrame(
            bgr=np.zeros((10, 10, 3), dtype=np.uint8),
            depth_m=None,
            quality=FrameQuality.EMPTY,
            original_shape=(10, 10),
            mean_brightness=0.0,
            is_low_light=False,
            clahe_applied=False,
            denoise_applied=False,
            preprocess_ms=0.1,
            depth_valid_frac=0.0,
        )
        self.assertFalse(pf.is_usable)

    def test_corrupted_not_usable(self):
        pf = ProcessedFrame(
            bgr=np.zeros((10, 10, 3), dtype=np.uint8),
            depth_m=None,
            quality=FrameQuality.CORRUPTED,
            original_shape=(10, 10),
            mean_brightness=0.0,
            is_low_light=False,
            clahe_applied=False,
            denoise_applied=False,
            preprocess_ms=0.1,
            depth_valid_frac=0.0,
        )
        self.assertFalse(pf.is_usable)


if __name__ == "__main__":
    unittest.main()
