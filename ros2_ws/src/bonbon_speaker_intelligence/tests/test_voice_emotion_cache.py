"""Tests for VoiceEmotionCache — staleness-gated voice emotion lookup."""

from __future__ import annotations

from bonbon_speaker_intelligence.core.voice_emotion_cache import VoiceEmotionCache


class _Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


class TestEmptyCache:
    def test_returns_empty_when_never_updated(self):
        cache = VoiceEmotionCache()
        emotion, conf = cache.get_if_fresh()
        assert emotion == ""
        assert conf == 0.0


class TestFreshness:
    def test_fresh_reading_returned(self):
        clock = _Clock()
        cache = VoiceEmotionCache(max_age_sec=3.0, clock=clock)
        cache.update("happy", 0.8)
        emotion, conf = cache.get_if_fresh()
        assert emotion == "happy"
        assert conf == 0.8

    def test_stale_reading_not_returned(self):
        clock = _Clock()
        cache = VoiceEmotionCache(max_age_sec=2.0, clock=clock)
        cache.update("angry", 0.7)
        clock.advance(5.0)
        emotion, conf = cache.get_if_fresh()
        assert emotion == ""
        assert conf == 0.0

    def test_update_replaces_previous_reading(self):
        clock = _Clock()
        cache = VoiceEmotionCache(max_age_sec=5.0, clock=clock)
        cache.update("sad", 0.6)
        clock.advance(1.0)
        cache.update("calm", 0.9)
        emotion, conf = cache.get_if_fresh()
        assert emotion == "calm"
        assert conf == 0.9
