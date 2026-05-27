"""
Tests for RiskAssessor.

Covers: person proximity (critical/high/medium), navigation with uncertainty,
crowded scene, stale sensors, conflicting commands.
"""

import math
import time

from bonbon_perception_ai.config.perception_config import RiskConfig
from bonbon_perception_ai.fusion.types import (
    FusionContext,
    NavStatus,
    PersonObservation,
    SpeechInput,
)
from bonbon_perception_ai.understanding.risk_assessor import RiskAssessor
from bonbon_perception_ai.understanding.scene_analyzer import SceneSnapshot


def _cfg(**kw) -> RiskConfig:
    defaults = dict(
        critical_proximity_m=0.40,
        high_proximity_m=0.70,
        caution_proximity_m=1.20,
        nav_uncertainty_risk=True,
        crowded_severity="LOW",
    )
    defaults.update(kw)
    return RiskConfig(**defaults)


def _ctx(
    persons=None, nav_status=None, stale=None, uncertainty="LOW", speech=None
) -> FusionContext:
    return FusionContext(
        timestamp=time.monotonic(),
        objects=[],
        persons=persons or [],
        speech=speech,
        robot_pose=None,
        nav_status=nav_status,
        stale_modalities=stale or [],
        uncertainty_level=uncertainty,
    )


def _person(pid="p1", distance_m=1.5) -> PersonObservation:
    return PersonObservation(person_id=pid, confidence=0.9, distance_m=distance_m)


def _snap(crowded=False, activity="idle", persons=None) -> SceneSnapshot:
    return SceneSnapshot(
        scene_id="s1",
        timestamp=time.monotonic(),
        confidence=0.8,
        uncertainty_level="LOW",
        present_object_classes=[],
        present_person_ids=persons or [],
        dominant_activity=activity,
        activity_label=activity,
        spatial_context="open_space",
        human_proximity_m=1.5,
        is_crowded=crowded,
        stale_modalities=[],
        description="test",
    )


class TestPersonProximity:
    def test_critical_proximity_critical_risk(self):
        ra = RiskAssessor(_cfg())
        risks = ra.assess(_ctx(persons=[_person("p1", distance_m=0.30)]), _snap())
        assert any(r.severity == "CRITICAL" and r.risk_type == "person_too_close" for r in risks)

    def test_critical_requires_immediate_action(self):
        ra = RiskAssessor(_cfg())
        risks = ra.assess(_ctx(persons=[_person("p1", distance_m=0.30)]), _snap())
        critical = [r for r in risks if r.severity == "CRITICAL"]
        assert critical[0].requires_immediate_action

    def test_high_proximity_high_risk(self):
        ra = RiskAssessor(_cfg())
        risks = ra.assess(_ctx(persons=[_person("p1", distance_m=0.55)]), _snap())
        assert any(r.severity == "HIGH" for r in risks)

    def test_caution_proximity_medium_risk(self):
        ra = RiskAssessor(_cfg())
        risks = ra.assess(_ctx(persons=[_person("p1", distance_m=0.90)]), _snap())
        assert any(r.severity == "MEDIUM" for r in risks)

    def test_far_person_no_risk(self):
        ra = RiskAssessor(_cfg())
        risks = ra.assess(_ctx(persons=[_person("p1", distance_m=3.0)]), _snap())
        prox_risks = [r for r in risks if "person" in r.risk_type]
        assert prox_risks == []

    def test_unknown_distance_nan_no_risk(self):
        ra = RiskAssessor(_cfg())
        p = PersonObservation(person_id="ghost", confidence=0.9, distance_m=math.nan)
        risks = ra.assess(_ctx(persons=[p]), _snap())
        prox = [r for r in risks if "person" in r.risk_type]
        assert prox == []

    def test_multiple_persons_multiple_risks(self):
        ra = RiskAssessor(_cfg())
        risks = ra.assess(
            _ctx(
                persons=[
                    _person("p1", distance_m=0.30),  # critical
                    _person("p2", distance_m=0.90),  # medium
                ]
            ),
            _snap(),
        )
        severities = {r.severity for r in risks if "person" in r.risk_type}
        assert "CRITICAL" in severities
        assert "MEDIUM" in severities

    def test_risks_sorted_by_severity_descending(self):
        ra = RiskAssessor(_cfg())
        risks = ra.assess(
            _ctx(
                persons=[
                    _person("p1", distance_m=0.30),
                    _person("p2", distance_m=0.90),
                ]
            ),
            _snap(),
        )
        sev_vals = [r.severity_int for r in risks]
        assert sev_vals == sorted(sev_vals, reverse=True)


class TestNavigationUncertainty:
    def test_moving_with_high_uncertainty_is_high_risk(self):
        ra = RiskAssessor(_cfg())
        nav = NavStatus(status="navigating", is_moving=True)
        ctx = _ctx(nav_status=nav, uncertainty="HIGH", stale=["objects", "persons", "speech"])
        risks = ra.assess(ctx, _snap())
        assert any(r.risk_type == "navigation_with_uncertainty" for r in risks)

    def test_moving_with_low_uncertainty_no_nav_risk(self):
        ra = RiskAssessor(_cfg())
        nav = NavStatus(status="navigating", is_moving=True)
        risks = ra.assess(_ctx(nav_status=nav, uncertainty="LOW"), _snap())
        assert not any(r.risk_type == "navigation_with_uncertainty" for r in risks)

    def test_stationary_no_nav_risk_even_if_uncertain(self):
        ra = RiskAssessor(_cfg())
        risks = ra.assess(_ctx(uncertainty="HIGH"), _snap())
        assert not any(r.risk_type == "navigation_with_uncertainty" for r in risks)

    def test_nav_risk_disabled_by_config(self):
        ra = RiskAssessor(_cfg(nav_uncertainty_risk=False))
        nav = NavStatus(status="navigating", is_moving=True)
        risks = ra.assess(_ctx(nav_status=nav, uncertainty="HIGH"), _snap())
        assert not any(r.risk_type == "navigation_with_uncertainty" for r in risks)


class TestCrowdedScene:
    def test_crowded_scene_low_risk(self):
        ra = RiskAssessor(_cfg(crowded_severity="LOW"))
        risks = ra.assess(_ctx(), _snap(crowded=True))
        assert any(r.risk_type == "crowded_area" for r in risks)

    def test_not_crowded_no_crowd_risk(self):
        ra = RiskAssessor(_cfg())
        risks = ra.assess(_ctx(), _snap(crowded=False))
        assert not any(r.risk_type == "crowded_area" for r in risks)


class TestStaleSensors:
    def test_two_stale_medium_risk(self):
        ra = RiskAssessor(_cfg())
        risks = ra.assess(_ctx(stale=["objects", "persons"], uncertainty="MEDIUM"), _snap())
        assert any(r.risk_type == "stale_sensors" for r in risks)

    def test_three_stale_requires_action(self):
        ra = RiskAssessor(_cfg())
        risks = ra.assess(
            _ctx(stale=["objects", "persons", "nav_status"], uncertainty="HIGH"), _snap()
        )
        stale_risks = [r for r in risks if r.risk_type == "stale_sensors"]
        assert any(r.requires_immediate_action for r in stale_risks)

    def test_one_stale_no_sensor_risk(self):
        ra = RiskAssessor(_cfg())
        risks = ra.assess(_ctx(stale=["speech"], uncertainty="MEDIUM"), _snap())
        assert not any(r.risk_type == "stale_sensors" for r in risks)


class TestConflictingCommands:
    def test_confirm_then_deny_conflict(self):
        ra = RiskAssessor(_cfg())
        snap = _snap()
        s1 = SpeechInput(text="yes", confidence=0.9, speaker_id="u1")
        s2 = SpeechInput(text="no", confidence=0.9, speaker_id="u1")
        ra.assess(_ctx(speech=s1), snap, latest_intent_class="confirm")
        risks = ra.assess(_ctx(speech=s2), snap, latest_intent_class="deny")
        assert any(r.risk_type == "conflicting_commands" for r in risks)

    def test_no_conflict_unrelated_intents(self):
        ra = RiskAssessor(_cfg())
        snap = _snap()
        ra.assess(_ctx(), snap, latest_intent_class="greeting")
        risks = ra.assess(_ctx(), snap, latest_intent_class="order_item")
        assert not any(r.risk_type == "conflicting_commands" for r in risks)

    def test_no_conflict_without_previous_command(self):
        ra = RiskAssessor(_cfg())
        risks = ra.assess(_ctx(), _snap(), latest_intent_class="cancel")
        assert not any(r.risk_type == "conflicting_commands" for r in risks)
