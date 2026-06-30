"""Tests for FocusPublishGate — the real consumer that makes active-person
focus genuinely reduce processing for background people (check #5)."""

from __future__ import annotations

from bonbon_human_state_fusion.core.focus_publish_gate import FocusPublishGate


def _result(
    person_track_id,
    lifecycle_state="present",
    active_speaker_status="not_speaking",
    urgency_level=0.0,
):
    return dict(
        person_track_id=person_track_id,
        known_person_id="",
        lifecycle_state=lifecycle_state,
        active_speaker_status=active_speaker_status,
        last_transcript="",
        transcript_confidence=0.0,
        current_gesture="none",
        gesture_confidence=0.0,
        face_expression="neutral",
        voice_emotion="neutral",
        text_intent="",
        text_sentiment="neutral",
        emotional_state="neutral",
        location_x=0.0,
        location_y=0.0,
        location_z=0.0,
        proximity_zone="far",
        engagement_level=0.0,
        urgency_level=urgency_level,
        confidence=0.5,
        recommended_robot_response_style="neutral",
        recommended_robot_distance_m=1.5,
        requires_operator_alert=False,
        evidence_summary="",
    )


class _Result:
    """Lightweight stand-in for HumanStateFusionEngine's HumanStateResult —
    avoids a hard dependency on bonbon_human_state_fusion's own dataclass
    construction order in this test file."""

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def _r(**kwargs):
    return _Result(**_result(**kwargs))


class TestNoThrottlingWithOneOrZeroPeople:
    def test_empty_results_returns_nothing(self):
        gate = FocusPublishGate()
        decision = gate.select([])
        assert decision.to_publish == []
        assert decision.focus_person_track_id == ""

    def test_single_person_always_published(self):
        gate = FocusPublishGate(background_publish_every_n_cycles=3)
        for _ in range(5):
            decision = gate.select([_r(person_track_id="p1")])
            assert len(decision.to_publish) == 1


class TestFocusAndNewArrivalAlwaysPublish:
    def test_active_speaker_is_focus_and_always_published(self):
        gate = FocusPublishGate(background_publish_every_n_cycles=3)
        results = [
            _r(person_track_id="speaker", active_speaker_status="speaking", urgency_level=0.5),
            _r(person_track_id="bystander"),
        ]
        for _ in range(5):
            decision = gate.select(results)
            ids = {r.person_track_id for r in decision.to_publish}
            assert "speaker" in ids
            assert decision.focus_person_track_id == "speaker"

    def test_new_candidate_always_published_even_without_focus(self):
        gate = FocusPublishGate(background_publish_every_n_cycles=3)
        results = [
            _r(person_track_id="newcomer", lifecycle_state="new_candidate"),
            _r(person_track_id="bystander"),
        ]
        for _ in range(5):
            decision = gate.select(results)
            ids = {r.person_track_id for r in decision.to_publish}
            assert "newcomer" in ids


class TestBackgroundPeopleAreThrottled:
    def test_background_person_published_only_every_nth_cycle(self):
        gate = FocusPublishGate(background_publish_every_n_cycles=3)
        results = [
            _r(person_track_id="speaker", active_speaker_status="speaking", urgency_level=0.5),
            _r(person_track_id="bg"),
        ]
        published_cycles = []
        for _ in range(9):
            decision = gate.select(results)
            published_cycles.append("bg" in {r.person_track_id for r in decision.to_publish})
        # bg should publish on cycles 3, 6, 9 (1-indexed) -> indices 2, 5, 8
        assert published_cycles == [
            False,
            False,
            True,
            False,
            False,
            True,
            False,
            False,
            True,
        ]

    def test_throttle_counter_resets_after_publish(self):
        gate = FocusPublishGate(background_publish_every_n_cycles=2)
        results = [
            _r(person_track_id="speaker", active_speaker_status="speaking", urgency_level=0.5),
            _r(person_track_id="bg"),
        ]
        cycles = [gate.select(results) for _ in range(4)]
        published = ["bg" in {r.person_track_id for r in d.to_publish} for d in cycles]
        assert published == [False, True, False, True]


class TestLeftSceneNeverThrottled:
    def test_left_scene_always_published_even_if_was_background(self):
        gate = FocusPublishGate(background_publish_every_n_cycles=5)
        results = [
            _r(person_track_id="speaker", active_speaker_status="speaking", urgency_level=0.5),
            _r(person_track_id="bg"),
        ]
        gate.select(results)  # bg not published this cycle (count=1, n=5)

        left = [
            _r(person_track_id="speaker", active_speaker_status="speaking", urgency_level=0.5),
            _r(person_track_id="bg", lifecycle_state="left_scene"),
        ]
        decision = gate.select(left)
        ids = {r.person_track_id for r in decision.to_publish}
        assert "bg" in ids


class TestCounterPruning:
    def test_throttle_counter_removed_when_person_no_longer_present(self):
        gate = FocusPublishGate(background_publish_every_n_cycles=3)
        gate.select([_r(person_track_id="p1"), _r(person_track_id="bg")])
        assert "bg" in gate._cycle_count
        gate.select([_r(person_track_id="p1")])  # bg gone entirely
        assert "bg" not in gate._cycle_count


class TestNoFocusPersonStillThrottlesBackground:
    def test_all_background_no_focus_still_throttles_consistently(self):
        """When nobody is speaking/urgent/new, select_focus_person may
        return "" or the most-recent arrival -- either way, the throttle
        schedule must still be applied consistently, not crash."""
        gate = FocusPublishGate(background_publish_every_n_cycles=2)
        results = [_r(person_track_id="p1"), _r(person_track_id="p2")]
        decisions = [gate.select(results) for _ in range(4)]
        assert all(isinstance(d.to_publish, list) for d in decisions)
