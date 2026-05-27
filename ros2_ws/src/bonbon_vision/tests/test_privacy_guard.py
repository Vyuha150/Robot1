"""
tests/test_privacy_guard.py
============================
Unit tests for bonbon_vision.face.privacy_guard.PrivacyGuard.

Covered
-------
* anonymise() returns a copy — original is NOT modified
* Disabled privacy guard returns original array unchanged
* No faces list → frame returned as-is
* Gaussian blur applied to face ROI
* Pixelation applied to face ROI
* Out-of-bounds bbox clamped — no crash
* Zero-size bbox handled gracefully
* Multiple faces all anonymised
* Non-square face bbox
* Tiny frame (4×4 pixels)
* NumPy fallback path (_blur, _convolve2d) — when cv2 absent
"""

import sys
import types
import unittest

import numpy as np

# ── We want to test both the cv2 path and the NumPy fallback.
#    To test the fallback we temporarily stub _HAS_CV2 = False.
# ─────────────────────────────────────────────────────────────

# Ensure module is importable even without cv2
_real_cv2_available = False
try:
    import cv2 as _cv2

    _real_cv2_available = True
except ImportError:
    pass

if not _real_cv2_available:
    _stub = types.ModuleType("cv2")
    _stub.GaussianBlur = lambda src, k, s: src
    _stub.resize = lambda src, dsize, interpolation=1: src
    _stub.INTER_LINEAR = 1
    _stub.INTER_NEAREST = 0
    sys.modules.setdefault("cv2", _stub)

from bonbon_vision.config.vision_config import PrivacyConfig  # noqa
from bonbon_vision.face.privacy_guard import PrivacyGuard  # noqa

# ── Helpers ───────────────────────────────────────────────────────────────────


def _cfg(**overrides) -> PrivacyConfig:
    defaults = dict(
        enabled=True,
        blur_faces=True,
        blur_kernel_size=7,  # small odd kernel — fast test
        pixelate_faces=False,
        pixelate_block_size=4,
        suppress_identity=True,
        disable_annotated_publish=False,
    )
    defaults.update(overrides)
    return PrivacyConfig(**defaults)


def _frame(h=120, w=160, brightness=100) -> np.ndarray:
    frame = np.full((h, w, 3), brightness, dtype=np.uint8)
    # Add some variation so blur is detectable
    frame[20:80, 30:120] = 200
    return frame


def _face_bbox(x=40, y=20, w=60, h=70):
    return (x, y, w, h)


# ── Original not modified ─────────────────────────────────────────────────────


class TestOriginalNotModified(unittest.TestCase):
    def test_original_unchanged_after_anonymise(self):
        guard = PrivacyGuard(_cfg())
        original = _frame()
        before = original.copy()
        guard.anonymise(original, [_face_bbox()])
        np.testing.assert_array_equal(original, before)

    def test_returns_different_array(self):
        guard = PrivacyGuard(_cfg())
        frame = _frame()
        result = guard.anonymise(frame, [_face_bbox()])
        self.assertIsNot(result, frame)


# ── Disabled guard ────────────────────────────────────────────────────────────


class TestDisabledGuard(unittest.TestCase):
    def test_disabled_returns_original(self):
        guard = PrivacyGuard(_cfg(enabled=False))
        frame = _frame()
        result = guard.anonymise(frame, [_face_bbox()])
        # When disabled, we return bgr directly (no copy guarantee)
        np.testing.assert_array_equal(result, frame)

    def test_disabled_no_modification(self):
        guard = PrivacyGuard(_cfg(enabled=False))
        frame = _frame()
        before = frame.copy()
        guard.anonymise(frame, [_face_bbox()])
        np.testing.assert_array_equal(frame, before)


# ── No faces ─────────────────────────────────────────────────────────────────


class TestNoFaces(unittest.TestCase):
    def test_no_faces_returns_bgr(self):
        guard = PrivacyGuard(_cfg())
        frame = _frame()
        result = guard.anonymise(frame, [])
        np.testing.assert_array_equal(result, frame)

    def test_none_equivalent_empty_list(self):
        guard = PrivacyGuard(_cfg())
        frame = _frame()
        result = guard.anonymise(frame, [])
        self.assertEqual(result.shape, frame.shape)


# ── Blur applied ─────────────────────────────────────────────────────────────


class TestBlurApplied(unittest.TestCase):
    @unittest.skipUnless(_real_cv2_available, "requires real cv2 for blur test")
    def test_blur_changes_roi(self):
        """The face ROI in the result must differ from the original ROI."""
        guard = PrivacyGuard(_cfg(blur_kernel_size=21))
        frame = _frame()
        x, y, w, h = _face_bbox()
        # Make the ROI a solid distinct colour
        frame[y : y + h, x : x + w] = [220, 50, 50]
        result = guard.anonymise(frame, [_face_bbox()])
        roi_before = frame[y : y + h, x : x + w].astype(float)
        roi_after = result[y : y + h, x : x + w].astype(float)
        self.assertGreater(np.mean(np.abs(roi_before - roi_after)), 1.0)

    def test_blur_outside_roi_unchanged(self):
        """Pixels outside the face bbox should not change."""
        guard = PrivacyGuard(_cfg(blur_kernel_size=7))
        frame = _frame()
        x, y, w, h = _face_bbox(x=40, y=20, w=30, h=30)
        result = guard.anonymise(frame, [(x, y, w, h)])
        # Check area well outside the bbox
        corner_before = frame[:10, :10].copy()
        corner_after = result[:10, :10]
        np.testing.assert_array_equal(corner_before, corner_after)


# ── Pixelation ────────────────────────────────────────────────────────────────


class TestPixelation(unittest.TestCase):
    @unittest.skipUnless(_real_cv2_available, "requires real cv2 for pixelate test")
    def test_pixelate_changes_roi(self):
        guard = PrivacyGuard(_cfg(pixelate_faces=True, pixelate_block_size=4))
        frame = np.random.randint(0, 255, (120, 160, 3), dtype=np.uint8)
        x, y, w, h = 20, 15, 60, 70
        result = guard.anonymise(frame, [(x, y, w, h)])
        roi_before = frame[y : y + h, x : x + w].astype(float)
        roi_after = result[y : y + h, x : x + w].astype(float)
        self.assertGreater(np.sum(np.abs(roi_before - roi_after)), 0)

    def test_pixelate_returns_correct_shape(self):
        guard = PrivacyGuard(_cfg(pixelate_faces=True, pixelate_block_size=4))
        frame = _frame()
        result = guard.anonymise(frame, [_face_bbox()])
        self.assertEqual(result.shape, frame.shape)


# ── Out-of-bounds bboxes ──────────────────────────────────────────────────────


class TestOutOfBounds(unittest.TestCase):
    def test_bbox_extending_outside_frame_clamped(self):
        guard = PrivacyGuard(_cfg())
        frame = _frame(h=120, w=160)
        # Bbox that goes beyond the frame edges
        result = guard.anonymise(frame, [(100, 90, 200, 200)])
        self.assertEqual(result.shape, (120, 160, 3))

    def test_negative_coords_clamped(self):
        guard = PrivacyGuard(_cfg())
        frame = _frame()
        result = guard.anonymise(frame, [(-20, -10, 80, 80)])
        self.assertEqual(result.shape, frame.shape)

    def test_zero_size_bbox_no_crash(self):
        guard = PrivacyGuard(_cfg())
        frame = _frame()
        result = guard.anonymise(frame, [(50, 50, 0, 0)])
        self.assertEqual(result.shape, frame.shape)

    def test_fully_outside_frame_no_crash(self):
        guard = PrivacyGuard(_cfg())
        frame = _frame(h=120, w=160)
        result = guard.anonymise(frame, [(200, 200, 50, 50)])  # fully outside
        self.assertEqual(result.shape, frame.shape)


# ── Multiple faces ────────────────────────────────────────────────────────────


class TestMultipleFaces(unittest.TestCase):
    def test_three_faces_all_processed(self):
        guard = PrivacyGuard(_cfg())
        frame = _frame()
        faces = [(5, 5, 20, 25), (60, 10, 30, 35), (110, 50, 25, 30)]
        result = guard.anonymise(frame, faces)
        self.assertEqual(result.shape, frame.shape)

    def test_result_is_single_array(self):
        guard = PrivacyGuard(_cfg())
        frame = _frame()
        result = guard.anonymise(frame, [(10, 10, 20, 20), (50, 50, 20, 20)])
        self.assertIsInstance(result, np.ndarray)


# ── Tiny frame ────────────────────────────────────────────────────────────────


class TestTinyFrame(unittest.TestCase):
    def test_4x4_frame_no_crash(self):
        guard = PrivacyGuard(_cfg(blur_kernel_size=3))
        frame = np.full((4, 4, 3), 128, dtype=np.uint8)
        result = guard.anonymise(frame, [(0, 0, 4, 4)])
        self.assertEqual(result.shape, (4, 4, 3))


# ── NumPy fallback ────────────────────────────────────────────────────────────


class TestNumpyFallback(unittest.TestCase):
    def test_blur_numpy_fallback(self):
        """Test _blur when _HAS_CV2 is False."""
        import bonbon_vision.face.privacy_guard as _mod

        original_has_cv2 = _mod._HAS_CV2
        try:
            _mod._HAS_CV2 = False
            guard = PrivacyGuard(_cfg(blur_kernel_size=3))
            roi = np.full((20, 20, 3), 200, dtype=np.uint8)
            result = guard._blur(roi)
            self.assertEqual(result.shape, roi.shape)
            self.assertEqual(result.dtype, np.uint8)
        finally:
            _mod._HAS_CV2 = original_has_cv2

    def test_pixelate_numpy_fallback(self):
        """Test _pixelate when _HAS_CV2 is False."""
        import bonbon_vision.face.privacy_guard as _mod

        original_has_cv2 = _mod._HAS_CV2
        try:
            _mod._HAS_CV2 = False
            guard = PrivacyGuard(_cfg(pixelate_faces=True, pixelate_block_size=4))
            roi = np.arange(20 * 20 * 3, dtype=np.uint8).reshape(20, 20, 3)
            result = guard._pixelate(roi)
            self.assertEqual(result.shape, roi.shape)
        finally:
            _mod._HAS_CV2 = original_has_cv2


if __name__ == "__main__":
    unittest.main()
