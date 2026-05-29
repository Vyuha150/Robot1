"""LLMCommandGate — validates and translates LLM-generated text into safe proposals.

CRITICAL SAFETY CONTRACT
-------------------------
An LLM output MUST NEVER directly:
- Publish to /cmd_vel or any navigation topic
- Command a servo directly
- Bypass the safety supervisor
- Perform any actuator control

This gate enforces that contract.  It receives raw LLM text, classifies its
risk, and when safe, converts it to a structured BehaviorProposal that still
goes through the safety supervisor before execution.

LLM-to-action mapping
---------------------
The gate maps approved LLM intents to exactly one of these proposal types:
  'speak'            — TTS output only (safest)
  'gesture'          — expressive gesture only (safe)
  'ask_clarification'— robot asks the user to repeat / clarify
  'alert_operator'   — escalate to human operator
  'navigate'         — navigation request (requires safety approval)
  'approach'         — approach a person (requires safety approval)
  'ignore'           — do nothing (safe)

Any LLM output that does not match these categories is rejected.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from bonbon_behavior_engine.core.command_risk_classifier import (
    CommandRiskClassifier,
    RiskAssessment,
)

_logger = logging.getLogger(__name__)


@dataclass
class GatedCommand:
    """The result of passing an LLM command through the gate."""

    allowed: bool
    """True when the command is safe to propose."""

    proposal_type: str
    """Mapped proposal type: 'speak', 'gesture', 'navigate', 'approach',
    'ask_clarification', 'alert_operator', 'ignore', or '' when rejected."""

    proposal_content: str
    """Content for the proposal (TTS text, gesture name, nav goal label, etc.)."""

    risk: RiskAssessment
    """Risk assessment from the classifier."""

    rejection_reason: str = ""
    """Human-readable explanation when allowed=False."""

    tts_text: str = ""
    """Pre-extracted TTS text when proposal_type='speak'."""

    gesture_name: str = ""
    """Pre-extracted gesture name when proposal_type='gesture'."""


# Patterns for intent extraction from LLM text.
_SAY_PAT     = re.compile(
    r'(?:say|speak|tell|announce)\s*[:\-]?\s*["\']?(.+?)["\']?(?:\.|$)',
    re.IGNORECASE,
)
_GESTURE_PAT = re.compile(
    r'\b(wave|nod|nod_yes|shake_no|bow|greet|point_left|point_right|'
    r'point_forward|invite_gesture|greeting_pose|apology_pose|thinking_pose|'
    r'listening_pose|rest_pose|stop_gesture)\b',
    re.IGNORECASE,
)
_NAV_PAT     = re.compile(
    r'\b(?:go|navigate|move|travel|head)\s+to\s+(?:the\s+)?(.+?)(?:\.|,|$)',
    re.IGNORECASE,
)
_APPROACH_PAT = re.compile(
    r'\b(?:approach|walk\s+up\s+to)\s+(?:the\s+)?(?:person|user|visitor|guest)',
    re.IGNORECASE,
)
_CLARIFY_PAT = re.compile(
    r'\b(?:clarif|unclear|didn\'?t\s+understand|repeat|pardon|come\s+again)\b',
    re.IGNORECASE,
)

# Allowed gesture names (must exist in GestureLibrary)
_ALLOWED_GESTURES = frozenset({
    "wave", "nod_yes", "shake_no", "greeting_pose", "apology_pose",
    "thinking_pose", "listening_pose", "rest_pose", "invite_gesture",
    "point_left", "point_right",
})


class LLMCommandGate:
    """Validate and translate LLM outputs into safe structured proposals.

    Args:
        risk_classifier: Optional pre-built :class:`CommandRiskClassifier`.
        max_tts_chars: Maximum TTS text length extracted from LLM output.
    """

    def __init__(
        self,
        risk_classifier: Optional[CommandRiskClassifier] = None,
        max_tts_chars: int = 200,
    ) -> None:
        self._clf = risk_classifier or CommandRiskClassifier()
        self._max_tts = max_tts_chars
        self._stats = {"total": 0, "approved": 0, "rejected": 0, "critical": 0}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(
        self,
        llm_text: str,
        person_id: str = "",
        context: str = "",
    ) -> GatedCommand:
        """Evaluate a raw LLM output string.

        Args:
            llm_text: The raw text produced by the LLM.
            person_id: The person this command relates to (for proposal).
            context: Optional context hint ('emergency', 'child_safe', etc.)

        Returns:
            A :class:`GatedCommand` describing whether the command is allowed
            and what structured proposal to create.
        """
        self._stats["total"] += 1

        if not llm_text or not llm_text.strip():
            self._stats["rejected"] += 1
            return GatedCommand(
                allowed=False,
                proposal_type="",
                proposal_content="",
                risk=self._clf.classify("", source="llm"),
                rejection_reason="Empty LLM output.",
            )

        risk = self._clf.classify(llm_text, source="llm")

        if risk.risk_level == "critical":
            self._stats["critical"] += 1
            self._stats["rejected"] += 1
            _logger.error(
                "LLM command BLOCKED (critical risk): '%s…'", llm_text[:80]
            )
            return GatedCommand(
                allowed=False,
                proposal_type="alert_operator",
                proposal_content="LLM produced a forbidden command",
                risk=risk,
                rejection_reason=(
                    f"Critical risk: {'; '.join(risk.reasons[:2])}"
                ),
            )

        if risk.risk_level == "high":
            self._stats["rejected"] += 1
            _logger.warning(
                "LLM command BLOCKED (high risk): '%s…'", llm_text[:80]
            )
            return GatedCommand(
                allowed=False,
                proposal_type="ask_clarification",
                proposal_content="Command requires human operator approval",
                risk=risk,
                rejection_reason=(
                    f"High risk: {'; '.join(risk.reasons[:2])}"
                ),
            )

        # Attempt intent extraction
        proposal_type, content, tts_text, gesture_name = self._extract_intent(
            llm_text, risk, context
        )

        self._stats["approved"] += 1
        _logger.debug(
            "LLM command APPROVED: type=%s risk=%s text='%s…'",
            proposal_type, risk.risk_level, llm_text[:60],
        )

        return GatedCommand(
            allowed=True,
            proposal_type=proposal_type,
            proposal_content=content,
            risk=risk,
            tts_text=tts_text,
            gesture_name=gesture_name,
        )

    def stats(self) -> dict:
        """Return a copy of the gate statistics."""
        return dict(self._stats)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _extract_intent(
        self,
        text: str,
        risk: RiskAssessment,
        context: str,
    ) -> Tuple[str, str, str, str]:
        """Map LLM text to (proposal_type, content, tts_text, gesture_name)."""

        # 1. Navigation intent (medium risk approved)
        if risk.risk_level == "medium":
            nav_m = _NAV_PAT.search(text)
            if nav_m:
                dest = nav_m.group(1).strip()[:60]
                return "navigate", dest, "", ""
            if _APPROACH_PAT.search(text):
                return "approach", "approach_person", "", ""
            # Other medium-risk phrases default to asking clarification
            return "ask_clarification", text[:60], "", ""

        # 2. Clarification
        if _CLARIFY_PAT.search(text):
            return "ask_clarification", "please repeat your request", "", ""

        # 3. Gesture intent
        gest_m = _GESTURE_PAT.search(text)
        if gest_m:
            name_raw = gest_m.group(1).lower().replace(" ", "_")
            name = name_raw if name_raw in _ALLOWED_GESTURES else "nod_yes"
            return "gesture", name, "", name

        # 4. Speech intent — extract TTS text
        say_m = _SAY_PAT.search(text)
        if say_m:
            tts = say_m.group(1).strip()[: self._max_tts]
            return "speak", tts, tts, ""

        # 5. Fallback — treat whole text as TTS if risk is low/none
        if risk.risk_level in ("none", "low"):
            # Strip surrounding quotes, trim length
            tts = text.strip('"\'').strip()[: self._max_tts]
            return "speak", tts, tts, ""

        return "ask_clarification", "I'm not sure how to help with that.", "", ""
