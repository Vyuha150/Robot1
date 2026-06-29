"""Tests for attribute_transcript_to_segments — word-timestamp-based
transcript-to-speaker attribution within a single utterance.
"""

from __future__ import annotations

from bonbon_speaker_intelligence.core.transcript_segment_mapper import (
    DiarizationSegment,
    WordTiming,
    attribute_transcript_to_segments,
)


class TestNoSegments:
    def test_empty_segments_returns_empty(self):
        result = attribute_transcript_to_segments([], [], "hello", 0.9)
        assert result == []


class TestSingleSpeakerNoAmbiguity:
    def test_single_segment_gets_full_text_regardless_of_words(self):
        seg = DiarizationSegment("SPEAKER_00", 0.0, 3.0)
        result = attribute_transcript_to_segments([seg], [], "hello there", 0.9)
        assert len(result) == 1
        assert result[0].transcript == "hello there"
        assert result[0].text_is_attributed is True


class TestMultiSpeakerWithWordTiming:
    def test_words_attributed_to_correct_segment(self):
        segs = [
            DiarizationSegment("SPEAKER_00", 0.0, 1.5),
            DiarizationSegment("SPEAKER_01", 1.5, 3.0),
        ]
        words = [
            WordTiming("hello", 0.0, 0.4, confidence=0.9),
            WordTiming("there", 0.5, 1.0, confidence=0.85),
            WordTiming("how", 1.6, 1.9, confidence=0.8),
            WordTiming("are", 2.0, 2.3, confidence=0.8),
            WordTiming("you", 2.4, 2.8, confidence=0.75),
        ]
        result = attribute_transcript_to_segments(segs, words, "hello there how are you", 0.85)
        assert len(result) == 2
        assert result[0].transcript == "hello there"
        assert result[1].transcript == "how are you"

    def test_confidence_averaged_per_segment(self):
        segs = [
            DiarizationSegment("SPEAKER_00", 0.0, 1.0),
            DiarizationSegment("SPEAKER_01", 1.0, 2.0),
        ]
        words = [
            WordTiming("a", 0.0, 0.3, confidence=0.8),
            WordTiming("b", 0.3, 0.6, confidence=1.0),
            WordTiming("c", 1.1, 1.4, confidence=0.5),
        ]
        result = attribute_transcript_to_segments(segs, words, "a b c", 0.8)
        assert abs(result[0].transcript_confidence - 0.9) < 1e-6
        assert abs(result[1].transcript_confidence - 0.5) < 1e-6

    def test_boundary_slack_tolerates_minor_timing_jitter(self):
        segs = [
            DiarizationSegment("SPEAKER_00", 0.0, 1.0),
            DiarizationSegment("SPEAKER_01", 1.0, 2.0),
        ]
        # Word ends 0.05s after the nominal segment boundary — within slack.
        words = [WordTiming("edge", 0.9, 1.05, confidence=0.9)]
        result = attribute_transcript_to_segments(segs, words, "edge", 0.9, boundary_slack_sec=0.1)
        assert result[0].transcript == "edge"

    def test_word_outside_all_segments_is_dropped_not_misattributed(self):
        segs = [
            DiarizationSegment("SPEAKER_00", 0.0, 1.0),
            DiarizationSegment("SPEAKER_01", 1.0, 2.0),
        ]
        words = [WordTiming("far_away", 50.0, 50.5, confidence=0.9)]
        result = attribute_transcript_to_segments(segs, words, "far_away", 0.9)
        assert result[0].transcript == ""
        assert result[1].transcript == ""


class TestMultiSpeakerNoWordTiming:
    def test_no_words_leaves_text_unattributed_rather_than_guessed(self):
        segs = [
            DiarizationSegment("SPEAKER_00", 0.0, 1.0),
            DiarizationSegment("SPEAKER_01", 1.0, 2.0),
        ]
        result = attribute_transcript_to_segments(segs, [], "hello there friend", 0.9)
        assert len(result) == 2
        assert all(r.transcript == "" for r in result)
        assert all(r.text_is_attributed is False for r in result)
        assert all(r.transcript_confidence == 0.0 for r in result)
