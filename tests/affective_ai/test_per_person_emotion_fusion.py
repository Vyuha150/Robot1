"""Tests for bonbon_affective_ai.fusion.emotion_fusion_engine -- per-person
emotion fusion (rule 6: dedicated face/voice/gesture models, never the
LLM) and the GAP-1 fix (DeepFace/SpeechBrain now enabled_by_default and
present in requirements/pi2_requirements.txt, not silently mock-only).

EmotionFusionEngine.fuse() itself constructs a real ROS2
bonbon_msgs.msg.HumanEmotionState message, which requires a colcon-built,
sourced ROS2 workspace (rosidl-generated message classes aren't plain-
importable Python) -- unavailable in this sandbox. Per rule 10, that path
is honestly marked rclpy_gated and SKIPped rather than faked. The private
weighted-voting/contribution/gesture-mapping helpers underneath it are
pure Python with no ROS2 dependency and are exercised directly and fully
here -- this is what actually determines per-person fusion correctness;
fuse() only wraps the result in a message envelope."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _extra in (
    _REPO_ROOT / "ros2_ws" / "src" / "bonbon_affective_ai",
    _REPO_ROOT / "ros2_ws" / "src" / "bonbon_ai_model_registry",
):
    if str(_extra) not in sys.path:
        sys.path.insert(0, str(_extra))

REGISTRY_PATH = _REPO_ROOT / "config" / "models" / "model_registry.yaml"

rclpy_gated = pytest.mark.skipif(
    importlib.util.find_spec("bonbon_msgs") is None,
    reason="bonbon_msgs is a colcon-generated ROS2 interface package, not plain-importable outside a sourced/built workspace -- BLOCKED, not failed.",
)


def _face(emotion="happiness", confidence=0.8, suppressed=False):
    return SimpleNamespace(
        dominant_emotion=emotion, dominant_confidence=confidence, privacy_suppressed=suppressed
    )


def _voice(emotion="calm", confidence=0.6, failed=False):
    return SimpleNamespace(
        dominant_emotion=emotion, dominant_confidence=confidence, model_failed=failed
    )


def _text(emotion="neutral", confidence=0.5, emergency=False, distress=False, safety=False):
    return SimpleNamespace(
        dominant_emotion=emotion,
        dominant_confidence=confidence,
        emergency_detected=emergency,
        distress_detected=distress,
        safety_concern_detected=safety,
    )


class TestPerPersonFusionIsIndependentAcrossPeople(unittest.TestCase):
    """The engine keeps per-person state (_state_history, _previous_state,
    etc, all keyed by person_id) -- these tests exercise the pure-Python
    weighted-voting math with two DIFFERENT people's signals and confirm
    neither computation leaks into or depends on the other."""

    def setUp(self):
        from bonbon_affective_ai.config.affective_config import AffectiveConfig
        from bonbon_affective_ai.fusion.emotion_fusion_engine import EmotionFusionEngine

        self.engine = EmotionFusionEngine(AffectiveConfig())

    def test_two_people_with_different_face_emotions_compute_independent_states(self):
        state_a, conf_a = self.engine._compute_weighted_state(
            _face("happiness", 0.9), None, None, "none"
        )
        state_b, conf_b = self.engine._compute_weighted_state(
            _face("anger", 0.9), None, None, "none"
        )
        self.assertEqual(state_a, "happy")
        # "anger" maps to the "angry" state, not "frustrated" -- see
        # emotion_fusion_engine.EMOTION_TO_STATE's own comment
        # (docs/MULTI_HUMAN_EMOTION_FAILURE_ANALYSIS.md Phase 4 fix).
        self.assertEqual(state_b, "angry")
        self.assertNotEqual(state_a, state_b)

    def test_state_history_dict_is_keyed_per_person_not_shared(self):
        history_a = self.engine._state_history["person_A"]
        history_b = self.engine._state_history["person_B"]
        history_a.append("happy")
        self.assertEqual(list(history_a), ["happy"])
        self.assertEqual(
            list(history_b), [], "person_B's history must not see person_A's appended state"
        )


class TestWeightedVotingAcrossModalities(unittest.TestCase):
    def setUp(self):
        from bonbon_affective_ai.config.affective_config import AffectiveConfig
        from bonbon_affective_ai.fusion.emotion_fusion_engine import EmotionFusionEngine

        self.engine = EmotionFusionEngine(AffectiveConfig())

    def test_no_modalities_available_defaults_to_neutral_zero_confidence(self):
        state, conf = self.engine._compute_weighted_state(None, None, None, "none")
        self.assertEqual(state, "neutral")
        self.assertEqual(conf, 0.0)

    def test_privacy_suppressed_face_is_excluded_from_voting(self):
        state, conf = self.engine._compute_weighted_state(
            _face("happiness", 0.99, suppressed=True), None, None, "none"
        )
        self.assertEqual(
            state, "neutral"
        )  # face vote excluded -> falls back to no signal -> neutral

    def test_failed_voice_model_is_excluded_from_voting(self):
        state, _ = self.engine._compute_weighted_state(
            None, _voice("angry", 0.99, failed=True), None, "none"
        )
        self.assertEqual(state, "neutral")

    def test_gesture_alone_contributes_a_vote(self):
        state, conf = self.engine._compute_weighted_state(None, None, None, "stop_palm")
        self.assertEqual(state, "urgent")
        self.assertGreater(conf, 0.0)


class TestContributionScoresNormalizeToOne(unittest.TestCase):
    def setUp(self):
        from bonbon_affective_ai.config.affective_config import AffectiveConfig
        from bonbon_affective_ai.fusion.emotion_fusion_engine import EmotionFusionEngine

        self.engine = EmotionFusionEngine(AffectiveConfig())

    def test_contributions_sum_to_approximately_one_when_all_modalities_present(self):
        face_c, voice_c, text_c, gesture_c = self.engine._contribution_scores(
            _face("happiness", 0.8), _voice("calm", 0.6), _text("neutral", 0.5), "wave"
        )
        total = face_c + voice_c + text_c + gesture_c
        self.assertAlmostEqual(total, 1.0, places=5)

    def test_all_zero_confidence_and_no_gesture_returns_all_zero_not_a_divide_by_zero_crash(self):
        result = self.engine._contribution_scores(None, None, None, "none")
        self.assertEqual(result, (0.0, 0.0, 0.0, 0.0))


class TestRegistryEnablesRealBackendsNotMockByDefault(unittest.TestCase):
    """Regression coverage for GAP-1: DeepFace/SpeechBrain were the code's
    de facto runtime default but missing from pi2_requirements.txt, which
    would have silently fallen back to mock on a real Pi install. Fixed
    this session in both the requirements file and this registry flag."""

    def setUp(self):
        from bonbon_ai_model_registry.model_registry import ModelRegistry

        self.registry = ModelRegistry.load(REGISTRY_PATH)

    def test_face_emotion_default_is_deepface_not_mock(self):
        default = self.registry.default_for_capability("face_emotion")
        self.assertEqual(default.model_id, "emotion_face_deepface")

    def test_voice_emotion_default_is_speechbrain_not_mock(self):
        default = self.registry.default_for_capability("voice_emotion")
        self.assertEqual(default.model_id, "voice_emotion_speechbrain")

    def test_deepface_and_speechbrain_are_declared_in_pi2_requirements(self):
        req_path = _REPO_ROOT / "requirements" / "pi2_requirements.txt"
        text = req_path.read_text(encoding="utf-8").lower()
        self.assertIn("deepface", text)
        self.assertIn("speechbrain", text)

    def test_no_gesture_or_emotion_capability_defaults_to_an_llm_runtime(self):
        for cap in ("face_emotion", "voice_emotion", "gesture_recognition"):
            entry = self.registry.default_for_capability(cap)
            self.assertIsNotNone(entry)
            self.assertNotEqual(
                entry.runtime,
                "ollama_http",
                f"{cap} default {entry.model_id} must not be LLM-routed -- rule 6",
            )


class TestFuseProducesARealMessage(unittest.TestCase):
    @rclpy_gated
    def test_fuse_emergency_gesture_overrides_to_urgent(self):
        from bonbon_affective_ai.config.affective_config import AffectiveConfig
        from bonbon_affective_ai.fusion.emotion_fusion_engine import EmotionFusionEngine

        engine = EmotionFusionEngine(AffectiveConfig())
        msg = engine.fuse(_face("happiness", 0.9), None, None, "fallen_posture", "person_1", 1)
        self.assertEqual(msg.dominant_state, "urgent")
        self.assertTrue(msg.requires_operator_alert)


if __name__ == "__main__":
    unittest.main()
