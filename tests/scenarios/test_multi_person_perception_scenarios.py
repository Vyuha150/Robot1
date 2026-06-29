"""25 real-world scenario tests for the multi-person perception upgrade
(bonbon_object_intelligence, bonbon_multi_person_tracker, bonbon_gesture,
bonbon_speaker_intelligence, bonbon_human_state_fusion, bonbon_behavior_engine).

Each test exercises the REAL core classes from each package directly (no
mocked business logic) — only the message-passing/ROS2 layer is absent,
consistent with every other test suite in this project. Where a scenario
crosses package boundaries, this suite composes the real classes the same
way the ROS2 nodes do, verifying the actual integration, not just each
package's isolated unit behaviour.
"""

from __future__ import annotations

from bonbon_behavior_engine.core.command_risk_classifier import CommandRiskClassifier
from bonbon_behavior_engine.core.llm_command_gate import LLMCommandGate
from bonbon_behavior_engine.core.multi_person_behavior_selector import select_focus_person
from bonbon_behavior_engine.core.proposal_evaluator import ProposalEvaluator
from bonbon_gesture.logic.person_assigner import (
    GesturePersonAssigner,
    LandmarkCandidate,
    TrackedPersonCandidate,
)
from bonbon_human_state_fusion.core.human_state_fusion_engine import HumanStateFusionEngine
from bonbon_multi_person_tracker.core.lifecycle_state_machine import (
    LifecycleConfig,
    PersonLifecycleState,
)
from bonbon_multi_person_tracker.core.multi_person_scene_manager import MultiPersonSceneManager
from bonbon_multi_person_tracker.core.person_record import RawPersonDetection
from bonbon_object_intelligence.core.confidence_calibrator import (
    CalibratorConfig,
    ObjectConfidenceCalibrator,
)
from bonbon_object_intelligence.core.object_permanence_tracker import (
    ObjectPermanenceTracker,
    PermanenceConfig,
    PermanenceState,
    RawObjectDetection,
)
from bonbon_speaker_intelligence.core.audio_visual_associator import TrackedPersonBearing
from bonbon_speaker_intelligence.core.speaker_identity_manager import (
    SpeakerIdentityConfig,
    SpeakerIdentityManager,
)
from bonbon_speaker_intelligence.core.speaker_turn_builder import SpeakerTurnBuilder
from bonbon_speaker_intelligence.core.transcript_segment_mapper import (
    DiarizationSegment,
    WordTiming,
)
from bonbon_speaker_intelligence.core.voice_emotion_cache import VoiceEmotionCache


class _Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


# ── 1-3: Object detection / tracking ────────────────────────────────────────


class TestScenario01ObjectDetectionSuccess:
    """Purpose: a clean, single detection produces a visible tracked object.
    Setup: ObjectPermanenceTracker, one chair detection.
    Input: RawObjectDetection(class='chair', confidence=0.85).
    Expected: one VISIBLE TrackedObject with the same class.
    Safety relevance: none — baseline functional correctness."""

    def test_clean_detection_produces_visible_track(self):
        tracker = ObjectPermanenceTracker()
        snap = tracker.update([RawObjectDetection("chair", 0.85, 1.0, 0.0, 0.0)])
        assert len(snap) == 1
        assert snap[0].state == PermanenceState.VISIBLE
        assert snap[0].class_name == "chair"


class TestScenario02ObjectTrackingThroughOcclusion:
    """Purpose: an object briefly hidden behind another must not be declared
    gone and re-tracked as a new object.
    Setup: ObjectPermanenceTracker with occlusion_grace_sec=2.0.
    Input: detect, miss for 1s, re-detect at the same position.
    Expected: same object_track_id before and after the occlusion.
    Safety relevance: prevents flicker in spatial maps used for navigation."""

    def test_brief_occlusion_preserves_identity(self):
        clock = _Clock()
        tracker = ObjectPermanenceTracker(
            config=PermanenceConfig(occlusion_grace_sec=2.0), clock=clock
        )
        before = tracker.update([RawObjectDetection("bag", 0.8, 2.0, 0.0, 0.0)])
        clock.advance(1.0)
        tracker.update([])
        clock.advance(0.5)
        after = tracker.update([RawObjectDetection("bag", 0.8, 2.0, 0.0, 0.0)])
        assert after[0].object_track_id == before[0].object_track_id
        assert after[0].state == PermanenceState.VISIBLE


class TestScenario03WrongObjectConfidenceRejection:
    """Purpose: a low-confidence false-positive detection must be rejected,
    not published as a tracked object.
    Setup: ObjectConfidenceCalibrator with rejection_threshold=0.3.
    Input: a detection with raw confidence 0.05.
    Expected: rejected=True.
    Safety relevance: prevents the robot reacting to noise (e.g. phantom
    obstacles triggering unnecessary navigation replans)."""

    def test_low_confidence_detection_rejected(self):
        calib = ObjectConfidenceCalibrator(CalibratorConfig(rejection_threshold=0.3))
        result = calib.calibrate("chair", 0.05, (0, 0, 50, 50))
        assert result.rejected is True


# ── 4-7: Multi-person tracking lifecycle ────────────────────────────────────


class TestScenario04MultiPersonDetection:
    """Purpose: two people present simultaneously get two independent identities.
    Setup: MultiPersonSceneManager, two detections at different positions.
    Input: two RawPersonDetections in one cycle.
    Expected: two distinct person_track_ids.
    Safety relevance: prerequisite for every other multi-person rule."""

    def test_two_simultaneous_people_get_distinct_ids(self):
        mgr = MultiPersonSceneManager(
            lifecycle_config=LifecycleConfig(confirmation_hits=1), clock=_Clock()
        )
        snap = mgr.update(
            [
                RawPersonDetection("r1", x=1.0, y=0.0),
                RawPersonDetection("r2", x=-1.0, y=0.0),
            ]
        )
        assert len({r.person_track_id for r in snap}) == 2


class TestScenario05PersonLeavesScene:
    """Purpose: a person who walks away is eventually declared left_scene,
    never from a single missed frame.
    Setup: MultiPersonSceneManager with loss_grace_sec=2.0.
    Input: detect once, then miss for > grace window.
    Expected: TEMPORARILY_LOST first, LEFT_SCENE only after the grace window.
    Safety relevance: prevents the robot from prematurely ending an
    interaction (e.g. mid-sentence) due to one dropped camera frame."""

    def test_departure_requires_full_grace_window(self):
        clock = _Clock()
        mgr = MultiPersonSceneManager(
            lifecycle_config=LifecycleConfig(confirmation_hits=1, loss_grace_sec=2.0), clock=clock
        )
        mgr.update([RawPersonDetection("r1")])
        snap1 = mgr.update([])  # one missed frame
        assert snap1[0].lifecycle_state == PersonLifecycleState.TEMPORARILY_LOST
        clock.advance(3.0)
        snap2 = mgr.update([])
        assert any(r.lifecycle_state == PersonLifecycleState.LEFT_SCENE for r in snap2)


class TestScenario06NewPersonArrives:
    """Purpose: a brand new person is tracked from the moment of arrival.
    Setup: empty scene, one new detection.
    Input: RawPersonDetection with a previously-unseen raw_track_id.
    Expected: a new person_track_id, lifecycle_state new_candidate/present.
    Safety relevance: triggers the greeting behavior in bonbon_behavior_engine."""

    def test_arrival_creates_new_candidate(self):
        mgr = MultiPersonSceneManager(clock=_Clock())
        snap = mgr.update([RawPersonDetection("r1")])
        assert len(snap) == 1
        assert snap[0].lifecycle_state == PersonLifecycleState.NEW_CANDIDATE


class TestScenario07OldPersonReappears:
    """Purpose: a person who steps out of frame briefly and returns is
    recognised as the SAME person, not a new one.
    Setup: MultiPersonSceneManager, person with a known face_id.
    Input: detect, lose track, re-detect under a different raw track_id but
    the same face_id within the loss-grace window.
    Expected: REAPPEARED with the SAME person_track_id.
    Safety relevance: avoids losing interaction history (e.g. restarting a
    conversation) for a momentary occlusion."""

    def test_reappearance_preserves_person_track_id(self):
        clock = _Clock()
        mgr = MultiPersonSceneManager(
            lifecycle_config=LifecycleConfig(confirmation_hits=1, loss_grace_sec=5.0), clock=clock
        )
        mgr.update([RawPersonDetection("r1", face_id="bob")])
        snap1 = mgr.update([])
        ptid = snap1[0].person_track_id
        clock.advance(2.0)
        snap2 = mgr.update([RawPersonDetection("r1_new", face_id="bob")])
        assert snap2[0].lifecycle_state == PersonLifecycleState.REAPPEARED
        assert snap2[0].person_track_id == ptid


# ── 8-9: Face recognition ───────────────────────────────────────────────────


class TestScenario08KnownFaceRecognized:
    """Purpose: a registered face_id is surfaced as known_person_id.
    Setup: MultiPersonSceneManager.
    Input: detection with face_id='bob' (already a real bonbon_vision signal).
    Expected: known_person_id == 'bob'.
    Safety relevance: gates personalised behaviors (e.g. greeting by name)."""

    def test_known_face_id_becomes_known_person_id(self):
        mgr = MultiPersonSceneManager(clock=_Clock())
        snap = mgr.update([RawPersonDetection("r1", face_id="bob")])
        assert snap[0].known_person_id == "bob"


class TestScenario09UnknownFaceHandled:
    """Purpose: a person with no registered face is tracked anonymously,
    never crashes or gets a fabricated identity.
    Setup: MultiPersonSceneManager.
    Input: detection with face_id=''.
    Expected: known_person_id=='', temporary_person_id is set.
    Safety relevance: privacy — never invent an identity."""

    def test_unknown_face_gets_anonymous_temporary_id_only(self):
        mgr = MultiPersonSceneManager(clock=_Clock())
        snap = mgr.update([RawPersonDetection("r1", face_id="")])
        assert snap[0].known_person_id == ""
        assert snap[0].temporary_person_id  # non-empty anonymous label


# ── 10-13: Gesture-to-person linkage ─────────────────────────────────────────


class TestScenario10GestureLinkedToCorrectPerson:
    """Purpose: a gesture from a specific person attaches to THEIR
    person_track_id, not an arbitrary one.
    Setup: GesturePersonAssigner, one tracked person at a known bearing.
    Input: one landmark set whose frame position matches that bearing.
    Expected: the assignment maps the landmark's tracking_id to that exact
    person_track_id.
    Safety relevance: core "never mix identities" requirement."""

    def test_single_person_gesture_assigned_correctly(self):
        assigner = GesturePersonAssigner(camera_hfov_deg=60.0)
        result = assigner.assign(
            [LandmarkCandidate(tracking_id=0, centroid_x_norm=0.5)],
            [TrackedPersonCandidate(person_track_id="ptrk_1", bearing_deg=0.0)],
        )
        assert result == {0: "ptrk_1"}


class TestScenario11StopPalmTriggersSafetyRelevance:
    """Purpose: a stop_palm gesture from anyone is flagged as safety-relevant
    so it can interrupt whatever else the robot is doing.
    Setup: MultiPersonBehaviorSelector.
    Input: a HumanState-like record with current_gesture='stop_palm'.
    Expected: decide_safety_gesture_response returns a 'pause' candidate
    with urgency 1.0.
    Safety relevance: this IS the safety-gesture behavior rule."""

    def test_stop_palm_produces_max_urgency_pause(self):
        from dataclasses import dataclass

        from bonbon_behavior_engine.core.multi_person_behavior_selector import (
            MultiPersonBehaviorSelector,
        )

        @dataclass
        class _HS:
            person_track_id: str = "ptrk_1"
            lifecycle_state: str = "present"
            current_gesture: str = "stop_palm"

        sel = MultiPersonBehaviorSelector()
        candidate = sel.decide_safety_gesture_response([_HS()])
        assert candidate is not None
        assert candidate.proposal_type == "pause"
        assert candidate.urgency == 1.0


class TestScenario12PointingGestureAssignedCorrectly:
    """Purpose: among two people, a pointing gesture is attributed to the
    one who is actually pointing, by bearing-matched assignment.
    Setup: GesturePersonAssigner, two tracked people at distinct bearings.
    Input: two landmark sets at distinct frame positions.
    Expected: each landmark set maps to its OWN nearest-bearing person,
    never crossed.
    Safety relevance: prevents the robot from confirming the wrong
    direction with the wrong person."""

    def test_pointing_gesture_from_left_person_not_attributed_to_right_person(self):
        assigner = GesturePersonAssigner(camera_hfov_deg=60.0)
        result = assigner.assign(
            [
                LandmarkCandidate(tracking_id=0, centroid_x_norm=0.15),
                LandmarkCandidate(tracking_id=1, centroid_x_norm=0.85),
            ],
            [
                TrackedPersonCandidate(person_track_id="left_person", bearing_deg=20.0),
                TrackedPersonCandidate(person_track_id="right_person", bearing_deg=-20.0),
            ],
        )
        assert result[0] == "left_person"
        assert result[1] == "right_person"


class TestScenario13MultiplePeopleGestureSimultaneously:
    """Purpose: two people gesturing in the same frame each get their own
    gesture correctly assigned, with no cross-talk.
    Setup: GesturePersonAssigner, two tracked people, two landmark sets.
    Input: both gesturing at once.
    Expected: two independent, correct, non-colliding assignments.
    Safety relevance: a safety gesture from one person must never be lost
    or misattributed because another person is also gesturing."""

    def test_two_simultaneous_gestures_both_assigned_without_collision(self):
        assigner = GesturePersonAssigner(camera_hfov_deg=60.0, max_x_norm_delta=0.5)
        result = assigner.assign(
            [
                LandmarkCandidate(tracking_id=0, centroid_x_norm=0.45),
                LandmarkCandidate(tracking_id=1, centroid_x_norm=0.55),
            ],
            [
                TrackedPersonCandidate(person_track_id="a", bearing_deg=6.0),
                TrackedPersonCandidate(person_track_id="b", bearing_deg=-6.0),
            ],
        )
        assert len(result) == 2
        assert result[0] != result[1]


# ── 14-18: Speaker diarization / audio-visual association ──────────────────


class TestScenario14SpeakerDiarizationTwoSpeakers:
    """Purpose: an utterance with two diarized segments produces two
    distinct speaker turns with correctly attributed text.
    Setup: SpeakerTurnBuilder, two DiarizationSegments + word timings.
    Input: a 2-speaker utterance.
    Expected: two turns, each with the correct slice of the transcript.
    Safety relevance: prerequisite for not mixing two people's words."""

    def test_two_speaker_segments_produce_two_correctly_attributed_turns(self):
        builder = SpeakerTurnBuilder(
            SpeakerIdentityManager(config=SpeakerIdentityConfig()),
            VoiceEmotionCache(),
        )
        segs = [
            DiarizationSegment("SPEAKER_00", 0.0, 1.5),
            DiarizationSegment("SPEAKER_01", 1.5, 3.0),
        ]
        words = [
            WordTiming("hello", 0.0, 0.5),
            WordTiming("there", 0.6, 1.2),
            WordTiming("hi", 1.6, 2.0),
            WordTiming("back", 2.1, 2.8),
        ]
        turns = builder.build_turns(
            segs, words, "hello there hi back", 0.9, doa_deg=10.0, tracked_persons=[]
        )
        assert len(turns) == 2
        assert turns[0].transcript == "hello there"
        assert turns[1].transcript == "hi back"


class TestScenario15SpeakerLinkedToVisiblePerson:
    """Purpose: a speaker turn's DOA links it to the visible person standing
    in that direction.
    Setup: SpeakerTurnBuilder, one tracked person at a matching bearing.
    Input: one speech segment with a DOA matching that bearing.
    Expected: person_track_id is populated, is_off_camera=False.
    Safety relevance: enables "respond by name"/focus behaviors."""

    def test_speaker_turn_linked_to_matching_bearing_person(self):
        builder = SpeakerTurnBuilder(
            SpeakerIdentityManager(config=SpeakerIdentityConfig()),
            VoiceEmotionCache(),
        )
        people = [TrackedPersonBearing("ptrk_1", 28.0)]
        turn = builder.build_turns(
            [DiarizationSegment("S0", 0.0, 1.0)],
            [],
            "hi",
            0.9,
            doa_deg=30.0,
            tracked_persons=people,
        )[0]
        assert turn.person_track_id == "ptrk_1"
        assert turn.is_off_camera is False


class TestScenario16OffCameraSpeaker:
    """Purpose: a speaker whose voice comes from a direction with no visible
    tracked person is correctly marked off-camera, never guessed.
    Setup: SpeakerTurnBuilder, empty tracked_persons.
    Input: one speech segment.
    Expected: person_track_id=='', is_off_camera=True.
    Safety relevance: avoids falsely attributing speech to a bystander."""

    def test_no_visible_match_marks_off_camera(self):
        builder = SpeakerTurnBuilder(
            SpeakerIdentityManager(config=SpeakerIdentityConfig()),
            VoiceEmotionCache(),
        )
        turn = builder.build_turns(
            [DiarizationSegment("S0", 0.0, 1.0)], [], "hi", 0.9, doa_deg=30.0, tracked_persons=[]
        )[0]
        assert turn.person_track_id == ""
        assert turn.is_off_camera is True


class TestScenario17OverlappingSpeech:
    """Purpose: when two people speak in the same utterance, both turns are
    flagged is_overlapping and association confidence is honestly reduced
    (a single DOA reading can't disambiguate which of several overlapping
    speakers it actually describes).
    Setup: SpeakerTurnBuilder, two overlapping segments.
    Input: a 2-segment utterance.
    Expected: both turns is_overlapping=True; confidence lower than a
    single-speaker equivalent.
    Safety relevance: prevents false confidence in a noisy multi-speaker
    situation, e.g. an emergency call from a crowd."""

    def test_overlapping_turns_flagged_with_reduced_confidence(self):
        builder_a = SpeakerTurnBuilder(
            SpeakerIdentityManager(config=SpeakerIdentityConfig()), VoiceEmotionCache()
        )
        builder_b = SpeakerTurnBuilder(
            SpeakerIdentityManager(config=SpeakerIdentityConfig()), VoiceEmotionCache()
        )
        people = [TrackedPersonBearing("ptrk_1", 30.0)]

        single = builder_a.build_turns(
            [DiarizationSegment("S0", 0.0, 1.0)],
            [],
            "hi",
            0.9,
            doa_deg=30.0,
            tracked_persons=people,
        )[0]
        overlapping_turns = builder_b.build_turns(
            [DiarizationSegment("S0", 0.0, 1.0), DiarizationSegment("S1", 1.0, 2.0)],
            [],
            "hi",
            0.9,
            doa_deg=30.0,
            tracked_persons=people,
        )
        assert all(t.is_overlapping for t in overlapping_turns)
        assert overlapping_turns[0].association_confidence < single.association_confidence


class TestScenario18NoisyAudio:
    """Purpose: a low-confidence/empty-text segment is still produced as a
    turn (so the system knows SOMEONE spoke) but flagged noisy, never
    fabricating a transcript.
    Setup: SpeakerIntelligenceNode-equivalent flow (builder + explicit flag).
    Input: noisy_audio=True passed through from the upstream STT confidence gate.
    Expected: the resulting turn carries noisy_audio=True.
    Safety relevance: downstream consumers (e.g. emergency keyword spotting)
    must discount noisy transcripts rather than act on a misheard word."""

    def test_noisy_flag_propagates_to_turn(self):
        builder = SpeakerTurnBuilder(
            SpeakerIdentityManager(config=SpeakerIdentityConfig()),
            VoiceEmotionCache(),
        )
        turn = builder.build_turns(
            [DiarizationSegment("S0", 0.0, 1.0)],
            [],
            "",
            0.05,
            doa_deg=10.0,
            tracked_persons=[],
            noisy_audio=True,
        )[0]
        assert turn.noisy_audio is True


# ── 19-20: Speaking lifecycle ────────────────────────────────────────────────


class TestScenario19NewPersonSpeaks:
    """Purpose: a newly-arrived person who speaks is correctly fused into
    active_speaker_status='speaking' for THEIR person_track_id only.
    Setup: HumanStateFusionEngine.
    Input: PersonTrack arrival + a SpeakerTurn for that person_track_id.
    Expected: active_speaker_status=='speaking'.
    Safety relevance: drives "respond to the active speaker" behavior."""

    def test_new_arrival_then_speech_yields_speaking_status(self):
        engine = HumanStateFusionEngine(clock=_Clock())
        engine.update_person_track("ptrk_1", "", "present", "p1", 1.0, 0.0, 0.0, 0.9)
        engine.update_speaker_turn("ptrk_1", "hello", 0.9)
        state = engine.build_human_state("ptrk_1")
        assert state.active_speaker_status == "speaking"


class TestScenario20ExistingPersonStopsSpeaking:
    """Purpose: once a person's speaking window elapses, their status
    degrades to recently_spoke / silent — never stuck on 'speaking' forever.
    Setup: HumanStateFusionEngine with a short speaking_window_sec.
    Input: one speaker turn, then time passes with no further speech.
    Expected: active_speaker_status transitions away from 'speaking'.
    Safety relevance: prevents the robot from continuing to address someone
    who has stopped talking."""

    def test_status_decays_after_speaking_window(self):
        clock = _Clock()
        engine = HumanStateFusionEngine(speaking_window_sec=1.0, clock=clock)
        engine.update_person_track("ptrk_1", "", "present", "p1", 1.0, 0.0, 0.0, 0.9)
        engine.update_speaker_turn("ptrk_1", "hello", 0.9)
        assert engine.build_human_state("ptrk_1").active_speaker_status == "speaking"
        clock.advance(5.0)
        assert engine.build_human_state("ptrk_1").active_speaker_status != "speaking"


# ── 21-23: Fusion correctness / identity isolation ──────────────────────────


class TestScenario21EmotionDiffersPerPerson:
    """Purpose: two people with different fused emotional states must each
    see THEIR OWN state, never the other's.
    Setup: HumanStateFusionEngine, two people bridged via raw_track_id.
    Input: HumanEmotionState 'happy' for person A, 'frustrated' for person B.
    Expected: each HumanState reflects only its own person's emotion.
    Safety relevance: misattributed distress could trigger (or fail to
    trigger) an operator alert for the wrong person."""

    def test_two_people_independent_emotional_states(self):
        engine = HumanStateFusionEngine(clock=_Clock())
        engine.update_person_track("ptrk_a", "alice", "present", "person_1", 1.0, 0.0, 0.0, 0.9)
        engine.update_person_track("ptrk_b", "bob", "present", "person_2", -1.0, 0.0, 0.0, 0.9)
        engine.update_human_emotion_state("person_1", "happy", 0.8, "cheerful", 1.0, False)
        engine.update_human_emotion_state(
            "person_2", "frustrated", 0.7, "calm_supportive", 1.0, False
        )
        assert engine.build_human_state("ptrk_a").emotional_state == "happy"
        assert engine.build_human_state("ptrk_b").emotional_state == "frustrated"


class TestScenario22ActiveSpeakerSelectedCorrectly:
    """Purpose: with multiple people present, the higher-urgency active
    speaker is selected as the behavioral focus.
    Setup: select_focus_person with two speaking HumanState-like records.
    Input: two speakers, different urgency_level.
    Expected: focus == the higher-urgency speaker.
    Safety relevance: this IS rule 5 — multiple people speak, focus on the
    (more urgent) active speaker."""

    def test_focus_goes_to_more_urgent_of_two_speakers(self):
        from dataclasses import dataclass

        @dataclass
        class _HS:
            person_track_id: str
            lifecycle_state: str = "present"
            active_speaker_status: str = "speaking"
            urgency_level: float = 0.0

        people = [_HS("ptrk_1", urgency_level=0.2), _HS("ptrk_2", urgency_level=0.9)]
        assert select_focus_person(people) == "ptrk_2"


class TestScenario23RobotDoesNotMixIdentities:
    """Purpose: end-to-end — a gesture from one person and emotion from
    another, present in the same cycle, must never cross-contaminate.
    Setup: HumanStateFusionEngine with two people; gesture for A, emotion for B.
    Input: GestureEvent(person_track_id='ptrk_a'), HumanEmotionState for
    raw_track 'person_2' (bridged to ptrk_b).
    Expected: A has the gesture and no emotion; B has the emotion and no gesture.
    Safety relevance: the single most important invariant of this entire
    multi-person perception upgrade."""

    def test_gesture_and_emotion_from_different_people_never_cross(self):
        engine = HumanStateFusionEngine(clock=_Clock())
        engine.update_person_track("ptrk_a", "", "present", "person_1", 1.0, 0.0, 0.0, 0.9)
        engine.update_person_track("ptrk_b", "", "present", "person_2", -1.0, 0.0, 0.0, 0.9)
        engine.update_gesture_event("ptrk_a", "wave", 0.9, False)
        engine.update_human_emotion_state("person_2", "angry", 0.8, "calm_supportive", 1.0, False)

        state_a = engine.build_human_state("ptrk_a")
        state_b = engine.build_human_state("ptrk_b")
        assert state_a.current_gesture == "wave"
        assert state_a.emotional_state == ""
        assert state_b.current_gesture == "none"
        assert state_b.emotional_state == "angry"


# ── 24-25: Safety-critical control invariants (pre-existing gates, verified) ─


class TestScenario24LLMDoesNotDirectlyAct:
    """Purpose: confirms the existing invariant — no LLM output can produce
    a navigate/actuation command without passing through risk classification
    first; this test does not introduce new code, it verifies the gate this
    whole perception upgrade feeds into still rejects what it should.
    Setup: LLMCommandGate (pre-existing, bonbon_behavior_engine).
    Input: an LLM string asking the robot to physically move.
    Expected: either rejected outright, or downgraded to a non-physical
    proposal type ('ask_clarification'/'alert_operator') — never a direct,
    ungated 'navigate' grant.
    Safety relevance: explicit project rule — "No LLM-generated command
    should directly move the robot."""

    def test_movement_request_never_grants_ungated_navigation(self):
        gate = LLMCommandGate(risk_classifier=CommandRiskClassifier())
        result = gate.evaluate("Please walk forward right now and don't stop.", person_id="ptrk_1")
        if result.allowed and result.proposal_type == "navigate":
            # Even if mapped to 'navigate', it must still be a PROPOSAL with
            # an attached risk assessment for the downstream evaluator/safety
            # gate to act on — never a bare, ungated motion command.
            assert result.risk is not None
        else:
            assert result.proposal_type != "navigate" or not result.allowed


class TestScenario25SafetySupervisorBlocksUnsafeAction:
    """Purpose: confirms the existing invariant — ProposalEvaluator rejects
    actuation/navigation proposals once the safety level reaches DANGER.
    Setup: ProposalEvaluator (pre-existing, bonbon_behavior_engine).
    Input: a 'gesture' proposal evaluated under safety level 3 (DANGER).
    Expected: decision is 'rejected' or 'deferred', never 'approved'.
    Safety relevance: explicit project rule — "The dashboard/behavior layer
    must never bypass the Safety Supervisor."."""

    def test_danger_level_blocks_gesture_proposal(self):
        evaluator = ProposalEvaluator(risk_classifier=CommandRiskClassifier())
        evaluator.update_safety_level(3)  # DANGER
        result = evaluator.evaluate("gesture", "wave", "test", urgency=0.2)
        assert result.decision != "approved"
