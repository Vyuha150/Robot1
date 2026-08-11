"""Tests for the voice emotion analyzer using MockVoiceBackend."""

from __future__ import annotations

import sys
import types
import unittest

import numpy as np


def _make_ros_stubs() -> None:
    """Inject minimal stub modules for rclpy and bonbon_msgs."""
    if "rclpy" not in sys.modules:
        rclpy_mod = types.ModuleType("rclpy")
        rclpy_mod.clock = types.ModuleType("rclpy.clock")
        sys.modules["rclpy"] = rclpy_mod
        sys.modules["rclpy.clock"] = rclpy_mod.clock

    if "bonbon_msgs" not in sys.modules:
        bonbon_msgs = types.ModuleType("bonbon_msgs")
        bonbon_msgs_msg = types.ModuleType("bonbon_msgs.msg")

        class VoiceEmotion:
            def __init__(self):
                self.header = type("H", (), {"stamp": None})()
                self.event_id = ""
                self.source_module = ""
                self.tracking_id = 0
                self.person_id = ""
                self.segment_duration_sec = 0.0
                self.dominant_emotion = "neutral"
                self.dominant_confidence = 0.0
                self.arousal = 0.0
                self.valence = 0.5
                self.arousal_valid = False
                self.valence_valid = False
                self.neutral_score = 0.0
                self.happy_score = 0.0
                self.sad_score = 0.0
                self.angry_score = 0.0
                self.fearful_score = 0.0
                self.stressed_score = 0.0
                self.calm_score = 0.0
                self.urgent_score = 0.0
                self.confused_score = 0.0
                self.noisy_audio = False
                self.silence_detected = False
                self.short_segment = False
                self.model_failed = False
                self.backend_used = ""

        bonbon_msgs_msg.VoiceEmotion = VoiceEmotion
        bonbon_msgs.msg = bonbon_msgs_msg
        sys.modules["bonbon_msgs"] = bonbon_msgs
        sys.modules["bonbon_msgs.msg"] = bonbon_msgs_msg


_make_ros_stubs()

from bonbon_affective_ai.analyzers.voice_emotion_analyzer import VoiceEmotionAnalyzer
from bonbon_affective_ai.backends.mock_backends import MockVoiceBackend
from bonbon_affective_ai.config.affective_config import AffectiveConfig
from bonbon_affective_ai.privacy.privacy_gate import PrivacyGate


class _FakeClock:
    def now(self):
        class _T:
            def to_msg(self):
                return None

        return _T()


class TestVoiceEmotionAnalyzer(unittest.TestCase):
    """Tests for VoiceEmotionAnalyzer with MockVoiceBackend."""

    _SR = 16000  # 16 kHz

    def setUp(self) -> None:
        """Set up fresh analyzer before each test."""
        self.backend = MockVoiceBackend()
        self.backend.warmup()
        self.config = AffectiveConfig(
            voice_segment_min_sec=0.5,
            voice_confidence_threshold=0.5,
        )
        self.privacy = PrivacyGate(self.config)
        self.analyzer = VoiceEmotionAnalyzer(self.config, self.backend, self.privacy, _FakeClock())

    def _silent_audio(self, duration_sec: float = 1.0) -> np.ndarray:
        """Return a silent (zero) PCM array of the given duration."""
        return np.zeros(int(self._SR * duration_sec), dtype=np.float32)

    def _noisy_audio(self, duration_sec: float = 1.0) -> np.ndarray:
        """Return a low-amplitude noise PCM array."""
        rng = np.random.default_rng(42)
        return rng.uniform(-0.1, 0.1, int(self._SR * duration_sec)).astype(np.float32)

    # ── Field population ──────────────────────────────────────────────────────

    def test_returns_voice_emotion_message(self) -> None:
        """A VoiceEmotion message is returned for a 1-second silent array."""
        from bonbon_msgs.msg import VoiceEmotion

        msg = self.analyzer.analyze_segment(self._silent_audio(1.0), self._SR)
        self.assertIsNotNone(msg)
        self.assertIsInstance(msg, VoiceEmotion)

    def test_dominant_emotion_set(self) -> None:
        """dominant_emotion is a non-empty string."""
        msg = self.analyzer.analyze_segment(self._silent_audio(1.0), self._SR)
        self.assertIsInstance(msg.dominant_emotion, str)
        self.assertGreater(len(msg.dominant_emotion), 0)

    def test_dominant_confidence_in_range(self) -> None:
        """dominant_confidence is in [0.0, 1.0]."""
        msg = self.analyzer.analyze_segment(self._silent_audio(1.0), self._SR)
        self.assertGreaterEqual(msg.dominant_confidence, 0.0)
        self.assertLessEqual(msg.dominant_confidence, 1.0)

    def test_mock_returns_neutral(self) -> None:
        """MockVoiceBackend returns neutral dominant emotion."""
        msg = self.analyzer.analyze_segment(self._noisy_audio(1.0), self._SR)
        self.assertEqual(msg.dominant_emotion, "neutral")

    def test_mock_high_confidence(self) -> None:
        """MockVoiceBackend returns high confidence (>= 0.8)."""
        msg = self.analyzer.analyze_segment(self._noisy_audio(1.0), self._SR)
        self.assertGreaterEqual(msg.dominant_confidence, 0.8)

    def test_segment_duration_recorded(self) -> None:
        """segment_duration_sec reflects the length of the audio array."""
        audio = self._silent_audio(1.5)
        msg = self.analyzer.analyze_segment(audio, self._SR)
        self.assertAlmostEqual(msg.segment_duration_sec, 1.5, delta=0.1)

    def test_silence_detected_flag(self) -> None:
        """silence_detected is True for a zero-amplitude array."""
        msg = self.analyzer.analyze_segment(self._silent_audio(1.0), self._SR)
        self.assertTrue(msg.silence_detected)

    def test_no_silence_flag_for_noise(self) -> None:
        """silence_detected is False for a noisy array."""
        msg = self.analyzer.analyze_segment(self._noisy_audio(1.0), self._SR)
        # MockVoiceBackend sets silence_detected based on RMS in the analyzer.
        # The analyzer checks RMS before calling the backend.
        self.assertFalse(msg.silence_detected)

    def test_backend_used_field(self) -> None:
        """backend_used is populated with a non-empty string."""
        msg = self.analyzer.analyze_segment(self._noisy_audio(1.0), self._SR)
        self.assertIsInstance(msg.backend_used, str)
        self.assertGreater(len(msg.backend_used), 0)

    def test_event_id_is_uuid(self) -> None:
        """event_id is a valid UUID."""
        import uuid

        msg = self.analyzer.analyze_segment(self._noisy_audio(1.0), self._SR)
        uuid.UUID(msg.event_id)

    # ── Short segment detection ───────────────────────────────────────────────

    def test_short_segment_flag(self) -> None:
        """short_segment=True for audio shorter than voice_segment_min_sec."""
        short_audio = self._silent_audio(0.1)  # 100 ms < 500 ms minimum
        msg = self.analyzer.analyze_segment(short_audio, self._SR)
        self.assertIsNotNone(msg)
        self.assertTrue(msg.short_segment)

    def test_short_segment_model_not_failed(self) -> None:
        """Short-segment messages have model_failed=False (not an error)."""
        short_audio = self._silent_audio(0.1)
        msg = self.analyzer.analyze_segment(short_audio, self._SR)
        self.assertFalse(msg.model_failed)

    def test_long_enough_segment_not_flagged(self) -> None:
        """1-second segments are not flagged as short."""
        msg = self.analyzer.analyze_segment(self._silent_audio(1.0), self._SR)
        self.assertFalse(msg.short_segment)

    # ── Privacy gate ──────────────────────────────────────────────────────────

    def test_suppressed_privacy_returns_message(self) -> None:
        """Suppressed privacy still returns a message (zeroed)."""
        self.privacy.set_level("suppressed")
        msg = self.analyzer.analyze_segment(self._noisy_audio(1.0), self._SR)
        self.assertIsNotNone(msg)
        self.assertEqual(msg.dominant_emotion, "neutral")

    # ── Backend failure ───────────────────────────────────────────────────────

    def test_unwarmed_backend_returns_failed_msg(self) -> None:
        """Unwarmed backend produces model_failed=True."""
        fresh = MockVoiceBackend()
        analyzer = VoiceEmotionAnalyzer(self.config, fresh, self.privacy, _FakeClock())
        msg = analyzer.analyze_segment(self._noisy_audio(1.0), self._SR)
        self.assertIsNotNone(msg)
        self.assertTrue(msg.model_failed)

    # ── Score fields ──────────────────────────────────────────────────────────

    def test_score_fields_are_floats(self) -> None:
        """Individual score fields are float values in [0.0, 1.0]."""
        msg = self.analyzer.analyze_segment(self._noisy_audio(1.0), self._SR)
        for field in (
            "neutral_score",
            "happy_score",
            "sad_score",
            "angry_score",
            "fearful_score",
            "stressed_score",
            "calm_score",
            "urgent_score",
            "confused_score",
        ):
            val = getattr(msg, field)
            self.assertIsInstance(val, float)
            self.assertGreaterEqual(val, 0.0)
            self.assertLessEqual(val, 1.0)

    def test_neutral_score_highest_for_mock(self) -> None:
        """Mock backend returns neutral as the highest individual score."""
        msg = self.analyzer.analyze_segment(self._noisy_audio(1.0), self._SR)
        self.assertGreater(msg.neutral_score, 0.5)


# ── Temporal smoothing (18-point edge-AI verification, check 9) ───────────────


class _VaryingVoiceBackend:
    """Deterministic backend that alternates between two very different
    readings across calls, so smoothing's averaging effect is observable
    (MockVoiceBackend above always returns the same fixed result, which
    can't distinguish 'smoothed' from 'not smoothed')."""

    def __init__(self) -> None:
        self._ready = False
        self._call_count = 0

    def warmup(self) -> None:
        self._ready = True

    @property
    def is_ready(self) -> bool:
        return self._ready

    def analyze_segment(self, audio_array, sample_rate) -> dict:
        self._call_count += 1
        if self._call_count % 2 == 1:
            return {
                "dominant_emotion": "angry", "dominant_confidence": 1.0,
                "arousal": 0.9, "valence": 0.1, "arousal_valid": True, "valence_valid": True,
                "neutral_score": 0.0, "happy_score": 0.0, "sad_score": 0.0, "angry_score": 1.0,
                "fearful_score": 0.0, "stressed_score": 0.0, "calm_score": 0.0,
                "urgent_score": 0.0, "confused_score": 0.0,
                "noisy_audio": False, "backend_used": "varying",
            }
        return {
            "dominant_emotion": "calm", "dominant_confidence": 1.0,
            "arousal": 0.1, "valence": 0.8, "arousal_valid": True, "valence_valid": True,
            "neutral_score": 0.0, "happy_score": 0.0, "sad_score": 0.0, "angry_score": 0.0,
            "fearful_score": 0.0, "stressed_score": 0.0, "calm_score": 1.0,
            "urgent_score": 0.0, "confused_score": 0.0,
            "noisy_audio": False, "backend_used": "varying",
        }


class TestVoiceEmotionTemporalSmoothing(unittest.TestCase):
    def setUp(self) -> None:
        self.backend = _VaryingVoiceBackend()
        self.backend.warmup()
        self.config = AffectiveConfig(voice_segment_min_sec=0.5, voice_temporal_window=4)
        self.privacy = PrivacyGate(self.config)
        self.analyzer = VoiceEmotionAnalyzer(self.config, self.backend, self.privacy, _FakeClock())

    def _noisy_audio(self, duration_sec: float = 1.0) -> np.ndarray:
        rng = np.random.default_rng(42)
        return rng.uniform(-0.1, 0.1, int(16000 * duration_sec)).astype(np.float32)

    def test_scores_are_averaged_not_raw_single_frame(self) -> None:
        # Raw backend alternates angry_score 1.0/0.0 -- a smoothed reading
        # over 2 calls must land strictly between the two raw extremes,
        # never exactly 0.0 or 1.0.
        self.analyzer.analyze_segment(self._noisy_audio(), 16000)
        msg = self.analyzer.analyze_segment(self._noisy_audio(), 16000)
        self.assertGreater(msg.angry_score, 0.0)
        self.assertLess(msg.angry_score, 1.0)

    def test_dominant_emotion_label_has_no_score_suffix(self) -> None:
        msg = self.analyzer.analyze_segment(self._noisy_audio(), 16000)
        self.assertNotIn("_score", msg.dominant_emotion)

    def test_non_averaged_fields_still_pass_through(self) -> None:
        # arousal/valence/backend_used are not part of the smoother's
        # averaged field set -- confirm the merge in analyze_segment()
        # still carries them onto the outgoing message.
        msg = self.analyzer.analyze_segment(self._noisy_audio(), 16000)
        self.assertEqual(msg.backend_used, "varying")
        self.assertTrue(msg.arousal_valid)


if __name__ == "__main__":
    unittest.main()
