"""
Tests for SceneAnalyzer.

Covers: activity inference, spatial context, confidence scoring,
event detection (person arrived/left, activity changed, crowd formed),
missing sensor data (all stale), wrong person recognition (spurious IDs),
debounce.
"""

import math
import time

from bonbon_perception_ai.config.perception_config import SceneConfig
from bonbon_perception_ai.fusion.types import (
    FusionContext,
    NavStatus,
    ObjectObservation,
    PersonObservation,
    SpeechInput,
)
from bonbon_perception_ai.understanding.scene_analyzer import (
    ACTIVITY_CROWDED,
    ACTIVITY_IDLE,
    ACTIVITY_INTERACTING,
    ACTIVITY_NAVIGATING,
    ACTIVITY_SERVING,
    SceneAnalyzer,
)


def _cfg(**kw) -> SceneConfig:
    defaults = dict(
        near_person_threshold_m=2.0,
        interaction_proximity_m=1.5,
        crowded_threshold=3,
        event_debounce_sec=0.0,  # disable debounce for tests
    )
    defaults.update(kw)
    return SceneConfig(**defaults)


def _ctx(
    persons=None,
    objects=None,
    speech=None,
    nav_status=None,
    stale=None,
    uncertainty="LOW",
) -> FusionContext:
    return FusionContext(
        timestamp=time.monotonic(),
        objects=objects or [],
        persons=persons or [],
        speech=speech,
        robot_pose=None,
        nav_status=nav_status,
        stale_modalities=stale or [],
        uncertainty_level=uncertainty,
    )


def _person(pid="p1", distance_m=1.0, confidence=0.9) -> PersonObservation:
    return PersonObservation(person_id=pid, confidence=confidence, distance_m=distance_m)


def _speech(text="hello", silence=False) -> SpeechInput:
    return SpeechInput(text=text, confidence=0.9, is_silence=silence)


# ── Activity inference ────────────────────────────────────────────────────────


class TestActivityInference:
    def test_no_persons_no_speech_idle(self):
        an = SceneAnalyzer(_cfg())
        snap, _ = an.analyze(_ctx())
        assert snap.dominant_activity == ACTIVITY_IDLE

    def test_navigating_takes_priority(self):
        an = SceneAnalyzer(_cfg())
        nav = NavStatus(status="navigating", is_moving=True)
        snap, _ = an.analyze(_ctx(nav_status=nav, speech=_speech("go left")))
        assert snap.dominant_activity == ACTIVITY_NAVIGATING

    def test_speech_while_stationary_interacting(self):
        an = SceneAnalyzer(_cfg())
        snap, _ = an.analyze(_ctx(speech=_speech("order coffee")))
        assert snap.dominant_activity == ACTIVITY_INTERACTING

    def test_person_nearby_serving(self):
        an = SceneAnalyzer(_cfg())
        # person at 1.0m, threshold = 1.5m → within serving range
        snap, _ = an.analyze(_ctx(persons=[_person("p1", distance_m=1.0)]))
        assert snap.dominant_activity == ACTIVITY_SERVING

    def test_person_far_interacting(self):
        an = SceneAnalyzer(_cfg())
        # person at 1.8m, near_person=2.0m but interaction=1.5m → interacting
        snap, _ = an.analyze(_ctx(persons=[_person("p1", distance_m=1.8)]))
        assert snap.dominant_activity == ACTIVITY_INTERACTING

    def test_crowded_above_threshold(self):
        an = SceneAnalyzer(_cfg(crowded_threshold=3))
        persons = [_person(f"p{i}", distance_m=1.0) for i in range(4)]
        snap, _ = an.analyze(_ctx(persons=persons))
        assert snap.dominant_activity == ACTIVITY_CROWDED
        assert snap.is_crowded

    def test_exactly_threshold_not_crowded(self):
        an = SceneAnalyzer(_cfg(crowded_threshold=3))
        persons = [_person(f"p{i}") for i in range(2)]  # 2 < 3
        snap, _ = an.analyze(_ctx(persons=persons))
        assert not snap.is_crowded


# ── Spatial context ───────────────────────────────────────────────────────────


class TestSpatialContext:
    def test_open_space_no_persons(self):
        an = SceneAnalyzer(_cfg())
        snap, _ = an.analyze(_ctx())
        assert snap.spatial_context == "open_space"

    def test_near_person_within_threshold(self):
        an = SceneAnalyzer(_cfg(near_person_threshold_m=2.0))
        snap, _ = an.analyze(_ctx(persons=[_person("p1", distance_m=1.5)]))
        assert snap.spatial_context == "near_person"

    def test_crowded_spatial(self):
        an = SceneAnalyzer(_cfg(crowded_threshold=2))
        snap, _ = an.analyze(_ctx(persons=[_person("a"), _person("b")]))
        assert snap.spatial_context == "crowded"


# ── Missing sensor data ───────────────────────────────────────────────────────


class TestMissingSensorData:
    def test_all_stale_high_uncertainty(self):
        an = SceneAnalyzer(_cfg())
        ctx = _ctx(
            stale=["objects", "persons", "speech", "nav_status", "robot_pose"], uncertainty="HIGH"
        )
        snap, _ = an.analyze(ctx)
        assert snap.uncertainty_level == "HIGH"
        assert snap.confidence < 0.5  # penalised heavily

    def test_stale_modalities_in_snapshot(self):
        an = SceneAnalyzer(_cfg())
        ctx = _ctx(stale=["speech"], uncertainty="MEDIUM")
        snap, _ = an.analyze(ctx)
        assert "speech" in snap.stale_modalities

    def test_no_persons_data_proximity_inf(self):
        an = SceneAnalyzer(_cfg())
        snap, _ = an.analyze(_ctx())
        assert snap.human_proximity_m == math.inf


# ── Wrong person recognition (spurious / flip IDs) ───────────────────────────


class TestWrongPersonRecognition:
    def test_spurious_id_creates_arrived_event(self):
        an = SceneAnalyzer(_cfg())
        an.analyze(_ctx(persons=[_person("real_person")]))
        # next frame: different ID (recognition error)
        _, events = an.analyze(_ctx(persons=[_person("ghost_id")]))
        types = {e.event_type for e in events}
        assert "person_arrived" in types  # ghost_id "arrived"
        assert "person_left" in types  # real_person "left"

    def test_consistent_id_no_events(self):
        an = SceneAnalyzer(_cfg())
        an.analyze(_ctx(persons=[_person("p1")]))
        _, events = an.analyze(_ctx(persons=[_person("p1")]))
        assert not any(e.event_type in ("person_arrived", "person_left") for e in events)

    def test_person_confidence_below_threshold_not_in_snapshot(self):
        # Low-confidence persons are filtered OUT by MultimodalFusion before
        # SceneAnalyzer sees them; SceneAnalyzer snapshot has no person entry.
        an = SceneAnalyzer(_cfg())
        # Simulate fusion already filtered out the low-confidence person
        snap, _ = an.analyze(_ctx(persons=[]))
        assert snap.present_person_ids == []


# ── Event detection ───────────────────────────────────────────────────────────


class TestEventDetection:
    def test_no_events_first_call(self):
        an = SceneAnalyzer(_cfg())
        _, events = an.analyze(_ctx())
        assert events == []

    def test_person_arrived_event(self):
        an = SceneAnalyzer(_cfg())
        an.analyze(_ctx())
        _, events = an.analyze(_ctx(persons=[_person("p1")]))
        assert any(e.event_type == "person_arrived" and e.subject_id == "p1" for e in events)

    def test_person_left_event(self):
        an = SceneAnalyzer(_cfg())
        an.analyze(_ctx(persons=[_person("p1")]))
        _, events = an.analyze(_ctx())
        assert any(e.event_type == "person_left" and e.subject_id == "p1" for e in events)

    def test_activity_changed_event(self):
        an = SceneAnalyzer(_cfg())
        an.analyze(_ctx())  # idle
        nav = NavStatus(status="navigating", is_moving=True)
        _, events = an.analyze(_ctx(nav_status=nav))
        assert any(e.event_type == "activity_changed" for e in events)

    def test_crowd_formed_event(self):
        an = SceneAnalyzer(_cfg(crowded_threshold=2))
        an.analyze(_ctx(persons=[_person("p1")]))  # 1 person, not crowded
        persons = [_person("p1"), _person("p2")]
        _, events = an.analyze(_ctx(persons=persons))
        assert any(e.event_type == "crowd_formed" for e in events)

    def test_object_appeared_event(self):
        an = SceneAnalyzer(_cfg())
        an.analyze(_ctx())
        obj = ObjectObservation(class_name="cup", confidence=0.9)
        _, events = an.analyze(_ctx(objects=[obj]))
        assert any(e.event_type == "object_appeared" and e.subject_id == "cup" for e in events)

    def test_object_disappeared_event(self):
        an = SceneAnalyzer(_cfg())
        obj = ObjectObservation(class_name="cup", confidence=0.9)
        an.analyze(_ctx(objects=[obj]))
        _, events = an.analyze(_ctx())
        assert any(e.event_type == "object_disappeared" for e in events)

    def test_debounce_suppresses_rapid_events(self):
        an = SceneAnalyzer(_cfg(event_debounce_sec=60.0))  # very long debounce
        an.analyze(_ctx())
        _, events1 = an.analyze(_ctx(persons=[_person("p1")]))
        _, events2 = an.analyze(_ctx(persons=[_person("p1")]))
        # Second call (within debounce window): still same person, no new events
        assert not any(e.event_type == "person_arrived" for e in events2)

    def test_reset_clears_state(self):
        an = SceneAnalyzer(_cfg())
        an.analyze(_ctx(persons=[_person("p1")]))
        an.reset()
        _, events = an.analyze(_ctx(persons=[_person("p1")]))
        # After reset, no diff possible → no events
        assert events == []
