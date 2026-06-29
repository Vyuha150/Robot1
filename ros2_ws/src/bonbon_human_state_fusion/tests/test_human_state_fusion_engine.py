"""Tests for HumanStateFusionEngine — verifies the explicit project rules:
never mix one person's speech with another's face, preserve uncertainty,
explain evidence, track new vs existing person separately, update on leave.
"""

from __future__ import annotations

from bonbon_human_state_fusion.core.human_state_fusion_engine import (
    HumanStateFusionEngine,
    classify_proximity_zone,
)


class _Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


def _engine(clock=None):
    return HumanStateFusionEngine(clock=clock or _Clock())


class TestProximityZones:
    def test_close_is_personal_space(self):
        assert classify_proximity_zone(0.5) == "personal_space"

    def test_medium_is_social_space(self):
        assert classify_proximity_zone(2.0) == "social_space"

    def test_far_is_public_space(self):
        assert classify_proximity_zone(10.0) == "public_space"


class TestBasicPersonTrackIngest:
    def test_unknown_person_has_no_state_before_ingest(self):
        engine = _engine()
        assert engine.build_human_state("ptrk_1") is None

    def test_after_person_track_update_state_exists(self):
        engine = _engine()
        engine.update_person_track("ptrk_1", "", "present", "person_3", 1.0, 0.0, 0.0, 0.9)
        state = engine.build_human_state("ptrk_1")
        assert state is not None
        assert state.lifecycle_state == "present"
        assert state.proximity_zone == "personal_space"


class TestDirectJoins:
    def test_gesture_joins_directly_via_person_track_id(self):
        engine = _engine()
        engine.update_person_track("ptrk_1", "", "present", "person_3", 1.0, 0.0, 0.0, 0.9)
        ok = engine.update_gesture_event("ptrk_1", "wave", 0.85, False)
        assert ok is True
        state = engine.build_human_state("ptrk_1")
        assert state.current_gesture == "wave"

    def test_gesture_for_unknown_person_rejected(self):
        engine = _engine()
        ok = engine.update_gesture_event("ptrk_ghost", "wave", 0.9, False)
        assert ok is False

    def test_speaker_turn_joins_directly_and_feeds_active_speaker_status(self):
        engine = _engine()
        engine.update_person_track("ptrk_1", "", "present", "person_3", 1.0, 0.0, 0.0, 0.9)
        ok = engine.update_speaker_turn("ptrk_1", "hello robot", 0.9)
        assert ok is True
        state = engine.build_human_state("ptrk_1")
        assert state.active_speaker_status == "speaking"
        assert state.last_transcript == "hello robot"


class TestRawTrackBridging:
    def test_human_emotion_state_bridges_via_raw_track_id(self):
        engine = _engine()
        engine.update_person_track("ptrk_1", "", "present", "person_3", 1.0, 0.0, 0.0, 0.9)
        ok = engine.update_human_emotion_state("person_3", "happy", 0.8, "cheerful", 1.5, False)
        assert ok is True
        state = engine.build_human_state("ptrk_1")
        assert state.emotional_state == "happy"
        assert state.recommended_robot_response_style == "cheerful"

    def test_unbridgeable_raw_id_rejected(self):
        engine = _engine()
        engine.update_person_track("ptrk_1", "", "present", "person_3", 1.0, 0.0, 0.0, 0.9)
        ok = engine.update_human_emotion_state("person_99", "happy", 0.8, "cheerful", 1.5, False)
        assert ok is False

    def test_voice_emotion_with_empty_person_id_never_bridges(self):
        """bonbon_affective_ai's voice analyzer is often unattributed
        (person_id='') — must not silently attach to some arbitrary person."""
        engine = _engine()
        engine.update_person_track("ptrk_1", "", "present", "person_3", 1.0, 0.0, 0.0, 0.9)
        ok = engine.update_voice_emotion("", "happy")
        assert ok is False


class TestNeverMixIdentities:
    def test_two_people_emotion_never_crosses(self):
        engine = _engine()
        engine.update_person_track("ptrk_alice", "alice", "present", "person_1", 1.0, 0.0, 0.0, 0.9)
        engine.update_person_track("ptrk_bob", "bob", "present", "person_2", -1.0, 0.0, 0.0, 0.9)
        engine.update_human_emotion_state("person_1", "happy", 0.8, "cheerful", 1.0, False)
        engine.update_human_emotion_state(
            "person_2", "frustrated", 0.7, "calm_supportive", 1.0, False
        )

        alice = engine.build_human_state("ptrk_alice")
        bob = engine.build_human_state("ptrk_bob")
        assert alice.emotional_state == "happy"
        assert bob.emotional_state == "frustrated"

    def test_raw_track_id_reassignment_does_not_leak_to_old_person(self):
        """If person_3's raw_track_id is reassigned to a DIFFERENT person_track_id
        (e.g. after churn), a stale lookup must never attach new evidence to
        the wrong (old) record."""
        engine = _engine()
        engine.update_person_track("ptrk_1", "", "present", "person_3", 1.0, 0.0, 0.0, 0.9)
        # person_3 raw id reassigned to a different individual entirely.
        engine.update_person_track("ptrk_2", "", "present", "person_3", 5.0, 5.0, 0.0, 0.9)
        ok = engine.update_human_emotion_state(
            "person_3", "angry", 0.9, "calm_supportive", 1.0, True
        )
        assert ok is True
        state1 = engine.build_human_state("ptrk_1")
        state2 = engine.build_human_state("ptrk_2")
        assert state1.emotional_state == ""  # old record never sees it
        assert state2.emotional_state == "angry"

    def test_text_intent_attributed_only_to_recent_speaker_not_silent_person(self):
        engine = _engine()
        engine.update_person_track("ptrk_alice", "alice", "present", "person_1", 1.0, 0.0, 0.0, 0.9)
        engine.update_person_track("ptrk_bob", "bob", "present", "person_2", -1.0, 0.0, 0.0, 0.9)
        engine.update_speaker_turn("ptrk_bob", "what time is it", 0.9)
        engine.update_user_intent("ask_question")

        alice = engine.build_human_state("ptrk_alice")
        bob = engine.build_human_state("ptrk_bob")
        assert alice.text_intent == ""
        assert bob.text_intent == "ask_question"


class TestNewVsExistingPerson:
    def test_two_simultaneous_people_tracked_separately(self):
        engine = _engine()
        engine.update_person_track("ptrk_1", "", "present", "p1", 1.0, 0.0, 0.0, 0.9)
        engine.update_person_track("ptrk_2", "", "new_candidate", "p2", 2.0, 0.0, 0.0, 0.5)
        assert engine.tracked_person_count == 2
        states = {s.person_track_id: s for s in engine.build_all()}
        assert states["ptrk_1"].lifecycle_state == "present"
        assert states["ptrk_2"].lifecycle_state == "new_candidate"


class TestPersonLeaving:
    def test_left_scene_state_still_built_before_eviction(self):
        engine = _engine()
        engine.update_person_track("ptrk_1", "bob", "present", "p1", 1.0, 0.0, 0.0, 0.9)
        engine.update_person_track("ptrk_1", "bob", "left_scene", "", 1.0, 0.0, 0.0, 0.1)
        state = engine.build_human_state("ptrk_1")
        assert state is not None
        assert state.lifecycle_state == "left_scene"

    def test_evict_left_scene_removes_record_and_returns_id(self):
        engine = _engine()
        engine.update_person_track("ptrk_1", "bob", "left_scene", "", 1.0, 0.0, 0.0, 0.1)
        evicted = engine.evict_left_scene()
        assert evicted == ["ptrk_1"]
        assert engine.tracked_person_count == 0
        assert engine.build_human_state("ptrk_1") is None

    def test_evict_also_forgets_raw_track_bridge(self):
        engine = _engine()
        engine.update_person_track("ptrk_1", "bob", "present", "person_5", 1.0, 0.0, 0.0, 0.9)
        engine.update_person_track("ptrk_1", "bob", "left_scene", "", 1.0, 0.0, 0.0, 0.1)
        engine.evict_left_scene()
        # A new person reusing raw id "person_5" must not inherit bob's old evidence.
        engine.update_person_track("ptrk_2", "", "new_candidate", "person_5", 9.0, 9.0, 0.0, 0.5)
        ok = engine.update_human_emotion_state("person_5", "neutral", 0.5, "normal", 1.0, False)
        assert ok is True
        state2 = engine.build_human_state("ptrk_2")
        assert state2.emotional_state == "neutral"


class TestPreserveUncertainty:
    def test_confidence_lower_with_only_lifecycle_evidence(self):
        engine = _engine()
        engine.update_person_track("ptrk_1", "", "present", "p1", 1.0, 0.0, 0.0, 0.9)
        state = engine.build_human_state("ptrk_1")
        assert state.confidence < 0.9  # less than the raw lifecycle confidence alone

    def test_confidence_increases_with_more_corroborating_modalities(self):
        engine = _engine()
        engine.update_person_track("ptrk_1", "", "present", "person_3", 1.0, 0.0, 0.0, 0.9)
        lifecycle_only = engine.build_human_state("ptrk_1").confidence

        engine.update_human_emotion_state("person_3", "happy", 0.9, "cheerful", 1.0, False)
        engine.update_gesture_event("ptrk_1", "wave", 0.9, False)
        engine.update_speaker_turn("ptrk_1", "hi", 0.9)
        with_more_evidence = engine.build_human_state("ptrk_1").confidence

        assert with_more_evidence > lifecycle_only


class TestExplainEvidence:
    def test_evidence_summary_is_non_empty_and_mentions_identity(self):
        engine = _engine()
        engine.update_person_track("ptrk_1", "bob", "present", "p1", 1.0, 0.0, 0.0, 0.9)
        state = engine.build_human_state("ptrk_1")
        assert state.evidence_summary
        assert "bob" in state.evidence_summary


class TestUrgencyFromSafetyGesture:
    def test_safety_gesture_drives_urgency_and_alert(self):
        engine = _engine()
        engine.update_person_track("ptrk_1", "", "present", "p1", 1.0, 0.0, 0.0, 0.9)
        engine.update_gesture_event("ptrk_1", "stop_palm", 0.95, True)
        state = engine.build_human_state("ptrk_1")
        assert state.urgency_level == 1.0
        assert state.requires_operator_alert is True


class TestStaleEvidenceExpires:
    def test_stale_gesture_not_reported_as_current(self):
        clock = _Clock()
        engine = _engine(clock)
        engine.update_person_track("ptrk_1", "", "present", "p1", 1.0, 0.0, 0.0, 0.9)
        engine.update_gesture_event("ptrk_1", "wave", 0.9, False)
        clock.advance(100.0)  # well beyond gesture recency window
        state = engine.build_human_state("ptrk_1")
        assert state.current_gesture == "none"
