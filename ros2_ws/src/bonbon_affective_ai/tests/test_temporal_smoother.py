"""Tests for TemporalSmoother, including the generalized `fields` param
added for voice emotion (18-point edge-AI verification, check 9: voice
emotion previously had no temporal smoothing at all, unlike face)."""

from __future__ import annotations

import unittest

from bonbon_affective_ai.fusion.temporal_smoother import (
    VOICE_EMOTION_FIELDS,
    TemporalSmoother,
)


class TestFaceFieldsBackwardCompatible(unittest.TestCase):
    """Default construction (no `fields` arg) must behave exactly as
    before this change -- face_emotion_analyzer.py relies on this."""

    def test_default_fields_average_face_emotion_keys(self):
        smoother = TemporalSmoother(window=3)
        smoother.smooth(1, {"happiness": 1.0, "neutral": 0.0})
        result = smoother.smooth(1, {"happiness": 0.0, "neutral": 1.0})
        self.assertAlmostEqual(result["happiness"], 0.5)
        self.assertAlmostEqual(result["neutral"], 0.5)

    def test_dominant_emotion_has_no_score_suffix_for_face_fields(self):
        smoother = TemporalSmoother(window=3)
        result = smoother.smooth(1, {"happiness": 0.9, "neutral": 0.1})
        self.assertEqual(result["dominant_emotion"], "happiness")


class TestVoiceEmotionFields(unittest.TestCase):
    def setUp(self):
        self.smoother = TemporalSmoother(window=3, fields=VOICE_EMOTION_FIELDS)

    def test_averages_voice_score_fields(self):
        self.smoother.smooth(1, {"happy_score": 1.0, "sad_score": 0.0})
        result = self.smoother.smooth(1, {"happy_score": 0.0, "sad_score": 1.0})
        self.assertAlmostEqual(result["happy_score"], 0.5)
        self.assertAlmostEqual(result["sad_score"], 0.5)

    def test_dominant_emotion_strips_score_suffix(self):
        # The raw field is "happy_score" but VoiceEmotion.msg.dominant_emotion
        # must read "happy", not "happy_score".
        result = self.smoother.smooth(1, {"happy_score": 0.9, "neutral_score": 0.1})
        self.assertEqual(result["dominant_emotion"], "happy")
        self.assertNotIn("_score", result["dominant_emotion"])

    def test_single_noisy_reading_does_not_dominate_the_average(self):
        for _ in range(4):
            self.smoother.smooth(1, {"neutral_score": 1.0})
        # One noisy angry spike shouldn't flip the smoothed dominant
        # emotion away from the well-established neutral trend.
        result = self.smoother.smooth(1, {"angry_score": 1.0})
        self.assertEqual(result["dominant_emotion"], "neutral")

    def test_per_tracking_id_isolation(self):
        self.smoother.smooth(1, {"happy_score": 1.0})
        self.smoother.smooth(2, {"sad_score": 1.0})
        r1 = self.smoother.smooth(1, {"happy_score": 1.0})
        r2 = self.smoother.smooth(2, {"sad_score": 1.0})
        self.assertEqual(r1["dominant_emotion"], "happy")
        self.assertEqual(r2["dominant_emotion"], "sad")

    def test_window_size_bounds_history(self):
        smoother = TemporalSmoother(window=2, fields=VOICE_EMOTION_FIELDS)
        smoother.smooth(1, {"happy_score": 1.0})
        smoother.smooth(1, {"happy_score": 0.0})
        result = smoother.smooth(1, {"happy_score": 0.0})
        # Window=2 means only the last 2 readings (0.0, 0.0) are averaged --
        # the first 1.0 must have been evicted.
        self.assertAlmostEqual(result["happy_score"], 0.0)


if __name__ == "__main__":
    unittest.main()
