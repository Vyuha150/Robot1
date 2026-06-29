"""Tests for SpeakerTurnBuilder — the full per-utterance orchestrator."""

from __future__ import annotations

from bonbon_speaker_intelligence.core.audio_visual_associator import TrackedPersonBearing
from bonbon_speaker_intelligence.core.speaker_identity_manager import (
    SpeakerIdentityConfig,
    SpeakerIdentityManager,
)
from bonbon_speaker_intelligence.core.speaker_turn_builder import SpeakerTurnBuilder
from bonbon_speaker_intelligence.core.transcript_segment_mapper import (
    DiarizationSegment,
    WordTiming,
)
from bonbon_speaker_intelligence.core.voice_emotion_cache import VoiceEmotionCache


class _Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


def _builder(clock=None):
    clock = clock or _Clock()
    identity = SpeakerIdentityManager(
        config=SpeakerIdentityConfig(doa_tolerance_deg=20.0, recency_window_sec=10.0), clock=clock
    )
    voice_cache = VoiceEmotionCache(max_age_sec=5.0, clock=clock)
    return SpeakerTurnBuilder(identity, voice_cache), clock, voice_cache


class TestSingleSpeakerTurn:
    def test_builds_one_turn_with_full_text(self):
        builder, _, _ = _builder()
        seg = DiarizationSegment("SPEAKER_00", 0.0, 2.0, confidence=0.9)
        turns = builder.build_turns([seg], [], "hello robot", 0.9, doa_deg=30.0, tracked_persons=[])
        assert len(turns) == 1
        t = turns[0]
        assert t.transcript == "hello robot"
        assert t.is_overlapping is False
        assert t.is_new_speaker is True

    def test_no_segments_returns_no_turns(self):
        builder, _, _ = _builder()
        turns = builder.build_turns([], [], "text", 0.9, doa_deg=10.0, tracked_persons=[])
        assert turns == []

    def test_repeat_speaker_same_bearing_continuity(self):
        builder, clock, _ = _builder()
        seg = DiarizationSegment("SPEAKER_00", 0.0, 1.0)
        t1 = builder.build_turns([seg], [], "hi", 0.9, doa_deg=30.0, tracked_persons=[])[0]
        clock.advance(1.0)
        t2 = builder.build_turns([seg], [], "again", 0.9, doa_deg=32.0, tracked_persons=[])[0]
        assert t1.speaker_id == t2.speaker_id
        assert t2.is_new_speaker is False


class TestAudioVisualAssociation:
    def test_turn_linked_to_visible_person(self):
        builder, _, _ = _builder()
        seg = DiarizationSegment("SPEAKER_00", 0.0, 1.0)
        people = [TrackedPersonBearing("ptrk_1", 28.0)]
        turn = builder.build_turns([seg], [], "hi", 0.9, doa_deg=30.0, tracked_persons=people)[0]
        assert turn.person_track_id == "ptrk_1"
        assert turn.is_off_camera is False
        assert turn.association_confidence > 0.0

    def test_off_camera_when_no_visible_match(self):
        builder, _, _ = _builder()
        seg = DiarizationSegment("SPEAKER_00", 0.0, 1.0)
        turn = builder.build_turns([seg], [], "hi", 0.9, doa_deg=30.0, tracked_persons=[])[0]
        assert turn.person_track_id == ""
        assert turn.is_off_camera is True


class TestOverlappingSpeech:
    def test_multiple_segments_all_flagged_overlapping(self):
        builder, _, _ = _builder()
        segs = [
            DiarizationSegment("SPEAKER_00", 0.0, 1.0),
            DiarizationSegment("SPEAKER_01", 1.0, 2.0),
        ]
        words = [
            WordTiming("hi", 0.0, 0.5),
            WordTiming("yo", 1.1, 1.6),
        ]
        turns = builder.build_turns(segs, words, "hi yo", 0.9, doa_deg=10.0, tracked_persons=[])
        assert len(turns) == 2
        assert all(t.is_overlapping for t in turns)

    def test_second_overlapping_speaker_gets_distinct_non_continuous_identity(self):
        builder, _, _ = _builder()
        segs = [
            DiarizationSegment("SPEAKER_00", 0.0, 1.0),
            DiarizationSegment("SPEAKER_01", 1.0, 2.0),
        ]
        turns = builder.build_turns(segs, [], "a b", 0.9, doa_deg=10.0, tracked_persons=[])
        assert turns[0].speaker_id != turns[1].speaker_id
        # The dominant segment claims continuity behaviour (allocated fresh
        # here since it's the first call), the second is also fresh — but
        # critically they must never collide on the SAME id.
        assert turns[1].is_new_speaker is True

    def test_association_confidence_reduced_when_overlapping(self):
        builder_a, _, _ = _builder()
        builder_b, _, _ = _builder()
        people = [TrackedPersonBearing("ptrk_1", 30.0)]
        single = builder_a.build_turns(
            [DiarizationSegment("S0", 0.0, 1.0)],
            [],
            "hi",
            0.9,
            doa_deg=30.0,
            tracked_persons=people,
        )[0]
        overlapping = builder_b.build_turns(
            [DiarizationSegment("S0", 0.0, 1.0), DiarizationSegment("S1", 1.0, 2.0)],
            [],
            "hi",
            0.9,
            doa_deg=30.0,
            tracked_persons=people,
        )[0]
        assert overlapping.association_confidence < single.association_confidence


class TestVoiceEmotionAttachment:
    def test_fresh_voice_emotion_attached(self):
        builder, clock, voice_cache = _builder()
        voice_cache.update("happy", 0.85)
        turn = builder.build_turns(
            [DiarizationSegment("S0", 0.0, 1.0)], [], "hi", 0.9, doa_deg=10.0, tracked_persons=[]
        )[0]
        assert turn.voice_emotion == "happy"
        assert turn.emotion_confidence == 0.85

    def test_stale_voice_emotion_not_attached(self):
        builder, clock, voice_cache = _builder()
        voice_cache.update("angry", 0.7)
        clock.advance(10.0)
        turn = builder.build_turns(
            [DiarizationSegment("S0", 0.0, 1.0)], [], "hi", 0.9, doa_deg=10.0, tracked_persons=[]
        )[0]
        assert turn.voice_emotion == ""


class TestShortSegmentFlag:
    def test_short_segment_flagged(self):
        builder, _, _ = _builder()
        seg = DiarizationSegment("S0", 0.0, 0.1)
        turn = builder.build_turns([seg], [], "uh", 0.5, doa_deg=10.0, tracked_persons=[])[0]
        assert turn.short_segment is True

    def test_normal_segment_not_flagged(self):
        builder, _, _ = _builder()
        seg = DiarizationSegment("S0", 0.0, 2.0)
        turn = builder.build_turns(
            [seg], [], "a longer utterance", 0.9, doa_deg=10.0, tracked_persons=[]
        )[0]
        assert turn.short_segment is False
