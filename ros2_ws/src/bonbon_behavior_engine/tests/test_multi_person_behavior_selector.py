"""Tests for MultiPersonBehaviorSelector — the 10 example behaviors from the
project brief, plus focus-person selection across multiple simultaneous people.
"""

from __future__ import annotations

from dataclasses import dataclass

from bonbon_behavior_engine.core.multi_person_behavior_selector import (
    MultiPersonBehaviorSelector,
    apply_child_safety_modifier,
    select_focus_person,
)


@dataclass
class _HS:
    person_track_id: str = "ptrk_1"
    known_person_id: str = ""
    lifecycle_state: str = "present"
    active_speaker_status: str = "silent"
    current_gesture: str = "none"
    emotional_state: str = "neutral"
    text_intent: str = ""
    urgency_level: float = 0.0


class TestFocusPersonSelection:
    def test_no_one_present_returns_empty(self):
        assert select_focus_person([]) == ""

    def test_single_present_person_is_focus(self):
        assert select_focus_person([_HS("ptrk_1")]) == "ptrk_1"

    def test_speaking_person_wins_over_silent(self):
        people = [
            _HS("ptrk_1", active_speaker_status="silent"),
            _HS("ptrk_2", active_speaker_status="speaking"),
        ]
        assert select_focus_person(people) == "ptrk_2"

    def test_two_speakers_higher_urgency_wins(self):
        """Rule 5: multiple people speak -> focus on (the more urgent) active speaker."""
        people = [
            _HS("ptrk_1", active_speaker_status="speaking", urgency_level=0.2),
            _HS("ptrk_2", active_speaker_status="speaking", urgency_level=0.8),
        ]
        assert select_focus_person(people) == "ptrk_2"

    def test_active_interaction_beats_plain_present(self):
        people = [
            _HS("ptrk_1", lifecycle_state="present"),
            _HS("ptrk_2", lifecycle_state="active_interaction"),
        ]
        assert select_focus_person(people) == "ptrk_2"

    def test_left_scene_people_excluded_from_focus(self):
        people = [
            _HS("ptrk_1", lifecycle_state="left_scene"),
            _HS("ptrk_2", lifecycle_state="present"),
        ]
        assert select_focus_person(people) == "ptrk_2"

    def test_all_left_scene_returns_empty(self):
        people = [_HS("ptrk_1", lifecycle_state="left_scene")]
        assert select_focus_person(people) == ""

    def test_high_urgency_silent_person_still_gets_focus(self):
        people = [_HS("ptrk_1", urgency_level=0.0), _HS("ptrk_2", urgency_level=0.9)]
        assert select_focus_person(people) == "ptrk_2"


class TestRule1ArrivalGreeting:
    def test_present_with_wave_triggers_greeting(self):
        sel = MultiPersonBehaviorSelector()
        hs = _HS("ptrk_1", lifecycle_state="present", current_gesture="wave")
        candidate = sel.decide_arrival_greeting(hs)
        assert candidate is not None
        assert candidate.proposal_type == "speak"
        assert "Hello" in candidate.content

    def test_present_without_wave_does_not_greet(self):
        sel = MultiPersonBehaviorSelector()
        hs = _HS("ptrk_1", lifecycle_state="present", current_gesture="none")
        assert sel.decide_arrival_greeting(hs) is None

    def test_only_greets_once_per_person(self):
        sel = MultiPersonBehaviorSelector()
        hs = _HS("ptrk_1", lifecycle_state="present", current_gesture="wave")
        first = sel.decide_arrival_greeting(hs)
        second = sel.decide_arrival_greeting(hs)
        assert first is not None
        assert second is None

    def test_reappeared_with_wave_also_greets(self):
        sel = MultiPersonBehaviorSelector()
        hs = _HS("ptrk_1", lifecycle_state="reappeared", current_gesture="wave")
        assert sel.decide_arrival_greeting(hs) is not None

    def test_forget_allows_re_greeting_a_genuinely_new_arrival(self):
        """Rule 4: a brand new person reusing a freed-up scenario must not be
        silently skipped just because some OTHER earlier person_track_id was
        already greeted — forget() is keyed per person_track_id."""
        sel = MultiPersonBehaviorSelector()
        hs1 = _HS("ptrk_1", lifecycle_state="present", current_gesture="wave")
        sel.decide_arrival_greeting(hs1)
        sel.forget("ptrk_1")
        hs2 = _HS("ptrk_2", lifecycle_state="present", current_gesture="wave")
        assert sel.decide_arrival_greeting(hs2) is not None


class TestRule2KnownPersonGreeting:
    def test_known_person_speaking_greeted_by_name(self):
        sel = MultiPersonBehaviorSelector()
        hs = _HS("ptrk_1", known_person_id="bob", active_speaker_status="speaking")
        candidate = sel.decide_known_person_greeting(hs, privacy_allows_name=True)
        assert candidate is not None
        assert "bob" in candidate.content

    def test_privacy_mode_suppresses_name(self):
        sel = MultiPersonBehaviorSelector()
        hs = _HS("ptrk_1", known_person_id="bob", active_speaker_status="speaking")
        assert sel.decide_known_person_greeting(hs, privacy_allows_name=False) is None

    def test_unknown_person_never_greeted_by_name(self):
        sel = MultiPersonBehaviorSelector()
        hs = _HS("ptrk_1", known_person_id="", active_speaker_status="speaking")
        assert sel.decide_known_person_greeting(hs, privacy_allows_name=True) is None

    def test_silent_known_person_not_greeted(self):
        sel = MultiPersonBehaviorSelector()
        hs = _HS("ptrk_1", known_person_id="bob", active_speaker_status="silent")
        assert sel.decide_known_person_greeting(hs, privacy_allows_name=True) is None

    def test_only_greeted_by_name_once_per_session(self):
        sel = MultiPersonBehaviorSelector()
        hs = _HS("ptrk_1", known_person_id="bob", active_speaker_status="speaking")
        first = sel.decide_known_person_greeting(hs, privacy_allows_name=True)
        second = sel.decide_known_person_greeting(hs, privacy_allows_name=True)
        assert first is not None
        assert second is None


class TestRule3DepartureClosesSession:
    def test_left_scene_triggers_close_session_candidate(self):
        sel = MultiPersonBehaviorSelector()
        hs = _HS("ptrk_1", lifecycle_state="left_scene")
        candidate = sel.decide_departure_close_session(hs)
        assert candidate is not None
        assert candidate.source == "rule3_departure"

    def test_present_person_does_not_trigger_departure(self):
        sel = MultiPersonBehaviorSelector()
        hs = _HS("ptrk_1", lifecycle_state="present")
        assert sel.decide_departure_close_session(hs) is None

    def test_departure_forgets_greeting_state(self):
        sel = MultiPersonBehaviorSelector()
        wave_hs = _HS("ptrk_1", lifecycle_state="present", current_gesture="wave")
        sel.decide_arrival_greeting(wave_hs)
        sel.decide_departure_close_session(_HS("ptrk_1", lifecycle_state="left_scene"))
        # Same person_track_id "returning" (e.g. recall-buffer scenario) can be
        # greeted again as a fresh arrival rather than silently suppressed.
        assert sel.decide_arrival_greeting(wave_hs) is not None


class TestRule6SafetyGestureFromAnyone:
    def test_safety_gesture_from_non_focus_person_still_triggers_pause(self):
        sel = MultiPersonBehaviorSelector()
        people = [
            _HS("ptrk_1", active_speaker_status="speaking"),
            _HS("ptrk_2", current_gesture="stop_palm"),
        ]
        candidate = sel.decide_safety_gesture_response(people)
        assert candidate is not None
        assert candidate.proposal_type == "pause"
        assert candidate.person_track_id == "ptrk_2"
        assert candidate.urgency == 1.0

    def test_raised_hand_also_triggers_pause(self):
        sel = MultiPersonBehaviorSelector()
        candidate = sel.decide_safety_gesture_response(
            [_HS("ptrk_1", current_gesture="raised_hand")]
        )
        assert candidate is not None

    def test_no_safety_gesture_no_pause(self):
        sel = MultiPersonBehaviorSelector()
        candidate = sel.decide_safety_gesture_response([_HS("ptrk_1", current_gesture="wave")])
        assert candidate is None

    def test_left_scene_person_gesture_ignored(self):
        sel = MultiPersonBehaviorSelector()
        people = [_HS("ptrk_1", lifecycle_state="left_scene", current_gesture="stop_palm")]
        assert sel.decide_safety_gesture_response(people) is None


class TestRule7CalmSupportiveResponse:
    def test_angry_triggers_calm_response(self):
        sel = MultiPersonBehaviorSelector()
        hs = _HS("ptrk_1", emotional_state="angry")
        candidate = sel.decide_calm_supportive_response(hs)
        assert candidate is not None
        assert candidate.tts_emotion == "calm"

    def test_frustrated_triggers_calm_response(self):
        sel = MultiPersonBehaviorSelector()
        hs = _HS("ptrk_1", emotional_state="frustrated")
        assert sel.decide_calm_supportive_response(hs) is not None

    def test_neutral_does_not_trigger(self):
        sel = MultiPersonBehaviorSelector()
        hs = _HS("ptrk_1", emotional_state="neutral")
        assert sel.decide_calm_supportive_response(hs) is None

    def test_distressed_and_fearful_excluded_to_avoid_double_dispatch(self):
        """These are exclusively handled by the older single-focus
        HumanEmotionState path — must not also fire here."""
        sel = MultiPersonBehaviorSelector()
        assert (
            sel.decide_calm_supportive_response(_HS("ptrk_1", emotional_state="distressed")) is None
        )
        assert sel.decide_calm_supportive_response(_HS("ptrk_1", emotional_state="fearful")) is None


class TestRule8ConfusedQuestion:
    def test_confused_plus_question_triggers_slow_explanation(self):
        sel = MultiPersonBehaviorSelector()
        hs = _HS("ptrk_1", emotional_state="confused", text_intent="ask_question")
        candidate = sel.decide_confused_question_response(hs)
        assert candidate is not None
        assert candidate.speed_scale < 1.0

    def test_confused_without_question_does_not_trigger(self):
        sel = MultiPersonBehaviorSelector()
        hs = _HS("ptrk_1", emotional_state="confused", text_intent="")
        assert sel.decide_confused_question_response(hs) is None

    def test_question_without_confusion_does_not_trigger(self):
        sel = MultiPersonBehaviorSelector()
        hs = _HS("ptrk_1", emotional_state="neutral", text_intent="ask_question")
        assert sel.decide_confused_question_response(hs) is None


class TestRule10PointingConfirmation:
    def test_pointing_left_asks_confirmation(self):
        sel = MultiPersonBehaviorSelector()
        hs = _HS("ptrk_1", current_gesture="pointing_left")
        candidate = sel.decide_pointing_confirmation(hs)
        assert candidate is not None
        assert "left" in candidate.content

    def test_pointing_forward(self):
        sel = MultiPersonBehaviorSelector()
        hs = _HS("ptrk_1", current_gesture="pointing_forward")
        candidate = sel.decide_pointing_confirmation(hs)
        assert "forward" in candidate.content

    def test_non_pointing_gesture_no_confirmation(self):
        sel = MultiPersonBehaviorSelector()
        hs = _HS("ptrk_1", current_gesture="wave")
        assert sel.decide_pointing_confirmation(hs) is None


class TestRule9ChildSafetyModifier:
    def test_non_child_candidate_unchanged(self):
        from bonbon_behavior_engine.core.multi_person_behavior_selector import BehaviorCandidate

        candidate = BehaviorCandidate("gesture", "wave", "test", 0.2, "ptrk_1", speed_scale=1.0)
        result = apply_child_safety_modifier(candidate, is_child_nearby=False)
        assert result.speed_scale == 1.0
        assert result.content == "wave"

    def test_child_nearby_caps_speed(self):
        from bonbon_behavior_engine.core.multi_person_behavior_selector import BehaviorCandidate

        candidate = BehaviorCandidate("speak", "hello", "test", 0.2, "ptrk_1", speed_scale=1.0)
        result = apply_child_safety_modifier(candidate, is_child_nearby=True)
        assert result.speed_scale <= 0.7

    def test_child_nearby_downgrades_expressive_gesture(self):
        from bonbon_behavior_engine.core.multi_person_behavior_selector import BehaviorCandidate

        candidate = BehaviorCandidate("gesture", "greeting_pose", "test", 0.2, "ptrk_1")
        result = apply_child_safety_modifier(candidate, is_child_nearby=True)
        assert result.content == "listening_pose"

    def test_child_nearby_does_not_downgrade_already_gentle_gesture(self):
        from bonbon_behavior_engine.core.multi_person_behavior_selector import BehaviorCandidate

        candidate = BehaviorCandidate("gesture", "rest_pose", "test", 0.2, "ptrk_1")
        result = apply_child_safety_modifier(candidate, is_child_nearby=True)
        assert result.content == "rest_pose"
