"""Tests for the EmotionFusionEngine."""

from __future__ import annotations

import sys
import types
import unittest


def _make_ros_stubs() -> None:
    """Inject minimal stubs for rclpy and bonbon_msgs."""
    if "rclpy" not in sys.modules:
        rclpy_mod = types.ModuleType("rclpy")
        sys.modules["rclpy"] = rclpy_mod

    if "bonbon_msgs" not in sys.modules:
        bonbon_msgs = types.ModuleType("bonbon_msgs")
        bonbon_msgs_msg = types.ModuleType("bonbon_msgs.msg")

        class HumanEmotionState:
            def __init__(self):
                self.header = type("H", (), {"stamp": None})()
                self.event_id = ""
                self.source_module = ""
                self.person_id = ""
                self.tracking_id = 0
                self.dominant_state = "neutral"
                self.dominant_confidence = 0.0
                self.is_stable = False
                self.face_contribution = 0.0
                self.voice_contribution = 0.0
                self.text_contribution = 0.0
                self.gesture_contribution = 0.0
                self.face_available = False
                self.voice_available = False
                self.text_available = False
                self.gesture_available = False
                self.recommended_response_style = "normal"
                self.recommended_distance_m = 1.0
                self.requires_operator_alert = False
                self.suggested_tts_emotion = "neutral"
                self.interaction_patience_multiplier = 1.0
                self.state_duration_sec = 0
                self.state_change_count_last_60s = 0
                self.previous_state = ""

            # Allow header stamp assignment.

        class FaceEmotion:
            def __init__(self):
                self.dominant_emotion = "neutral"
                self.dominant_confidence = 0.0
                self.privacy_suppressed = False
                self.low_quality_input = False

        class VoiceEmotion:
            def __init__(self):
                self.dominant_emotion = "neutral"
                self.dominant_confidence = 0.0
                self.model_failed = False

        class TextEmotion:
            def __init__(self):
                self.dominant_emotion = "neutral"
                self.dominant_confidence = 0.0
                self.emergency_detected = False
                self.distress_detected = False
                self.safety_concern_detected = False

        bonbon_msgs_msg.HumanEmotionState = HumanEmotionState
        bonbon_msgs_msg.FaceEmotion = FaceEmotion
        bonbon_msgs_msg.VoiceEmotion = VoiceEmotion
        bonbon_msgs_msg.TextEmotion = TextEmotion
        bonbon_msgs.msg = bonbon_msgs_msg
        sys.modules["bonbon_msgs"] = bonbon_msgs
        sys.modules["bonbon_msgs.msg"] = bonbon_msgs_msg


_make_ros_stubs()

from bonbon_msgs.msg import FaceEmotion, VoiceEmotion, TextEmotion  # type: ignore[import]
from bonbon_affective_ai.config.affective_config import AffectiveConfig
from bonbon_affective_ai.fusion.emotion_fusion_engine import EmotionFusionEngine


def _make_angry_face() -> FaceEmotion:
    """Return a FaceEmotion stub with angry dominant emotion."""
    msg = FaceEmotion()
    msg.dominant_emotion = "anger"
    msg.dominant_confidence = 0.85
    msg.privacy_suppressed = False
    msg.low_quality_input = False
    return msg


def _make_angry_voice() -> VoiceEmotion:
    """Return a VoiceEmotion stub with angry dominant emotion."""
    msg = VoiceEmotion()
    msg.dominant_emotion = "angry"
    msg.dominant_confidence = 0.75
    msg.model_failed = False
    return msg


def _make_complaint_text() -> TextEmotion:
    """Return a TextEmotion stub with complaint/anger dominant."""
    msg = TextEmotion()
    msg.dominant_emotion = "anger"
    msg.dominant_confidence = 0.70
    msg.emergency_detected = False
    msg.distress_detected = False
    msg.safety_concern_detected = False
    return msg


def _make_emergency_text() -> TextEmotion:
    """Return a TextEmotion stub flagged as emergency."""
    msg = TextEmotion()
    msg.dominant_emotion = "emergency"
    msg.dominant_confidence = 0.95
    msg.emergency_detected = True
    msg.distress_detected = True
    msg.safety_concern_detected = False
    return msg


def _make_happy_face() -> FaceEmotion:
    """Return a FaceEmotion stub with happy dominant emotion."""
    msg = FaceEmotion()
    msg.dominant_emotion = "happiness"
    msg.dominant_confidence = 0.80
    msg.privacy_suppressed = False
    msg.low_quality_input = False
    return msg


class TestEmotionFusionEngine(unittest.TestCase):
    """Tests for EmotionFusionEngine fusion logic."""

    def setUp(self) -> None:
        """Create a fresh engine with default config."""
        self.config = AffectiveConfig(
            fusion_face_weight=0.4,
            fusion_voice_weight=0.35,
            fusion_text_weight=0.15,
            fusion_gesture_weight=0.10,
            state_stability_window=3,
        )
        self.engine = EmotionFusionEngine(self.config)

    def _fuse(self, face=None, voice=None, text=None, gesture="none",
              person_id="p1", tracking_id=1):
        """Convenience wrapper for engine.fuse."""
        return self.engine.fuse(face, voice, text, gesture, person_id, tracking_id)

    # ── Angry face + angry voice + complaint text → frustrated ───────────────

    def test_angry_triple_gives_frustrated_state(self) -> None:
        """Angry face + angry voice + complaint text → 'frustrated' state."""
        msg = self._fuse(
            face=_make_angry_face(),
            voice=_make_angry_voice(),
            text=_make_complaint_text(),
        )
        self.assertEqual(msg.dominant_state, "frustrated")

    def test_angry_triple_gives_apologetic_style(self) -> None:
        """Frustrated state maps to 'apologetic' response style."""
        msg = self._fuse(
            face=_make_angry_face(),
            voice=_make_angry_voice(),
            text=_make_complaint_text(),
        )
        self.assertEqual(msg.recommended_response_style, "apologetic")

    def test_angry_triple_gives_increased_distance(self) -> None:
        """Frustrated/angry state increases recommended distance beyond 1.0 m."""
        msg = self._fuse(
            face=_make_angry_face(),
            voice=_make_angry_voice(),
            text=_make_complaint_text(),
        )
        self.assertGreater(msg.recommended_distance_m, 1.0)

    def test_angry_triple_face_contribution_positive(self) -> None:
        """Face modality contributes to the fused result."""
        msg = self._fuse(
            face=_make_angry_face(),
            voice=_make_angry_voice(),
            text=_make_complaint_text(),
        )
        self.assertGreater(msg.face_contribution, 0.0)

    def test_angry_triple_voice_contribution_positive(self) -> None:
        """Voice modality contributes to the fused result."""
        msg = self._fuse(
            face=_make_angry_face(),
            voice=_make_angry_voice(),
            text=_make_complaint_text(),
        )
        self.assertGreater(msg.voice_contribution, 0.0)

    def test_angry_triple_text_contribution_positive(self) -> None:
        """Text modality contributes to the fused result."""
        msg = self._fuse(
            face=_make_angry_face(),
            voice=_make_angry_voice(),
            text=_make_complaint_text(),
        )
        self.assertGreater(msg.text_contribution, 0.0)

    # ── Emergency text overrides happy face → urgent ──────────────────────────

    def test_emergency_overrides_happy_face(self) -> None:
        """Emergency text overrides a happy face to produce 'urgent' state."""
        msg = self._fuse(
            face=_make_happy_face(),
            text=_make_emergency_text(),
        )
        self.assertEqual(msg.dominant_state, "urgent")

    def test_emergency_sets_operator_alert(self) -> None:
        """Emergency signal sets requires_operator_alert=True."""
        msg = self._fuse(
            face=_make_happy_face(),
            text=_make_emergency_text(),
        )
        self.assertTrue(msg.requires_operator_alert)

    def test_emergency_style_is_emergency_clear(self) -> None:
        """Emergency/urgent state maps to 'emergency_clear' response style."""
        msg = self._fuse(text=_make_emergency_text())
        self.assertEqual(msg.recommended_response_style, "emergency_clear")

    def test_emergency_confidence_is_max(self) -> None:
        """Emergency override yields dominant_confidence=1.0."""
        msg = self._fuse(text=_make_emergency_text())
        self.assertAlmostEqual(msg.dominant_confidence, 1.0, places=5)

    # ── Neutral baseline ──────────────────────────────────────────────────────

    def test_all_none_gives_neutral(self) -> None:
        """No modality inputs produce 'neutral' state."""
        msg = self._fuse()
        self.assertEqual(msg.dominant_state, "neutral")

    def test_all_none_no_alert(self) -> None:
        """No inputs → no operator alert."""
        msg = self._fuse()
        self.assertFalse(msg.requires_operator_alert)

    # ── Availability flags ────────────────────────────────────────────────────

    def test_face_available_flag(self) -> None:
        """face_available=True when a non-suppressed face message is provided."""
        msg = self._fuse(face=_make_happy_face())
        self.assertTrue(msg.face_available)

    def test_face_not_available_when_none(self) -> None:
        """face_available=False when face is None."""
        msg = self._fuse()
        self.assertFalse(msg.face_available)

    def test_text_available_flag(self) -> None:
        """text_available=True when a text message is provided."""
        msg = self._fuse(text=_make_complaint_text())
        self.assertTrue(msg.text_available)

    # ── Field validation ──────────────────────────────────────────────────────

    def test_event_id_is_uuid(self) -> None:
        """event_id is a valid UUID."""
        import uuid
        msg = self._fuse()
        uuid.UUID(msg.event_id)

    def test_person_id_preserved(self) -> None:
        """person_id is passed through to the output message."""
        msg = self._fuse(person_id="person_007")
        self.assertEqual(msg.person_id, "person_007")

    def test_tracking_id_preserved(self) -> None:
        """tracking_id is passed through to the output message."""
        msg = self._fuse(tracking_id=99)
        self.assertEqual(msg.tracking_id, 99)

    def test_confidence_in_range(self) -> None:
        """dominant_confidence is always in [0.0, 1.0]."""
        msg = self._fuse(face=_make_angry_face(), voice=_make_angry_voice())
        self.assertGreaterEqual(msg.dominant_confidence, 0.0)
        self.assertLessEqual(msg.dominant_confidence, 1.0)

    def test_gesture_fallen_posture_is_urgent(self) -> None:
        """fallen_posture gesture overrides to 'urgent' with operator alert."""
        msg = self._fuse(gesture="fallen_posture")
        self.assertEqual(msg.dominant_state, "urgent")
        self.assertTrue(msg.requires_operator_alert)

    def test_stability_after_repeated_same_state(self) -> None:
        """is_stable becomes True after state_stability_window consistent calls."""
        for _ in range(self.config.state_stability_window):
            msg = self._fuse(face=_make_happy_face(), person_id="stable_p")
        self.assertTrue(msg.is_stable)

    def test_tts_emotion_set(self) -> None:
        """suggested_tts_emotion is a non-empty string."""
        msg = self._fuse()
        self.assertIsInstance(msg.suggested_tts_emotion, str)
        self.assertGreater(len(msg.suggested_tts_emotion), 0)

    def test_patience_multiplier_set(self) -> None:
        """interaction_patience_multiplier is a positive float."""
        msg = self._fuse()
        self.assertGreater(msg.interaction_patience_multiplier, 0.0)


if __name__ == "__main__":
    unittest.main()
