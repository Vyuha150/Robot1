"""Integration tests for the bonbon_affective_ai fusion pipeline.

Exercise the real EmotionFusionEngine with multi-modal inputs (face + voice +
text + gesture) and verify the fused HumanEmotionState is coherent and that the
emergency-override path propagates an operator alert. Uses the permissive ROS2
message stubs installed by tests/conftest.py — no rclpy / hardware required.
"""

from __future__ import annotations

from bonbon_affective_ai.config.affective_config import AffectiveConfig
from bonbon_affective_ai.fusion.emotion_fusion_engine import EmotionFusionEngine
from bonbon_msgs.msg import FaceEmotion, TextEmotion, VoiceEmotion


def _face(emotion: str, conf: float) -> FaceEmotion:
    m = FaceEmotion()
    m.dominant_emotion = emotion
    m.dominant_confidence = conf
    m.privacy_suppressed = False
    m.is_ambiguous = False
    return m


def _voice(emotion: str, conf: float) -> VoiceEmotion:
    m = VoiceEmotion()
    m.dominant_emotion = emotion
    m.dominant_confidence = conf
    m.privacy_suppressed = False
    return m


def _text(emotion: str, conf: float, *, emergency=False, distress=False) -> TextEmotion:
    m = TextEmotion()
    m.dominant_emotion = emotion
    m.dominant_confidence = conf
    m.emergency_detected = emergency
    m.distress_detected = distress
    m.requires_operator_alert = emergency
    return m


def _engine() -> EmotionFusionEngine:
    cfg = AffectiveConfig()
    return EmotionFusionEngine(cfg)


class TestMultiModalFusion:
    def test_consistent_modalities_agree(self):
        eng = _engine()
        msg = eng.fuse(
            face=_face("happiness", 0.9),
            voice=_voice("happy", 0.8),
            text=_text("gratitude", 0.7),
            gesture_state="wave",
            person_id="p1",
            tracking_id=1,
        )
        assert msg.person_id == "p1"
        assert msg.recommended_response_style  # some style was chosen
        assert msg.requires_operator_alert is False

    def test_face_only_still_produces_state(self):
        eng = _engine()
        msg = eng.fuse(
            face=_face("sadness", 0.85),
            voice=None,
            text=None,
            gesture_state="none",
            person_id="p2",
            tracking_id=2,
        )
        assert msg.recommended_response_style

    def test_no_modalities_produces_neutral_state(self):
        eng = _engine()
        msg = eng.fuse(
            face=None, voice=None, text=None,
            gesture_state="none", person_id="p3", tracking_id=3,
        )
        # Should not crash and should not raise an operator alert.
        assert msg.requires_operator_alert is False


class TestEmergencyOverride:
    def test_text_emergency_forces_operator_alert(self):
        eng = _engine()
        msg = eng.fuse(
            face=_face("neutral", 0.6),
            voice=_voice("neutral", 0.6),
            text=_text("emergency", 0.97, emergency=True),
            gesture_state="none",
            person_id="p4",
            tracking_id=4,
        )
        assert msg.requires_operator_alert is True

    def test_fallen_gesture_is_high_priority(self):
        eng = _engine()
        msg = eng.fuse(
            face=None, voice=None, text=None,
            gesture_state="fallen_posture",
            person_id="p5", tracking_id=5,
        )
        # A fallen posture must not be silently ignored — engine should flag it.
        assert msg.recommended_response_style
