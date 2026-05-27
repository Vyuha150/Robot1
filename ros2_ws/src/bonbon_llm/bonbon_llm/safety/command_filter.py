"""
bonbon_llm.safety.command_filter
=================================
Safety-filtered command interpretation layer.

Every piece of text or command dict that the LLM produces passes through
this filter before anything is dispatched.

Three tiers
-----------
BLOCKED  — hard deny; the command can NEVER be executed regardless of
           safety state.  Logged as a safety incident.
RISKY    — permitted only when SafetyState allows it; requires
           authorization before dispatch.
SAFE     — may be dispatched immediately.

The filter is intentionally conservative: when in doubt it escalates
to RISKY rather than BLOCKED so legitimate commands aren't silently
dropped, while still requiring human-visible authorization.

No LLM-generated text ever reaches actuators or the nav stack directly.
All SAFE/RISKY commands are dispatched as BehaviorRecommendation messages
which are then validated by the Safety Supervisor and Behavior Engine.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import StrEnum

from bonbon_llm.config.llm_config import SafetyFilterConfig

logger = logging.getLogger(__name__)


# ── Filter result ─────────────────────────────────────────────────────────────


class FilterStatus(StrEnum):
    SAFE = "SAFE"
    RISKY = "RISKY"
    BLOCKED = "BLOCKED"


@dataclass
class FilterResult:
    status: FilterStatus
    reason: str
    sanitized_text: str  # text with blocked patterns removed/replaced
    matched_pattern: str | None = None
    original_text: str = ""


# ── Hard-blocked patterns (regex) ────────────────────────────────────────────
#
# These represent direct hardware control attempts that must NEVER reach
# the actuation layer from LLM output.  The list is deliberately broad.

_HARD_BLOCKED_PATTERNS: list[tuple[str, str]] = [
    # ROS2 velocity / Twist
    (r"\bcmd_vel\b", "direct velocity command"),
    (r"\bTwist\b", "Twist message reference"),
    (r"\bpublish.*veloc", "velocity publish call"),
    (r"\blinear\.x\b", "Twist linear.x field"),
    (r"\bangular\.z\b", "Twist angular.z field"),
    # Navigation stack
    (r"\bNavigateToPose\b", "direct NavigateToPose action"),
    (r"\bnavigate_to_pose\b", "navigate_to_pose action reference"),
    (r"\bnav2\b", "direct nav2 reference"),
    (r"\bnav\s+stack\b", "nav stack reference"),
    (r"\bmove_base\b", "move_base direct call"),
    (r"\bset_goal\b", "direct goal setter"),
    (r"\bsend_goal\b", "direct action goal"),
    # Hardware / GPIO
    (r"\bGPIO\b", "GPIO direct access"),
    (r"\bPWM\b", "PWM direct control"),
    (r"\bservo.*angle\b", "direct servo angle set"),
    (r"\bdirect.*motor\b", "direct motor control"),
    (r"\bmotor\s+speed\b", "motor speed control"),
    (r"\bdirect\w*\s+actuat", "direct actuator control"),
    (r"\bi2c\b", "I2C bus access"),
    (r"\bserial.*write\b", "serial port write"),
    # Code execution
    (r"\bos\.system\s*\(", "os.system call"),
    (r"\bsubprocess\b", "subprocess invocation"),
    (r"\beval\s*\(", "eval() call"),
    (r"\bexec\s*\(", "exec() call"),
    (r"\b__import__\b", "dynamic import"),
    # Safety system bypass
    (r"\bdisable.*safety\b", "safety disable attempt"),
    (r"\boverride.*safety\b", "safety override attempt"),
    (r"\bbypass.*safety\b", "safety bypass attempt"),
    (r"\bdisable.*watchdog\b", "watchdog disable attempt"),
    (r"\bestop.*off\b", "e-stop disable attempt"),
]

# Compiled once at module load
_COMPILED_BLOCKED = [
    (re.compile(pattern, re.IGNORECASE), reason) for pattern, reason in _HARD_BLOCKED_PATTERNS
]


# ── Speech output filters ─────────────────────────────────────────────────────
#
# Words that should not appear in robot speech (to avoid alarming customers
# or usurping the safety announcement system).

_SPEECH_FORBIDDEN_RE = re.compile(
    r"\b(emergency|malfunction|critical\s+failure|system\s+error|hardware\s+fault"
    r"|fire|evacuation|call\s+911|call\s+999|call\s+995)\b",
    re.IGNORECASE,
)


# ── Intent class risk map ─────────────────────────────────────────────────────

_RISKY_INTENT_CLASSES = frozenset(
    {
        "navigate_to",
        "navigate_to_goal",
        "approach_person",
        "serve_item",
    }
)

_SAFE_INTENT_CLASSES = frozenset(
    {
        "greeting",
        "ask_question",
        "confirm",
        "deny",
        "cancel",
        "silence",
        "unknown",
        "speak_response",
        "speak_greeting",
        "speak_clarification",
        "speak_information",
        "wait_for_input",
        "idle",
    }
)


# ── Filter ────────────────────────────────────────────────────────────────────


class SafetyCommandFilter:
    """
    Stateless filter — no internal state, thread-safe by design.

    Usage
    -----
        filt = SafetyCommandFilter(cfg.safety_filter)
        result = filt.filter_text("navigate to table 3")
        if result.status == FilterStatus.BLOCKED:
            ...
    """

    def __init__(self, cfg: SafetyFilterConfig) -> None:
        self._cfg = cfg
        # Compile any extra blocked patterns from config
        self._extra_blocked = [re.compile(p, re.IGNORECASE) for p in cfg.blocked_patterns]

    # ── Public API ────────────────────────────────────────────────────────────

    def filter_text(self, text: str) -> FilterResult:
        """
        Scan arbitrary text for blocked / risky patterns.

        Used to pre-screen the LLM's raw output before any dispatch.
        """
        # 1. Hard block check
        blocked, pattern, reason = self._check_blocked(text)
        if blocked:
            sanitized = self._redact_blocked(text)
            logger.warning("BLOCKED LLM output [pattern=%r]: %.80s", pattern, text)
            return FilterResult(
                status=FilterStatus.BLOCKED,
                reason=f"Blocked pattern: {reason}",
                sanitized_text=sanitized,
                matched_pattern=pattern,
                original_text=text,
            )

        # 2. Speech safety word check
        m = _SPEECH_FORBIDDEN_RE.search(text)
        if m:
            sanitized = _SPEECH_FORBIDDEN_RE.sub("[omitted]", text)
            logger.warning("BLOCKED speech word [%r]: %.80s", m.group(), text)
            return FilterResult(
                status=FilterStatus.BLOCKED,
                reason=f"Forbidden speech word: {m.group()!r}",
                sanitized_text=sanitized,
                matched_pattern=m.group(),
                original_text=text,
            )

        return FilterResult(
            status=FilterStatus.SAFE,
            reason="No blocked patterns found",
            sanitized_text=text,
            original_text=text,
        )

    def filter_behavior(
        self,
        behavior_class: str,
        confidence: float,
    ) -> FilterResult:
        """
        Classify a proposed behavior_class as SAFE / RISKY / BLOCKED.
        BLOCKED if behavior directly maps to hardware commands.
        RISKY if it requires Safety Supervisor approval.
        """
        bc = behavior_class.lower()

        # Anything that smells like direct hardware control
        if any(kw in bc for kw in ("cmd_vel", "twist", "gpio", "servo", "motor", "nav2")):
            return FilterResult(
                status=FilterStatus.BLOCKED,
                reason="Direct hardware control in behavior_class",
                sanitized_text="idle",
                original_text=behavior_class,
            )

        if bc in _RISKY_INTENT_CLASSES:
            if confidence < self._cfg.min_risky_confidence:
                return FilterResult(
                    status=FilterStatus.RISKY,
                    reason=f"Low confidence ({confidence:.2f}) for risky behavior",
                    sanitized_text=behavior_class,
                    original_text=behavior_class,
                )
            return FilterResult(
                status=FilterStatus.RISKY,
                reason="Requires Safety Supervisor authorization",
                sanitized_text=behavior_class,
                original_text=behavior_class,
            )

        return FilterResult(
            status=FilterStatus.SAFE,
            reason="Behavior class is safe to dispatch",
            sanitized_text=behavior_class,
            original_text=behavior_class,
        )

    def is_safe_speech(self, text: str) -> bool:
        """Quick check: True if text is safe to pass to TTS."""
        result = self.filter_text(text)
        return result.status == FilterStatus.SAFE

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _check_blocked(self, text: str) -> tuple[bool, str | None, str]:
        for regex, reason in _COMPILED_BLOCKED:
            m = regex.search(text)
            if m:
                return True, m.group(), reason
        for regex in self._extra_blocked:
            m = regex.search(text)
            if m:
                return True, m.group(), "extra blocked pattern"
        return False, None, ""

    def _redact_blocked(self, text: str) -> str:
        result = text
        for regex, _ in _COMPILED_BLOCKED:
            result = regex.sub("[REDACTED]", result)
        return result
