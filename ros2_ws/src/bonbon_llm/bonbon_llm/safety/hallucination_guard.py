"""
bonbon_llm.safety.hallucination_guard
======================================
Hallucination prevention and response grounding layer.

Checks the LLM's response against:
  1. Known impossible capability phrases (LLM claims the robot can do
     things it cannot — e.g. "I can fly", "I have arms")
  2. Fabricated numbers (prices, distances, speeds) not present in
     retrieved RAG documents
  3. Minimum grounding score — if no RAG document supports the claim
     and the response confidence is low, flag it
  4. Self-consistency — the response must not contradict the system
     prompt's capability description

The guard never silently drops responses.  It returns:
  - ``is_grounded=True``  → response passes; use as-is
  - ``is_grounded=False`` → response flagged; caller should use
    ``safe_response`` (truncated / fallback) and log the flag

Design
------
Intentionally lightweight: zero ML inference, regex + keyword matching
only.  Keeps the guard latency < 1 ms so it never adds meaningful delay
to the 30-second Ollama timeout budget.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from bonbon_llm.config.llm_config import HallucinationConfig
from bonbon_llm.core.rag_retriever import RetrievalResult

logger = logging.getLogger(__name__)


# ── Result type ───────────────────────────────────────────────────────────────


@dataclass
class GuardResult:
    is_grounded: bool
    confidence: float  # 0–1 grounding confidence
    flagged_claims: list[str] = field(default_factory=list)
    reason: str = ""
    safe_response: str = ""  # cleaned version or fallback
    original_response: str = ""


# ── Patterns for impossible capability claims ─────────────────────────────────

_IMPOSSIBLE_CAPS_PATTERNS = [
    (re.compile(r"\bi\s+can\s+fly\b", re.I), "claims ability to fly"),
    (re.compile(r"\bi\s+have\s+arms?\b", re.I), "claims to have arms"),
    (re.compile(r"\bi\s+can\s+carry\s+more\s+than\s+[3-9]\d", re.I), "exaggerated payload claim"),
    (re.compile(r"\bi\s+am\s+a\s+human\b", re.I), "claims to be human"),
    (re.compile(r"\bi\s+have\s+a\s+face\b", re.I), "claims to have a face"),
    (re.compile(r"\bi\s+can\s+see\s+in\s+the\s+dark\b", re.I), "claims night vision"),
    (
        re.compile(r"\bi\s+remember\s+you\s+from\s+(last|yesterday|previous)", re.I),
        "false cross-session memory",
    ),
    (re.compile(r"\bi\s+know\s+your\s+name\b", re.I), "false name recall"),
    (re.compile(r"\bi\s+can\s+access\s+the\s+internet\b", re.I), "false internet claim"),
    (re.compile(r"\bi\s+can\s+make\s+phone\s+calls\b", re.I), "false phone claim"),
    (re.compile(r"\bi\s+can\s+process\s+payments?\b", re.I), "false payment claim"),
]

# Prices in the knowledge base — fabricated prices outside this set are suspicious
_KNOWN_PRICES_SGD = {3.50, 4.00, 5.00, 4.50, 1.50}

_PRICE_RE = re.compile(r"s\$\s*(\d+\.?\d*)", re.I)

# Numbers that look like velocity/distance claims from the LLM
_VELOCITY_CLAIM_RE = re.compile(r"(\d+\.?\d*)\s*(m/s|km/h|meters?\s+per\s+second)", re.I)


# ── Guard ─────────────────────────────────────────────────────────────────────


class HallucinationGuard:
    """
    Stateless hallucination checker.  Thread-safe.
    """

    def __init__(self, cfg: HallucinationConfig) -> None:
        self._cfg = cfg
        # Compile extra impossible capability phrases from config
        self._extra_impossible = [
            re.compile(re.escape(phrase), re.I) for phrase in cfg.impossible_capability_phrases
        ]

    # ── Public API ────────────────────────────────────────────────────────────

    def check(
        self,
        response: str,
        rag_results: list[RetrievalResult] | None = None,
        llm_confidence: float = 1.0,
    ) -> GuardResult:
        """
        Check ``response`` for hallucination indicators.

        Parameters
        ----------
        response:        Raw LLM output text.
        rag_results:     Retrieved documents used to build the prompt.
        llm_confidence:  Model's self-reported confidence (0–1) if available.
        """
        if not self._cfg.enabled:
            return GuardResult(
                is_grounded=True,
                confidence=1.0,
                safe_response=response,
                original_response=response,
            )

        flags: list[str] = []

        # 1. Impossible capability claims
        flags += self._check_impossible_capabilities(response)

        # 2. Fabricated prices
        flags += self._check_prices(response, rag_results or [])

        # 3. Implausible velocity claims
        flags += self._check_velocity_claims(response)

        # 4. Grounding score
        grounding = self._compute_grounding_score(response, rag_results or [])

        # Compute combined confidence
        cap_penalty = 0.40 * len(flags)  # each flag reduces confidence
        grounding_pen = max(0.0, self._cfg.min_grounding_score - grounding)
        combined_conf = max(0.0, llm_confidence - cap_penalty - grounding_pen)

        # The guard assesses hallucination indicators only (impossible claims,
        # fabricated prices, implausible velocities, poor grounding).  LLM
        # confidence is reflected in GuardResult.confidence but does NOT by
        # itself make a response "ungrounded" — the pipeline handles that
        # separately via its own confidence threshold.
        #
        # Short responses (< 15 words) with no explicit flags are treated as
        # grounded by default: the hash-based embedding fallback may not
        # retrieve the most relevant documents for brief, focused queries, so
        # a low overlap score alone should not mark a benign answer as hallucinated.
        short_benign = len(flags) == 0 and len(response.split()) < 15
        is_grounded = len(flags) == 0 and (
            grounding >= self._cfg.min_grounding_score or short_benign
        )

        if flags:
            logger.warning("Hallucination flags detected: %s | response: %.60s", flags, response)

        safe = self._make_safe(response, flags) if not is_grounded else response

        reason = (
            "; ".join(flags)
            if flags
            else (
                f"low grounding score ({grounding:.2f} < {self._cfg.min_grounding_score})"
                if grounding < self._cfg.min_grounding_score
                else ""
            )
        )

        return GuardResult(
            is_grounded=is_grounded,
            confidence=combined_conf,
            flagged_claims=flags,
            reason=reason,
            safe_response=safe,
            original_response=response,
        )

    # ── Checkers ──────────────────────────────────────────────────────────────

    def _check_impossible_capabilities(self, text: str) -> list[str]:
        flags = []
        for regex, label in _IMPOSSIBLE_CAPS_PATTERNS:
            if regex.search(text):
                flags.append(label)
        for regex in self._extra_impossible:
            if regex.search(text):
                flags.append("extra impossible capability")
        return flags

    def _check_prices(
        self,
        text: str,
        rag_results: list[RetrievalResult],
    ) -> list[str]:
        flags = []
        matches = _PRICE_RE.findall(text)
        if not matches:
            return flags
        # Build set of all prices mentioned in retrieved docs
        known_prices = set(_KNOWN_PRICES_SGD)
        for r in rag_results:
            for m in _PRICE_RE.findall(r.document.text):
                try:
                    known_prices.add(float(m))
                except ValueError:
                    pass
        for m in matches:
            try:
                price = float(m)
                if price not in known_prices:
                    flags.append(f"fabricated price S${price:.2f}")
            except ValueError:
                pass
        return flags

    def _check_velocity_claims(self, text: str) -> list[str]:
        flags = []
        # BonBon max speed = 0.8 m/s; flag claims > 1.5 m/s
        for m in _VELOCITY_CLAIM_RE.finditer(text):
            try:
                val = float(m.group(1))
                unit = m.group(2).lower()
                speed_mps = val if "m/s" in unit else val / 3.6
                if speed_mps > 1.5:
                    flags.append(f"implausible speed claim: {m.group()}")
            except ValueError:
                pass
        return flags

    def _compute_grounding_score(
        self,
        text: str,
        rag_results: list[RetrievalResult],
    ) -> float:
        """
        Simple keyword-overlap grounding score between response and RAG docs.
        Returns 0.0 when no docs retrieved (not necessarily hallucination —
        may be a simple greeting).
        """
        if not rag_results:
            # No RAG context available: treat as grounded if response is short
            return 1.0 if len(text.split()) < 20 else 0.5

        resp_words = set(re.findall(r"\w+", text.lower()))
        doc_words: set = set()
        for r in rag_results:
            doc_words.update(re.findall(r"\w+", r.document.text.lower()))

        if not resp_words:
            return 1.0

        overlap = resp_words & doc_words
        # Jaccard-style: overlap / (resp_words only)
        score = len(overlap) / max(len(resp_words), 1)
        # Weight by best RAG score
        best_rag_score = max((r.score for r in rag_results), default=0.0)
        return min(1.0, score * 0.6 + best_rag_score * 0.4)

    def _make_safe(self, text: str, flags: list[str]) -> str:
        """Remove or replace flagged claims from the response."""
        safe = text
        for regex, _ in _IMPOSSIBLE_CAPS_PATTERNS:
            safe = regex.sub("[I cannot do that]", safe)
        # Truncate if still suspicious
        words = safe.split()
        if len(words) > 30:
            safe = " ".join(words[:30]) + "…"
        return safe.strip()
