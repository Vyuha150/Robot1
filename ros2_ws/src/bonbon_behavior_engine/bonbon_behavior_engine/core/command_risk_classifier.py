"""CommandRiskClassifier — pattern-based risk classification for incoming commands.

This module is intentionally **LLM-free**.  Safety classification must be
deterministic and fast; relying on another LLM call to assess an LLM-generated
command would create an unsafe feedback loop.

Risk levels
-----------
none     — administrative/query (e.g. "what time is it?")
low      — social / expressive (e.g. "wave goodbye", "say hello")
medium   — navigational with human oversight (e.g. "go to the lobby")
high     — actuation with contact risk (e.g. "extend arm toward person")
critical — directly dangerous or forbidden (e.g. "publish to cmd_vel", "stop")

Critical patterns are hard-coded and cannot be overridden at runtime.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import List, Tuple

_logger = logging.getLogger(__name__)

# ── Risk pattern tables ─────────────────────────────────────────────────────

# Patterns that are ALWAYS critical — no override allowed.
_CRITICAL_PATTERNS: List[re.Pattern] = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"\bcmd_vel\b",
        r"\bservo\s*(command|angle|position)\b",
        r"\bjoint\s*(state|command)\b",
        r"\bpublish\s+to\b",
        r"\b(emergency\s+)?stop\s+(robot|movement|all)\b",
        r"\breset\s+(safety|supervisor)\b",
        r"\boverride\s+(safety|gate|supervisor)\b",
        r"\bignore\s+(safety|obstacle|person)\b",
        r"\bdeactivate\s+(safety|node)\b",
        r"\bkill\s+(node|process|robot)\b",
        r"\bhardware\s+reset\b",
        r"\braw\s+servo\b",
        r"\bdirect\s+(motor|servo|actuator)\b",
    ]
]

_HIGH_PATTERNS: List[re.Pattern] = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"\b(extend|raise|lower)\s+(arm|hand|limb)\b",
        r"\btouch\b",
        r"\bgrab\s+(the\s+)?\w+\b",
        r"\bpick\s+up\b",
        r"\bphysical\s+contact\b",
        r"\bforce\s+sensor\b",
        r"\bapply\s+(force|pressure)\b",
    ]
]

_MEDIUM_PATTERNS: List[re.Pattern] = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"\b(go|move|navigate|drive|travel)\s+(to|toward|into)\b",
        r"\bapproach\s+(the\s+)?\w+\b",
        r"\bfollow\b",
        r"\breturn\s+to\s+(base|home|dock)\b",
        r"\bdock(ing)?\b",
        r"\bdeliver\b",
        r"\bcarry\b",
    ]
]

_LOW_PATTERNS: List[re.Pattern] = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"\b(wave|nod|bow|gesture|point)\b",
        r"\b(say|speak|announce|greet|tell)\b",
        r"\b(play|sing)\b",
        r"\bdisplay\b",
        r"\bsmile\b",
        r"\bshow\b",
    ]
]


@dataclass
class RiskAssessment:
    """Result of a risk classification pass."""

    risk_level: str
    """One of: 'none', 'low', 'medium', 'high', 'critical'."""

    reasons: List[str] = field(default_factory=list)
    """Human-readable explanations for the assigned risk level."""

    matched_patterns: List[str] = field(default_factory=list)
    """Regex pattern strings that triggered the classification."""

    recommended_action: str = "approve"
    """One of: 'approve', 'reject', 'modify', 'escalate'."""

    is_safe: bool = True
    """Convenience: False when risk_level is 'critical'."""


_LEVEL_ORDER = {"none": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
_RECOMMENDED_ACTION = {
    "none":     "approve",
    "low":      "approve",
    "medium":   "approve",
    "high":     "escalate",
    "critical": "reject",
}


class CommandRiskClassifier:
    """Classify a natural-language command into a safety risk tier.

    Pattern-matching only — no external calls, no ML inference.
    Classification is O(n_patterns) and sub-millisecond.

    Usage::

        clf = CommandRiskClassifier()
        assessment = clf.classify("Go to the lobby and greet the visitor")
        # assessment.risk_level → 'medium'
    """

    def classify(self, command_text: str, source: str = "unknown") -> RiskAssessment:
        """Classify *command_text* into a risk level.

        Args:
            command_text: Raw command string to classify.
            source: Originating module ('llm', 'operator', 'speech', 'gesture').

        Returns:
            A :class:`RiskAssessment` with risk level and recommended action.
        """
        if not command_text or not command_text.strip():
            return RiskAssessment(
                risk_level="none",
                reasons=["Empty command."],
                recommended_action="approve",
                is_safe=True,
            )

        level = "none"
        reasons: List[str] = []
        matched: List[str] = []

        def _check(patterns: List[re.Pattern], risk: str) -> None:
            nonlocal level
            for pat in patterns:
                m = pat.search(command_text)
                if m:
                    matched.append(pat.pattern)
                    reasons.append(f"Pattern '{pat.pattern}' matched: '{m.group()}'")
                    if _LEVEL_ORDER[risk] > _LEVEL_ORDER[level]:
                        level = risk

        _check(_CRITICAL_PATTERNS, "critical")
        _check(_HIGH_PATTERNS,     "high")
        _check(_MEDIUM_PATTERNS,   "medium")
        _check(_LOW_PATTERNS,      "low")

        # LLM-sourced commands always start at 'low' minimum risk
        if source == "llm" and _LEVEL_ORDER[level] < _LEVEL_ORDER["low"]:
            level = "low"
            reasons.append("LLM-sourced command: minimum risk level is 'low'.")

        is_safe = level != "critical"
        rec = _RECOMMENDED_ACTION.get(level, "escalate")

        if not is_safe:
            _logger.warning(
                "CRITICAL risk in command from '%s': %s", source, command_text[:80]
            )

        _logger.debug(
            "Risk classification: level=%s source=%s text='%s…'",
            level, source, command_text[:60],
        )

        return RiskAssessment(
            risk_level=level,
            reasons=reasons,
            matched_patterns=matched,
            recommended_action=rec,
            is_safe=is_safe,
        )
