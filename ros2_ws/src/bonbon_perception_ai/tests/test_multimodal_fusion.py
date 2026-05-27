"""Tests for MultimodalFusion."""

import math

import pytest
from bonbon_perception_ai.config.perception_config import FusionConfig
from bonbon_perception_ai.fusion.multimodal_fusion import MultimodalFusion
from bonbon_perception_ai.fusion.types import (
    FusionContext,
    NavStatus,
    ObjectObservation,
    PersonObservation,
    RobotPose,
    SpeechInput,
)


def _cfg(**kw) -> FusionConfig:
    defaults = dict(
        objects_stale_sec=2.0,
        persons_stale_sec=2.0,
        speech_stale_sec=5.0,
        pose_stale_sec=5.0,
        nav_stale_sec=5.0,
        min_object_confidence=0.40,
        min_person_confidence=0.50,
    )
    defaults.update(kw)
    return FusionConfig(**defaults)


def _obj(class_name="cup", confidence=0.9, distance_m=1.5) -> ObjectObservation:
    return ObjectObservation(class_name=class_name, confidence=confidence, distance_m=distance_m)


def _person(person_id="p1", confidence=0.9, distance_m=1.5) -> PersonObservation:
    return PersonObservation(person_id=person_id, confidence=confidence, distance_m=distance_m)


def _speech(text="hello", confidence=0.9) -> SpeechInput:
    return SpeechInput(text=text, confidence=confidence)


class TestFreshContext:
    def test_empty_fusion_all_stale(self):
        f = MultimodalFusion(_cfg())
        ctx = f.fuse()
        assert isinstance(ctx, FusionContext)
        assert ctx.objects == []
        assert ctx.persons == []
        assert ctx.speech is None
        assert "objects" in ctx.stale_modalities

    def test_after_update_not_stale(self):
        f = MultimodalFusion(_cfg())
        f.update_objects([_obj()])
        f.update_persons([_person()])
        ctx = f.fuse()
        assert "objects" not in ctx.stale_modalities
        assert "persons" not in ctx.stale_modalities

    def test_objects_filtered_by_confidence(self):
        f = MultimodalFusion(_cfg(min_object_confidence=0.6))
        f.update_objects(
            [
                _obj("chair", confidence=0.8),
                _obj("table", confidence=0.3),  # below threshold
            ]
        )
        ctx = f.fuse()
        assert len(ctx.objects) == 1
        assert ctx.objects[0].class_name == "chair"

    def test_persons_filtered_by_confidence(self):
        f = MultimodalFusion(_cfg(min_person_confidence=0.7))
        f.update_persons(
            [
                _person("p1", confidence=0.9),
                _person("p2", confidence=0.4),  # below threshold
            ]
        )
        ctx = f.fuse()
        assert len(ctx.persons) == 1
        assert ctx.persons[0].person_id == "p1"


class TestSpeechFusion:
    def test_speech_in_context(self):
        f = MultimodalFusion(_cfg())
        s = _speech("order coffee")
        f.update_speech(s)
        ctx = f.fuse()
        assert ctx.speech is not None
        assert ctx.speech.text == "order coffee"
        assert ctx.has_speech

    def test_silence_not_has_speech(self):
        f = MultimodalFusion(_cfg())
        f.update_speech(SpeechInput(text="", confidence=0.9, is_silence=True))
        ctx = f.fuse()
        assert not ctx.has_speech

    def test_timeout_not_has_speech(self):
        f = MultimodalFusion(_cfg())
        f.update_speech(SpeechInput(text="", confidence=0.0, is_timeout=True))
        ctx = f.fuse()
        assert not ctx.has_speech


class TestNavAndPose:
    def test_nav_status_in_context(self):
        f = MultimodalFusion(_cfg())
        f.update_nav_status(NavStatus(status="navigating", is_moving=True))
        ctx = f.fuse()
        assert ctx.nav_status is not None
        assert ctx.is_moving

    def test_pose_in_context(self):
        f = MultimodalFusion(_cfg())
        f.update_pose(RobotPose(x=1.0, y=2.0, theta_deg=45.0))
        ctx = f.fuse()
        assert ctx.robot_pose is not None
        assert ctx.robot_pose.x == pytest.approx(1.0)


class TestUncertaintyLevels:
    def test_all_stale_high_uncertainty(self):
        f = MultimodalFusion(_cfg())
        ctx = f.fuse()
        assert ctx.uncertainty_level == "HIGH"

    def test_all_fresh_low_uncertainty(self):
        f = MultimodalFusion(_cfg())
        f.update_objects([])
        f.update_persons([])
        f.update_speech(SpeechInput(text="", confidence=1.0, is_silence=True))
        f.update_pose(RobotPose())
        f.update_nav_status(NavStatus())
        ctx = f.fuse()
        assert ctx.uncertainty_level == "LOW"


class TestDerivedProperties:
    def test_nearest_person_distance(self):
        f = MultimodalFusion(_cfg())
        f.update_persons(
            [
                _person("p1", distance_m=3.0),
                _person("p2", distance_m=1.5),
                _person("p3", distance_m=2.2),
            ]
        )
        ctx = f.fuse()
        assert ctx.nearest_person_distance_m == pytest.approx(1.5)

    def test_nearest_person_no_persons_is_inf(self):
        f = MultimodalFusion(_cfg())
        f.update_persons([])
        ctx = f.fuse()
        assert ctx.nearest_person_distance_m == math.inf

    def test_person_count(self):
        f = MultimodalFusion(_cfg())
        f.update_persons([_person("p1"), _person("p2")])
        assert f.fuse().person_count == 2


class TestClearAll:
    def test_clear_all_flushes_data(self):
        f = MultimodalFusion(_cfg())
        f.update_objects([_obj()])
        f.update_persons([_person()])
        f.clear_all()
        ctx = f.fuse()
        assert ctx.objects == []
        assert ctx.persons == []
        assert ctx.speech is None
