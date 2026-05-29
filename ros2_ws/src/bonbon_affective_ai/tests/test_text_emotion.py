"""Tests for the rule-based text emotion analyzer."""

from __future__ import annotations

import sys
import types
import unittest


def _make_ros_stubs() -> None:
    """Inject minimal stub modules for rclpy and bonbon_msgs."""
    if "rclpy" not in sys.modules:
        rclpy_mod = types.ModuleType("rclpy")
        sys.modules["rclpy"] = rclpy_mod

    if "bonbon_msgs" not in sys.modules:
        bonbon_msgs = types.ModuleType("bonbon_msgs")
        bonbon_msgs_msg = types.ModuleType("bonbon_msgs.msg")

        class TextEmotion:
            def __init__(self):
                self.header = type("H", (), {"stamp": None})()
                self.event_id = ""
                self.source_module = ""
                self.tracking_id = 0
                self.person_id = ""
                self.text_snippet = ""
                self.dominant_emotion = "neutral"
                self.dominant_confidence = 0.0
                self.emergency_detected = False
                self.distress_detected = False
                self.medical_concern_detected = False
                self.safety_concern_detected = False
                self.anger_detected = False
                self.confusion_detected = False
                self.emergency_score = 0.0
                self.distress_score = 0.0
                self.confusion_score = 0.0
                self.anger_score = 0.0
                self.gratitude_score = 0.0
                self.complaint_score = 0.0
                self.request_score = 0.0
                self.medical_score = 0.0
                self.safety_score = 0.0
                self.neutral_score = 0.0
                self.backend_used = ""
                self.requires_operator_alert = False

        bonbon_msgs_msg.TextEmotion = TextEmotion
        bonbon_msgs.msg = bonbon_msgs_msg
        sys.modules["bonbon_msgs"] = bonbon_msgs
        sys.modules["bonbon_msgs.msg"] = bonbon_msgs_msg


_make_ros_stubs()

from bonbon_affective_ai.config.affective_config import AffectiveConfig
from bonbon_affective_ai.privacy.privacy_gate import PrivacyGate
from bonbon_affective_ai.analyzers.text_emotion_analyzer import TextEmotionAnalyzer


class _FakeClock:
    def now(self):
        class _T:
            def to_msg(self):
                return None
        return _T()


class TestTextEmotionAnalyzer(unittest.TestCase):
    """Tests for the rule-based TextEmotionAnalyzer."""

    def setUp(self) -> None:
        """Set up a fresh analyzer before each test."""
        self.config = AffectiveConfig(
            text_backend="rules",
            text_confidence_threshold=0.1,
        )
        self.privacy = PrivacyGate(self.config)
        self.analyzer = TextEmotionAnalyzer(self.config, self.privacy, _FakeClock())

    def _analyze(self, text: str):
        """Convenience wrapper for analyze_text."""
        return self.analyzer.analyze_text(text, person_id="p1", tracking_id=1)

    # ── Emergency detection ───────────────────────────────────────────────────

    def test_emergency_fallen(self) -> None:
        """'I need help, I fell down' triggers emergency_detected=True."""
        msg = self._analyze("I need help, I fell down")
        self.assertTrue(msg.emergency_detected)

    def test_emergency_requires_operator_alert(self) -> None:
        """Emergency text sets requires_operator_alert=True."""
        msg = self._analyze("I need help, I fell down")
        self.assertTrue(msg.requires_operator_alert)

    def test_emergency_dominant_emotion(self) -> None:
        """Emergency text yields 'emergency' as dominant_emotion."""
        msg = self._analyze("I need help, I fell down")
        self.assertEqual(msg.dominant_emotion, "emergency")

    def test_emergency_score_positive(self) -> None:
        """Emergency score is greater than 0 for emergency text."""
        msg = self._analyze("I need help, I fell down")
        self.assertGreater(msg.emergency_score, 0.0)

    def test_pain_triggers_emergency(self) -> None:
        """'I'm in a lot of pain, please help' triggers emergency."""
        msg = self._analyze("I'm in a lot of pain, please help")
        self.assertTrue(msg.emergency_detected)

    # ── Gratitude detection ───────────────────────────────────────────────────

    def test_gratitude_dominant(self) -> None:
        """'Thank you so much!' yields dominant_emotion='gratitude'."""
        msg = self._analyze("Thank you so much!")
        self.assertEqual(msg.dominant_emotion, "gratitude")

    def test_gratitude_score_positive(self) -> None:
        """Gratitude score > 0 for thank-you text."""
        msg = self._analyze("Thank you so much!")
        self.assertGreater(msg.gratitude_score, 0.0)

    def test_excellent_gratitude(self) -> None:
        """'That was excellent, I really appreciate it' is gratitude."""
        msg = self._analyze("That was excellent, I really appreciate it")
        self.assertEqual(msg.dominant_emotion, "gratitude")

    # ── Confusion detection ───────────────────────────────────────────────────

    def test_confusion_dominant(self) -> None:
        """'I'm confused, I don't understand' → dominant_emotion='confusion'."""
        msg = self._analyze("I'm confused, I don't understand")
        self.assertEqual(msg.dominant_emotion, "confusion")

    def test_confusion_score_positive(self) -> None:
        """Confusion score > 0 for confused text."""
        msg = self._analyze("I'm confused, I don't understand")
        self.assertGreater(msg.confusion_score, 0.0)

    def test_confusion_flag_set(self) -> None:
        """confusion_detected flag is True for confused text."""
        msg = self._analyze("I'm confused, I don't understand")
        self.assertTrue(msg.confusion_detected)

    # ── Anger detection ───────────────────────────────────────────────────────

    def test_anger_dominant(self) -> None:
        """'This is unacceptable, I'm angry!' → dominant_emotion='anger'."""
        msg = self._analyze("This is unacceptable, I'm angry!")
        self.assertEqual(msg.dominant_emotion, "anger")

    def test_anger_score_positive(self) -> None:
        """Anger score > 0 for angry text."""
        msg = self._analyze("This is unacceptable, I'm angry!")
        self.assertGreater(msg.anger_score, 0.0)

    def test_anger_flag_set(self) -> None:
        """anger_detected flag is True for angry text."""
        msg = self._analyze("This is unacceptable, I'm angry!")
        self.assertTrue(msg.anger_detected)

    # ── Neutral detection ─────────────────────────────────────────────────────

    def test_neutral_hello(self) -> None:
        """'Hello' → dominant_emotion='neutral'."""
        msg = self._analyze("Hello")
        self.assertEqual(msg.dominant_emotion, "neutral")

    def test_neutral_no_emergency(self) -> None:
        """'Hello' does not trigger any alert flags."""
        msg = self._analyze("Hello")
        self.assertFalse(msg.emergency_detected)
        self.assertFalse(msg.requires_operator_alert)

    # ── Field validation ──────────────────────────────────────────────────────

    def test_text_snippet_truncated_to_200(self) -> None:
        """text_snippet is at most 200 characters."""
        long_text = "word " * 100
        msg = self._analyze(long_text)
        self.assertLessEqual(len(msg.text_snippet), 200)

    def test_event_id_is_uuid(self) -> None:
        """event_id is a valid UUID."""
        import uuid
        msg = self._analyze("Hello")
        uuid.UUID(msg.event_id)

    def test_backend_used_is_rules(self) -> None:
        """backend_used is 'rules' for the rule-based analyzer."""
        msg = self._analyze("Hello")
        self.assertEqual(msg.backend_used, "rules")

    def test_confidence_in_range(self) -> None:
        """dominant_confidence is in [0.0, 1.0]."""
        msg = self._analyze("I'm confused, I don't understand")
        self.assertGreaterEqual(msg.dominant_confidence, 0.0)
        self.assertLessEqual(msg.dominant_confidence, 1.0)

    # ── Medical concern ───────────────────────────────────────────────────────

    def test_medical_concern_detected(self) -> None:
        """Medical keywords trigger medical_concern_detected=True."""
        msg = self._analyze("I need to see a doctor about my medication")
        self.assertTrue(msg.medical_concern_detected)
        self.assertGreater(msg.medical_score, 0.0)

    # ── Privacy suppression ───────────────────────────────────────────────────

    def test_suppressed_privacy_returns_neutral(self) -> None:
        """Privacy suppression returns a neutral message."""
        self.privacy.set_level("suppressed")
        msg = self._analyze("I need help, I fell down")
        self.assertEqual(msg.dominant_emotion, "neutral")
        self.assertFalse(msg.emergency_detected)

    def test_suppressed_privacy_no_alert(self) -> None:
        """Privacy suppression clears requires_operator_alert."""
        self.privacy.set_level("suppressed")
        msg = self._analyze("I need help emergency")
        self.assertFalse(msg.requires_operator_alert)


if __name__ == "__main__":
    unittest.main()
