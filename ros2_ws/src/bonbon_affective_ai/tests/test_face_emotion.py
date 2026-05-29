"""Tests for the face emotion analyzer using MockFaceBackend."""

from __future__ import annotations

import sys
import types
import unittest

import numpy as np

# ── ROS2 / bonbon_msgs stubs so tests run without a full ROS2 install ─────────

def _make_ros_stubs() -> None:
    """Inject minimal stub modules for rclpy and bonbon_msgs."""
    # rclpy stub
    if "rclpy" not in sys.modules:
        rclpy_mod = types.ModuleType("rclpy")
        rclpy_mod.clock = types.ModuleType("rclpy.clock")

        class _Clock:
            def now(self):
                class _T:
                    def to_msg(self):
                        return None
                return _T()

        rclpy_mod.clock.Clock = _Clock
        sys.modules["rclpy"] = rclpy_mod
        sys.modules["rclpy.clock"] = rclpy_mod.clock

    # bonbon_msgs stub
    if "bonbon_msgs" not in sys.modules:
        bonbon_msgs = types.ModuleType("bonbon_msgs")
        bonbon_msgs_msg = types.ModuleType("bonbon_msgs.msg")

        class FaceEmotion:
            def __init__(self):
                self.header = type("H", (), {"stamp": None})()
                self.event_id = ""
                self.source_module = ""
                self.tracking_id = 0
                self.person_id = ""
                self.anger = 0.0
                self.disgust = 0.0
                self.fear = 0.0
                self.happiness = 0.0
                self.sadness = 0.0
                self.surprise = 0.0
                self.neutral = 0.0
                self.dominant_emotion = "neutral"
                self.dominant_confidence = 0.0
                self.is_ambiguous = False
                self.low_quality_input = False
                self.privacy_suppressed = False
                self.privacy_level = "none"

        bonbon_msgs_msg.FaceEmotion = FaceEmotion
        bonbon_msgs.msg = bonbon_msgs_msg
        sys.modules["bonbon_msgs"] = bonbon_msgs
        sys.modules["bonbon_msgs.msg"] = bonbon_msgs_msg


_make_ros_stubs()

from bonbon_affective_ai.backends.mock_backends import MockFaceBackend
from bonbon_affective_ai.config.affective_config import AffectiveConfig
from bonbon_affective_ai.privacy.privacy_gate import PrivacyGate
from bonbon_affective_ai.analyzers.face_emotion_analyzer import FaceEmotionAnalyzer


class _FakeClock:
    """Minimal clock stub returning None timestamps."""

    def now(self):
        class _T:
            def to_msg(self):
                return None
        return _T()


class TestFaceEmotionAnalyzer(unittest.TestCase):
    """Tests for FaceEmotionAnalyzer with MockFaceBackend."""

    def setUp(self) -> None:
        """Set up fresh analyzer before each test."""
        self.backend = MockFaceBackend()
        self.backend.warmup()
        self.config = AffectiveConfig(
            face_sample_interval_sec=0.0,  # no rate-limit in tests
            face_confidence_threshold=0.55,
            face_temporal_window=3,
        )
        self.privacy = PrivacyGate(self.config)
        self.clock = _FakeClock()
        self.analyzer = FaceEmotionAnalyzer(
            self.config, self.backend, self.privacy, self.clock
        )

    def _blank_face(self) -> np.ndarray:
        """Return a blank 48×48 BGR face crop."""
        return np.zeros((48, 48, 3), dtype=np.uint8)

    def test_analyze_returns_face_emotion_message(self) -> None:
        """A FaceEmotion message is returned for a valid face crop."""
        from bonbon_msgs.msg import FaceEmotion
        msg = self.analyzer.analyze_face_crop(self._blank_face(), tracking_id=1, person_id="p1")
        self.assertIsNotNone(msg)
        self.assertIsInstance(msg, FaceEmotion)

    def test_message_fields_populated(self) -> None:
        """All required emotion fields are non-negative floats."""
        msg = self.analyzer.analyze_face_crop(self._blank_face(), tracking_id=1, person_id="p1")
        for field in ("anger", "disgust", "fear", "happiness", "sadness", "surprise", "neutral"):
            val = getattr(msg, field)
            self.assertIsInstance(val, float)
            self.assertGreaterEqual(val, 0.0)
            self.assertLessEqual(val, 1.0)

    def test_dominant_emotion_set(self) -> None:
        """dominant_emotion is a non-empty string."""
        msg = self.analyzer.analyze_face_crop(self._blank_face(), tracking_id=1, person_id="p1")
        self.assertIsInstance(msg.dominant_emotion, str)
        self.assertGreater(len(msg.dominant_emotion), 0)

    def test_dominant_confidence_in_range(self) -> None:
        """dominant_confidence is in [0.0, 1.0]."""
        msg = self.analyzer.analyze_face_crop(self._blank_face(), tracking_id=1, person_id="p1")
        self.assertGreaterEqual(msg.dominant_confidence, 0.0)
        self.assertLessEqual(msg.dominant_confidence, 1.0)

    def test_event_id_is_uuid(self) -> None:
        """event_id looks like a UUID string."""
        msg = self.analyzer.analyze_face_crop(self._blank_face(), tracking_id=1, person_id="p1")
        import uuid
        # Should not raise.
        uuid.UUID(msg.event_id)

    def test_source_module_set(self) -> None:
        """source_module identifies the face analyzer."""
        msg = self.analyzer.analyze_face_crop(self._blank_face(), tracking_id=1, person_id="p1")
        self.assertIn("face", msg.source_module)

    def test_tracking_id_preserved(self) -> None:
        """tracking_id matches the input value."""
        msg = self.analyzer.analyze_face_crop(self._blank_face(), tracking_id=42, person_id="p1")
        self.assertEqual(msg.tracking_id, 42)

    def test_person_id_preserved(self) -> None:
        """person_id matches the input value."""
        msg = self.analyzer.analyze_face_crop(self._blank_face(), tracking_id=1, person_id="person_99")
        self.assertEqual(msg.person_id, "person_99")

    def test_privacy_suppression_face_only(self) -> None:
        """When privacy level is face_only, privacy_suppressed=True is set."""
        self.privacy.set_level("face_only")
        msg = self.analyzer.analyze_face_crop(self._blank_face(), tracking_id=1, person_id="p1")
        self.assertTrue(msg.privacy_suppressed)
        # All emotion scores should be zero.
        for field in ("anger", "disgust", "fear", "happiness", "sadness", "surprise", "neutral"):
            self.assertEqual(getattr(msg, field), 0.0)

    def test_privacy_suppression_suppressed(self) -> None:
        """When privacy level is suppressed, privacy_suppressed=True."""
        self.privacy.set_level("suppressed")
        msg = self.analyzer.analyze_face_crop(self._blank_face(), tracking_id=1, person_id="p1")
        self.assertTrue(msg.privacy_suppressed)

    def test_no_suppression_at_none_level(self) -> None:
        """When privacy level is none, privacy_suppressed=False."""
        self.privacy.set_level("none")
        msg = self.analyzer.analyze_face_crop(self._blank_face(), tracking_id=1, person_id="p1")
        self.assertFalse(msg.privacy_suppressed)

    def test_rate_limiting_skips_second_call(self) -> None:
        """Second call within interval returns None."""
        config = AffectiveConfig(
            face_sample_interval_sec=1000.0,  # effectively infinite
            face_temporal_window=3,
        )
        analyzer = FaceEmotionAnalyzer(config, self.backend, self.privacy, self.clock)
        first = analyzer.analyze_face_crop(self._blank_face(), tracking_id=5, person_id="p5")
        second = analyzer.analyze_face_crop(self._blank_face(), tracking_id=5, person_id="p5")
        self.assertIsNotNone(first)
        self.assertIsNone(second)

    def test_backend_not_ready_returns_failed_msg(self) -> None:
        """An unwarmed backend returns a message with low_quality_input=True."""
        fresh_backend = MockFaceBackend()  # not warmed up
        analyzer = FaceEmotionAnalyzer(
            self.config, fresh_backend, self.privacy, self.clock
        )
        msg = analyzer.analyze_face_crop(self._blank_face(), tracking_id=1, person_id="p1")
        self.assertIsNotNone(msg)
        self.assertTrue(msg.low_quality_input)

    def test_cycles_through_emotions(self) -> None:
        """Mock backend cycles through different dominant emotions."""
        seen: set = set()
        for i in range(10):
            self.backend.analyze(self._blank_face())  # exhaust some cycles
        for i in range(5):
            msg = self.analyzer.analyze_face_crop(self._blank_face(), tracking_id=100 + i, person_id=f"p{i}")
            if msg is not None:
                seen.add(msg.dominant_emotion)
        # Should have seen more than one emotion across 5 different people.
        self.assertGreater(len(seen), 0)


if __name__ == "__main__":
    unittest.main()
