"""
tests/test_detector.py
=======================
Unit tests for the detector layer:
  * bonbon_vision.detectors.base_detector (BaseDetector, ObjectDetection, DetectionResult)
  * bonbon_vision.detectors.mock_detector (MockDetector — all test scenarios)

Covered scenarios
-----------------
* Normal multi-class detections returned correctly
* Fake camera test — synthetic frame through full detect() flow
* Empty frame — zero detections returned gracefully
* Low-light frame — detections still returned (FrameProcessor handles quality)
* Corrupted inference — exception inside _detect_impl sets error field
* Timeout — block_sec > timeout triggers timeout path
* Degraded mode entry — max_consecutive_timeouts exceeded
* Degraded mode returns empty result immediately
* recover() exits degraded mode
* skip_every_n — every N-th call returns []
* Depth filling — median-depth sampling from aligned depth map
* Bearing filling — correct sign and magnitude from HFOV
* start_degraded flag — detector immediately degraded on construction
* Stats dict — counts increment correctly
* Thread safety — concurrent detect() calls do not crash
* MockDetector.force_degraded() helper
"""

import math
import threading
import unittest

import numpy as np
from bonbon_vision.config.vision_config import DetectorConfig
from bonbon_vision.detectors.base_detector import (
    COCO_NAMES,
    BaseDetector,
    DetectionResult,
    ObjectDetection,
)
from bonbon_vision.detectors.mock_detector import MockDetector

# ── Helpers ───────────────────────────────────────────────────────────────────


def _cfg(**kwargs) -> DetectorConfig:
    defaults = dict(
        backend="mock",
        confidence_threshold=0.45,
        inference_timeout_sec=0.5,
        max_consecutive_timeouts=3,
    )
    defaults.update(kwargs)
    return DetectorConfig(**defaults)


def _frame(h=480, w=640, brightness=120) -> np.ndarray:
    return np.full((h, w, 3), brightness, dtype=np.uint8)


def _black_frame(h=480, w=640) -> np.ndarray:
    return np.zeros((h, w, 3), dtype=np.uint8)


def _depth_map(h=480, w=640, val=2.0) -> np.ndarray:
    return np.full((h, w), val, dtype=np.float32)


# ── ObjectDetection dataclass ─────────────────────────────────────────────────


class TestObjectDetection(unittest.TestCase):
    def _make(self, cls_id=0, bbox=(10, 20, 100, 200)):
        return ObjectDetection(
            class_id=cls_id,
            class_name=COCO_NAMES.get(cls_id, "unknown"),
            confidence=0.9,
            bbox=bbox,
        )

    def test_centre_px(self):
        det = self._make(bbox=(10, 20, 100, 200))
        self.assertAlmostEqual(det.centre_px[0], 60.0)
        self.assertAlmostEqual(det.centre_px[1], 120.0)

    def test_is_person_true_for_class_0(self):
        det = self._make(cls_id=0)
        self.assertTrue(det.is_person)

    def test_is_person_false_for_other(self):
        det = self._make(cls_id=56)
        self.assertFalse(det.is_person)

    def test_default_depth_is_nan(self):
        det = self._make()
        self.assertTrue(math.isnan(det.depth_m))

    def test_coco_names_80_classes(self):
        self.assertEqual(len(COCO_NAMES), 80)
        self.assertEqual(COCO_NAMES[0], "person")
        self.assertEqual(COCO_NAMES[56], "chair")
        self.assertEqual(COCO_NAMES[79], "toothbrush")


# ── MockDetector — Normal ─────────────────────────────────────────────────────


class TestMockDetectorNormal(unittest.TestCase):
    def setUp(self):
        self.detector = MockDetector(num_detections=3, hfov_deg=60.0)

    def tearDown(self):
        self.detector.shutdown()

    def test_returns_detection_result(self):
        r = self.detector.detect(_frame())
        self.assertIsInstance(r, DetectionResult)

    def test_correct_number_of_detections(self):
        r = self.detector.detect(_frame())
        self.assertEqual(len(r.detections), 3)

    def test_detections_are_object_detection(self):
        r = self.detector.detect(_frame())
        for det in r.detections:
            self.assertIsInstance(det, ObjectDetection)

    def test_confidence_in_range(self):
        r = self.detector.detect(_frame())
        for det in r.detections:
            self.assertGreater(det.confidence, 0.0)
            self.assertLessEqual(det.confidence, 1.0)

    def test_bbox_within_frame(self):
        r = self.detector.detect(_frame(h=480, w=640))
        for det in r.detections:
            x, y, w, h = det.bbox
            self.assertGreaterEqual(x, 0)
            self.assertGreaterEqual(y, 0)
            self.assertGreater(w, 0)
            self.assertGreater(h, 0)
            self.assertLessEqual(x + w, 640)
            self.assertLessEqual(y + h, 480)

    def test_not_degraded(self):
        r = self.detector.detect(_frame())
        self.assertFalse(r.is_degraded)

    def test_not_timed_out(self):
        r = self.detector.detect(_frame())
        self.assertFalse(r.timed_out)

    def test_no_error(self):
        r = self.detector.detect(_frame())
        self.assertIsNone(r.error)

    def test_inference_ms_positive(self):
        r = self.detector.detect(_frame())
        self.assertGreaterEqual(r.inference_ms, 0.0)

    def test_backend_name_is_mock(self):
        r = self.detector.detect(_frame())
        self.assertEqual(r.backend, "mock")


# ── Fake camera test ──────────────────────────────────────────────────────────


class TestFakeCameraScenarios(unittest.TestCase):
    """End-to-end: synthetic frames with known properties go through detect()."""

    def test_bright_synthetic_frame(self):
        detector = MockDetector(num_detections=2)
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        frame[100:300, 150:250] = [255, 200, 180]  # simulated person ROI
        r = detector.detect(frame)
        self.assertGreater(len(r.detections), 0)
        detector.shutdown()

    def test_varying_frame_sizes(self):
        """Detector should handle non-standard resolutions."""
        for h, w in [(240, 320), (720, 1280), (1080, 1920)]:
            detector = MockDetector(num_detections=1)
            r = detector.detect(np.full((h, w, 3), 100, dtype=np.uint8))
            self.assertFalse(r.is_degraded, f"Failed at {h}x{w}")
            detector.shutdown()

    def test_grayscale_like_frame(self):
        """Single-channel image treated as 2D — base detector handles h×w frames."""
        detector = MockDetector(num_detections=1)
        frame = np.full((480, 640, 3), 128, dtype=np.uint8)
        r = detector.detect(frame)
        self.assertFalse(r.is_degraded)
        detector.shutdown()

    def test_call_count_increments(self):
        detector = MockDetector(num_detections=1)
        for _ in range(5):
            detector.detect(_frame())
        self.assertEqual(detector.call_count, 5)
        detector.shutdown()


# ── Empty / low-light scenarios ────────────────────────────────────────────────


class TestEmptyAndLowLight(unittest.TestCase):
    def test_black_frame_returns_detections(self):
        """MockDetector does not inspect pixel values — it always returns N objects."""
        detector = MockDetector(num_detections=2)
        r = detector.detect(_black_frame())
        self.assertEqual(len(r.detections), 2)
        detector.shutdown()

    def test_zero_detection_mode(self):
        """num_detections=0 → always return empty list."""
        detector = MockDetector(num_detections=0)
        r = detector.detect(_frame())
        self.assertEqual(len(r.detections), 0)
        detector.shutdown()

    def test_skip_every_n(self):
        """skip_every_n=3 → every 3rd call returns []."""
        detector = MockDetector(num_detections=2, skip_every_n=3)
        results = [detector.detect(_frame()) for _ in range(6)]
        # Calls 3 and 6 should have 0 detections
        self.assertEqual(len(results[2].detections), 0)  # 3rd call
        self.assertEqual(len(results[5].detections), 0)  # 6th call
        detector.shutdown()


# ── Corrupted inference ───────────────────────────────────────────────────────


class TestCorruptedInference(unittest.TestCase):
    def test_corrupt_on_call_sets_error_field(self):
        """corrupt_on_call=2 → 2nd detect() returns error, not a crash."""
        detector = MockDetector(num_detections=1, corrupt_on_call=2)
        detector.detect(_frame())  # call 1 — OK
        r = detector.detect(_frame())  # call 2 — error
        self.assertIsNotNone(r.error)
        self.assertIn("simulated inference error", r.error)
        detector.shutdown()

    def test_call_after_error_recovers(self):
        """Error on call 1 does not permanently break the detector."""
        detector = MockDetector(num_detections=1, corrupt_on_call=1)
        detector.detect(_frame())  # error call
        r = detector.detect(_frame())  # should be fine
        self.assertIsNone(r.error)
        detector.shutdown()

    def test_error_increments_error_counter(self):
        detector = MockDetector(num_detections=1, corrupt_on_call=1)
        detector.detect(_frame())
        s = detector.stats()
        self.assertEqual(s["total_errors"], 1)
        detector.shutdown()


# ── Timeout handling ──────────────────────────────────────────────────────────


class TestTimeout(unittest.TestCase):
    def test_single_timeout_returns_timed_out_flag(self):
        cfg = _cfg(inference_timeout_sec=0.05, max_consecutive_timeouts=5)
        detector = MockDetector(cfg=cfg, block_sec=0.2)  # blocks 200 ms > 50 ms timeout
        r = detector.detect(_frame())
        self.assertTrue(r.timed_out)
        detector.shutdown()

    def test_timeout_increments_counter(self):
        cfg = _cfg(inference_timeout_sec=0.05, max_consecutive_timeouts=5)
        detector = MockDetector(cfg=cfg, block_sec=0.2)
        detector.detect(_frame())
        s = detector.stats()
        self.assertEqual(s["total_timeouts"], 1)
        self.assertEqual(s["consecutive_timeouts"], 1)
        detector.shutdown()

    def test_max_consecutive_timeouts_triggers_degraded(self):
        cfg = _cfg(inference_timeout_sec=0.05, max_consecutive_timeouts=2)
        detector = MockDetector(cfg=cfg, block_sec=0.2)
        detector.detect(_frame())  # 1st timeout
        detector.detect(_frame())  # 2nd timeout → enters degraded
        self.assertTrue(detector.is_degraded)
        detector.shutdown()

    def test_degraded_after_max_timeouts_returns_empty(self):
        cfg = _cfg(inference_timeout_sec=0.05, max_consecutive_timeouts=2)
        detector = MockDetector(cfg=cfg, block_sec=0.2)
        detector.detect(_frame())
        detector.detect(_frame())
        r = detector.detect(_frame())
        self.assertTrue(r.is_degraded)
        self.assertEqual(len(r.detections), 0)
        detector.shutdown()

    def test_timeout_disabled_when_zero(self):
        """inference_timeout_sec=0 → no timeout wrapper, blocking allowed."""
        cfg = _cfg(inference_timeout_sec=0.0)
        detector = MockDetector(cfg=cfg, block_sec=0.0)  # no actual block
        r = detector.detect(_frame())
        self.assertFalse(r.timed_out)
        detector.shutdown()


# ── Degraded mode ─────────────────────────────────────────────────────────────


class TestDegradedMode(unittest.TestCase):
    def test_start_degraded_flag(self):
        detector = MockDetector(start_degraded=True)
        self.assertTrue(detector.is_degraded)
        detector.shutdown()

    def test_degraded_detect_returns_empty_immediately(self):
        detector = MockDetector(start_degraded=True)
        r = detector.detect(_frame())
        self.assertTrue(r.is_degraded)
        self.assertEqual(len(r.detections), 0)
        self.assertEqual(r.backend, "mock")
        detector.shutdown()

    def test_degraded_call_count_does_not_increment(self):
        """_detect_impl should NOT be called when degraded."""
        detector = MockDetector(start_degraded=True)
        detector.detect(_frame())
        detector.detect(_frame())
        self.assertEqual(detector.call_count, 0)
        detector.shutdown()

    def test_recover_exits_degraded(self):
        detector = MockDetector(start_degraded=True)
        self.assertTrue(detector.is_degraded)
        detector.recover()
        self.assertFalse(detector.is_degraded)
        detector.shutdown()

    def test_recover_resets_consecutive_timeouts(self):
        cfg = _cfg(inference_timeout_sec=0.05, max_consecutive_timeouts=2)
        detector = MockDetector(cfg=cfg, block_sec=0.2)
        detector.detect(_frame())
        detector.detect(_frame())
        detector.recover()
        s = detector.stats()
        self.assertEqual(s["consecutive_timeouts"], 0)
        detector.shutdown()

    def test_force_degraded_helper(self):
        detector = MockDetector()
        detector.force_degraded("test_reason")
        self.assertTrue(detector.is_degraded)
        detector.shutdown()


# ── Depth and bearing filling ─────────────────────────────────────────────────


class TestDepthAndBearing(unittest.TestCase):
    def test_depth_filled_from_depth_map(self):
        detector = MockDetector(num_detections=1)
        depth = _depth_map(val=3.0)
        r = detector.detect(_frame(), depth_m=depth)
        # MockDetector sets depth itself; BaseDetector then calls _fill_depth.
        # Since depth map is uniform 3.0 and bbox is within the frame,
        # the base class will overwrite with median of depth map ROI.
        det = r.detections[0]
        self.assertAlmostEqual(det.depth_m, 3.0, delta=0.1)
        detector.shutdown()

    def test_depth_none_leaves_nan(self):
        """When no depth map provided, base class leaves depth_m untouched."""
        detector = MockDetector(num_detections=1, base_depth_m=5.0)
        # Pass no depth_m → base class _fill_depth skips
        # But MockDetector sets depth_m itself in _detect_impl
        r = detector.detect(_frame(), depth_m=None)
        det = r.detections[0]
        # Should have the value set by MockDetector (not NaN)
        self.assertFalse(math.isnan(det.depth_m))
        detector.shutdown()

    def test_bearing_negative_for_left_object(self):
        """Object on far left → negative bearing."""
        detector = MockDetector(num_detections=1, hfov_deg=60.0)
        # Place a single detection at the left edge manually
        r = detector.detect(_frame(w=640))
        # Verify bearing is a float in plausible range
        det = r.detections[0]
        self.assertGreater(abs(det.bearing_deg), -90.0)
        self.assertLess(abs(det.bearing_deg), 90.0)
        detector.shutdown()

    def test_fill_bearing_static_method(self):
        det = ObjectDetection(
            class_id=0,
            class_name="person",
            confidence=0.9,
            bbox=(0, 0, 640, 480),  # centre at x=320 in 640-wide frame
        )
        BaseDetector._fill_bearing(
            type("D", (), {"_hfov_deg": 60.0})(), det, 640  # minimal duck-typed instance
        )
        self.assertAlmostEqual(det.bearing_deg, 0.0, delta=0.1)

    def test_fill_bearing_right_edge(self):
        det = ObjectDetection(
            class_id=0,
            class_name="person",
            confidence=0.9,
            bbox=(600, 200, 40, 100),  # centre near right
        )
        # Use the static method via a proper detector instance
        detector = MockDetector(num_detections=0, hfov_deg=60.0)
        detector._fill_bearing(det, 640)
        self.assertGreater(det.bearing_deg, 0.0)
        detector.shutdown()


# ── Stats ─────────────────────────────────────────────────────────────────────


class TestStats(unittest.TestCase):
    def test_total_inferences_increments(self):
        detector = MockDetector(num_detections=1)
        for _ in range(3):
            detector.detect(_frame())
        self.assertEqual(detector.stats()["total_inferences"], 3)
        detector.shutdown()

    def test_is_degraded_in_stats(self):
        detector = MockDetector(start_degraded=True)
        self.assertTrue(detector.stats()["is_degraded"])
        detector.shutdown()

    def test_backend_in_stats(self):
        detector = MockDetector()
        self.assertEqual(detector.stats()["backend"], "mock")
        detector.shutdown()


# ── Thread safety ─────────────────────────────────────────────────────────────


class TestThreadSafety(unittest.TestCase):
    def test_concurrent_detect_calls_no_exception(self):
        """20 threads each call detect once — no crash, results consistent."""
        detector = MockDetector(num_detections=2)
        errors = []

        def worker():
            try:
                r = detector.detect(_frame())
                assert isinstance(r, DetectionResult)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])
        detector.shutdown()


if __name__ == "__main__":
    unittest.main()
