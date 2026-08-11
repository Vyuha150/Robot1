"""transcript_normalizer — cleans a raw ASR transcript before it reaches
the intent detector / RAG-LLM gateway: collapses whitespace, strips ASR
filler-artifact tokens, normalizes digit sequences (so "double oh seven"
-> "007"-style room/token numbers can be matched by
hospital_entity_corrector downstream), and applies per-language
punctuation conventions. Pure string transformation, no ML model.
"""

from __future__ import annotations

import re

_FILLER_TOKENS = {"en": {"um", "uh", "erm"}, "hi": {"matlab", "haan"}, "te": {"ante", "kada"}}

_WORD_DIGITS = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
}


def normalize(text: str, language_code: str = "en") -> str:
    if not text:
        return ""

    collapsed = re.sub(r"\s+", " ", text.strip())

    fillers = _FILLER_TOKENS.get(language_code, set())
    tokens = [t for t in collapsed.split(" ") if t.lower().strip(".,!?") not in fillers]

    if language_code == "en":
        tokens = [_WORD_DIGITS.get(t.lower().strip(".,!?"), t) for t in tokens]

    normalized = " ".join(tokens)
    normalized = re.sub(r"\s+([.,!?])", r"\1", normalized)
    return normalized.strip()


def collapse_spoken_number(tokens: list[str]) -> str | None:
    """Turns a run of spoken digit-words ("three", "seven") into a
    contiguous number string ("37") -- used for room/token number
    entities where ASR often emits digits as separate words. Returns
    None if the token run contains no recognizable digit words."""
    digits = [_WORD_DIGITS[t.lower()] for t in tokens if t.lower() in _WORD_DIGITS]
    if not digits:
        return None
    return "".join(digits)
