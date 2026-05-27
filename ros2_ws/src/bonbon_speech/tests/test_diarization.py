"""
Tests for the diarization layer:
  - SpeakerSegment / DiarizationResult helpers
  - MockDiarizer deterministic responses
  - Multi-speaker detection
  - Timeout simulation
  - Dominant speaker calculation
"""

import time

import numpy as np
import pytest
from bonbon_speech.config.speech_config import DiarizationConfig
from bonbon_speech.diarization.base_diarizer import (
    DiarizationResult,
    SpeakerSegment,
)
from bonbon_speech.diarization.mock_diarizer import MockDiarizer


def make_cfg(**kwargs) -> DiarizationConfig:
    defaults = dict(enabled=True, backend="mock")
    defaults.update(kwargs)
    return DiarizationConfig(**defaults)


def make_diarizer(**kwargs) -> MockDiarizer:
    d = MockDiarizer(cfg=make_cfg())
    d.load()
    return d


def samples(n: int = 16000) -> np.ndarray:
    return np.zeros(n, dtype=np.float32)


# ── SpeakerSegment ────────────────────────────────────────────────────────────


class TestSpeakerSegment:
    def test_duration_property(self):
        seg = SpeakerSegment("SPEAKER_00", 1.0, 3.5)
        assert seg.duration_sec == pytest.approx(2.5)

    def test_zero_duration(self):
        seg = SpeakerSegment("SPEAKER_00", 2.0, 2.0)
        assert seg.duration_sec == pytest.approx(0.0)

    def test_negative_clamped_to_zero(self):
        seg = SpeakerSegment("SPEAKER_00", 3.0, 1.0)
        assert seg.duration_sec == pytest.approx(0.0)


# ── DiarizationResult ─────────────────────────────────────────────────────────


class TestDiarizationResult:
    def test_empty_result_defaults(self):
        r = DiarizationResult()
        assert r.segments == []
        assert r.dominant_speaker == "SPEAKER_00"
        assert r.all_speaker_ids == []
        assert not r.is_timeout

    def test_all_speaker_ids_populated_from_segments(self):
        segs = [
            SpeakerSegment("SPEAKER_00", 0.0, 1.0),
            SpeakerSegment("SPEAKER_01", 1.0, 2.0),
            SpeakerSegment("SPEAKER_00", 2.0, 3.0),
        ]
        r = DiarizationResult(segments=segs)
        assert set(r.all_speaker_ids) == {"SPEAKER_00", "SPEAKER_01"}

    def test_dominant_speaker_longest_time(self):
        segs = [
            SpeakerSegment("SPEAKER_00", 0.0, 1.0),  # 1.0 sec
            SpeakerSegment("SPEAKER_01", 1.0, 4.0),  # 3.0 sec  ← dominant
        ]
        r = DiarizationResult(segments=segs)
        assert r.dominant_speaker == "SPEAKER_01"

    def test_dominant_speaker_cumulative(self):
        segs = [
            SpeakerSegment("SPEAKER_00", 0.0, 1.0),  # 1.0
            SpeakerSegment("SPEAKER_01", 1.0, 2.5),  # 1.5
            SpeakerSegment("SPEAKER_00", 2.5, 5.0),  # 2.5 → total 3.5
        ]
        r = DiarizationResult(segments=segs)
        assert r.dominant_speaker == "SPEAKER_00"

    def test_timeout_flag(self):
        r = DiarizationResult(is_timeout=True)
        assert r.is_timeout


# ── MockDiarizer ──────────────────────────────────────────────────────────────


class TestMockDiarizerBasics:
    def test_load_unload(self):
        d = MockDiarizer(cfg=make_cfg())
        d.load()
        assert d.loaded
        d.unload()
        assert not d.loaded

    def test_default_response(self):
        d = make_diarizer()
        result = d.diarize(samples())
        assert isinstance(result, DiarizationResult)
        assert result.dominant_speaker == "SPEAKER_00"

    def test_call_count(self):
        d = make_diarizer()
        d.diarize(samples())
        d.diarize(samples())
        assert d.call_count == 2

    def test_response_cycles(self):
        responses = [
            DiarizationResult(
                segments=[SpeakerSegment("SPK_A", 0, 1)],
                dominant_speaker="SPK_A",
                all_speaker_ids=["SPK_A"],
            ),
            DiarizationResult(
                segments=[SpeakerSegment("SPK_B", 0, 2)],
                dominant_speaker="SPK_B",
                all_speaker_ids=["SPK_B"],
            ),
        ]
        d = MockDiarizer(cfg=make_cfg(), responses=responses)
        d.load()
        r1 = d.diarize(samples())
        r2 = d.diarize(samples())
        r3 = d.diarize(samples())  # cycles
        assert r1.dominant_speaker == "SPK_A"
        assert r2.dominant_speaker == "SPK_B"
        assert r3.dominant_speaker == "SPK_A"


# ── Multi-speaker ─────────────────────────────────────────────────────────────


class TestMultiSpeaker:
    def test_two_speaker_result(self):
        segs = [
            SpeakerSegment("SPEAKER_00", 0.0, 2.0),
            SpeakerSegment("SPEAKER_01", 2.0, 5.0),
        ]
        responses = [
            DiarizationResult(
                segments=segs,
                dominant_speaker="SPEAKER_01",
                all_speaker_ids=["SPEAKER_00", "SPEAKER_01"],
            )
        ]
        d = MockDiarizer(cfg=make_cfg(), responses=responses)
        d.load()
        result = d.diarize(samples())
        assert len(result.segments) == 2
        assert "SPEAKER_01" in result.all_speaker_ids
        assert result.dominant_speaker == "SPEAKER_01"

    def test_three_speakers(self):
        segs = [
            SpeakerSegment("S0", 0.0, 1.0),
            SpeakerSegment("S1", 1.0, 2.0),
            SpeakerSegment("S2", 2.0, 3.0),
        ]
        responses = [
            DiarizationResult(
                segments=segs,
                dominant_speaker="S0",
                all_speaker_ids=["S0", "S1", "S2"],
            )
        ]
        d = MockDiarizer(cfg=make_cfg(), responses=responses)
        d.load()
        result = d.diarize(samples())
        assert len(result.all_speaker_ids) == 3

    def test_single_speaker_result(self):
        segs = [SpeakerSegment("SPEAKER_00", 0.0, 3.0)]
        responses = [
            DiarizationResult(
                segments=segs,
                dominant_speaker="SPEAKER_00",
                all_speaker_ids=["SPEAKER_00"],
            )
        ]
        d = MockDiarizer(cfg=make_cfg(), responses=responses)
        d.load()
        result = d.diarize(samples())
        assert result.dominant_speaker == "SPEAKER_00"
        assert len(result.all_speaker_ids) == 1


# ── Timeout simulation ────────────────────────────────────────────────────────


class TestDiarizationTimeout:
    def test_timeout_response(self):
        responses = [DiarizationResult(is_timeout=True)]
        d = MockDiarizer(cfg=make_cfg(), responses=responses)
        d.load()
        result = d.diarize(samples())
        assert result.is_timeout

    def test_block_simulates_latency(self):
        d = MockDiarizer(cfg=make_cfg(), block_sec=0.1)
        d.load()
        t0 = time.monotonic()
        d.diarize(samples())
        elapsed = time.monotonic() - t0
        assert elapsed >= 0.08  # at least 80 ms

    def test_set_responses_reset(self):
        d = make_diarizer()
        d.diarize(samples())
        new_responses = [
            DiarizationResult(
                dominant_speaker="NEW",
                all_speaker_ids=["NEW"],
            )
        ]
        d.set_responses(new_responses)
        result = d.diarize(samples())
        assert result.dominant_speaker == "NEW"
