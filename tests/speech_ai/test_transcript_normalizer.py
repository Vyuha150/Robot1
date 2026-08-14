"""Tests for bonbon_speech_ai.transcript_normalizer -- filler stripping,
digit-word conversion, and the code-mixed-input per-token-rules fix.

A real bug this round caught: `normalize()` only applied English
digit-word conversion when `language_code == "en"` exactly, so a
Hindi-dominant code-mixed utterance like "mera room number seven hai"
never got "seven" -> "7" converted, which silently broke
hospital_entity_corrector's `_ROOM_PATTERN` (`\\d{1,4}` required) --
the room number was dropped with no error. Fixed by threading
`is_code_mixed` through from `language_detector.detect()`.
"""

from __future__ import annotations

import unittest


class TestNormalizeSingleLanguage(unittest.TestCase):
    def setUp(self):
        from bonbon_speech_ai.transcript_normalizer import normalize

        self.normalize = normalize

    def test_empty_text_returns_empty(self):
        self.assertEqual(self.normalize(""), "")

    def test_collapses_whitespace(self):
        self.assertEqual(self.normalize("hello   there   doctor"), "hello there doctor")

    def test_strips_english_filler_tokens(self):
        result = self.normalize("um where is the uh cardiology department", "en")
        self.assertNotIn("um", result.split())
        self.assertNotIn("uh", result.split())

    def test_strips_hindi_filler_tokens_for_hindi_language_code(self):
        result = self.normalize("matlab cardiology kahan hai haan", "hi")
        self.assertNotIn("matlab", result.split())
        self.assertNotIn("haan", result.split())

    def test_english_digit_words_converted_when_language_is_en(self):
        result = self.normalize("room number seven", "en")
        self.assertEqual(result, "room number 7")

    def test_digit_words_not_converted_for_pure_hindi_non_mixed(self):
        # No English digit-words expected in pure Hindi speech; converting
        # would be a no-op here regardless, this documents the boundary.
        result = self.normalize("kamra teen", "hi")
        self.assertEqual(result, "kamra teen")


class TestNormalizeCodeMixed(unittest.TestCase):
    """Reproduces the real bug: dominant-language-only rules silently
    drop entities that come from the non-dominant language."""

    def setUp(self):
        from bonbon_speech_ai.transcript_normalizer import normalize

        self.normalize = normalize

    def test_english_digit_words_converted_when_hindi_dominant_but_code_mixed(self):
        # "mera room number seven hai" -- Hindi-dominant per script count
        # in the real mixed-script sentence, but the digit word here is
        # the English "seven"; without is_code_mixed=True this stayed as
        # the word "seven" and hospital_entity_corrector's room-number
        # regex (which requires \d{1,4}) never matched.
        result = self.normalize("mera room number seven hai", "hi", is_code_mixed=True)
        self.assertEqual(result, "mera room number 7 hai")

    def test_room_number_extraction_survives_code_mixed_normalization(self):
        from bonbon_speech_ai.hospital_entity_corrector import HospitalVocabulary, correct

        normalized = self.normalize("mera room number seven hai", "hi", is_code_mixed=True)
        result = correct(normalized, HospitalVocabulary())
        self.assertEqual(result.room_number, "7")

    def test_room_number_extraction_fails_without_code_mixed_flag(self):
        # Documents the pre-fix failure mode so a regression is obvious:
        # calling normalize() without is_code_mixed reproduces the bug.
        from bonbon_speech_ai.hospital_entity_corrector import HospitalVocabulary, correct

        normalized = self.normalize("mera room number seven hai", "hi", is_code_mixed=False)
        result = correct(normalized, HospitalVocabulary())
        self.assertIsNone(result.room_number)

    def test_filler_tokens_from_both_languages_stripped_when_code_mixed(self):
        result = self.normalize("matlab room number seven um hai", "hi", is_code_mixed=True)
        self.assertNotIn("matlab", result.split())
        self.assertNotIn("um", result.split())

    def test_non_mixed_call_keeps_hindi_only_filler_set(self):
        # is_code_mixed=False (default) must NOT change existing
        # single-language behavior -- "um" is an English filler, not
        # Hindi, so it stays when language_code="hi" and not mixed.
        result = self.normalize("matlab kahan hai um", "hi")
        self.assertNotIn("matlab", result.split())
        self.assertIn("um", result.split())


if __name__ == "__main__":
    unittest.main()
