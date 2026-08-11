"""bonbon_edge_ai_runtime.task_router -- Edge AI Runtime brief Phase 4.
THE genuinely new piece per docs/DUPLICATE_PIPELINE_AUDIT.md: no
cross-capability router existed anywhere in this repo before this
(confirmed by direct search across the whole codebase -- zero hits for
TaskRouter/RequestDispatcher; `pi_human_ai.yaml`'s declared
`resolution_order: [rule_engine, rag, llm]` was read by zero code).

Picks the cheapest safe route for a classified text intent, gesture
event, or emotion reading, following this brief's exact routing
examples: rule -> cache -> RAG -> tiny LLM -> ASR/TTS/vision -> degraded
fallback -> staff escalation. Every route that could touch navigation or
actuation is passed through SafetySeparationGuard before being returned,
so a caller can never accidentally skip that classification step.
"""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum

from bonbon_edge_ai_runtime.safety_separation_guard import ClassifiedAction, SafetySeparationGuard


class ChosenMethod(str, Enum):
    DETERMINISTIC_RULE = "deterministic_rule"
    EXACT_DATABASE_LOOKUP = "exact_database_lookup"
    CACHED_ANSWER = "cached_answer"
    RAG_RETRIEVAL = "rag_retrieval"
    TINY_LOCAL_LLM = "tiny_local_llm"
    ASR_MODEL = "asr_model"
    TTS_MODEL = "tts_model"
    HAILO_VISION_MODEL = "hailo_vision_model"
    CPU_FALLBACK_MODEL = "cpu_fallback_model"
    DEGRADED_FALLBACK_TEMPLATE = "degraded_fallback_template"
    STAFF_ESCALATION = "operator_staff_escalation"


@dataclass
class RouteDecision:
    route_id: str
    task_type: str
    chosen_method: ChosenMethod
    chosen_model: str | None
    fallback_model: str | None
    reason: str
    confidence: float
    estimated_latency_ms: float
    safety_required: bool
    dashboard_event: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "routeId": self.route_id,
            "taskType": self.task_type,
            "chosenMethod": self.chosen_method.value,
            "chosenModel": self.chosen_model,
            "fallbackModel": self.fallback_model,
            "reason": self.reason,
            "confidence": self.confidence,
            "estimatedLatencyMs": self.estimated_latency_ms,
            "safetyRequired": self.safety_required,
            "dashboardEvent": self.dashboard_event,
        }


# ── Deterministic rule tables -- checked FIRST for every text intent,
# matching this brief's rule/cache/RAG/LLM cost ordering. Deliberately
# small and conservative; a real deployment should widen these from
# real transcript logs, not from guessing every phrasing up front.
_EMERGENCY_KEYWORDS = (
    "help",
    "emergency",
    "fire",
    "collapsed",
    "chest pain",
    "can't breathe",
    "cant breathe",
    "bleeding",
    "heart attack",
)
_NAVIGATION_PATTERN = re.compile(r"\b(guide|take|walk)\s+me\s+to\b|\bnavigate\s+(me\s+)?to\b", re.I)
_APPOINTMENT_PATTERN = re.compile(r"\bbook\b.*\bappointment\b|\bappointment\b.*\bwith\b", re.I)

_GESTURE_SAFETY_CLASSES = frozenset({"stop_palm"})
_GESTURE_KNOWN_CLASSES = frozenset(
    {
        "wave",
        "raised_hand",
        "stop_palm",
        "pointing_left",
        "pointing_right",
        "pointing_forward",
        "pointing_at_object",
        "thumbs_up",
        "thumbs_down",
        "come_here",
        "go_away",
        "head_nod_yes",
        "head_shake_no",
        "namaste",
    }
)

# An emotion reading below this confidence must never strongly change
# robot behavior -- it's preserved as uncertain evidence for
# human-state fusion, not acted on directly.
_EMOTION_ACTIONABLE_CONFIDENCE = 0.6


class TaskRouter:
    def __init__(
        self,
        safety_guard: SafetySeparationGuard | None = None,
        cache_manager=None,
    ) -> None:
        self._safety_guard = safety_guard or SafetySeparationGuard()
        self._cache = cache_manager

    # ── Text / intent routing ────────────────────────────────────────

    def route_text_intent(
        self,
        text: str,
        intent_class: str | None = None,
        source_module: str = "ai_pi_speech",
    ) -> RouteDecision:
        text_lower = text.lower()
        route_id = uuid.uuid4().hex[:8]

        # 1. Emergency -- deterministic, no LLM, always allowed, always
        # staff-alerted + Safety Supervisor notified. Checked before
        # everything else -- an emergency phrase must never wait behind
        # a cache lookup or LLM call.
        if intent_class == "emergency" or any(kw in text_lower for kw in _EMERGENCY_KEYWORDS):
            classified = self._safety_guard.classify(source_module, "staff_alert", {"text": text})
            return self._decision(
                route_id,
                "emergency",
                ChosenMethod.DETERMINISTIC_RULE,
                None,
                None,
                "emergency phrase matched -- routed to the deterministic emergency workflow, "
                "staff alerted and Safety Supervisor notified, no LLM involved",
                confidence=1.0,
                estimated_latency_ms=5.0,
                safety_required=True,
                classified=classified,
            )

        # 2. Navigation request -- semantic only, never a direct Nav2 goal.
        if intent_class == "navigation" or _NAVIGATION_PATTERN.search(text_lower):
            classified = self._safety_guard.classify(source_module, "navigation_request", {"text": text})
            return self._decision(
                route_id,
                "navigation",
                ChosenMethod.DETERMINISTIC_RULE,
                None,
                None,
                "semantic navigation request resolved to a named location and submitted as a "
                "proposal only -- Safety Supervisor approval required before any Nav2 dispatch",
                confidence=0.9,
                estimated_latency_ms=20.0,
                safety_required=True,
                classified=classified,
            )

        # 3. Appointment booking -- deterministic workflow, never the LLM.
        if intent_class == "appointment" or _APPOINTMENT_PATTERN.search(text_lower):
            return self._decision(
                route_id,
                "appointment",
                ChosenMethod.DETERMINISTIC_RULE,
                None,
                None,
                "appointment booking is a deterministic workflow (patient/token/appointment "
                "system) -- never routed through the LLM",
                confidence=0.95,
                estimated_latency_ms=15.0,
                safety_required=False,
            )

        # 4. FAQ / hospital info -- cache, then RAG; LLM only for wording.
        if intent_class in ("faq", "hospital_info", None):
            if self._cache is not None:
                cached = self._cache.rag_get(text, "faq")
                if cached is not None:
                    return self._decision(
                        route_id,
                        "faq",
                        ChosenMethod.CACHED_ANSWER,
                        None,
                        None,
                        "cached FAQ answer hit -- no RAG retrieval or LLM call",
                        confidence=0.85,
                        estimated_latency_ms=2.0,
                        safety_required=False,
                    )
            return self._decision(
                route_id,
                "faq",
                ChosenMethod.RAG_RETRIEVAL,
                "rag_bonbon_llm_chroma",
                "rag_numpy_fallback",
                "hospital database / semantic map lookup -- the LLM is only invoked afterward "
                "for wording, never for the lookup itself",
                confidence=0.75,
                estimated_latency_ms=150.0,
                safety_required=False,
            )

        # 5. Small talk -- last resort: tiny local LLM, short reply, timeout-bounded.
        return self._decision(
            route_id,
            "small_talk",
            ChosenMethod.TINY_LOCAL_LLM,
            "llm_qwen25_05b",
            None,
            "no rule/cache/RAG match -- routed to the local qwen2.5:0.5b for a short, "
            "timeout-bounded reply",
            confidence=0.5,
            estimated_latency_ms=1500.0,
            safety_required=False,
        )

    # ── Gesture routing ──────────────────────────────────────────────

    def route_gesture(
        self,
        gesture_class: str,
        confidence: float,
        source_module: str = "ai_pi_gesture",
    ) -> RouteDecision:
        route_id = uuid.uuid4().hex[:8]

        if gesture_class in _GESTURE_SAFETY_CLASSES:
            classified = self._safety_guard.classify(source_module, "actuation_request", {"gesture": gesture_class})
            return self._decision(
                route_id,
                "gesture_safety",
                ChosenMethod.DETERMINISTIC_RULE,
                "gesture_mediapipe_holistic",
                "gesture_mock",
                f"{gesture_class!r} is a safety-relevant gesture -- routed to the Behavior Engine "
                "as a proposal, Safety Supervisor approval required, no direct hardware control",
                confidence=confidence,
                estimated_latency_ms=10.0,
                safety_required=True,
                classified=classified,
            )

        if gesture_class not in _GESTURE_KNOWN_CLASSES or confidence < 0.5:
            return self._decision(
                route_id,
                "gesture_unknown",
                ChosenMethod.DEGRADED_FALLBACK_TEMPLATE,
                None,
                None,
                f"gesture {gesture_class!r} unrecognized or low-confidence ({confidence:.2f}) -- "
                "ignored, no action taken",
                confidence=confidence,
                estimated_latency_ms=1.0,
                safety_required=False,
            )

        return self._decision(
            route_id,
            "gesture_social",
            ChosenMethod.DETERMINISTIC_RULE,
            "gesture_mediapipe_holistic",
            "gesture_mock",
            f"{gesture_class!r} is a non-safety social gesture -- routed to the Behavior Engine "
            "as a low-priority proposal",
            confidence=confidence,
            estimated_latency_ms=10.0,
            safety_required=False,
        )

    # ── Affective (emotion) routing ──────────────────────────────────

    def route_emotion(
        self,
        emotion_label: str,
        confidence: float,
        source_module: str = "ai_pi_affective",
    ) -> RouteDecision:
        route_id = uuid.uuid4().hex[:8]
        strongly_actionable = confidence >= _EMOTION_ACTIONABLE_CONFIDENCE
        reason = (
            f"emotion {emotion_label!r} at confidence {confidence:.2f} used to adapt tone/pacing only"
            if strongly_actionable
            else f"emotion {emotion_label!r} confidence {confidence:.2f} is below the actionable "
            f"threshold ({_EMOTION_ACTIONABLE_CONFIDENCE}) -- preserved as uncertain evidence for "
            "human-state fusion, no behavior change"
        )
        return self._decision(
            route_id,
            "affective_state",
            ChosenMethod.DETERMINISTIC_RULE,
            None,
            None,
            reason,
            confidence=confidence,
            estimated_latency_ms=1.0,
            safety_required=False,
        )

    # ── Shared decision builder ──────────────────────────────────────

    def _decision(
        self,
        route_id: str,
        task_type: str,
        chosen_method: ChosenMethod,
        chosen_model: str | None,
        fallback_model: str | None,
        reason: str,
        *,
        confidence: float,
        estimated_latency_ms: float,
        safety_required: bool,
        classified: ClassifiedAction | None = None,
    ) -> RouteDecision:
        dashboard_event = {
            "routeId": route_id,
            "taskType": task_type,
            "chosenMethod": chosen_method.value,
            "safetyRequired": safety_required,
            "timestamp": time.monotonic(),
        }
        if classified is not None:
            dashboard_event["safetyCategory"] = classified.category.value
            dashboard_event["safetyBlocked"] = classified.blocked
        return RouteDecision(
            route_id=route_id,
            task_type=task_type,
            chosen_method=chosen_method,
            chosen_model=chosen_model,
            fallback_model=fallback_model,
            reason=reason,
            confidence=confidence,
            estimated_latency_ms=estimated_latency_ms,
            safety_required=safety_required,
            dashboard_event=dashboard_event,
        )
