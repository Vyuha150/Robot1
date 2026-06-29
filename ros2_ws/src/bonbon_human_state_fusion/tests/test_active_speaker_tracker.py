"""Tests for ActiveSpeakerTracker — per-person speaking recency + cross-ID-space
text attribution bridge."""

from __future__ import annotations

from bonbon_human_state_fusion.core.active_speaker_tracker import (
    RECENTLY_SPOKE,
    SILENT,
    SPEAKING,
    UNKNOWN,
    ActiveSpeakerTracker,
)


class _Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


class TestStatusTransitions:
    def test_unknown_for_never_seen_person(self):
        tracker = ActiveSpeakerTracker()
        assert tracker.status_for("ptrk_x") == UNKNOWN

    def test_speaking_immediately_after_turn(self):
        clock = _Clock()
        tracker = ActiveSpeakerTracker(speaking_window_sec=2.0, clock=clock)
        tracker.record_turn("ptrk_1", "hello", 0.9)
        assert tracker.status_for("ptrk_1") == SPEAKING

    def test_recently_spoke_after_speaking_window(self):
        clock = _Clock()
        tracker = ActiveSpeakerTracker(
            speaking_window_sec=2.0, recently_spoke_window_sec=15.0, clock=clock
        )
        tracker.record_turn("ptrk_1", "hello", 0.9)
        clock.advance(5.0)
        assert tracker.status_for("ptrk_1") == RECENTLY_SPOKE

    def test_silent_after_recently_spoke_window(self):
        clock = _Clock()
        tracker = ActiveSpeakerTracker(
            speaking_window_sec=2.0, recently_spoke_window_sec=15.0, clock=clock
        )
        tracker.record_turn("ptrk_1", "hello", 0.9)
        clock.advance(30.0)
        assert tracker.status_for("ptrk_1") == SILENT


class TestLastTranscript:
    def test_returns_empty_for_unseen_person(self):
        tracker = ActiveSpeakerTracker()
        text, conf = tracker.last_transcript_for("ptrk_x")
        assert text == ""
        assert conf == 0.0

    def test_returns_last_recorded_transcript(self):
        tracker = ActiveSpeakerTracker()
        tracker.record_turn("ptrk_1", "hello there", 0.85)
        text, conf = tracker.last_transcript_for("ptrk_1")
        assert text == "hello there"
        assert conf == 0.85


class TestMostRecentSpeaker:
    def test_empty_when_nobody_has_spoken(self):
        tracker = ActiveSpeakerTracker()
        assert tracker.most_recent_speaker(max_age_sec=5.0) == ""

    def test_returns_most_recent_within_window(self):
        clock = _Clock()
        tracker = ActiveSpeakerTracker(clock=clock)
        tracker.record_turn("ptrk_1", "a", 0.9)
        clock.advance(1.0)
        tracker.record_turn("ptrk_2", "b", 0.9)
        assert tracker.most_recent_speaker(max_age_sec=5.0) == "ptrk_2"

    def test_empty_when_most_recent_too_stale(self):
        clock = _Clock()
        tracker = ActiveSpeakerTracker(clock=clock)
        tracker.record_turn("ptrk_1", "a", 0.9)
        clock.advance(10.0)
        assert tracker.most_recent_speaker(max_age_sec=2.0) == ""

    def test_ignoring_person_with_no_id_never_recorded(self):
        tracker = ActiveSpeakerTracker()
        tracker.record_turn("", "a", 0.9)
        assert tracker.most_recent_speaker(max_age_sec=100.0) == ""


class TestForget:
    def test_forget_removes_status_and_most_recent(self):
        tracker = ActiveSpeakerTracker()
        tracker.record_turn("ptrk_1", "hello", 0.9)
        tracker.forget("ptrk_1")
        assert tracker.status_for("ptrk_1") == UNKNOWN
        assert tracker.most_recent_speaker(max_age_sec=100.0) == ""

    def test_forget_unrelated_person_keeps_most_recent(self):
        tracker = ActiveSpeakerTracker()
        tracker.record_turn("ptrk_1", "hello", 0.9)
        tracker.forget("ptrk_999")
        assert tracker.most_recent_speaker(max_age_sec=100.0) == "ptrk_1"
