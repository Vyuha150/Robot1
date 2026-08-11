"""Tests for bonbon_speech_ai.language_detector -- EN/HI/TE detection by
Unicode script range, and the code-mixed-speech handling rule."""

from __future__ import annotations

import unittest


class TestLanguageDetector(unittest.TestCase):
    def setUp(self):
        from bonbon_speech_ai.language_detector import detect

        self.detect = detect

    def test_pure_english_detected_as_en(self):
        result = self.detect("Where is the cardiology department?")
        self.assertEqual(result.language_code, "en")
        self.assertFalse(result.is_code_mixed)

    def test_pure_hindi_devanagari_detected_as_hi(self):
        result = self.detect("कार्डियोलॉजी विभाग कहाँ है")
        self.assertEqual(result.language_code, "hi")
        self.assertFalse(result.is_code_mixed)

    def test_pure_telugu_detected_as_te(self):
        result = self.detect("కార్డియాలజీ విభాగం ఎక్కడ ఉంది")
        self.assertEqual(result.language_code, "te")
        self.assertFalse(result.is_code_mixed)

    def test_code_mixed_text_flags_is_code_mixed(self):
        # Majority-Hindi with an embedded English word -- realistic
        # hospital code-mixed speech ("token number" is common in
        # code-mixed Hindi/Telugu speech to a reception robot).
        result = self.detect("मुझे token चाहिए कार्डियोलॉजी के लिए कृपया")
        self.assertTrue(result.is_code_mixed)
        self.assertEqual(result.language_code, "hi")  # Hindi is the majority script

    def test_asr_reported_language_short_circuits_script_detection(self):
        # If the ASR engine already reports a language, trust it and skip
        # script counting entirely (script counts empty).
        result = self.detect("some ambiguous text", asr_reported_language="te")
        self.assertEqual(result.language_code, "te")
        self.assertEqual(result.script_counts, {})

    def test_asr_reported_auto_or_unknown_falls_through_to_script_detection(self):
        result = self.detect("Hello there", asr_reported_language="auto")
        self.assertEqual(result.language_code, "en")
        self.assertNotEqual(result.script_counts, {})

    def test_empty_text_with_no_asr_language_defaults_to_english_not_mixed(self):
        result = self.detect("", asr_reported_language=None)
        self.assertEqual(result.language_code, "en")
        self.assertFalse(result.is_code_mixed)

    def test_numeric_and_punctuation_only_text_does_not_crash(self):
        result = self.detect("42, 3.14 - #!", asr_reported_language=None)
        self.assertEqual(result.language_code, "en")  # no scripted characters -> total=0 -> default


if __name__ == "__main__":
    unittest.main()
