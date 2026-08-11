"""bonbon_edge_ai_runtime.safety_separation_guard -- Edge AI Runtime
brief Phase 7. Classifies every proposed action from every source
(LLM, UI, AI-Pi perception/gesture, behavior engine, safety system
itself) into one of 9 categories and blocks anything that would let a
non-authorized source directly control motors, servos, or issue a raw
Nav2 goal.

This is a NEW, centralized classifier -- per docs/DUPLICATE_PIPELINE_AUDIT.md
and docs/SAFETY_SEPARATION_AUDIT.md Finding 3, at least 5-6 independent
safety mechanisms already exist in this repo (safety_gate_node,
bonbon_motion_approval_gateway, bonbon_behavior_engine's risk
classifier, SafetyCommandFilter, CommandAuthorizer, SafetyStopBridge)
with inconsistent fail-open/fail-closed defaults between them. This
guard does not replace any of them -- it gives every one of them (and
every future caller) ONE place to ask "what category is this action,
and is it allowed from this source" with a single, always-fail-closed
answer, so a new caller can't accidentally reintroduce GAP-E1's mistake
by writing a 7th bespoke check.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum


class ActionCategory(str, Enum):
    TEXT_ONLY = "TEXT_ONLY"
    INFO_LOOKUP = "INFO_LOOKUP"
    STAFF_ALERT = "STAFF_ALERT"
    NAVIGATION_REQUEST = "NAVIGATION_REQUEST"
    ACTUATION_REQUEST = "ACTUATION_REQUEST"
    SAFETY_CRITICAL = "SAFETY_CRITICAL"
    UNSAFE_DIRECT_CONTROL = "UNSAFE_DIRECT_CONTROL"
    MEDICAL_DIAGNOSIS_RISK = "MEDICAL_DIAGNOSIS_RISK"
    PRIVACY_RISK = "PRIVACY_RISK"


# The only sources ever allowed to issue a direct hardware-control action.
# Everything else (llm, ui, ai_pi_gesture, ai_pi_perception,
# behavior_engine, patient_kiosk, operator_dashboard, ...) may only ever
# produce a NAVIGATION_REQUEST/ACTUATION_REQUEST proposal, never a direct
# command -- matching this brief's rules 1-6.
_AUTHORIZED_DIRECT_CONTROL_SOURCES = frozenset(
    {"safety_supervisor", "safety_gate", "motion_approval_gateway"}
)

# Action types that ARE a direct hardware command (not a proposal) --
# these are the ones the brief's "Never allow" table names explicitly.
_DIRECT_CONTROL_ACTION_TYPES = frozenset(
    {
        "direct_motor_command",
        "direct_servo_command",
        "raw_nav2_goal",
        "direct_navigation_command",
        "emergency_override",
    }
)

_PROPOSAL_ACTION_TYPES = {
    "navigation_request": ActionCategory.NAVIGATION_REQUEST,
    "actuation_request": ActionCategory.ACTUATION_REQUEST,
}

_INFORMATIONAL_ACTION_TYPES = {
    "text_response": ActionCategory.TEXT_ONLY,
    "speak": ActionCategory.TEXT_ONLY,
    "info_lookup": ActionCategory.INFO_LOOKUP,
    "staff_alert": ActionCategory.STAFF_ALERT,
    "idle": ActionCategory.TEXT_ONLY,
    "wait_for_input": ActionCategory.TEXT_ONLY,
}

# Deliberately small and conservative -- a real medical-diagnosis guard
# is a product/legal decision, not something a keyword list should claim
# to fully solve. This exists to catch the obvious cases (the LLM must
# never sound like it's diagnosing a patient) and route them for
# escalation rather than let them through as ordinary text.
_DIAGNOSIS_RISK_PHRASES = (
    "you have",
    "you probably have",
    "this is likely",
    "i diagnose",
    "you are diagnosed with",
    "take this medication",
    "stop taking your medication",
)

_PRIVACY_RISK_FIELDS = frozenset(
    {"ssn", "national_id", "patient_medical_record", "diagnosis_history", "credit_card"}
)


@dataclass
class ClassifiedAction:
    category: ActionCategory
    source_module: str
    action_type: str
    blocked: bool
    requires_approval: bool
    reason: str
    timestamp: float = field(default_factory=time.monotonic)


class SafetySeparationGuard:
    """Stateless classification logic + a bounded log of blocked actions
    for dashboard visibility (rule 10, Phase 7 requirement 8)."""

    def __init__(self, *, blocked_log_size: int = 200) -> None:
        self._blocked_log: deque[ClassifiedAction] = deque(maxlen=blocked_log_size)
        self._blocked_count = 0
        self._total_count = 0

    def classify(
        self,
        source_module: str,
        action_type: str,
        payload: dict | None = None,
    ) -> ClassifiedAction:
        payload = payload or {}
        self._total_count += 1
        result = self._classify_inner(source_module, action_type, payload)
        if result.blocked:
            self._blocked_count += 1
            self._blocked_log.append(result)
        return result

    def _classify_inner(self, source_module: str, action_type: str, payload: dict) -> ClassifiedAction:
        # 1. Direct hardware control -- only the Navigation Pi's own
        # safety authority may ever issue one. Everything else, no
        # matter how it's phrased or where it claims to come from, is
        # UNSAFE_DIRECT_CONTROL and blocked. This is the rule GAP-E1
        # violated before being fixed.
        if action_type in _DIRECT_CONTROL_ACTION_TYPES:
            if source_module in _AUTHORIZED_DIRECT_CONTROL_SOURCES:
                return ClassifiedAction(
                    category=ActionCategory.SAFETY_CRITICAL,
                    source_module=source_module,
                    action_type=action_type,
                    blocked=False,
                    requires_approval=False,
                    reason="direct control issued by the authorized safety authority",
                )
            return ClassifiedAction(
                category=ActionCategory.UNSAFE_DIRECT_CONTROL,
                source_module=source_module,
                action_type=action_type,
                blocked=True,
                requires_approval=False,
                reason=(
                    f"{source_module!r} attempted {action_type!r} directly -- only "
                    f"{sorted(_AUTHORIZED_DIRECT_CONTROL_SOURCES)} may issue direct hardware control; "
                    "everything else must go through a NAVIGATION_REQUEST/ACTUATION_REQUEST proposal"
                ),
            )

        # 2. Proposals -- always ALLOWED to be submitted, but always
        # require downstream Safety Supervisor / motion approval gateway
        # sign-off before they become real motion. requires_approval=True
        # is the load-bearing field callers must check.
        if action_type in _PROPOSAL_ACTION_TYPES:
            return ClassifiedAction(
                category=_PROPOSAL_ACTION_TYPES[action_type],
                source_module=source_module,
                action_type=action_type,
                blocked=False,
                requires_approval=True,
                reason="proposal accepted -- requires Safety Supervisor / motion approval gateway sign-off before dispatch",
            )

        # 3. Text/informational actions -- scanned for the two content
        # risk categories before being allowed through.
        if action_type in _INFORMATIONAL_ACTION_TYPES:
            text = str(payload.get("text", "")).lower()
            if text and any(phrase in text for phrase in _DIAGNOSIS_RISK_PHRASES):
                return ClassifiedAction(
                    category=ActionCategory.MEDICAL_DIAGNOSIS_RISK,
                    source_module=source_module,
                    action_type=action_type,
                    blocked=True,
                    requires_approval=False,
                    reason="response text resembles a medical diagnosis or medication instruction -- must be escalated to staff, not spoken by the robot",
                )
            leaked_fields = _PRIVACY_RISK_FIELDS.intersection(payload.keys())
            if leaked_fields:
                return ClassifiedAction(
                    category=ActionCategory.PRIVACY_RISK,
                    source_module=source_module,
                    action_type=action_type,
                    blocked=True,
                    requires_approval=False,
                    reason=f"payload includes sensitive field(s) {sorted(leaked_fields)} not safe to speak/display/cache",
                )
            return ClassifiedAction(
                category=_INFORMATIONAL_ACTION_TYPES[action_type],
                source_module=source_module,
                action_type=action_type,
                blocked=False,
                requires_approval=False,
                reason="informational action, no safety authority required",
            )

        # 4. Anything not explicitly recognized is blocked, not passed
        # through -- rule 13 ("if unsure, degrade safely instead of
        # failing silently"). A new action_type must be deliberately
        # added above, never default-allowed.
        return ClassifiedAction(
            category=ActionCategory.UNSAFE_DIRECT_CONTROL,
            source_module=source_module,
            action_type=action_type,
            blocked=True,
            requires_approval=False,
            reason=f"unrecognized action_type {action_type!r} -- fail closed rather than guess",
        )

    # ── Dashboard visibility ─────────────────────────────────────────

    def recent_blocked(self, n: int = 20) -> list[ClassifiedAction]:
        return list(self._blocked_log)[-n:]

    def summary(self) -> dict:
        return {
            "totalClassified": self._total_count,
            "totalBlocked": self._blocked_count,
            "recentBlocked": [
                {
                    "category": a.category.value,
                    "sourceModule": a.source_module,
                    "actionType": a.action_type,
                    "reason": a.reason,
                    "timestamp": a.timestamp,
                }
                for a in self.recent_blocked()
            ],
        }
