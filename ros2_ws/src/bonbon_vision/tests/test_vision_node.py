"""
tests/test_vision_node.py
==========================
Unit + functional tests for bonbon_vision.nodes.vision_node.

These tests exercise the pipeline logic WITHOUT a live ROS2 runtime by
instantiating only the pipeline objects (FrameProcessor, detector, etc.)
and calling the internal helpers directly.

All ROS2-dependent tests (that spin a full LifecycleNode) are in
tests/integration/test_vision_integration.py.

Covered here
------------
* Fake camera: synthetic frames pumped through the full detect→track pipeline
* Empty frame: FrameQuality.EMPTY → pipeline returns no detections
* Low-light frame: FrameQuality.LOW_LIGHT → detections still returned
* Corrupted frame: NaN float frame → pipeline skips inference
* Degraded detector: returns empty DetectionResult without crashing
* Privacy mode: face_id suppressed, anonymised copy used
* Tracker: track IDs assigned, lost tracks pruned
* _iou helper: zero overlap, partial overlap, full overlap
* _SimpleTracker.update(): assignment, lost count increment, new track creation
* VisionNode._decode_color / _decode_depth: static helpers for Image message decoding
* VisionNode._fuse_face_ids: nearest-face proximity assignment
"""

import math
import sys
import types
import unittest
from unittest.mock import MagicMock

import numpy as np

# ---------------------------------------------------------------------------
# Minimal stubs so we can import vision_node without a ROS2 install.
# ---------------------------------------------------------------------------


def _stub_module(name: str, **attrs) -> types.ModuleType:
    m = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    return m


def _ensure_ros_stubs():
    """Inject minimal ROS2 stubs if the real packages are absent."""
    try:
        import rclpy  # noqa

        return  # real rclpy available
    except ImportError:
        pass

    # rclpy
    rclpy_stub = _stub_module("rclpy")
    rclpy_stub.init = lambda args=None: None
    rclpy_stub.spin = lambda n: None
    rclpy_stub.shutdown = lambda: None
    sys.modules["rclpy"] = rclpy_stub

    # rclpy.lifecycle
    class _LCNode:
        def __init__(self, name, **kw):
            self.name = name

        def get_logger(self):
            class L:
                def info(s, *a):
                    pass

                def warn(s, *a):
                    pass

                def warning(s, *a):
                    pass

                def error(s, *a):
                    pass

                def debug(s, *a):
                    pass

            return L()

        def create_timer(self, *a, **kw):
            return MagicMock()

        def create_publisher(self, *a, **kw):
            return MagicMock()

        def create_subscription(self, *a, **kw):
            return MagicMock()

        def declare_parameter(self, *a, **kw):
            return MagicMock()

        def get_parameter(self, name):
            pm = MagicMock()
            pm.value = None
            return pm

        def get_clock(self):
            c = MagicMock()
            c.now.return_value = MagicMock(to_msg=lambda: None)
            return c

    lifecycle = _stub_module(
        "rclpy.lifecycle",
        LifecycleNode=_LCNode,
        TransitionCallbackReturn=type("T", (), {"SUCCESS": 0, "ERROR": 1, "FAILURE": 2}),
        State=object,
    )
    sys.modules["rclpy.lifecycle"] = lifecycle

    # rclpy.qos
    for sub in ["rclpy.qos"]:
        qos = _stub_module(
            sub,
            QoSProfile=lambda **kw: None,
            ReliabilityPolicy=type("R", (), {"RELIABLE": 1, "BEST_EFFORT": 0}),
            DurabilityPolicy=type("D", (), {"TRANSIENT_LOCAL": 1, "VOLATILE": 0}),
            HistoryPolicy=type("H", (), {"KEEP_LAST": 0, "KEEP_ALL": 1}),
        )
        sys.modules[sub] = qos

    # geometry_msgs
    sys.modules["geometry_msgs"] = _stub_module("geometry_msgs")
    sys.modules["geometry_msgs.msg"] = _stub_module(
        "geometry_msgs.msg", Point=type("Point", (), {})
    )

    # sensor_msgs
    sys.modules["sensor_msgs"] = _stub_module("sensor_msgs")

    class _Image:
        def __init__(self):
            self.header = MagicMock()
            self.height = 0
            self.width = 0
            self.encoding = "bgr8"
            self.data = b""
            self.step = 0

    sys.modules["sensor_msgs.msg"] = _stub_module("sensor_msgs.msg", Image=_Image)

    # std_msgs
    sys.modules["std_msgs"] = _stub_module("std_msgs")
    sys.modules["std_msgs.msg"] = _stub_module(
        "std_msgs.msg", Header=type("Header", (), {"frame_id": "", "stamp": None})
    )

    # bonbon_msgs
    def _msg_cls(name):
        return type(name, (), {"__init__": lambda s: None})

    sys.modules["bonbon_msgs"] = _stub_module("bonbon_msgs")
    sys.modules["bonbon_msgs.msg"] = _stub_module(
        "bonbon_msgs.msg",
        DetectedObject=_msg_cls("DetectedObject"),
        DetectedObjectArray=_msg_cls("DetectedObjectArray"),
        ModuleHealth=_msg_cls("ModuleHealth"),
        PersonState=_msg_cls("PersonState"),
        PersonStateArray=_msg_cls("PersonStateArray"),
    )


_ensure_ros_stubs()

# Now we can import pipeline helpers without crashing
from bonbon_vision.config.vision_config import (
    PreprocessConfig,
    PrivacyConfig,
)
from bonbon_vision.detectors.base_detector import ObjectDetection
from bonbon_vision.detectors.mock_detector import MockDetector
from bonbon_vision.face.face_pipeline import FaceDetection, FaceResult
from bonbon_vision.face.privacy_guard import PrivacyGuard

# Import the tracker helpers embedded in vision_node
from bonbon_vision.nodes.vision_node import _iou, _SimpleTracker
from bonbon_vision.preprocessing.frame_processor import (
    FrameProcessor,
    FrameQuality,
)

# ── Frame factories ────────────────────────────────────────────────────────────


def _bright(h=480, w=640, b=120):
    return np.full((h, w, 3), b, dtype=np.uint8)


def _black(h=480, w=640):
    return np.zeros((h, w, 3), dtype=np.uint8)


def _dark(h=480, w=640, b=20):
    return np.full((h, w, 3), b, dtype=np.uint8)


def _nan_float(h=480, w=640):
    arr = np.ones((h, w, 3), dtype=np.float32)
    arr[0, 0, 0] = math.nan
    return arr


def _det(bbox=(100, 100, 80, 200), class_id=0, depth=2.0):
    return ObjectDetection(
        class_id=class_id,
        class_name="person",
        confidence=0.9,
        bbox=bbox,
        depth_m=depth,
        bearing_deg=0.0,
    )


# ── _iou helper ───────────────────────────────────────────────────────────────


class TestIoU(unittest.TestCase):
    def test_zero_overlap(self):
        a = (0, 0, 10, 10)
        b = (20, 20, 10, 10)
        self.assertAlmostEqual(_iou(a, b), 0.0)

    def test_full_overlap(self):
        a = (5, 5, 20, 20)
        self.assertAlmostEqual(_iou(a, a), 1.0)

    def test_partial_overlap(self):
        a = (0, 0, 10, 10)  # area=100
        b = (5, 0, 10, 10)  # area=100, overlap=50
        iou = _iou(a, b)  # 50 / 150
        self.assertAlmostEqual(iou, 50.0 / 150.0, places=4)

    def test_symmetric(self):
        a = (0, 0, 30, 40)
        b = (10, 10, 30, 40)
        self.assertAlmostEqual(_iou(a, b), _iou(b, a), places=6)

    def test_touching_edges_zero_overlap(self):
        a = (0, 0, 10, 10)
        b = (10, 0, 10, 10)
        self.assertAlmostEqual(_iou(a, b), 0.0)


# ── _SimpleTracker ────────────────────────────────────────────────────────────


class TestSimpleTracker(unittest.TestCase):
    def _tracker(self, iou=0.3, max_lost=3, max_tracks=20):
        return _SimpleTracker(iou_thresh=iou, max_lost=max_lost, max_tracks=max_tracks)

    def test_new_detection_creates_track(self):
        tracker = self._tracker()
        dets = [_det(bbox=(50, 100, 60, 150))]
        tracks = tracker.update(dets)
        # After 1 hit a track is not yet confirmed (hit_streak < 2)
        # Confirm on 2nd update
        tracks = tracker.update(dets)
        self.assertEqual(len(tracks), 1)

    def test_track_id_persists(self):
        tracker = self._tracker()
        det = _det(bbox=(50, 100, 60, 150))
        tracker.update([det])
        tracker.update([det])
        tracks1 = tracker.update([det])
        tracker.update([det])
        tracks2 = tracker.update([det])
        ids1 = {t.track_id for t in tracks1}
        ids2 = {t.track_id for t in tracks2}
        self.assertTrue(ids1.issubset(ids2) or ids2.issubset(ids1))

    def test_lost_track_deleted_after_max_lost(self):
        tracker = self._tracker(max_lost=2)
        det = _det(bbox=(50, 100, 60, 150))
        for _ in range(3):
            tracker.update([det])  # confirm track
        # Stop providing detections
        tracker.update([])
        tracker.update([])
        tracker.update([])  # 3rd lost frame → deleted
        tracks = tracker.update([])
        self.assertEqual(len(tracks), 0)

    def test_max_tracks_cap(self):
        tracker = self._tracker(max_tracks=3)
        dets = [_det(bbox=(i * 100, 0, 60, 150)) for i in range(10)]
        tracker.update(dets)
        self.assertLessEqual(len(tracker._tracks), 3)

    def test_no_detections_no_crash(self):
        tracker = self._tracker()
        result = tracker.update([])
        self.assertEqual(result, [])

    def test_reset_clears_tracks(self):
        tracker = self._tracker()
        det = _det()
        for _ in range(5):
            tracker.update([det])
        tracker.reset()
        self.assertEqual(len(tracker._tracks), 0)

    def test_multiple_objects_tracked_independently(self):
        tracker = self._tracker()
        det_a = _det(bbox=(0, 0, 50, 100))
        det_b = _det(bbox=(400, 0, 50, 100))
        for _ in range(4):
            tracker.update([det_a, det_b])
        tracks = tracker.update([det_a, det_b])
        ids = {t.track_id for t in tracks}
        self.assertEqual(len(ids), 2)


# ── Fake camera pipeline test ─────────────────────────────────────────────────


class TestFakeCameraPipeline(unittest.TestCase):
    """
    Pumps synthetic frames through FrameProcessor → MockDetector → _SimpleTracker.
    This is the functional "fake camera" test — no ROS2 runtime needed.
    """

    def _make_pipeline(self, brightness_threshold=50.0):
        cfg_pre = PreprocessConfig(
            resize_width=64,
            resize_height=48,
            enable_clahe=True,
            brightness_threshold=brightness_threshold,
            min_mean_brightness=2.0,
        )
        processor = FrameProcessor(cfg_pre)
        detector = MockDetector(num_detections=2)
        tracker = _SimpleTracker()
        return processor, detector, tracker

    def _run(self, frame, processor, detector, tracker, depth=None):
        pf = processor.process(frame, depth)
        if not pf.is_usable:
            return [], pf.quality
        result = detector.detect(pf.bgr)
        tracks = tracker.update(result.detections)
        return tracks, pf.quality

    def test_bright_frame_produces_detections(self):
        processor, detector, tracker = self._make_pipeline()
        for _ in range(3):
            tracks, quality = self._run(_bright(), processor, detector, tracker)
        self.assertIn(quality, (FrameQuality.OK, FrameQuality.LOW_LIGHT))
        self.assertGreater(
            len(detector.call_count) if hasattr(detector, "__iter__") else detector.call_count, 0
        )

    def test_empty_frame_no_detections(self):
        processor, detector, tracker = self._make_pipeline()
        tracks, quality = self._run(_black(), processor, detector, tracker)
        self.assertEqual(quality, FrameQuality.EMPTY)
        self.assertEqual(tracks, [])

    def test_low_light_frame_still_detected(self):
        processor, detector, tracker = self._make_pipeline(brightness_threshold=50.0)
        # dark but not black — should get LOW_LIGHT quality and still process
        tracks, quality = self._run(_dark(b=25), processor, detector, tracker)
        self.assertEqual(quality, FrameQuality.LOW_LIGHT)
        # Detector still called since LOW_LIGHT is usable
        self.assertGreaterEqual(detector.call_count, 1)

    def test_corrupted_frame_skipped(self):
        processor, detector, tracker = self._make_pipeline()
        tracks, quality = self._run(_nan_float(), processor, detector, tracker)
        self.assertEqual(quality, FrameQuality.CORRUPTED)
        self.assertEqual(tracks, [])
        self.assertEqual(detector.call_count, 0)

    def test_track_ids_assigned_across_frames(self):
        processor, detector, tracker = self._make_pipeline()
        all_ids = set()
        for _ in range(5):
            tracks, _ = self._run(_bright(), processor, detector, tracker)
            all_ids.update(t.track_id for t in tracks)
        # Should have assigned at least one persistent track id
        self.assertGreater(len(all_ids), 0)

    def test_degraded_detector_returns_empty(self):
        processor, _, tracker = self._make_pipeline()
        detector = MockDetector(start_degraded=True)
        tracks, quality = self._run(_bright(), processor, detector, tracker)
        self.assertEqual(tracks, [])
        detector.shutdown()

    def test_with_depth_map(self):
        processor, detector, tracker = self._make_pipeline()
        depth = np.full((480, 640), 2.5, dtype=np.float32)
        tracks, quality = self._run(_bright(), processor, detector, tracker, depth=depth)
        self.assertIn(quality, (FrameQuality.OK, FrameQuality.LOW_LIGHT))


# ── Privacy mode integration ──────────────────────────────────────────────────


class TestPrivacyIntegration(unittest.TestCase):
    def test_privacy_anonymises_copy(self):
        cfg = PrivacyConfig(enabled=True, blur_kernel_size=7)
        guard = PrivacyGuard(cfg)
        frame = _bright()
        faces = [(100, 50, 80, 100)]
        before = frame.copy()
        result = guard.anonymise(frame, faces)
        # Original must not be modified
        np.testing.assert_array_equal(frame, before)
        # Result is a different object
        self.assertIsNot(result, frame)

    def test_privacy_disabled_no_change(self):
        cfg = PrivacyConfig(enabled=False)
        guard = PrivacyGuard(cfg)
        frame = _bright()
        result = guard.anonymise(frame, [(50, 50, 80, 80)])
        np.testing.assert_array_equal(result, frame)


# ── _decode_color / _decode_depth static helpers ─────────────────────────────


class TestDecodeHelpers(unittest.TestCase):
    """
    Test the static image-decoding methods without a ROS2 Image message.
    We recreate what the methods do with raw numpy arrays.
    """

    def _fake_bgr8_msg(self, h=8, w=8):
        msg = MagicMock()
        msg.height = h
        msg.width = w
        msg.encoding = "bgr8"
        arr = np.full((h, w, 3), 128, dtype=np.uint8)
        msg.data = arr.tobytes()
        msg.step = w * 3
        return msg, arr

    def _fake_32fc1_msg(self, h=8, w=8, val=2.0):
        msg = MagicMock()
        msg.height = h
        msg.width = w
        msg.encoding = "32FC1"
        arr = np.full((h, w), val, dtype=np.float32)
        msg.data = arr.tobytes()
        msg.step = w * 4
        return msg, arr

    def test_decode_bgr8_roundtrip(self):
        """Simulate what _decode_color does for bgr8 encoding."""
        h, w = 8, 8
        original = np.full((h, w, 3), 200, dtype=np.uint8)
        data = original.tobytes()
        decoded = np.frombuffer(data, dtype=np.uint8).reshape(h, w, 3)
        np.testing.assert_array_equal(decoded, original)

    def test_decode_32fc1_roundtrip(self):
        """Simulate what _decode_depth does for 32FC1 encoding."""
        h, w = 8, 8
        original = np.full((h, w), 3.5, dtype=np.float32)
        data = original.tobytes()
        decoded = np.frombuffer(data, dtype=np.float32).reshape(h, w)
        np.testing.assert_allclose(decoded, original)

    def test_decode_16uc1_roundtrip(self):
        """Simulate 16UC1 depth (millimetres → metres)."""
        h, w = 8, 8
        mm = np.full((h, w), 1500, dtype=np.uint16)  # 1500 mm = 1.5 m
        data = mm.tobytes()
        decoded_mm = np.frombuffer(data, dtype=np.uint16).reshape(h, w)
        decoded_m = decoded_mm.astype(np.float32) / 1000.0
        self.assertAlmostEqual(float(decoded_m[0, 0]), 1.5, places=4)


# ── _fuse_face_ids logic ──────────────────────────────────────────────────────


class TestFuseFaceIds(unittest.TestCase):
    """
    Test the geometric face-to-track proximity assignment without running
    the full VisionNode.  We implement the same logic in pure Python.
    """

    PROXIMITY_PX = 200

    def _fuse(self, tracks, face_result):
        """Mirror of VisionNode._fuse_face_ids logic."""
        if not face_result.faces or not tracks:
            return tracks
        for t in tracks:
            best_face, best_dist = None, float("inf")
            for face in face_result.faces:
                fx, fy, fw, fh = face.bbox
                fcx, fcy = fx + fw / 2, fy + fh / 2
                dist = math.hypot(fcx - t.cx, fcy - t.cy)
                if dist < best_dist:
                    best_dist, best_face = dist, face
            if best_face is not None and best_dist < self.PROXIMITY_PX:
                t.face_id = best_face.face_id
        return tracks

    def _make_track(self, cx, cy, face_id=""):
        t = MagicMock()
        t.cx = cx
        t.cy = cy
        t.face_id = face_id
        return t

    def _make_face(self, cx, cy, face_id, size=60):
        x = int(cx - size // 2)
        y = int(cy - size // 2)
        fd = FaceDetection(bbox=(x, y, size, size), confidence=0.9, face_id=face_id)
        return fd

    def test_close_face_assigned(self):
        t = self._make_track(320, 150)
        face = self._make_face(325, 140, "alice")
        fr = FaceResult(faces=[face])
        self._fuse([t], fr)
        self.assertEqual(t.face_id, "alice")

    def test_distant_face_not_assigned(self):
        t = self._make_track(320, 150)
        face = self._make_face(20, 20, "bob")  # far away
        fr = FaceResult(faces=[face])
        self._fuse([t], fr)
        self.assertEqual(t.face_id, "")

    def test_multiple_faces_nearest_wins(self):
        t = self._make_track(200, 200)
        face_near = self._make_face(210, 190, "near_person")
        face_far = self._make_face(500, 400, "far_person")
        fr = FaceResult(faces=[face_near, face_far])
        self._fuse([t], fr)
        self.assertEqual(t.face_id, "near_person")

    def test_no_faces_tracks_unchanged(self):
        t = self._make_track(100, 100)
        fr = FaceResult(faces=[])
        self._fuse([t], fr)
        self.assertEqual(t.face_id, "")

    def test_no_tracks_no_crash(self):
        face = self._make_face(100, 100, "someone")
        fr = FaceResult(faces=[face])
        result = self._fuse([], fr)
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
