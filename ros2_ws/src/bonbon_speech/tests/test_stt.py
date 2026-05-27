"""
Tests for the STT layer:
  - MockSTT deterministic responses
  - Confidence threshold + is_low_confidence
  - Timeout handling + degraded mode
  - Error / exception handling
  - Multi-language responses
  - Silence / empty segment
  - Word timestamps pass-through
"""

import numpy as np
import pytest
from bonbon_speech.config.speech_config import STTConfig
from bonbon_speech.stt.base_stt import TranscriptionResult
from bonbon_speech.stt.mock_stt import MockSTT


def make_cfg(**kwargs) -> STTConfig:
    defaults = dict(
        backend="mock",
        confidence_threshold=0.50,
        inference_timeout_sec=2.0,
        max_consecutive_timeouts=3,
    )
    defaults.update(kwargs)
    return STTConfig(**defaults)


def make_stt(**kwargs) -> MockSTT:
    cfg = make_cfg(**kwargs)
    stt = MockSTT(cfg=cfg)
    stt.load()
    return stt


def samples(n: int = 16000) -> np.ndarray:
    return np.random.randn(n).astype(np.float32) * 0.1


# ── TranscriptionResult ───────────────────────────────────────────────────────


class TestTranscriptionResult:
    def test_defaults(self):
        r = TranscriptionResult()
        assert r.text == ""
        assert r.confidence == 0.0
        assert not r.is_low_confidence
        assert not r.is_timeout
        assert not r.is_silence

    def test_word_lists_default_empty(self):
        r = TranscriptionResult()
        assert r.words == []
        assert r.word_start_times_sec == []
        assert r.word_end_times_sec == []
        assert r.word_confidences == []


# ── MockSTT basics ────────────────────────────────────────────────────────────


class TestMockSTTBasics:
    def test_load_sets_loaded(self):
        stt = MockSTT(make_cfg())
        stt.load()
        assert stt.loaded

    def test_unload_clears_loaded(self):
        stt = MockSTT(make_cfg())
        stt.load()
        stt.unload()
        assert not stt.loaded

    def test_default_response(self):
        stt = make_stt()
        result = stt.transcribe(samples())
        assert result.text == "hello world"
        assert result.language == "en"
        assert result.confidence == pytest.approx(0.95)

    def test_call_count_increments(self):
        stt = make_stt()
        stt.transcribe(samples())
        stt.transcribe(samples())
        assert stt.call_count == 2

    def test_empty_segment_returns_silence(self):
        stt = make_stt()
        result = stt.transcribe(np.zeros(0, dtype=np.float32))
        assert result.is_silence is True

    def test_multiple_responses_cycle(self):
        responses = [
            TranscriptionResult(text="one", confidence=0.9),
            TranscriptionResult(text="two", confidence=0.8),
        ]
        stt = MockSTT(make_cfg(), responses=responses)
        stt.load()
        r1 = stt.transcribe(samples())
        r2 = stt.transcribe(samples())
        r3 = stt.transcribe(samples())  # cycles back
        assert r1.text == "one"
        assert r2.text == "two"
        assert r3.text == "one"


# ── Confidence gate ───────────────────────────────────────────────────────────


class TestConfidenceGate:
    def test_low_confidence_flagged(self):
        responses = [TranscriptionResult(text="maybe", confidence=0.3)]
        stt = MockSTT(make_cfg(confidence_threshold=0.5), responses=responses)
        stt.load()
        result = stt.transcribe(samples())
        assert result.is_low_confidence is True

    def test_high_confidence_not_flagged(self):
        responses = [TranscriptionResult(text="clear", confidence=0.9)]
        stt = MockSTT(make_cfg(confidence_threshold=0.5), responses=responses)
        stt.load()
        result = stt.transcribe(samples())
        assert result.is_low_confidence is False

    def test_exact_threshold_not_flagged(self):
        # confidence == threshold → NOT low confidence (strictly below)
        responses = [TranscriptionResult(text="ok", confidence=0.5)]
        stt = MockSTT(make_cfg(confidence_threshold=0.5), responses=responses)
        stt.load()
        result = stt.transcribe(samples())
        assert not result.is_low_confidence


# ── Timeout handling ──────────────────────────────────────────────────────────


class TestTimeout:
    def test_timeout_returns_is_timeout_true(self):
        stt = MockSTT(
            make_cfg(inference_timeout_sec=0.1, max_consecutive_timeouts=5),
            block_sec=0.5,  # will exceed timeout
        )
        stt.load()
        result = stt.transcribe(samples())
        assert result.is_timeout is True

    def test_consecutive_timeouts_counted(self):
        stt = MockSTT(
            make_cfg(inference_timeout_sec=0.05, max_consecutive_timeouts=10),
            block_sec=0.3,
        )
        stt.load()
        for _ in range(3):
            stt.transcribe(samples())
        assert stt.consecutive_timeouts == 3

    def test_degraded_after_max_timeouts(self):
        stt = MockSTT(
            make_cfg(inference_timeout_sec=0.05, max_consecutive_timeouts=2),
            block_sec=0.3,
        )
        stt.load()
        for _ in range(2):
            stt.transcribe(samples())
        assert stt.is_degraded

    def test_successful_call_resets_timeout_count(self):
        stt = MockSTT(
            make_cfg(inference_timeout_sec=0.05, max_consecutive_timeouts=5),
            block_sec=0.3,
        )
        stt.load()
        stt.transcribe(samples())  # times out
        assert stt.consecutive_timeouts == 1
        stt.set_block(0.0)
        stt.transcribe(samples())  # succeeds
        assert stt.consecutive_timeouts == 0

    def test_reset_degraded(self):
        stt = MockSTT(
            make_cfg(inference_timeout_sec=0.05, max_consecutive_timeouts=1),
            block_sec=0.3,
        )
        stt.load()
        stt.transcribe(samples())
        assert stt.is_degraded
        stt.reset_degraded()
        assert not stt.is_degraded


# ── Error handling ────────────────────────────────────────────────────────────


class TestErrorHandling:
    def test_corrupt_call_returns_result_not_raises(self):
        stt = MockSTT(make_cfg(), corrupt_on=[0])
        stt.load()
        result = stt.transcribe(samples())
        # Should NOT raise; returns an empty/failed result
        assert isinstance(result, TranscriptionResult)
        assert not result.is_timeout  # exception path, not timeout

    def test_after_corrupt_next_call_ok(self):
        responses = [
            TranscriptionResult(text="ok", confidence=0.9),
        ]
        stt = MockSTT(make_cfg(), responses=responses, corrupt_on=[0])
        stt.load()
        stt.transcribe(samples())  # corrupted call
        result = stt.transcribe(samples())  # should work
        assert result.text == "ok"


# ── Multi-language ────────────────────────────────────────────────────────────


class TestMultiLanguage:
    def test_language_from_response(self):
        responses = [
            TranscriptionResult(text="hola", language="es", confidence=0.88),
        ]
        stt = MockSTT(make_cfg(), responses=responses)
        stt.load()
        result = stt.transcribe(samples())
        assert result.language == "es"
        assert result.text == "hola"

    def test_chinese_language(self):
        responses = [
            TranscriptionResult(text="你好", language="zh", confidence=0.92),
        ]
        stt = MockSTT(make_cfg(), responses=responses)
        stt.load()
        result = stt.transcribe(samples())
        assert result.language == "zh"

    def test_japanese_language(self):
        responses = [
            TranscriptionResult(text="こんにちは", language="ja", confidence=0.85),
        ]
        stt = MockSTT(make_cfg(), responses=responses)
        stt.load()
        result = stt.transcribe(samples())
        assert result.language == "ja"


# ── Word timestamps ───────────────────────────────────────────────────────────


class TestWordTimestamps:
    def test_word_fields_passed_through(self):
        responses = [
            TranscriptionResult(
                text="hello world",
                language="en",
                confidence=0.95,
                words=["hello", "world"],
                word_start_times_sec=[0.0, 0.5],
                word_end_times_sec=[0.4, 1.0],
                word_confidences=[0.99, 0.97],
            )
        ]
        stt = MockSTT(make_cfg(), responses=responses)
        stt.load()
        result = stt.transcribe(samples())
        assert result.words == ["hello", "world"]
        assert result.word_start_times_sec == [0.0, 0.5]
        assert result.word_end_times_sec == [0.4, 1.0]
        assert result.word_confidences == [0.99, 0.97]

    def test_word_fields_independent_copy(self):
        """Result words list should be independent of response."""
        words = ["a", "b"]
        responses = [TranscriptionResult(words=words)]
        stt = MockSTT(make_cfg(), responses=responses)
        stt.load()
        result = stt.transcribe(samples())
        result.words.append("c")
        # Original response words should be unmodified
        assert words == ["a", "b"]


# ── Inference timing ──────────────────────────────────────────────────────────


class TestInferenceTiming:
    def test_inference_ms_set(self):
        stt = make_stt()
        result = stt.transcribe(samples())
        assert result.inference_ms >= 0.0

    def test_inference_ms_includes_block_time(self):
        stt = MockSTT(make_cfg(inference_timeout_sec=5.0), block_sec=0.05)
        stt.load()
        result = stt.transcribe(samples())
        assert result.inference_ms >= 50.0  # at least 50 ms
