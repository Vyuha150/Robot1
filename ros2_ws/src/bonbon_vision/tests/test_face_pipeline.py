"""
tests/test_face_pipeline.py
============================
Unit tests for bonbon_vision.face.face_pipeline.

Covered
-------
* Mock backend — returns exactly one face at centre of image
* FaceDetection dataclass fields
* FaceResult dataclass defaults
* Privacy mode suppresses face_id
* Detect timeout returns detect_timed_out flag, empty faces
* Recognition timeout returns faces with empty face_id
* Error inside detector sets error field
* shutdown() does not crash
* run() on tiny / odd-shaped images
* Zero-size crop is handled gracefully (no crash)
"""

import unittest
from concurrent.futures import TimeoutError as FuturesTimeout
from unittest.mock import MagicMock

import numpy as np
from bonbon_vision.config.vision_config import FaceConfig
from bonbon_vision.face.face_pipeline import (
    FaceDetection,
    FacePipeline,
    FaceResult,
    _MockFaceDetector,
)

# ── Helpers ───────────────────────────────────────────────────────────────────


def _cfg(**overrides) -> FaceConfig:
    defaults = dict(
        detect_backend="mock",
        recognize_backend="mock",
        db_path="",
        recognition_threshold=0.40,
        dnn_prototxt_path="",
        dnn_weights_path="",
        inference_timeout_sec=1.0,
        min_face_confidence=0.70,
    )
    defaults.update(overrides)
    return FaceConfig(**defaults)


def _frame(h=480, w=640, brightness=120):
    return np.full((h, w, 3), brightness, dtype=np.uint8)


# ── FaceDetection dataclass ───────────────────────────────────────────────────


class TestFaceDetection(unittest.TestCase):
    def test_defaults(self):
        fd = FaceDetection(bbox=(10, 20, 80, 100), confidence=0.95)
        self.assertEqual(fd.face_id, "")
        self.assertEqual(fd.age_group, "unknown")
        self.assertFalse(fd.facing_robot)

    def test_custom_fields(self):
        fd = FaceDetection(
            bbox=(5, 5, 60, 80),
            confidence=0.80,
            face_id="alice",
            age_group="adult",
            facing_robot=True,
        )
        self.assertEqual(fd.face_id, "alice")
        self.assertTrue(fd.facing_robot)


class TestFaceResult(unittest.TestCase):
    def test_defaults(self):
        fr = FaceResult()
        self.assertEqual(fr.faces, [])
        self.assertAlmostEqual(fr.detect_ms, 0.0)
        self.assertFalse(fr.detect_timed_out)
        self.assertFalse(fr.recognize_timed_out)
        self.assertIsNone(fr.error)


# ── Mock detector unit ────────────────────────────────────────────────────────


class TestMockFaceDetector(unittest.TestCase):
    def test_returns_one_face(self):
        det = _MockFaceDetector()
        faces = det.detect(_frame())
        self.assertEqual(len(faces), 1)

    def test_bbox_tuple(self):
        det = _MockFaceDetector()
        bbox = det.detect(_frame())[0]
        self.assertEqual(len(bbox), 4)

    def test_bbox_within_frame(self):
        det = _MockFaceDetector()
        x, y, w, h = det.detect(_frame(h=480, w=640))[0]
        self.assertGreaterEqual(x, 0)
        self.assertGreaterEqual(y, 0)
        self.assertGreater(w, 0)
        self.assertGreater(h, 0)


# ── FacePipeline with mock backend ───────────────────────────────────────────


class TestFacePipelineMock(unittest.TestCase):
    def setUp(self):
        self.pipe = FacePipeline(_cfg())

    def tearDown(self):
        self.pipe.shutdown()

    def test_returns_face_result(self):
        r = self.pipe.run(_frame())
        self.assertIsInstance(r, FaceResult)

    def test_one_face_detected(self):
        r = self.pipe.run(_frame())
        self.assertEqual(len(r.faces), 1)

    def test_face_detection_in_result(self):
        r = self.pipe.run(_frame())
        self.assertIsInstance(r.faces[0], FaceDetection)

    def test_detect_ms_nonnegative(self):
        r = self.pipe.run(_frame())
        self.assertGreaterEqual(r.detect_ms, 0.0)

    def test_recognize_ms_nonnegative(self):
        r = self.pipe.run(_frame())
        self.assertGreaterEqual(r.recognize_ms, 0.0)

    def test_no_error(self):
        r = self.pipe.run(_frame())
        self.assertIsNone(r.error)

    def test_not_timed_out(self):
        r = self.pipe.run(_frame())
        self.assertFalse(r.detect_timed_out)
        self.assertFalse(r.recognize_timed_out)

    def test_face_id_empty_with_mock_recognizer(self):
        """MockFaceRecognizer.identify() always returns ''."""
        r = self.pipe.run(_frame())
        for face in r.faces:
            self.assertEqual(face.face_id, "")


# ── Privacy mode ──────────────────────────────────────────────────────────────


class TestPrivacyMode(unittest.TestCase):
    def test_privacy_suppresses_face_id(self):
        pipe = FacePipeline(_cfg(), privacy_mode=True)
        # Monkey-patch recognizer to return a non-empty id
        pipe._recognizer = type("R", (), {"identify": lambda self, crop, db, thresh: "alice"})()
        r = pipe.run(_frame())
        for face in r.faces:
            self.assertEqual(face.face_id, "")
        pipe.shutdown()

    def test_privacy_false_allows_face_id(self):
        pipe = FacePipeline(_cfg(), privacy_mode=False)
        # Monkey-patch recognizer
        pipe._recognizer = type("R", (), {"identify": lambda self, crop, db, thresh: "bob"})()
        r = pipe.run(_frame())
        # face_id should be set by recognizer
        # (MockFaceDetector returns at least 1 face)
        # face_id depends on mock recognizer which returns "bob"
        # but the original MockFaceRecognizer returns ""; we patched it.
        if r.faces:
            self.assertEqual(r.faces[0].face_id, "bob")
        pipe.shutdown()


# ── Timeout handling ──────────────────────────────────────────────────────────


class TestFacePipelineTimeout(unittest.TestCase):
    def test_detect_timeout_sets_flag(self):
        """
        Patch the executor so it raises FuturesTimeout on face detection.
        """
        pipe = FacePipeline(_cfg(inference_timeout_sec=0.01))

        original_submit = pipe._executor.submit

        call_count = [0]

        def patched_submit(fn, *args, **kwargs):
            f = original_submit(fn, *args, **kwargs)
            call_count[0] += 1
            if call_count[0] == 1:
                # First submit → timeout
                mock_f = MagicMock()
                mock_f.result.side_effect = FuturesTimeout()
                return mock_f
            return f

        pipe._executor.submit = patched_submit
        r = pipe.run(_frame())
        self.assertTrue(r.detect_timed_out)
        self.assertEqual(len(r.faces), 0)
        pipe.shutdown()

    def test_recognize_timeout_sets_flag(self):
        """Patch executor so recognition future raises FuturesTimeout."""
        pipe = FacePipeline(_cfg(inference_timeout_sec=0.01))

        original_submit = pipe._executor.submit
        call_count = [0]

        def patched_submit(fn, *args, **kwargs):
            f = original_submit(fn, *args, **kwargs)
            call_count[0] += 1
            if call_count[0] == 2:  # 2nd submit = recognition
                mock_f = MagicMock()
                mock_f.result.side_effect = FuturesTimeout()
                return mock_f
            return f

        pipe._executor.submit = patched_submit
        r = pipe.run(_frame())
        self.assertTrue(r.recognize_timed_out)
        pipe.shutdown()


# ── Error handling ────────────────────────────────────────────────────────────


class TestFacePipelineErrors(unittest.TestCase):
    def test_detector_exception_sets_error_field(self):
        pipe = FacePipeline(_cfg())
        # Replace detector with one that always raises
        pipe._detector = type(
            "D", (), {"detect": lambda self, bgr: (_ for _ in ()).throw(RuntimeError("test error"))}
        )()

        # Simpler approach: patch the future

        def patched_submit(fn, *args, **kwargs):
            mock_f = MagicMock()
            mock_f.result.side_effect = RuntimeError("detect error")
            return mock_f

        pipe._executor.submit = patched_submit
        r = pipe.run(_frame())
        self.assertIsNotNone(r.error)
        pipe.shutdown()

    def test_zero_size_crop_handled(self):
        """
        If the detector returns a bbox with w=0 or h=0, the crop is empty.
        The pipeline must not crash.
        """
        pipe = FacePipeline(_cfg())
        pipe._detector = type(
            "D", (), {"detect": lambda self, bgr: [(100, 100, 0, 0)]}  # zero-size box
        )()
        r = pipe.run(_frame())
        # No exception, at least one face (with empty face_id)
        self.assertIsNone(r.error)
        pipe.shutdown()


# ── Edge cases ────────────────────────────────────────────────────────────────


class TestFacePipelineEdgeCases(unittest.TestCase):
    def test_tiny_image(self):
        pipe = FacePipeline(_cfg())
        r = pipe.run(np.full((10, 10, 3), 128, dtype=np.uint8))
        self.assertIsInstance(r, FaceResult)
        pipe.shutdown()

    def test_no_faces_in_image(self):
        """Patch detector to return no faces."""
        pipe = FacePipeline(_cfg())
        pipe._detector = type("D", (), {"detect": lambda self, bgr: []})()
        r = pipe.run(_frame())
        self.assertEqual(len(r.faces), 0)
        self.assertIsNone(r.error)
        pipe.shutdown()

    def test_many_faces(self):
        """Detector returns 20 faces — pipeline processes all."""
        pipe = FacePipeline(_cfg())
        bboxes = [(i * 20, 10, 15, 20) for i in range(20)]
        pipe._detector = type("D", (), {"detect": lambda self, bgr, _b=bboxes: _b})()
        r = pipe.run(_frame())
        self.assertEqual(len(r.faces), 20)
        pipe.shutdown()

    def test_shutdown_idempotent(self):
        pipe = FacePipeline(_cfg())
        pipe.shutdown()
        pipe.shutdown()  # second call must not crash


if __name__ == "__main__":
    unittest.main()
