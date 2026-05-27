"""Tests for BehaviorRecommender."""

import math
import time

from bonbon_perception_ai.fusion.types import FusionContext
from bonbon_perception_ai.understanding.behavior_recommender import (
    PRIORITY_HIGH,
    PRIORITY_LOW,
    PRIORITY_URGENT,
    BehaviorRecommender,
)
from bonbon_perception_ai.understanding.intent_engine import IntentSlot, UserIntent
from bonbon_perception_ai.understanding.risk_assessor import RiskEvent
from bonbon_perception_ai.understanding.scene_analyzer import SceneSnapshot


def _snap(activity="idle", persons=None, crowded=False) -> SceneSnapshot:
    import uuid

    return SceneSnapshot(
        scene_id=str(uuid.uuid4()),
        timestamp=time.monotonic(),
        confidence=0.9,
        uncertainty_level="LOW",
        present_object_classes=[],
        present_person_ids=persons or [],
        dominant_activity=activity,
        activity_label=activity,
        spatial_context="open_space",
        human_proximity_m=math.inf,
        is_crowded=crowded,
        stale_modalities=[],
        description="",
    )


def _ctx() -> FusionContext:
    return FusionContext(
        timestamp=time.monotonic(),
        objects=[],
        persons=[],
        speech=None,
        robot_pose=None,
        nav_status=None,
        stale_modalities=[],
        uncertainty_level="LOW",
    )


def _intent(
    cls="order_item", ambiguous=False, speaker="u1", slots=None, text="coffee"
) -> UserIntent:
    return UserIntent(
        intent_class=cls,
        confidence=0.9,
        speaker_id=speaker,
        raw_text=text,
        slots=slots or [],
        is_ambiguous=ambiguous,
        fallback_response="Sorry, I didn't understand." if ambiguous else "",
    )


def _risk(risk_type="person_too_close", severity="CRITICAL", requires=True) -> RiskEvent:
    import uuid

    return RiskEvent(
        risk_type=risk_type,
        severity=severity,
        confidence=0.9,
        subject_id="p1",
        description="test risk",
        requires_immediate_action=requires,
        risk_id=str(uuid.uuid4()),
    )


class TestDefaultIdle:
    def test_no_input_returns_idle(self):
        rec = BehaviorRecommender().recommend(_ctx(), _snap(), None, [])
        assert rec.behavior_class == "idle"
        assert rec.priority == PRIORITY_LOW

    def test_idle_has_recommendation_id(self):
        rec = BehaviorRecommender().recommend(_ctx(), _snap(), None, [])
        assert len(rec.recommendation_id) > 0


class TestRiskDrivenBehavior:
    def test_critical_risk_overrides_intent(self):
        intent = _intent("order_item")
        risk = _risk("person_too_close", "CRITICAL")
        rec = BehaviorRecommender().recommend(_ctx(), _snap(), intent, [risk])
        assert rec.behavior_class == "alert_safety"
        assert rec.priority == PRIORITY_URGENT

    def test_nav_uncertainty_stops_navigation(self):
        risk = _risk("navigation_with_uncertainty", "HIGH", requires=False)
        rec = BehaviorRecommender().recommend(_ctx(), _snap(), None, [risk])
        assert rec.behavior_class == "stop_navigation"
        assert rec.priority == PRIORITY_HIGH

    def test_conflicting_commands_asks_clarification(self):
        risk = _risk("conflicting_commands", "LOW", requires=False)
        rec = BehaviorRecommender().recommend(_ctx(), _snap(), None, [risk])
        assert rec.behavior_class == "speak_clarification"

    def test_trigger_type_is_risk_event(self):
        risk = _risk("person_too_close", "CRITICAL")
        rec = BehaviorRecommender().recommend(_ctx(), _snap(), None, [risk])
        assert rec.trigger_type == "risk_event"
        assert rec.trigger_id == risk.risk_id


class TestIntentDrivenBehavior:
    def test_greeting_speak_greeting(self):
        rec = BehaviorRecommender().recommend(
            _ctx(), _snap(), _intent("greeting", text="hello"), []
        )
        assert rec.behavior_class == "speak_greeting"

    def test_order_item_serve_item(self):
        slots = [IntentSlot("item", "coffee", 0.9)]
        rec = BehaviorRecommender().recommend(
            _ctx(), _snap(), _intent("order_item", slots=slots), []
        )
        assert rec.behavior_class == "serve_item"
        assert rec.params.get("item") == "coffee"

    def test_navigate_to_navigate_goal(self):
        slots = [IntentSlot("destination", "table 3", 0.9)]
        rec = BehaviorRecommender().recommend(
            _ctx(), _snap(), _intent("navigate_to", slots=slots, text="go to table 3"), []
        )
        assert rec.behavior_class == "navigate_to_goal"
        assert "destination" in rec.params

    def test_cancel_stop_navigation(self):
        rec = BehaviorRecommender().recommend(_ctx(), _snap(), _intent("cancel", text="stop"), [])
        assert rec.behavior_class == "stop_navigation"
        assert rec.priority == PRIORITY_HIGH

    def test_help_request_alert_safety(self):
        rec = BehaviorRecommender().recommend(
            _ctx(), _snap(), _intent("help_request", text="help me"), []
        )
        assert rec.behavior_class == "alert_safety"

    def test_ambiguous_intent_speak_clarification(self):
        rec = BehaviorRecommender().recommend(
            _ctx(), _snap(), _intent("unknown", ambiguous=True), []
        )
        assert rec.behavior_class == "speak_clarification"
        assert "speech_text" in rec.params

    def test_trigger_type_user_intent(self):
        intent = _intent("greeting")
        rec = BehaviorRecommender().recommend(_ctx(), _snap(), intent, [])
        assert rec.trigger_type == "user_intent"
        assert rec.trigger_id == intent.intent_id


class TestSceneDrivenBehavior:
    def test_idle_with_distant_person_approach(self):
        import uuid

        from bonbon_perception_ai.understanding.scene_analyzer import SceneSnapshot

        snap = SceneSnapshot(
            scene_id=str(uuid.uuid4()),
            timestamp=time.monotonic(),
            confidence=0.9,
            uncertainty_level="LOW",
            present_object_classes=[],
            present_person_ids=["p1"],
            dominant_activity="idle",
            activity_label="idle",
            spatial_context="open_space",
            human_proximity_m=2.5,
            is_crowded=False,
            stale_modalities=[],
            description="",
        )
        rec = BehaviorRecommender().recommend(_ctx(), snap, None, [])
        assert rec.behavior_class == "approach_person"
        assert rec.params.get("target_id") == "p1"

    def test_silence_intent_returns_idle(self):
        intent = _intent("silence", text="")
        rec = BehaviorRecommender().recommend(_ctx(), _snap(), intent, [])
        # Silence → recommender sees intent_class="silence" → falls through to scene/idle
        assert rec.behavior_class in ("idle", "approach_person")
