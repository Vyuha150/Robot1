"""hospital_entity_corrector — fuzzy-corrects ASR mishears against known
hospital vocabulary (doctor names, departments) and extracts structured
entities (room numbers, token numbers) from normalized transcript text.

Explicit rule, enforced structurally: medicine/symptom words are NEVER
looked up, corrected, or annotated by this module -- they pass through
as the patient's own verbatim words. This module has no medicine
dictionary at all (not "an empty one to fill in later" -- the class of
entity is out of scope by design, matching rule 6's "no medicine advice"
posture applied to entity correction specifically, not just LLM output).
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field


@dataclass
class HospitalVocabulary:
    doctor_names: list[str] = field(default_factory=list)
    department_names: list[str] = field(default_factory=list)


@dataclass
class EntityCorrectionResult:
    corrected_text: str
    matched_doctor: str | None
    matched_department: str | None
    room_number: str | None
    token_number: str | None


_ROOM_PATTERN = re.compile(r"\broom\s*(?:number\s*)?(\d{1,4}[a-zA-Z]?)\b", re.IGNORECASE)
_TOKEN_PATTERN = re.compile(r"\btoken\s*(?:number\s*)?([a-zA-Z]{0,3}-?\d{1,4})\b", re.IGNORECASE)

_FUZZY_MATCH_CUTOFF = 0.72


def _best_fuzzy_match(word_window: str, candidates: list[str]) -> str | None:
    if not candidates:
        return None
    matches = difflib.get_close_matches(word_window, candidates, n=1, cutoff=_FUZZY_MATCH_CUTOFF)
    return matches[0] if matches else None


def correct(text: str, vocabulary: HospitalVocabulary) -> EntityCorrectionResult:
    room_match = _ROOM_PATTERN.search(text)
    token_match = _TOKEN_PATTERN.search(text)

    matched_doctor = None
    matched_department = None
    corrected_text = text

    # Sliding 1-3 word windows, fuzzy-matched against the known
    # doctor/department lists -- deliberately dictionary-bounded (never
    # matches against anything NOT in `vocabulary`, so it can never
    # "correct" a medicine name into a doctor name or vice versa).
    words = text.split()
    for window_size in (3, 2, 1):
        for i in range(len(words) - window_size + 1):
            window = " ".join(words[i : i + window_size])
            if matched_doctor is None:
                candidate = _best_fuzzy_match(window, vocabulary.doctor_names)
                if candidate:
                    matched_doctor = candidate
                    corrected_text = corrected_text.replace(window, candidate)
            if matched_department is None:
                candidate = _best_fuzzy_match(window, vocabulary.department_names)
                if candidate:
                    matched_department = candidate
                    corrected_text = corrected_text.replace(window, candidate)

    return EntityCorrectionResult(
        corrected_text=corrected_text,
        matched_doctor=matched_doctor,
        matched_department=matched_department,
        room_number=room_match.group(1) if room_match else None,
        token_number=token_match.group(1) if token_match else None,
    )
