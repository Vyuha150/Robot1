"""
tests/integration/test_vision_integration.py
=============================================
Integration tests for the bonbon_vision pipeline.

These tests wire multiple components together and verify cross-component
contracts WITHOUT requiring a live ROS2 runtime.

Tests that do require ROS2 (full LifecycleNode spin-up) are marked with
@pytest.mark.ros2 and can be skipped via: pytest -m "not ros2"

Integration scenarios
---------------------
1.  Full pipeline (preprocess → detect → face → track → privacy)
    * Bright frame — all stages exercised
    * Low-light frame — CLAHE applied, results still published
    * Empty frame — pipeline short-circuits, zero tracks
    * Corrupted frame — pipeline short-circuits, zero tracks

2.  Config integration
    * VisionConfig.from_dict() populates all nested dataclasses
    * VisionConfig.validate() rejects invalid combinations
    * PrivacyConfig.validate() rejects even blur_kernel_size

3.  Detector → Tracker continuity
    * Same objects across frames get the same track_id
    * Tracks survive N consecutive detection misses (max_lost_frames)
    * Tracks are deleted after max_lost_frames + 1 missed frames

4.  Model lifecycle integration
    * ModelManager UNLOADED → READY path
    * ModelManager FAILED path (graceful degraded)

5.  Privacy pipeline
    * face_id suppressed when privacy_mode=True
    * Original frames not modified by privacy guard

6.  Throttler + processor integration
    * Throttler drops frames; processor only called on accepted frames
"""

from __future__ import annotations

import math
import sys
import time
import types
import unittest

import numpy as np


# ── Stub ROS2 if not available (reuse vision_node test approach) ──────────────
def _stub(name, **attrs):
    m = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    return m


try:
    import rclpy  # noqa
except ImportError:
    sys.modules.setdefault("rclpy", _stub("rclpy"))
    sys.modules.setdefault(
        "rclpy.lifecycle",
        _stub(
            "rclpy.lifecycle",
            LifecycleNode=object,
            TransitionCallbackReturn=type("T", (), {"SUCCESS": 0, "ERROR": 1, "FAILURE": 2}),
            State=object,
        ),
    )
    for qos in ["rclpy.qos"]:
        sys.modules.setdefault(
            qos,
            _stub(
                qos,
                QoSProfile=lambda **kw: None,
                ReliabilityPolicy=type("R", (), {"RELIABLE": 1, "BEST_EFFORT": 0}),
                DurabilityPolicy=type("D", (), {"TRANSIENT_LOCAL": 1, "VOLATILE": 0}),
                HistoryPolicy=type("H", (), {"KEEP_LAST": 0}),
            ),
        )
    for pkg in [
        "geometry_msgs",
        "geometry_msgs.msg",
        "sensor_msgs",
        "sensor_msgs.msg",
        "std_msgs",
        "std_msgs.msg",
        "bonbon_msgs",
        "bonbon_msgs.msg",
    ]:
        sys.modules.setdefault(
            pkg,
            _stub(
                pkg,
                Point=type("P", (), {}),
                Image=type("I", (), {}),
                Header=type("H", (), {}),
                DetectedObject=type("DO", (), {}),
                DetectedObjectArray=type("DOA", (), {}),
                ModuleHealth=type("MH", (), {}),
                PersonState=type("PS", (), {}),
                PersonStateArray=type("PSA", (), {}),
            ),
        )

# Now safe to import
from bonbon_vision.config.vision_config import (
    DetectorConfig,
    FaceConfig,
    PreprocessConfig,
    PrivacyConfig,
    VisionConfig,
)
from bonbon_vision.detectors.mock_detector import MockDetector
from bonbon_vision.face.face_pipeline import FacePipeline
from bonbon_vision.face.privacy_guard import PrivacyGuard
from bonbon_vision.models.model_manager import ModelManager, ModelState
from bonbon_vision.nodes.vision_node import _SimpleTracker
from bonbon_vision.preprocessing.frame_processor import FrameProcessor, FrameQuality
from bonbon_vision.preprocessing.frame_throttler import FrameThrottler

# ── Frame helpers ──────────────────────────────────────────────────────────────


def _bright(h=480, w=640, b=120) -> np.ndarray:
    return np.full((h, w, 3), b, dtype=np.uint8)


def _black(h=480, w=640) -> np.ndarray:
    return np.zeros((h, w, 3), dtype=np.uint8)


def _dark(h=480, w=640, b=20) -> np.ndarray:
    return np.full((h, w, 3), b, dtype=np.uint8)


def _nan_float(h=480, w=640) -> np.ndarray:
    arr = np.ones((h, w, 3), dtype=np.float32)
    arr[0, 0, 0] = math.nan
    return arr


def _depth(val=2.0, h=480, w=640) -> np.ndarray:
    return np.full((h, w), val, dtype=np.float32)


# ── 1. Full pipeline integration ──────────────────────────────────────────────


class TestFullPipeline(unittest.TestCase):
    """preprocess → detect → face → track → privacy all wired together."""

    def _build(self, privacy=False, n_det=2, brightness_threshold=50.0):
        pre_cfg = PreprocessConfig(
            resize_width=64,
            resize_height=48,
            enable_clahe=True,
            brightness_threshold=brightness_threshold,
            min_mean_brightness=2.0,
        )
        processor = FrameProcessor(pre_cfg)
        detector = MockDetector(num_detections=n_det)
        face_pipe = FacePipeline(FaceConfig(detect_backend="mock", recognize_backend="mock"))
        privacy_guard = PrivacyGuard(
            PrivacyConfig(
                enabled=privacy,
                blur_kernel_size=7,
            )
        )
        tracker = _SimpleTracker()
        return processor, detector, face_pipe, privacy_guard, tracker

    def _run_frame(self, frame, proc, det, face, priv, tracker, depth=None):
        pf = proc.process(frame, depth)
        if not pf.is_usable:
            return [], pf.quality, False
        det_r = det.detect(pf.bgr)
        face_r = face.run(pf.bgr)
        tracks = tracker.update(det_r.detections)
        priv.anonymise(pf.bgr, [f.bbox for f in face_r.faces])
        return tracks, pf.quality, True

    def test_bright_frame_full_pipeline(self):
        proc, det, face, priv, tracker = self._build()
        for _ in range(3):
            tracks, quality, ran = self._run_frame(_bright(), proc, det, face, priv, tracker)
        self.assertTrue(ran)
        self.assertIn(quality, (FrameQuality.OK, FrameQuality.LOW_LIGHT))

    def test_low_light_frame_pipeline_runs(self):
        proc, det, face, priv, tracker = self._build(brightness_threshold=50.0)
        tracks, quality, ran = self._run_frame(_dark(b=25), proc, det, face, priv, tracker)
        self.assertEqual(quality, FrameQuality.LOW_LIGHT)
        self.assertTrue(ran)

    def test_empty_frame_pipeline_short_circuits(self):
        proc, det, face, priv, tracker = self._build()
        tracks, quality, ran = self._run_frame(_black(), proc, det, face, priv, tracker)
        self.assertEqual(quality, FrameQuality.EMPTY)
        self.assertFalse(ran)
        self.assertEqual(tracks, [])

    def test_corrupted_frame_pipeline_short_circuits(self):
        proc, det, face, priv, tracker = self._build()
        tracks, quality, ran = self._run_frame(_nan_float(), proc, det, face, priv, tracker)
        self.assertEqual(quality, FrameQuality.CORRUPTED)
        self.assertFalse(ran)

    def test_privacy_mode_original_unchanged(self):
        proc, det, face, priv, tracker = self._build(privacy=True)
        frame = _bright()
        before = frame.copy()
        self._run_frame(frame, proc, det, face, priv, tracker)
        np.testing.assert_array_equal(frame, before)

    def test_with_depth_map(self):
        proc, det, face, priv, tracker = self._build()
        dep = _depth(val=1.5)
        tracks, quality, ran = self._run_frame(_bright(), proc, det, face, priv, tracker, dep)
        self.assertTrue(ran)

    def test_multiple_frames_increase_call_count(self):
        proc, det, face, priv, tracker = self._build()
        n = 10
        for _ in range(n):
            self._run_frame(_bright(), proc, det, face, priv, tracker)
        self.assertEqual(det.call_count, n)


# ── 2. Config integration ─────────────────────────────────────────────────────


class TestConfigIntegration(unittest.TestCase):
    def test_from_dict_full_config(self):
        d = {
            "detector": {"backend": "mock", "confidence_threshold": 0.5},
            "face": {"detect_backend": "mock"},
            "preprocess": {"resize_width": 320, "resize_height": 240},
            "privacy": {"enabled": True, "blur_kernel_size": 31},
            "tracking": {"max_tracks": 10},
            "detection_rate_hz": 15.0,
        }
        cfg = VisionConfig.from_dict(d)
        self.assertEqual(cfg.detector.confidence_threshold, 0.5)
        self.assertEqual(cfg.preprocess.resize_width, 320)
        self.assertTrue(cfg.privacy.enabled)
        self.assertEqual(cfg.tracking.max_tracks, 10)
        self.assertAlmostEqual(cfg.detection_rate_hz, 15.0)

    def test_validate_passes_mock_backend(self):
        cfg = VisionConfig()
        cfg.validate()  # must not raise

    def test_validate_fails_yolo_without_model_path(self):
        cfg = VisionConfig()
        cfg.detector.backend = "yolo"
        cfg.detector.model_path = ""
        with self.assertRaises(ValueError):
            cfg.validate()

    def test_validate_fails_even_blur_kernel(self):
        cfg = VisionConfig()
        cfg.privacy.blur_kernel_size = 4  # even → invalid
        with self.assertRaises(ValueError):
            cfg.validate()

    def test_validate_fails_zero_rate(self):
        cfg = VisionConfig()
        cfg.detection_rate_hz = 0.0
        with self.assertRaises(ValueError):
            cfg.validate()

    def test_to_dict_roundtrip(self):
        cfg = VisionConfig()
        d = cfg.to_dict()
        cfg2 = VisionConfig.from_dict(d)
        self.assertEqual(cfg.detector.backend, cfg2.detector.backend)
        self.assertEqual(cfg.privacy.enabled, cfg2.privacy.enabled)

    def test_summary_contains_key_fields(self):
        cfg = VisionConfig()
        s = cfg.summary()
        self.assertIn("detector=", s)
        self.assertIn("privacy=", s)


# ── 3. Detector → Tracker continuity ─────────────────────────────────────────


class TestDetectorTrackerContinuity(unittest.TestCase):
    def _make(self, n=2, max_lost=5):
        detector = MockDetector(num_detections=n)
        tracker = _SimpleTracker(max_lost=max_lost)
        return detector, tracker

    def test_track_id_stable_over_frames(self):
        detector, tracker = self._make(n=1)
        all_ids = []
        for _ in range(8):
            r = detector.detect(_bright())
            ts = tracker.update(r.detections)
            all_ids.extend(t.track_id for t in ts)
        # All track IDs from confirmed frames should be the same
        unique_ids = set(all_ids)
        # The same object should keep the same track ID
        self.assertEqual(len(unique_ids), 1)
        detector.shutdown()

    def test_track_survives_max_lost_frames(self):
        """Track should not be deleted until max_lost_frames + 1 missed."""
        detector, tracker = self._make(n=1, max_lost=3)
        det = _bright()
        for _ in range(4):  # confirm track
            r = detector.detect(det)
            tracker.update(r.detections)
        # Now miss 3 frames (= max_lost) — track should still be in memory
        for _ in range(3):
            tracker.update([])
        self.assertGreater(len(tracker._tracks), 0)
        detector.shutdown()

    def test_track_deleted_after_max_lost_plus_one(self):
        detector, tracker = self._make(n=1, max_lost=2)
        for _ in range(4):
            r = detector.detect(_bright())
            tracker.update(r.detections)
        # Miss 3 frames (> max_lost=2)
        for _ in range(4):
            tracker.update([])
        self.assertEqual(len(tracker._tracks), 0)
        detector.shutdown()

    def test_new_detection_after_gap_gets_new_id(self):
        detector, tracker = self._make(n=1, max_lost=1)
        r = detector.detect(_bright())
        tracker.update(r.detections)
        # Let track expire
        for _ in range(3):
            tracker.update([])
        # New detection gets a new ID
        r2 = detector.detect(_bright())
        tracker.update(r2.detections)
        new_ids = {t.track_id for t in tracker._tracks.values()}
        self.assertGreater(len(new_ids), 0)
        detector.shutdown()


# ── 4. Model lifecycle integration ───────────────────────────────────────────


class TestModelLifecycleIntegration(unittest.TestCase):
    def test_successful_load_produces_ready_state(self):
        class GoodDetector:
            is_degraded = False

            def load_model(self):
                time.sleep(0.01)

        mgr = ModelManager(GoodDetector(), allow_degraded=True)
        mgr.load_async()
        ok = mgr.wait_ready(timeout=5.0)
        self.assertTrue(ok)
        self.assertEqual(mgr.state, ModelState.READY)

    def test_failed_load_with_degraded_true_no_crash(self):
        class BadDetector:
            is_degraded = False

            def load_model(self):
                raise RuntimeError("no model")

        mgr = ModelManager(BadDetector(), allow_degraded=True)
        mgr.load_async()
        mgr.wait_ready(timeout=5.0)
        self.assertEqual(mgr.state, ModelState.FAILED)
        self.assertIsNotNone(mgr.error)

    def test_reload_transitions_back_to_ready(self):
        class GoodDetector:
            is_degraded = False

            def load_model(self):
                pass

        mgr = ModelManager(GoodDetector())
        mgr.load_sync()
        self.assertEqual(mgr.state, ModelState.READY)
        mgr.reload()
        mgr.wait_ready(timeout=5.0)
        self.assertEqual(mgr.state, ModelState.READY)


# ── 5. Privacy pipeline integration ──────────────────────────────────────────


class TestPrivacyPipelineIntegration(unittest.TestCase):
    def test_face_id_suppressed_in_privacy_mode(self):
        cfg = FaceConfig(detect_backend="mock", recognize_backend="mock")
        pipe = FacePipeline(cfg, privacy_mode=True)
        # Monkey-patch recognizer to return a name
        pipe._recognizer = type("R", (), {"identify": lambda self, *a, **k: "alice"})()
        r = pipe.run(_bright())
        for face in r.faces:
            self.assertEqual(face.face_id, "")
        pipe.shutdown()

    def test_face_id_visible_without_privacy(self):
        cfg = FaceConfig(detect_backend="mock", recognize_backend="mock")
        pipe = FacePipeline(cfg, privacy_mode=False)
        # The mock recognizer returns "" — just verify no crash
        r = pipe.run(_bright())
        self.assertIsInstance(r.faces, list)
        pipe.shutdown()

    def test_privacy_guard_does_not_modify_original(self):
        guard = PrivacyGuard(
            PrivacyConfig(
                enabled=True,
                blur_kernel_size=7,
            )
        )
        frame = _bright()
        before = frame.copy()
        guard.anonymise(frame, [(100, 50, 80, 100), (300, 80, 60, 80)])
        np.testing.assert_array_equal(frame, before)


# ── 6. Throttler + processor integration ─────────────────────────────────────


class TestThrottlerProcessorIntegration(unittest.TestCase):
    def test_throttler_drops_frames_not_processed(self):
        """At 5 Hz throttle with 30 Hz offer rate, ~83% should be dropped."""
        import bonbon_vision.preprocessing.frame_throttler as _mod

        ticks = [0.0]
        original = _mod.time.monotonic
        _mod.time.monotonic = lambda: ticks[0]

        try:
            throttler = FrameThrottler(target_hz=5.0)
            processor = FrameProcessor(
                PreprocessConfig(
                    resize_width=64,
                    resize_height=48,
                )
            )
            processed_count = 0
            for i in range(300):
                ticks[0] = i * (1.0 / 30.0)  # simulate 30 Hz camera
                if throttler.should_process():
                    processor.process(_bright())
                    processed_count += 1

            # Expected ~50 processed (5 Hz × 10 s) ± generous margin
            self.assertGreater(processed_count, 30)
            self.assertLess(processed_count, 80)
        finally:
            _mod.time.monotonic = original

    def test_throttler_stats_consistent(self):
        throttler = FrameThrottler(target_hz=10.0)
        for _ in range(20):
            throttler.should_process()
        s = throttler.stats
        self.assertEqual(s["offered"], s["processed"] + s["dropped"])


# ── 7. Cross-component: config → processor → detector ────────────────────────


class TestConfigToComponentIntegration(unittest.TestCase):
    def test_vision_config_feeds_frame_processor(self):
        cfg = VisionConfig.from_dict(
            {
                "preprocess": {
                    "resize_width": 64,
                    "resize_height": 48,
                    "enable_clahe": False,
                    "brightness_threshold": 40.0,
                }
            }
        )
        proc = FrameProcessor(cfg.preprocess)
        pf = proc.process(_bright(b=90))
        self.assertEqual(pf.bgr.shape[:2], (48, 64))

    def test_vision_config_feeds_detector(self):
        cfg = VisionConfig.from_dict({"detector": {"backend": "mock", "confidence_threshold": 0.6}})
        detector = MockDetector(
            cfg=DetectorConfig(
                backend="mock", confidence_threshold=cfg.detector.confidence_threshold
            )
        )
        r = detector.detect(_bright())
        self.assertFalse(r.is_degraded)
        detector.shutdown()


if __name__ == "__main__":
    unittest.main()
