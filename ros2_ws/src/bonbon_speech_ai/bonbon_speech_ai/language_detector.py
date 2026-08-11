"""language_detector — lightweight EN/HI/TE detection by Unicode script,
used when the ASR engine itself doesn't report a language (or reports
"auto"). Real, deterministic technique (no ML model, no network call) --
Devanagari codepoints (U+0900-U+097F) mean Hindi, Telugu codepoints
(U+0C00-U+0C7F) mean Telugu, otherwise Latin-script text is treated as
English. Code-mixed input (rule: "code-mixed speech handling") is
resolved by majority script, with the mixed flag preserved so downstream
normalization/entity-correction can apply per-token rules rather than
assuming a single language.
"""

from __future__ import annotations

from dataclasses import dataclass

_DEVANAGARI_RANGE = (0x0900, 0x097F)
_TELUGU_RANGE = (0x0C00, 0x0C7F)


@dataclass
class LanguageDetectionResult:
    language_code: str  # "en" | "hi" | "te"
    is_code_mixed: bool
    script_counts: dict[str, int]


def _script_of(ch: str) -> str | None:
    code = ord(ch)
    if _DEVANAGARI_RANGE[0] <= code <= _DEVANAGARI_RANGE[1]:
        return "hi"
    if _TELUGU_RANGE[0] <= code <= _TELUGU_RANGE[1]:
        return "te"
    if ch.isalpha():
        return "en"
    return None


def detect(text: str, asr_reported_language: str | None = None) -> LanguageDetectionResult:
    if asr_reported_language and asr_reported_language not in ("auto", "unknown", ""):
        return LanguageDetectionResult(asr_reported_language, False, {})

    counts = {"en": 0, "hi": 0, "te": 0}
    for ch in text:
        script = _script_of(ch)
        if script:
            counts[script] += 1

    total = sum(counts.values())
    if total == 0:
        return LanguageDetectionResult("en", False, counts)

    dominant = max(counts, key=lambda k: counts[k])
    non_dominant_present = sum(1 for k, v in counts.items() if k != dominant and v > 0)
    is_mixed = non_dominant_present > 0 and counts[dominant] / total < 0.9

    return LanguageDetectionResult(dominant, is_mixed, counts)
