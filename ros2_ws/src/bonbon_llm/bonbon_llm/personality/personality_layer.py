"""
bonbon_llm.personality.personality_layer
=========================================
Robot personality and response style layer.

Applied as the final transformation step after safety filtering and
hallucination checking, before TTS dispatch.

Responsibilities
----------------
* Enforce response length limits (important for TTS — too long = bad UX)
* Prepend natural affirmation when appropriate
* Mirror the user's language (basic EN/ZH/etc detection)
* Strip markdown formatting that TTS would read aloud literally
* Ensure the robot always introduces itself by its configured name
* Format currency, numbers and units for spoken output
"""
from __future__ import annotations

import random
import re
from typing import Optional

from bonbon_llm.config.llm_config import PersonalityConfig


# ── Markdown cleanup ──────────────────────────────────────────────────────────

_MD_STRIP_RE = re.compile(
    r"(\*{1,2}|_{1,2}|`{1,3}|#{1,6}\s*|>\s*|\[.*?\]\(.*?\)|\!\[.*?\]\(.*?\))",
    re.S,
)
_BULLET_RE = re.compile(r"^\s*[-*•]\s+", re.M)
_NUMBERED_RE = re.compile(r"^\s*\d+\.\s+", re.M)

# ── Language detection (minimal, no deps) ────────────────────────────────────

_ZH_RE = re.compile(r"[一-鿿]")
_MALAY_KEYWORDS = re.compile(r"\b(nak|tolong|terima kasih|boleh|saya)\b", re.I)


def _detect_language(text: str) -> str:
    if _ZH_RE.search(text):
        return "zh"
    if _MALAY_KEYWORDS.search(text):
        return "ms"
    return "en"


# ── Personality layer ─────────────────────────────────────────────────────────

class PersonalityLayer:
    """
    Applies the BonBon personality style to a raw LLM response.
    Stateless — thread-safe.
    """

    def __init__(self, cfg: PersonalityConfig) -> None:
        self._cfg  = cfg
        self._rng  = random.Random()   # not seeded — non-deterministic affirmations

    def apply(
        self,
        raw_response: str,
        user_text:    Optional[str] = None,
        use_affirmation: bool = False,
    ) -> str:
        """
        Transform ``raw_response`` according to the personality configuration.

        Parameters
        ----------
        raw_response:    LLM output after safety/hallucination filtering.
        user_text:       Original user utterance (for language mirroring).
        use_affirmation: If True, prepend a random affirmation phrase.
        """
        text = raw_response.strip()

        # 1. Strip markdown / formatting artefacts
        text = self._strip_markdown(text)

        # 2. Enforce word limit
        text = self._enforce_length(text)

        # 3. Prepend affirmation (randomly, not for every response)
        if use_affirmation and self._cfg.affirmations:
            affirmation = self._rng.choice(self._cfg.affirmations)
            text = f"{affirmation} {text}"

        # 4. Language adaptation (replace self-references with correct name)
        text = self._apply_name(text)

        # 5. Format for TTS (expand abbreviations, currency symbols)
        text = self._tts_format(text)

        return text.strip()

    def format_for_tts(self, text: str) -> str:
        """Standalone TTS formatter (used by fallback templates too)."""
        return self._tts_format(self._strip_markdown(text)).strip()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _strip_markdown(self, text: str) -> str:
        text = _MD_STRIP_RE.sub("", text)
        text = _BULLET_RE.sub("", text)
        text = _NUMBERED_RE.sub("", text)
        return re.sub(r"\n{2,}", " ", text).strip()

    def _enforce_length(self, text: str) -> str:
        words = text.split()
        if len(words) <= self._cfg.max_response_words:
            return text
        truncated = " ".join(words[: self._cfg.max_response_words])
        # Try to end at a sentence boundary
        for end in (".", "!", "?"):
            idx = truncated.rfind(end)
            if idx > len(truncated) // 2:
                return truncated[: idx + 1]
        return truncated + "."

    def _apply_name(self, text: str) -> str:
        # Replace generic "the robot" self-references with the configured name
        text = re.sub(r"\bthe robot\b", self._cfg.name, text, flags=re.I)
        return text

    def _tts_format(self, text: str) -> str:
        # Expand S$ to Singapore dollars
        text = re.sub(r"S\$\s*(\d)", r"S$\1", text)       # normalise spacing
        text = re.sub(r"S\$(\d+\.?\d*)", r"\1 Singapore dollars", text)
        # Expand common abbreviations
        text = re.sub(r"\bm/s\b", "metres per second", text, flags=re.I)
        text = re.sub(r"\bkg\b",  "kilograms",         text, flags=re.I)
        text = re.sub(r"\bcm\b",  "centimetres",       text, flags=re.I)
        return text
