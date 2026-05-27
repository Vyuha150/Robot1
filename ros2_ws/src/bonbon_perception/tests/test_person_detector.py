"""
test_person_detector.py
========================
Tests for PersonDetector (abstract), Detection, and MockPersonDetector.
All tests are pure Python — no ROS2, no hardware required.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from bonbon_perception.detectors.mock_person_detector import MockPersonDetector
from bonbon_perception.detectors.person_detector import Detection, PersonDetector

# ── Helpers ───────────────────────────────────────────────────────────────────


def _blank_frame(h: int = 480, w: int = 640) -> np.ndarray:
    return np.zeros((h, w, 3), dtype=np.uint8)


def _depth_frame(h: int = 480, w: int = 640, value: float = 2.0) -> np.ndarray:
    return np.full((h, w), value, dtype=np.float32)


# ═══════════════════════════════════════════════════════════════════════════════
# Detection dataclass
# ═══════════════════════════════════════════════════════════════════════════════


class TestDetection:
    def test_centre_px_correct(self):
        d = Detection(bbox=(10, 20, 80, 180))
        cx, cy = d.centre_px
        assert cx == pytest.approx(50.0)
        assert cy == pytest.approx(110.0)

    def test_area_px2(self):
        d = Detection(bbox=(0, 0, 50, 100))
        assert d.area_px2 == 5000

    def test_distance_m_alias(self):
        d = Detection(bbox=(0, 0, 10, 10), depth_m=1.5)
        assert d.distance_m == pytest.approx(1.5)

    def test_compute_bearing_centre_zero(self):
        d = Detection(bbox=(260, 100, 120, 200))  # centre at 320 of 640
        d.compute_bearing(image_width=640, hfov_deg=60.0)
        assert d.bearing_deg == pytest.approx(0.0, abs=1.0)

    def test_compute_bearing_right_positive(self):
        """Person on right half → positive bearing."""
        d = Detection(bbox=(400, 100, 80, 160))  # cx ≈ 440 of 640
        d.compute_bearing(image_width=640, hfov_deg=60.0)
        assert d.bearing_deg > 0

    def test_compute_bearing_left_negative(self):
        """Person on left half → negative bearing."""
        d = Detection(bbox=(50, 100, 80, 160))  # cx ≈ 90 of 640
        d.compute_bearing(image_width=640, hfov_deg=60.0)
        assert d.bearing_deg < 0

    def test_compute_bearing_max_magnitude(self):
        """At image edge bearing should equal ±hfov/2."""
        d_left = Detection(bbox=(0, 0, 1, 1))  # cx ≈ 0.5 → far left
        d_right = Detection(bbox=(639, 0, 1, 1))  # cx ≈ 639.5 → far right
        d_left.compute_bearing(640, 60.0)
        d_right.compute_bearing(640, 60.0)
        assert d_left.bearing_deg == pytest.approx(-30.0, abs=1.0)
        assert d_right.bearing_deg == pytest.approx(+30.0, abs=1.0)

    def test_iou_full_overlap(self):
        a = Detection(bbox=(0, 0, 100, 100))
        b = Detection(bbox=(0, 0, 100, 100))
        assert Detection.iou(a, b) == pytest.approx(1.0)

    def test_iou_no_overlap(self):
        a = Detection(bbox=(0, 0, 50, 50))
        b = Detection(bbox=(100, 100, 50, 50))
        assert Detection.iou(a, b) == pytest.approx(0.0)

    def test_iou_partial_overlap(self):
        a = Detection(bbox=(0, 0, 100, 100))
        b = Detection(bbox=(50, 50, 100, 100))
        iou = Detection.iou(a, b)
        assert 0.0 < iou < 1.0

    def test_iou_symmetric(self):
        a = Detection(bbox=(10, 10, 60, 80))
        b = Detection(bbox=(40, 30, 50, 90))
        assert Detection.iou(a, b) == pytest.approx(Detection.iou(b, a))


# ═══════════════════════════════════════════════════════════════════════════════
# PersonDetector._sample_depth (static)
# ═══════════════════════════════════════════════════════════════════════════════


class TestDepthSampling:
    def test_uniform_depth_returns_value(self):
        depth = _depth_frame(value=2.5)
        det = Detection(bbox=(100, 100, 200, 200))
        result = PersonDetector._sample_depth(det, depth)
        assert result == pytest.approx(2.5, abs=0.01)

    def test_out_of_range_depth_nan(self):
        """Depths < 0.1 or > 10 are masked out."""
        depth = _depth_frame(value=0.0)  # all invalid
        det = Detection(bbox=(100, 100, 200, 200))
        result = PersonDetector._sample_depth(det, depth)
        assert math.isnan(result)

    def test_nan_depth_returns_nan(self):
        depth = np.full((480, 640), float("nan"), dtype=np.float32)
        det = Detection(bbox=(100, 100, 200, 200))
        result = PersonDetector._sample_depth(det, depth)
        assert math.isnan(result)

    def test_bbox_at_image_edge_clamped(self):
        """Bbox at edge of image should not crash."""
        depth = _depth_frame(value=3.0)
        det = Detection(bbox=(600, 450, 100, 100))  # extends outside 640×480
        result = PersonDetector._sample_depth(det, depth)
        # Just verify it doesn't raise and returns a finite value or nan
        assert math.isfinite(result) or math.isnan(result)


# ═══════════════════════════════════════════════════════════════════════════════
# MockPersonDetector
# ═══════════════════════════════════════════════════════════════════════════════


class TestMockPersonDetectorNormal:
    def test_zero_persons(self):
        det = MockPersonDetector(num_persons=0)
        dets = det.detect(_blank_frame())
        assert len(dets) == 0

    def test_one_person(self):
        det = MockPersonDetector(num_persons=1)
        dets = det.detect(_blank_frame())
        assert len(dets) == 1

    def test_three_persons(self):
        det = MockPersonDetector(num_persons=3)
        dets = det.detect(_blank_frame())
        assert len(dets) == 3

    def test_eight_persons(self):
        det = MockPersonDetector(num_persons=8)
        dets = det.detect(_blank_frame())
        assert len(dets) == 8

    def test_detections_sorted_by_confidence(self):
        det = MockPersonDetector(num_persons=4)
        dets = det.detect(_blank_frame())
        for i in range(len(dets) - 1):
            assert dets[i].confidence >= dets[i + 1].confidence

    def test_detection_confidence_range(self):
        det = MockPersonDetector(num_persons=3, confidence=0.9)
        dets = det.detect(_blank_frame())
        for d in dets:
            assert 0.0 < d.confidence <= 1.0

    def test_detection_has_bbox(self):
        det = MockPersonDetector(num_persons=1)
        dets = det.detect(_blank_frame())
        x, y, w, h = dets[0].bbox
        assert w > 0 and h > 0

    def test_detection_bbox_within_image(self):
        det = MockPersonDetector(num_persons=1, image_width=640, image_height=480)
        dets = det.detect(_blank_frame(480, 640))
        for d in dets:
            x, y, w, h = d.bbox
            assert x >= 0 and y >= 0
            assert x + w <= 640
            assert y + h <= 480

    def test_bearing_within_fov(self):
        det = MockPersonDetector(num_persons=3, hfov_deg=60.0)
        dets = det.detect(_blank_frame())
        for d in dets:
            assert -30.0 <= d.bearing_deg <= 30.0

    def test_depth_filled_from_depth_image(self):
        """When a real depth frame is passed, depth_m should be sampled."""
        det = MockPersonDetector(num_persons=1)
        depth = _depth_frame(value=3.0)
        frame = _blank_frame()
        dets = det.detect(frame, depth)
        # MockPersonDetector sets depth_m directly; it equals base_distance_m
        # But after PersonDetector.detect() _sample_depth overwrites it.
        # With the whole image at 3.0 m, the sampled value should be ≈3.0
        assert math.isfinite(dets[0].depth_m)

    def test_call_count_increments(self):
        det = MockPersonDetector()
        det.detect(_blank_frame())
        det.detect(_blank_frame())
        assert det.call_count == 2

    def test_label_is_person(self):
        det = MockPersonDetector(num_persons=1)
        dets = det.detect(_blank_frame())
        assert dets[0].label == "person"


class TestMockPersonDetectorFaults:
    def test_skip_every_n(self):
        """Every N-th call returns an empty list."""
        det = MockPersonDetector(num_persons=2, skip_every_n=3)
        results = [det.detect(_blank_frame()) for _ in range(6)]
        # Calls 3 and 6 return empty
        assert len(results[2]) == 0
        assert len(results[5]) == 0
        # Other calls return persons
        assert len(results[0]) == 2

    def test_fail_on_call(self):
        det = MockPersonDetector(fail_on_call=2)
        det.detect(_blank_frame())  # call 1 — OK
        with pytest.raises(RuntimeError, match="simulated failure"):
            det.detect(_blank_frame())  # call 2 — raises

    def test_inject_once(self):
        det = MockPersonDetector(num_persons=0)
        det.inject_once(cx_px=320, cy_px=240, distance_m=1.5, bearing_deg=5.0)
        dets = det.detect(_blank_frame())
        assert len(dets) == 1
        assert dets[0].depth_m == pytest.approx(1.5)
        # Second call: injection consumed
        dets2 = det.detect(_blank_frame())
        assert len(dets2) == 0

    def test_set_num_persons(self):
        det = MockPersonDetector(num_persons=1)
        det.set_num_persons(3)
        dets = det.detect(_blank_frame())
        assert len(dets) == 3


# ═══════════════════════════════════════════════════════════════════════════════
# PersonDetector NMS
# ═══════════════════════════════════════════════════════════════════════════════


class _ConcreteDetector(PersonDetector):
    """Minimal concrete subclass for testing NMS."""

    def __init__(self, detections_to_return):
        super().__init__(nms_iou_threshold=0.5)
        self._pool = detections_to_return

    def _detect_impl(self, color_bgr):
        return list(self._pool)


class TestNMS:
    def test_non_overlapping_kept(self):
        pool = [
            Detection(bbox=(0, 0, 50, 100), confidence=0.9),
            Detection(bbox=(200, 0, 50, 100), confidence=0.8),
        ]
        det = _ConcreteDetector(pool)
        kept = det._nms(sorted(pool, key=lambda d: d.confidence, reverse=True))
        assert len(kept) == 2

    def test_highly_overlapping_suppressed(self):
        pool = [
            Detection(bbox=(0, 0, 100, 200), confidence=0.9),
            Detection(bbox=(5, 5, 100, 200), confidence=0.7),  # IoU > 0.5
        ]
        det = _ConcreteDetector(pool)
        kept = det._nms(sorted(pool, key=lambda d: d.confidence, reverse=True))
        assert len(kept) == 1
        assert kept[0].confidence == pytest.approx(0.9)

    def test_empty_list(self):
        det = _ConcreteDetector([])
        kept = det._nms([])
        assert len(kept) == 0
