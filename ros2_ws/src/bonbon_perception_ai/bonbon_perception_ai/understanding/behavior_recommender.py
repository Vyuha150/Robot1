"""
bonbon_perception_ai.understanding.behavior_recommender
========================================================
Maps (SceneSnapshot, UserIntent?, RiskEvent[]) → BehaviorRecommendation.

Design principles
-----------------
* Rule-based priority table — deterministic, auditable, no external deps.
* Highest-severity risk always overrides intent-driven recommendations.
* Falls back to "idle" when nothing actionable is detected.
* Confidence is propagated from the triggering source.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

from bonbon_perception_ai.fusion.types import FusionContext
from bonbon_perception_ai.understanding.intent_engine import UserIntent
from bonbon_perception_ai.understanding.risk_assessor import RiskEvent
from bonbon_perception_ai.understanding.scene_analyzer import SceneSnapshot

# ── Output type ───────────────────────────────────────────────────────────────


@dataclass
class BehaviorRecommendation:
    behavior_class: str
    confidence: float
    priority: int  # 0=LOW 1=NORMAL 2=HIGH 3=URGENT
    trigger_type: str  # "user_intent"|"risk_event"|"context_event"|"periodic"
    trigger_id: str
    params: dict[str, str] = field(default_factory=dict)
    timeout_sec: float = 0.0
    recommendation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = field(default_factory=time.monotonic)


# ── Priority constants ────────────────────────────────────────────────────────
PRIORITY_LOW = 0
PRIORITY_NORMAL = 1
PRIORITY_HIGH = 2
PRIORITY_URGENT = 3

# ── Behavior class → param template keys ─────────────────────────────────────
_BEHAVIOR_CLASSES = {
    "idle",
    "approach_person",
    "speak_greeting",
    "speak_clarification",
    "speak_response",
    "navigate_to_goal",
    "stop_navigation",
    "alert_safety",
    "wait_for_input",
    "serve_item",
    "slow_down",
}


class BehaviorRecommender:
    """Stateless rule-based recommender."""

    # ── Public ────────────────────────────────────────────────────────────────

    def recommend(
        self,
        ctx: FusionContext,
        scene: SceneSnapshot,
        intent: UserIntent | None,
        risks: list[RiskEvent],
    ) -> BehaviorRecommendation:
        """
        Return the single highest-priority recommendation for this cycle.
        """
        # 1. Safety risks always take priority
        if risks:
            top_risk = risks[0]  # already sorted by severity
            rec = self._from_risk(top_risk)
            if rec is not None:
                return rec

        # 2. User intent
        if intent is not None and intent.intent_class not in ("silence", "unknown"):
            rec = self._from_intent(intent, scene)
            if rec is not None:
                return rec

        # 3. Ambient scene recommendations (no explicit command)
        rec = self._from_scene(scene, ctx)
        if rec is not None:
            return rec

        # 4. Default: idle
        return BehaviorRecommendation(
            behavior_class="idle",
            confidence=0.95,
            priority=PRIORITY_LOW,
            trigger_type="periodic",
            trigger_id=scene.scene_id,
        )

    # ── Risk-driven behavior ──────────────────────────────────────────────────

    def _from_risk(self, risk: RiskEvent) -> BehaviorRecommendation | None:
        mapping: dict[str, tuple[str, int]] = {
            "person_too_close": ("alert_safety", PRIORITY_URGENT),
            "navigation_with_uncertainty": ("stop_navigation", PRIORITY_HIGH),
            "conflicting_commands": ("speak_clarification", PRIORITY_NORMAL),
            "stale_sensors": ("wait_for_input", PRIORITY_HIGH),
        }
        if risk.risk_type in mapping:
            behavior, priority = mapping[risk.risk_type]
            return BehaviorRecommendation(
                behavior_class=behavior,
                confidence=risk.confidence,
                priority=priority,
                trigger_type="risk_event",
                trigger_id=risk.risk_id,
                params={
                    "risk_type": risk.risk_type,
                    "severity": risk.severity,
                    "subject_id": risk.subject_id,
                },
                timeout_sec=5.0,
            )
        return None

    # ── Intent-driven behavior ────────────────────────────────────────────────

    def _from_intent(
        self, intent: UserIntent, scene: SceneSnapshot
    ) -> BehaviorRecommendation | None:
        if intent.is_ambiguous:
            return BehaviorRecommendation(
                behavior_class="speak_clarification",
                confidence=0.80,
                priority=PRIORITY_NORMAL,
                trigger_type="user_intent",
                trigger_id=intent.intent_id,
                params={
                    "speaker_id": intent.speaker_id,
                    "speech_text": intent.fallback_response,
                },
                timeout_sec=8.0,
            )

        slot = intent.slot_dict

        if intent.intent_class == "greeting":
            return BehaviorRecommendation(
                behavior_class="speak_greeting",
                confidence=intent.confidence,
                priority=PRIORITY_NORMAL,
                trigger_type="user_intent",
                trigger_id=intent.intent_id,
                params={"speaker_id": intent.speaker_id},
                timeout_sec=5.0,
            )

        if intent.intent_class == "order_item":
            params = {"speaker_id": intent.speaker_id}
            if "item" in slot:
                params["item"] = slot["item"]
            if "quantity" in slot:
                params["quantity"] = slot["quantity"]
            return BehaviorRecommendation(
                behavior_class="serve_item",
                confidence=intent.confidence,
                priority=PRIORITY_NORMAL,
                trigger_type="user_intent",
                trigger_id=intent.intent_id,
                params=params,
                timeout_sec=30.0,
            )

        if intent.intent_class == "navigate_to":
            params = {"speaker_id": intent.speaker_id}
            if "destination" in slot:
                params["destination"] = slot["destination"]
            return BehaviorRecommendation(
                behavior_class="navigate_to_goal",
                confidence=intent.confidence,
                priority=PRIORITY_NORMAL,
                trigger_type="user_intent",
                trigger_id=intent.intent_id,
                params=params,
                timeout_sec=60.0,
            )

        if intent.intent_class == "cancel":
            return BehaviorRecommendation(
                behavior_class="stop_navigation",
                confidence=intent.confidence,
                priority=PRIORITY_HIGH,
                trigger_type="user_intent",
                trigger_id=intent.intent_id,
                params={"speaker_id": intent.speaker_id},
            )

        if intent.intent_class in ("ask_question", "confirm", "deny"):
            return BehaviorRecommendation(
                behavior_class="speak_response",
                confidence=intent.confidence,
                priority=PRIORITY_NORMAL,
                trigger_type="user_intent",
                trigger_id=intent.intent_id,
                params={
                    "speaker_id": intent.speaker_id,
                    "intent": intent.intent_class,
                    "raw_text": intent.raw_text[:100],
                },
                timeout_sec=8.0,
            )

        if intent.intent_class == "help_request":
            return BehaviorRecommendation(
                behavior_class="alert_safety",
                confidence=intent.confidence,
                priority=PRIORITY_HIGH,
                trigger_type="user_intent",
                trigger_id=intent.intent_id,
                params={"speaker_id": intent.speaker_id},
            )

        return None

    # ── Scene-driven behavior ─────────────────────────────────────────────────

    def _from_scene(
        self, scene: SceneSnapshot, ctx: FusionContext
    ) -> BehaviorRecommendation | None:
        # Person just entered scene and robot is idle → approach / greet
        if (
            scene.dominant_activity == "idle"
            and scene.present_person_ids
            and scene.human_proximity_m > 1.5
        ):
            return BehaviorRecommendation(
                behavior_class="approach_person",
                confidence=0.65,
                priority=PRIORITY_LOW,
                trigger_type="context_event",
                trigger_id=scene.scene_id,
                params={
                    "target_id": scene.present_person_ids[0],
                },
                timeout_sec=10.0,
            )
        return None
