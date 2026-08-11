"""Tests for gesture_recognition model selection -- rule 6 (never use the
LLM for gesture recognition) enforced structurally by checking every
registered gesture_recognition entry's runtime is a real CV
model/mediapipe/mock, never an LLM runtime, plus the mediapipe default
selection and the gesture-to-emotion-state mapping
(bonbon_affective_ai.fusion.emotion_fusion_engine._gesture_to_state) that
routes gesture output onward -- itself a plain dict lookup, never an LLM
call, keeping the safety-relevant stop_palm/fallen_posture path
deterministic end-to-end."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _extra in (
    _REPO_ROOT / "ros2_ws" / "src" / "bonbon_ai_model_registry",
    _REPO_ROOT / "ros2_ws" / "src" / "bonbon_affective_ai",
):
    if str(_extra) not in sys.path:
        sys.path.insert(0, str(_extra))

REGISTRY_PATH = _REPO_ROOT / "config" / "models" / "model_registry.yaml"

_LLM_RUNTIMES = {"ollama_http"}  # every runtime string used by local_llm entries in this registry


class TestGestureRecognitionNeverRoutesThroughTheLLM(unittest.TestCase):
    def setUp(self):
        from bonbon_ai_model_registry.model_registry import ModelRegistry

        self.registry = ModelRegistry.load(REGISTRY_PATH)

    def test_no_gesture_or_pose_entry_uses_an_llm_runtime(self):
        entries = self.registry.by_capability("gesture_recognition") + self.registry.by_capability("pose_estimation")
        self.assertTrue(entries)
        for entry in entries:
            self.assertNotIn(entry.runtime, _LLM_RUNTIMES, f"{entry.model_id} uses an LLM runtime ({entry.runtime}) -- rule 6 violation")

    def test_mediapipe_holistic_is_the_default_and_is_a_real_cv_runtime(self):
        default = self.registry.default_for_capability("gesture_recognition")
        self.assertEqual(default.model_id, "gesture_mediapipe_holistic")
        self.assertEqual(default.runtime, "mediapipe")

    def test_gesture_mock_is_the_only_fallback_and_is_also_not_llm_based(self):
        chain = [e.model_id for e in self.registry.fallback_chain("gesture_mediapipe_holistic")]
        self.assertEqual(chain, ["gesture_mediapipe_holistic", "gesture_mock"])


class TestGestureToEmotionStateMappingIsDeterministic(unittest.TestCase):
    """This is the downstream consumer of gesture output in the affective
    pipeline -- confirms it is a plain lookup table, not an LLM call, so
    safety-relevant gestures resolve deterministically regardless of LLM
    availability/load."""

    def setUp(self):
        from bonbon_affective_ai.fusion.emotion_fusion_engine import EmotionFusionEngine

        self._gesture_to_state = EmotionFusionEngine._gesture_to_state

    def test_stop_palm_maps_to_urgent(self):
        self.assertEqual(self._gesture_to_state("stop_palm"), "urgent")

    def test_fallen_posture_maps_to_urgent(self):
        self.assertEqual(self._gesture_to_state("fallen_posture"), "urgent")

    def test_unknown_gesture_defaults_to_neutral_not_an_exception(self):
        self.assertEqual(self._gesture_to_state("some_never_seen_gesture_type"), "neutral")

    def test_wave_maps_to_engaged(self):
        self.assertEqual(self._gesture_to_state("wave"), "engaged")


if __name__ == "__main__":
    unittest.main()
