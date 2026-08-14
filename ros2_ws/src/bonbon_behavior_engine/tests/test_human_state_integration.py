"""Verifies BehaviorEngineNode._on_human_state / _decide_multi_person_behavior
-- the actual node-level orchestration around bonbon_human_state_fusion's
HumanState output, not just MultiPersonBehaviorSelector in isolation
(already covered by test_multi_person_behavior_selector.py's 39 tests).

Exercises the REAL unbound node methods against a lightweight fake "self"
carrying just the attributes they touch (real MultiPersonBehaviorSelector
instance, real _is_child/_dispatch_multi_person_candidate/_dispatch_proposal
logic) -- stops exactly at the _dispatch_proposal boundary (mocked here)
since ProposalEvaluator/safety-gate dispatch is a different, already-tested
unit. Needs conftest.py's rclpy/bonbon_msgs stubs to import the node class
at all.

Also regression-covers a real gap this verification pass found and fixed:
the multi-person path computed a per-rule BehaviorCandidate.tts_emotion
(warm/calm/neutral) that never reached _dispatch_tts -- every multi-person
response was spoken in a flat "neutral" tone regardless of what the rule
intended, unlike the single-person EmotionAwareResponsePlanner path which
already threaded plan.tts_emotion through correctly.
"""

from __future__ import annotations

import unittest
from dataclasses import dataclass, field
from typing import Any

from bonbon_behavior_engine.core.multi_person_behavior_selector import (
    MultiPersonBehaviorSelector,
)
from bonbon_behavior_engine.nodes.behavior_engine_node import BehaviorEngineNode
from bonbon_msgs.msg import HumanState


class _FakeLock:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _SyncExecutor:
    """Runs submitted work synchronously so tests can assert immediately."""

    def submit(self, fn, *args, **kwargs):
        fn(*args, **kwargs)

        class _Future:
            def result(self_inner):
                return None

        return _Future()


@dataclass
class _FakeBehaviorEngineSelf:
    _lock: Any = field(default_factory=_FakeLock)
    _human_states: dict = field(default_factory=dict)
    _privacy_mode: bool = False
    _executor: Any = field(default_factory=_SyncExecutor)
    _behavior_selector: MultiPersonBehaviorSelector = field(
        default_factory=MultiPersonBehaviorSelector
    )
    _person_track_raw_ids: dict = field(default_factory=dict)
    _person_categories: dict = field(default_factory=dict)
    dispatch_calls: list = field(default_factory=list)

    def _is_child(self, person_track_id: str) -> bool:
        return BehaviorEngineNode._is_child(self, person_track_id)

    def _dispatch_multi_person_candidate(self, candidate) -> None:
        return BehaviorEngineNode._dispatch_multi_person_candidate(self, candidate)

    def _dispatch_proposal(
        self,
        proposal_type,
        proposal_content,
        source,
        person_id,
        tracking_id,
        urgency,
        raw_llm_command="",
        tts_emotion="neutral",
    ) -> None:
        self.dispatch_calls.append(
            dict(
                proposal_type=proposal_type,
                content=proposal_content,
                source=source,
                person_id=person_id,
                urgency=urgency,
                tts_emotion=tts_emotion,
            )
        )

    def _on_human_state(self, msg) -> None:
        return BehaviorEngineNode._on_human_state(self, msg)

    def _decide_multi_person_behavior(self, msg, snapshot, privacy_mode) -> None:
        return BehaviorEngineNode._decide_multi_person_behavior(self, msg, snapshot, privacy_mode)


def _human_state(
    person_track_id: str,
    *,
    lifecycle_state: str = "present",
    active_speaker_status: str = "",
    urgency_level: float = 0.0,
    current_gesture: str = "none",
    known_person_id: str = "",
    emotional_state: str = "neutral",
    text_intent: str = "",
) -> HumanState:
    return HumanState(
        person_track_id=person_track_id,
        lifecycle_state=lifecycle_state,
        active_speaker_status=active_speaker_status,
        urgency_level=urgency_level,
        current_gesture=current_gesture,
        known_person_id=known_person_id,
        emotional_state=emotional_state,
        text_intent=text_intent,
    )


class TestArrivalGreetingForSoleFocusPerson(unittest.TestCase):
    def test_arrival_wave_dispatches_greeting(self):
        node = _FakeBehaviorEngineSelf()
        msg = _human_state("ptrk_1", lifecycle_state="present", current_gesture="wave")
        node._on_human_state(msg)
        self.assertEqual(len(node.dispatch_calls), 1)
        call = node.dispatch_calls[0]
        self.assertEqual(call["proposal_type"], "speak")
        self.assertEqual(call["source"], "rule1_arrival_wave")
        self.assertEqual(call["person_id"], "ptrk_1")
        self.assertEqual(call["tts_emotion"], "warm")  # regression: was silently dropped


class TestFocusPersonRouting(unittest.TestCase):
    def test_non_focus_person_update_is_not_dispatched(self):
        node = _FakeBehaviorEngineSelf()
        # Person A is speaking (the real focus); seed it directly into state.
        person_a = _human_state("ptrk_a", active_speaker_status="speaking", urgency_level=0.1)
        node._human_states["ptrk_a"] = person_a

        # Person B sends a wave update -- not the focus, not a safety gesture.
        person_b = _human_state("ptrk_b", lifecycle_state="present", current_gesture="wave")
        node._on_human_state(person_b)

        self.assertEqual(node.dispatch_calls, [])

    def test_focus_person_update_is_dispatched(self):
        node = _FakeBehaviorEngineSelf()
        person_b = _human_state("ptrk_b", active_speaker_status="", urgency_level=0.0)
        node._human_states["ptrk_b"] = person_b

        # Person A is unambiguously the most urgent present person (person B
        # stays at urgency 0.0) -> select_focus_person must pick A regardless
        # of dict insertion order, so A's own update dispatches.
        person_a = _human_state(
            "ptrk_a", lifecycle_state="present", current_gesture="wave", urgency_level=0.5
        )
        node._on_human_state(person_a)

        self.assertEqual(len(node.dispatch_calls), 1)
        self.assertEqual(node.dispatch_calls[0]["person_id"], "ptrk_a")


class TestSafetyGestureOverridesFocus(unittest.TestCase):
    def test_safety_gesture_from_non_focus_person_still_dispatches(self):
        node = _FakeBehaviorEngineSelf()
        # Person A is the focus (speaking).
        person_a = _human_state("ptrk_a", active_speaker_status="speaking", urgency_level=0.1)
        node._human_states["ptrk_a"] = person_a

        # Person B (not focus) shows a safety gesture -- must still dispatch,
        # per rule 6 ("safety gesture from ANYONE nearby").
        person_b = _human_state("ptrk_b", current_gesture="stop_palm")
        node._on_human_state(person_b)

        self.assertEqual(len(node.dispatch_calls), 1)
        call = node.dispatch_calls[0]
        self.assertEqual(call["source"], "rule6_safety_gesture")
        self.assertEqual(call["person_id"], "ptrk_b")
        self.assertEqual(call["proposal_type"], "speak")  # pause -> dispatched as speak
        self.assertEqual(call["tts_emotion"], "calm")


class TestChildSafetyModifierApplied(unittest.TestCase):
    def test_child_nearby_suffixes_source_with_child_safety(self):
        node = _FakeBehaviorEngineSelf()
        node._person_track_raw_ids["ptrk_1"] = "person_3"
        node._person_categories["person_3"] = "child"

        msg = _human_state("ptrk_1", lifecycle_state="present", current_gesture="wave")
        node._on_human_state(msg)

        self.assertEqual(len(node.dispatch_calls), 1)
        self.assertTrue(node.dispatch_calls[0]["source"].endswith("+child_safety"))

    def test_no_child_nearby_does_not_suffix_source(self):
        node = _FakeBehaviorEngineSelf()
        msg = _human_state("ptrk_1", lifecycle_state="present", current_gesture="wave")
        node._on_human_state(msg)

        self.assertEqual(len(node.dispatch_calls), 1)
        self.assertFalse(node.dispatch_calls[0]["source"].endswith("+child_safety"))


class TestLeftSceneLifecycle(unittest.TestCase):
    def test_left_scene_dispatches_then_removes_from_state(self):
        node = _FakeBehaviorEngineSelf()
        present_msg = _human_state("ptrk_1", lifecycle_state="present", current_gesture="wave")
        node._on_human_state(present_msg)
        node.dispatch_calls.clear()

        left_msg = _human_state("ptrk_1", lifecycle_state="left_scene")
        node._on_human_state(left_msg)

        self.assertEqual(len(node.dispatch_calls), 1)
        self.assertEqual(node.dispatch_calls[0]["source"], "rule3_departure")
        self.assertNotIn("ptrk_1", node._human_states)


if __name__ == "__main__":
    unittest.main()
