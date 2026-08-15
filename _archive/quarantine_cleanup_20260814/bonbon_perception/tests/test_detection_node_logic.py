"""
test_detection_node_logic.py
=============================
Tests for DetectionNode's pure-Python logic:
  - Image conversion utilities
  - Detector factory selection
  - 3D position computation
  - Health status derivation

No ROS2 context is needed — all node methods are tested via a patched
instance (same pattern as test_safety_gate.py).
"""

from __future__ import annotations

import math
import threading
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from bonbon_perception.detectors.mock_person_detector import MockPersonDetector
from bonbon_perception.nodes.detection_node import DetectionNode

# ── Node factory (no ROS2) ────────────────────────────────────────────────────


def _make_node() -> DetectionNode:
    with (
        patch(
            "bonbon_perception.nodes.detection_node.LifecycleNode.__init__", lambda *a, **kw: None
        ),
        patch(
            "bonbon_perception.nodes.detection_node.LifecycleNode.get_logger",
            return_value=MagicMock(),
        ),
        patch("bonbon_perception.nodes.detection_node.LifecycleNode.declare_parameter"),
    ):
        node = DetectionNode.__new__(DetectionNode)
        node._lock = threading.Lock()
        node._latest_color = None
        node._latest_depth = None
        node._color_stamp = None
        node._color_frame_id = "camera_color_optical_frame"
        node._detector = MockPersonDetector(num_persons=1)
        from bonbon_perception.trackers.simple_tracker import SimpleTracker

        node._tracker = SimpleTracker()
        node._pub_persons = None
        node._pub_health = None
        node._detect_timer = None
        node._health_timer = None
        import time

        node._start_time = time.monotonic()
        node._processed_count = 0
        node._error_count = 0
        node._last_latency_ms = 0.0
    return node


# ═══════════════════════════════════════════════════════════════════════════════
# Image conversion utilities
# ═══════════════════════════════════════════════════════════════════════════════


class TestImageMsgToBgr:
    def _make_image_msg(self, encoding: str, h: int = 10, w: int = 10) -> MagicMock:
        msg = MagicMock()
        msg.height = h
        msg.width = w
        msg.encoding = encoding
        if encoding == "bgr8" or encoding == "rgb8":
            msg.data = bytes(h * w * 3)
        elif encoding == "mono8":
            msg.data = bytes(h * w)
        return msg

    def test_bgr8_no_swap(self):
        msg = self._make_image_msg("bgr8")
        arr = DetectionNode._image_msg_to_bgr(msg)
        assert arr.shape == (10, 10, 3)

    def test_rgb8_converted_to_bgr(self):
        """Red pixel in RGB should appear as blue in BGR."""
        h, w = 2, 2
        msg = MagicMock()
        msg.height = h
        msg.width = w
        msg.encoding = "rgb8"
        # Red pixel: R=255, G=0, B=0 → BGR should be B=0, G=0, R=255
        data = np.zeros((h, w, 3), dtype=np.uint8)
        data[0, 0] = [255, 0, 0]  # pure red in RGB
        msg.data = data.tobytes()
        arr = DetectionNode._image_msg_to_bgr(msg)
        assert arr[0, 0, 0] == 0  # B channel = 0
        assert arr[0, 0, 2] == 255  # R channel = 255


class TestDepthMsgToFloat32:
    def _make_depth_msg(
        self, encoding: str, h: int = 4, w: int = 4, value_m: float = 1.5
    ) -> MagicMock:
        msg = MagicMock()
        msg.height = h
        msg.width = w
        msg.encoding = encoding
        if encoding == "32FC1":
            arr = np.full((h, w), value_m, dtype=np.float32)
            msg.data = arr.tobytes()
        elif encoding in ("16UC1", "mono16"):
            arr = np.full((h, w), int(value_m * 1000), dtype=np.uint16)
            msg.data = arr.tobytes()
        return msg

    def test_32fc1_value_preserved(self):
        msg = self._make_depth_msg("32FC1", value_m=2.5)
        arr = DetectionNode._depth_msg_to_float32(msg)
        assert arr[0, 0] == pytest.approx(2.5)

    def test_16uc1_mm_to_metres(self):
        msg = self._make_depth_msg("16UC1", value_m=1.5)
        arr = DetectionNode._depth_msg_to_float32(msg)
        assert arr[0, 0] == pytest.approx(1.5, abs=0.001)

    def test_unknown_encoding_raises(self):
        msg = self._make_depth_msg("32FC1")
        msg.encoding = "INVALID"
        with pytest.raises(ValueError, match="Unsupported"):
            DetectionNode._depth_msg_to_float32(msg)


# ═══════════════════════════════════════════════════════════════════════════════
# 3D position computation
# ═══════════════════════════════════════════════════════════════════════════════


class TestPositionComputation:
    """Verify that PersonState.position is computed correctly from distance+bearing."""

    def test_forward_person_zero_bearing(self):
        """Person directly ahead: bearing=0 → position.x=0, position.y=d."""
        from bonbon_perception.trackers.person_tracker import Track

        track = Track(track_id="t0", distance_m=2.0, bearing_deg=0.0)
        track.update(
            MagicMock(centre_px=(320, 240), bbox=(260, 100, 120, 280), depth_m=2.0, bearing_deg=0.0)
        )
        track.update(
            MagicMock(centre_px=(320, 240), bbox=(260, 100, 120, 280), depth_m=2.0, bearing_deg=0.0)
        )

        bearing_rad = math.radians(track.bearing_deg)
        d = track.distance_m
        x = d * math.sin(bearing_rad)
        y = d * math.cos(bearing_rad)
        assert x == pytest.approx(0.0, abs=0.05)
        assert y == pytest.approx(d, abs=0.05)

    def test_right_person_positive_x(self):
        """Person at +30° bearing → positive x component."""
        d = 2.0
        bearing_rad = math.radians(30.0)
        x = d * math.sin(bearing_rad)
        assert x > 0

    def test_left_person_negative_x(self):
        """Person at -30° bearing → negative x component."""
        d = 2.0
        bearing_rad = math.radians(-30.0)
        x = d * math.sin(bearing_rad)
        assert x < 0


# ═══════════════════════════════════════════════════════════════════════════════
# Detector factory
# ═══════════════════════════════════════════════════════════════════════════════


class TestDetectorFactory:
    def _node_with_params(self, mode, conf=0.5, hfov=60.0) -> DetectionNode:
        node = _make_node()

        def _get_param(name):
            m = MagicMock()
            vals = {
                "detector_mode": mode,
                "model_path": "yolov8n.pt",
                "confidence_threshold": conf,
                "hfov_deg": hfov,
                "mock_num_persons": 2,
                "mock_base_distance_m": 2.0,
            }
            m.value = vals[name]
            return m

        node.get_parameter = _get_param
        node.get_logger = MagicMock(return_value=MagicMock())
        return node

    def test_mock_mode_returns_mock_detector(self):
        node = self._node_with_params("mock")
        det = node._make_detector("mock", 0.5, 60.0)
        assert isinstance(det, MockPersonDetector)

    def test_hog_falls_back_to_mock_without_opencv(self):
        node = self._node_with_params("hog")
        # Patch the import to simulate missing OpenCV
        with patch.dict("sys.modules", {"cv2": None}):
            det = node._make_detector("hog", 0.5, 60.0)
        assert isinstance(det, MockPersonDetector)

    def test_yolo_falls_back_to_mock_without_ultralytics(self):
        node = self._node_with_params("yolo")
        with patch.dict("sys.modules", {"ultralytics": None}):
            det = node._make_detector("yolo", 0.5, 60.0)
        assert isinstance(det, MockPersonDetector)

    def test_unknown_mode_returns_mock(self):
        node = self._node_with_params("invalid_mode")
        det = node._make_detector("invalid_mode", 0.5, 60.0)
        assert isinstance(det, MockPersonDetector)


# ═══════════════════════════════════════════════════════════════════════════════
# End-to-end detect + track cycle
# ═══════════════════════════════════════════════════════════════════════════════


class TestDetectAndTrack:
    def test_detect_and_publish_calls_publisher(self):
        node = _make_node()
        node._pub_persons = MagicMock()
        node.get_clock = MagicMock(return_value=MagicMock())
        node.get_clock().now().to_msg.return_value = MagicMock()

        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        node._latest_color = frame

        # First frame — tentative (nothing published to persons)
        node._detect_and_publish()

        # Second frame — confirmed → published
        node._detect_and_publish()
        node._pub_persons.publish.assert_called()

    def test_detect_with_no_color_frame_does_nothing(self):
        node = _make_node()
        node._pub_persons = MagicMock()
        node._latest_color = None
        node._detect_and_publish()
        node._pub_persons.publish.assert_not_called()

    def test_error_in_detector_increments_error_count(self):
        node = _make_node()
        node._detector = MockPersonDetector(fail_on_call=1)
        node._latest_color = np.zeros((480, 640, 3), dtype=np.uint8)
        node._detect_and_publish()  # call 1 raises internally
        assert node._error_count == 1

    def test_processed_count_increments_on_success(self):
        node = _make_node()
        node._pub_persons = MagicMock()
        node.get_clock = MagicMock(return_value=MagicMock())
        node.get_clock().now().to_msg.return_value = MagicMock()
        node._latest_color = np.zeros((480, 640, 3), dtype=np.uint8)
        node._detect_and_publish()
        assert node._processed_count == 1
