"""ProposalEvaluator — evaluates BehaviorProposal messages and produces decisions.

The evaluator is the last internal gate before a proposal is dispatched as a
BehaviorDecision.  It integrates:
  - Risk classification (CommandRiskClassifier)
  - Safety state (from bonbon_safety)
  - Operating mode constraints
  - Rate-limiting (prevents flooding actuation/TTS)

Decisions
---------
approved   — proposal is safe and consistent with current state
rejected   — proposal is unsafe or violates current operating constraints
modified   — proposal content was sanitised (e.g. TTS text truncated)
deferred   — proposal is valid but cannot execute now (e.g. robot is navigating)
escalated  — proposal requires operator acknowledgement
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from bonbon_behavior_engine.core.command_risk_classifier import CommandRiskClassifier

_logger = logging.getLogger(__name__)

# Safety levels
_LEVEL_DANGER = 3
_LEVEL_FAULT  = 6

# Rate limits (seconds between same proposal type)
_RATE_LIMITS: Dict[str, float] = {
    "speak":            1.5,
    "gesture":          2.0,
    "navigate":         5.0,
    "approach":         3.0,
    "ask_clarification": 4.0,
    "alert_operator":   10.0,
    "ignore":           0.0,
    "pause":            1.0,
    "resume":           1.0,
}

MAX_TTS_CHARS = 300
MAX_URGENCY_FOR_DEFERRAL = 0.7  # proposals with urgency > this are not deferred


@dataclass
class EvaluationResult:
    """Outcome of evaluating a single BehaviorProposal."""

    decision: str
    """'approved', 'rejected', 'modified', 'deferred', 'escalated'."""

    approved_action: str
    approved_content: str
    confidence: float
    safety_approved: bool
    operator_alerted: bool
    rejection_reason: str = ""
    modification_note: str = ""


class ProposalEvaluator:
    """Evaluate BehaviorProposals against safety, rate limits, and operating mode.

    Args:
        risk_classifier: Pre-built classifier (a new one is created if omitted).
        operating_mode: Current operating mode string.
    """

    def __init__(
        self,
        risk_classifier: Optional[CommandRiskClassifier] = None,
        operating_mode: str = "normal",
    ) -> None:
        self._clf = risk_classifier or CommandRiskClassifier()
        self._mode = operating_mode
        self._safety_level: int = 0
        self._last_dispatch: Dict[str, float] = {}

    # ------------------------------------------------------------------
    # State update
    # ------------------------------------------------------------------

    def update_safety_level(self, level: int) -> None:
        """Refresh the cached safety level."""
        self._safety_level = level

    def set_operating_mode(self, mode: str) -> None:
        """Update the operating mode."""
        _logger.info("ProposalEvaluator: mode %s → %s", self._mode, mode)
        self._mode = mode

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    def evaluate(
        self,
        proposal_type: str,
        proposal_content: str,
        source: str,
        urgency: float,
        raw_llm_command: str = "",
    ) -> EvaluationResult:
        """Evaluate a proposal and return an :class:`EvaluationResult`.

        Args:
            proposal_type: One of the known proposal types.
            proposal_content: Content string (TTS text, gesture name, nav label).
            source: Originating module ('llm', 'speech_intent', 'operator', etc.).
            urgency: 0.0–1.0 urgency value from the proposal.
            raw_llm_command: Original LLM text if source is 'llm'.

        Returns:
            An :class:`EvaluationResult`.
        """
        # ── 1. Emergency / high safety level ────────────────────────────────
        if self._safety_level >= _LEVEL_FAULT:
            if proposal_type not in ("alert_operator", "speak"):
                return EvaluationResult(
                    decision="rejected",
                    approved_action="",
                    approved_content="",
                    confidence=1.0,
                    safety_approved=False,
                    operator_alerted=False,
                    rejection_reason=(
                        f"Safety level {self._safety_level}: only 'speak' and "
                        "'alert_operator' proposals allowed."
                    ),
                )

        if self._safety_level >= _LEVEL_DANGER:
            if proposal_type in ("navigate", "approach"):
                return EvaluationResult(
                    decision="rejected",
                    approved_action="",
                    approved_content="",
                    confidence=1.0,
                    safety_approved=False,
                    operator_alerted=False,
                    rejection_reason=(
                        f"Safety level {self._safety_level}: "
                        "navigation/approach not allowed."
                    ),
                )

        # ── 2. LLM source — additional risk check ───────────────────────────
        if source == "llm" and raw_llm_command:
            risk = self._clf.classify(raw_llm_command, source="llm")
            if not risk.is_safe:
                return EvaluationResult(
                    decision="rejected",
                    approved_action="alert_operator",
                    approved_content="LLM produced a forbidden command",
                    confidence=1.0,
                    safety_approved=False,
                    operator_alerted=True,
                    rejection_reason=f"Critical LLM risk: {'; '.join(risk.reasons[:2])}",
                )
            if risk.risk_level == "high" and proposal_type in ("navigate", "approach"):
                return EvaluationResult(
                    decision="escalated",
                    approved_action="ask_clarification",
                    approved_content="",
                    confidence=0.5,
                    safety_approved=False,
                    operator_alerted=True,
                    rejection_reason="High-risk LLM navigation command requires operator.",
                )

        # ── 3. Rate limiting ─────────────────────────────────────────────────
        rate_limit = _RATE_LIMITS.get(proposal_type, 0.0)
        now = time.monotonic()
        last = self._last_dispatch.get(proposal_type, 0.0)
        if rate_limit > 0 and (now - last) < rate_limit and urgency < MAX_URGENCY_FOR_DEFERRAL:
            return EvaluationResult(
                decision="deferred",
                approved_action=proposal_type,
                approved_content=proposal_content,
                confidence=0.8,
                safety_approved=True,
                operator_alerted=False,
                rejection_reason=(
                    f"Rate limit: {proposal_type} last dispatched "
                    f"{now - last:.1f}s ago (min {rate_limit}s)."
                ),
            )

        # ── 4. Content sanitisation ──────────────────────────────────────────
        modified = False
        note = ""
        content = proposal_content

        if proposal_type == "speak" and len(content) > MAX_TTS_CHARS:
            content = content[:MAX_TTS_CHARS] + "…"
            modified = True
            note = f"TTS text truncated to {MAX_TTS_CHARS} characters."

        # ── 5. Child-safe mode content filter ───────────────────────────────
        if self._mode == "child_safe":
            # Remove any potentially scary phrases
            for phrase in ("danger", "emergency", "alert", "warning"):
                if phrase in content.lower():
                    content = content.replace(phrase, "").strip()
                    modified = True
                    note += f" Phrase '{phrase}' removed for child-safe mode."

        # ── 6. Approve ───────────────────────────────────────────────────────
        self._last_dispatch[proposal_type] = now
        decision = "modified" if modified else "approved"

        return EvaluationResult(
            decision=decision,
            approved_action=proposal_type,
            approved_content=content,
            confidence=0.9 if not modified else 0.75,
            safety_approved=True,
            operator_alerted=False,
            modification_note=note,
        )
