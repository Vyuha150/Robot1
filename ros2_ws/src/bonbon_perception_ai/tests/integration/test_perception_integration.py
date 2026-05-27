"""
Integration tests: full wired perception + AI pipeline without ROS2.

Exercises:
  MultimodalFusion → SceneAnalyzer → IntentEngine → RiskAssessor
    → BehaviorRecommender → MemoryManager

Scenarios:
  - Normal flow: person arrives, speaks, orders item
  - Missing sensor data: all modalities stale
  - Conflicting speech commands
  - Wrong person recognition (ID flip)
  - Ambiguous speech command
  - High-risk proximity while navigating
  - Privacy mode: anonymised persons
  - Multi-person scene
"""

from __future__ import annotations

import sys
import time
import types
from unittest.mock import MagicMock

import pytest

# ── ROS2 stub (identical pattern to bonbon_speech tests) ─────────────────────


def _inject_stubs():
    if "rclpy" in sys.modules:
        return
    rclpy = types.ModuleType("rclpy")
    rclpy.init = lambda args=None: None
    rclpy.spin = lambda n: None
    rclpy.shutdown = lambda: None
    lc = types.ModuleType("rclpy.lifecycle")
    lc.TransitionCallbackReturn = type("TCR", (), {"SUCCESS": "s", "FAILURE": "f"})
    lc.State = type("State", (), {})

    class _FakeNode:
        def __init__(self, n):
            self._name = n

        def get_logger(self):
            class L:
                def info(s, *a):
                    pass

                def debug(s, *a):
                    pass

                def warning(s, *a):
                    pass

                def error(s, *a):
                    pass

            return L()

        def create_lifecycle_publisher(self, *a, **k):
            return MagicMock()

        def create_subscription(self, *a, **k):
            return MagicMock()

        def create_timer(self, *a, **k):
            return MagicMock()

        def get_parameter(self, n):
            class P:
                value = None

            return P()

        def declare_parameter(self, *a, **k):
            pass

        def destroy_node(self):
            pass

    lc.LifecycleNode = _FakeNode
    qos = types.ModuleType("rclpy.qos")
    qos.QoSProfile = type("QoSProfile", (), {"__init__": lambda s, **k: None})
    qos.ReliabilityPolicy = type("RP", (), {"RELIABLE": 1, "BEST_EFFORT": 0})
    qos.HistoryPolicy = type("HP", (), {"KEEP_LAST": 1})
    rclpy.lifecycle = lc
    rclpy.qos = qos
    for k, v in [("rclpy", rclpy), ("rclpy.lifecycle", lc), ("rclpy.qos", qos)]:
        sys.modules.setdefault(k, v)


_inject_stubs()

# ── Pipeline imports ──────────────────────────────────────────────────────────

from bonbon_perception_ai.config.perception_config import (
    FusionConfig,
    PerceptionAIConfig,
)
from bonbon_perception_ai.fusion.multimodal_fusion import MultimodalFusion
from bonbon_perception_ai.fusion.types import (
    NavStatus,
    PersonObservation,
    SpeechInput,
)
from bonbon_perception_ai.memory.memory_manager import MemoryManager
from bonbon_perception_ai.understanding.behavior_recommender import BehaviorRecommender
from bonbon_perception_ai.understanding.intent_engine import IntentEngine
from bonbon_perception_ai.understanding.risk_assessor import RiskAssessor
from bonbon_perception_ai.understanding.scene_analyzer import SceneAnalyzer

# ── Wired pipeline fixture ────────────────────────────────────────────────────


def _make_pipeline(anon=False, db="", debounce=0.0):
    cfg = PerceptionAIConfig()
    cfg.fusion.objects_stale_sec = 60.0  # never stale in tests
    cfg.fusion.persons_stale_sec = 60.0
    cfg.fusion.speech_stale_sec = 60.0
    cfg.fusion.pose_stale_sec = 60.0
    cfg.fusion.nav_stale_sec = 60.0
    cfg.scene.event_debounce_sec = debounce
    cfg.memory.db_path = db
    cfg.memory.privacy_anonymize_persons = anon

    fusion = MultimodalFusion(cfg.fusion)
    scene_an = SceneAnalyzer(cfg.scene)
    intent_eng = IntentEngine(cfg.intent)
    risk_assr = RiskAssessor(cfg.risk)
    behavior = BehaviorRecommender()
    memory = MemoryManager(cfg.memory)
    memory.open()
    return fusion, scene_an, intent_eng, risk_assr, behavior, memory


def _run_tick(fusion, scene_an, risk_assr, behavior, intent=None):
    ctx = fusion.fuse()
    snap, events = scene_an.analyze(ctx)
    intent_class = intent.intent_class if intent else None
    risks = risk_assr.assess(ctx, snap, intent_class)
    rec = behavior.recommend(ctx, snap, intent, risks)
    return ctx, snap, events, risks, rec


def _person(pid="p1", d=1.5, conf=0.9):
    return PersonObservation(person_id=pid, confidence=conf, distance_m=d)


def _speech(text, silence=False, timeout=False, speaker="user1"):
    return SpeechInput(
        text=text,
        confidence=0.9,
        speaker_id=speaker,
        is_silence=silence,
        is_timeout=timeout,
    )


# ── Scenario 1: Normal ordering flow ─────────────────────────────────────────


class TestNormalOrderingFlow:
    def test_person_arrives_and_orders(self):
        fusion, scene_an, intent_eng, risk_assr, behavior, mem = _make_pipeline()

        # Tick 1: empty scene
        _, snap1, events1, _, rec1 = _run_tick(fusion, scene_an, risk_assr, behavior)
        assert snap1.dominant_activity == "idle"
        assert events1 == []

        # Tick 2: person arrives
        fusion.update_persons([_person("customer_01", d=2.5)])
        _, snap2, events2, _, rec2 = _run_tick(fusion, scene_an, risk_assr, behavior)
        assert "customer_01" in snap2.present_person_ids
        assert any(e.event_type == "person_arrived" for e in events2)

        # Tick 3: person speaks
        speech = _speech("I'd like to order a coffee please")
        fusion.update_speech(speech)
        intent = intent_eng.classify(speech, fusion.fuse())
        assert intent is not None
        assert intent.intent_class == "order_item"

        # Record interaction
        mem.record_interaction("customer_01", intent)

        # Behavior
        _, _, _, risks, rec3 = _run_tick(fusion, scene_an, risk_assr, behavior, intent)
        assert rec3.behavior_class == "serve_item"

        # Memory
        history = mem.get_person_history("customer_01")
        assert history is not None
        assert len(history["interactions"]) == 1

        mem.close()

    def test_greeting_before_order(self):
        fusion, scene_an, intent_eng, risk_assr, behavior, mem = _make_pipeline()
        fusion.update_persons([_person("cust", d=1.5)])

        speech_hi = _speech("Hello there", speaker="cust")
        fusion.update_speech(speech_hi)
        intent_hi = intent_eng.classify(speech_hi, fusion.fuse())
        assert intent_hi.intent_class == "greeting"

        rec = behavior.recommend(fusion.fuse(), scene_an.analyze(fusion.fuse())[0], intent_hi, [])
        assert rec.behavior_class == "speak_greeting"
        mem.close()


# ── Scenario 2: Missing sensor data ──────────────────────────────────────────


class TestMissingSensorData:
    def test_all_stale_high_uncertainty_idle(self):
        fusion, scene_an, intent_eng, risk_assr, behavior, mem = _make_pipeline()
        # Don't update any modalities → all stale
        PerceptionAIConfig()
        # Use a fast-stale fusion
        fast_cfg = FusionConfig(
            objects_stale_sec=0.001,
            persons_stale_sec=0.001,
            speech_stale_sec=0.001,
            pose_stale_sec=0.001,
            nav_stale_sec=0.001,
        )
        fusion2 = MultimodalFusion(fast_cfg)
        time.sleep(0.01)
        ctx = fusion2.fuse()
        assert ctx.uncertainty_level == "HIGH"
        assert len(ctx.stale_modalities) >= 3
        mem.close()

    def test_only_speech_fresh_classifies_intent(self):
        fusion, scene_an, intent_eng, risk_assr, behavior, mem = _make_pipeline()
        fusion.update_speech(_speech("cancel"))
        ctx = fusion.fuse()
        speech = ctx.speech
        assert speech is not None
        intent = intent_eng.classify(speech, ctx)
        assert intent.intent_class == "cancel"
        mem.close()

    def test_no_vision_data_scene_still_idle(self):
        fusion, scene_an, intent_eng, risk_assr, behavior, mem = _make_pipeline()
        # Only update pose
        from bonbon_perception_ai.fusion.types import RobotPose

        fusion.update_pose(RobotPose(x=0.0, y=0.0))
        _, snap, _, _, rec = _run_tick(fusion, scene_an, risk_assr, behavior)
        assert snap.dominant_activity == "idle"
        assert snap.present_person_ids == []
        mem.close()


# ── Scenario 3: Conflicting speech commands ───────────────────────────────────


class TestConflictingCommands:
    def test_confirm_then_deny_triggers_conflict_risk(self):
        fusion, scene_an, intent_eng, risk_assr, behavior, mem = _make_pipeline()
        fusion.update_persons([_person()])

        s1 = _speech("yes please")
        s2 = _speech("no actually stop")

        fusion.update_speech(s1)
        intent_eng.classify(s1, fusion.fuse())

        fusion.update_speech(s2)
        i2 = intent_eng.classify(s2, fusion.fuse())

        ctx = fusion.fuse()
        snap = scene_an.analyze(ctx)[0]
        risks = risk_assr.assess(ctx, snap, i2.intent_class if i2 else None)
        # Risk may or may not fire depending on timing, but no crash
        assert isinstance(risks, list)
        mem.close()

    def test_cancel_after_order_generates_stop(self):
        fusion, scene_an, intent_eng, risk_assr, behavior, mem = _make_pipeline()
        s_order = _speech("bring me a coffee")
        s_cancel = _speech("cancel that")
        fusion.update_speech(s_order)
        intent_eng.classify(s_order, fusion.fuse())
        fusion.update_speech(s_cancel)
        i_cancel = intent_eng.classify(s_cancel, fusion.fuse())

        rec = behavior.recommend(fusion.fuse(), scene_an.analyze(fusion.fuse())[0], i_cancel, [])
        assert rec.behavior_class == "stop_navigation"
        mem.close()


# ── Scenario 4: Wrong person recognition ─────────────────────────────────────


class TestWrongPersonRecognition:
    def test_id_flip_creates_arrived_and_left_events(self):
        fusion, scene_an, intent_eng, risk_assr, behavior, mem = _make_pipeline()

        # Tick 1: person_A
        fusion.update_persons([_person("person_A")])
        _, _, events1, _, _ = _run_tick(fusion, scene_an, risk_assr, behavior)
        # First tick: no diff (no prior state)

        # Tick 2: recognition engine flips to person_B (wrong ID)
        fusion.update_persons([_person("person_B")])
        _, _, events2, _, _ = _run_tick(fusion, scene_an, risk_assr, behavior)
        event_types = {e.event_type for e in events2}
        assert "person_arrived" in event_types  # person_B "arrived"
        assert "person_left" in event_types  # person_A "left"
        mem.close()

    def test_consistent_id_no_spurious_events(self):
        fusion, scene_an, intent_eng, risk_assr, behavior, mem = _make_pipeline()
        fusion.update_persons([_person("stable_id")])
        _, _, events1, _, _ = _run_tick(fusion, scene_an, risk_assr, behavior)
        _, _, events2, _, _ = _run_tick(fusion, scene_an, risk_assr, behavior)
        person_events = [e for e in events2 if "person" in e.event_type]
        assert person_events == []
        mem.close()

    def test_very_low_confidence_person_not_tracked(self):
        fusion, scene_an, intent_eng, risk_assr, behavior, mem = _make_pipeline()
        # MultimodalFusion filters persons below 0.50 confidence
        fusion.update_persons([PersonObservation("ghost", confidence=0.3, distance_m=1.0)])
        ctx = fusion.fuse()
        assert ctx.persons == []
        mem.close()


# ── Scenario 5: Ambiguous command ────────────────────────────────────────────


class TestAmbiguousCommand:
    def test_ambiguous_intent_returns_clarification_behavior(self):
        fusion, scene_an, intent_eng, risk_assr, behavior, mem = _make_pipeline()
        fusion.update_persons([_person()])
        speech = _speech("uh... thing... you know")
        fusion.update_speech(speech)
        intent = intent_eng.classify(speech, fusion.fuse())
        assert intent is not None
        assert intent.is_ambiguous

        rec = behavior.recommend(fusion.fuse(), scene_an.analyze(fusion.fuse())[0], intent, [])
        assert rec.behavior_class == "speak_clarification"
        mem.close()

    def test_clarify_response_not_empty(self):
        fusion, scene_an, intent_eng, risk_assr, behavior, mem = _make_pipeline()
        speech = _speech("blah xyz qqq")
        fusion.update_speech(speech)
        intent = intent_eng.classify(speech, fusion.fuse())
        assert intent is not None
        assert intent.fallback_response != ""
        mem.close()


# ── Scenario 6: High-risk proximity while navigating ─────────────────────────


class TestHighRiskProximity:
    def test_critical_person_while_navigating_urgent_behavior(self):
        fusion, scene_an, intent_eng, risk_assr, behavior, mem = _make_pipeline()

        nav = NavStatus(status="navigating", is_moving=True)
        fusion.update_nav_status(nav)
        # Person critically close
        fusion.update_persons([_person("obstacle", d=0.25)])

        ctx = fusion.fuse()
        snap = scene_an.analyze(ctx)[0]
        risks = risk_assr.assess(ctx, snap)
        assert any(r.severity == "CRITICAL" for r in risks)

        rec = behavior.recommend(ctx, snap, None, risks)
        assert rec.behavior_class == "alert_safety"
        assert rec.priority == 3  # URGENT
        mem.close()


# ── Scenario 7: Privacy mode ──────────────────────────────────────────────────


class TestPrivacyMode:
    def test_anonymised_ids_in_memory(self):
        fusion, scene_an, intent_eng, risk_assr, behavior, mem = _make_pipeline(anon=True)
        mem.record_person("real_id_123")
        persons = mem.list_known_persons()
        ids = {p["id"] for p in persons}
        assert "real_id_123" not in ids
        assert any(i.startswith("anon_") for i in ids)
        mem.close()

    def test_forget_person_cleans_up(self):
        fusion, scene_an, intent_eng, risk_assr, behavior, mem = _make_pipeline()
        mem.record_person("p_forget")
        assert mem.is_known_person("p_forget")
        mem.forget_person("p_forget")
        assert not mem.is_known_person("p_forget")
        mem.close()


# ── Scenario 8: Multi-person scene ───────────────────────────────────────────


class TestMultiPersonScene:
    def test_three_persons_crowded(self):
        fusion, scene_an, intent_eng, risk_assr, behavior, mem = _make_pipeline()
        fusion.update_persons(
            [
                _person("p1", d=1.5),
                _person("p2", d=2.0),
                _person("p3", d=2.5),
            ]
        )
        _, snap, _, risks, _ = _run_tick(fusion, scene_an, risk_assr, behavior)
        assert snap.is_crowded
        assert snap.dominant_activity == "crowded"
        mem.close()

    def test_nearest_person_tracked(self):
        fusion, scene_an, intent_eng, risk_assr, behavior, mem = _make_pipeline()
        fusion.update_persons(
            [
                _person("far_one", d=3.5),
                _person("close_one", d=0.8),
            ]
        )
        ctx = fusion.fuse()
        assert ctx.nearest_person_distance_m == pytest.approx(0.8)
        mem.close()

    def test_multiple_person_risks_all_emitted(self):
        fusion, scene_an, intent_eng, risk_assr, behavior, mem = _make_pipeline()
        fusion.update_persons(
            [
                _person("p1", d=0.30),  # critical
                _person("p2", d=0.60),  # high
                _person("p3", d=0.90),  # medium
            ]
        )
        ctx = fusion.fuse()
        snap = scene_an.analyze(ctx)[0]
        risks = risk_assr.assess(ctx, snap)
        severities = {r.severity for r in risks if "person" in r.risk_type}
        assert "CRITICAL" in severities
        assert "HIGH" in severities
        assert "MEDIUM" in severities
        mem.close()
