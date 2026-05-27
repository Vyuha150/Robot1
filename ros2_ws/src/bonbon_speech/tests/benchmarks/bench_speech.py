"""
bonbon_speech latency benchmarks
=================================
Measures wall-clock latency for every stage in the speech pipeline using
deterministic mock backends — no real model weights required.

Usage
-----
    # human-readable table
    python -m pytest tests/benchmarks/bench_speech.py -s -v

    # minimal timings only (quick mode, 10 reps per bench)
    python tests/benchmarks/bench_speech.py --quick

    # machine-readable JSON (for CI or charting)
    python tests/benchmarks/bench_speech.py --json

Output columns (table mode)
---------------------------
  bench         — stage / scenario name
  reps          — number of repetitions measured
  mean_ms       — arithmetic mean latency  (milliseconds)
  p50_ms        — median
  p95_ms        — 95th-percentile
  p99_ms        — 99th-percentile
  min_ms        — minimum observed
  max_ms        — maximum observed
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import types
from collections.abc import Callable
from statistics import mean, median
from unittest.mock import MagicMock

import numpy as np

# ── Minimal ROS2 / bonbon_msgs stubs ─────────────────────────────────────────


def _inject_stubs() -> None:
    if "rclpy" in sys.modules:
        return

    rclpy_mod = types.ModuleType("rclpy")
    rclpy_mod.init = lambda args=None: None
    rclpy_mod.spin = lambda node: None
    rclpy_mod.shutdown = lambda: None

    lc_mod = types.ModuleType("rclpy.lifecycle")
    lc_mod.TransitionCallbackReturn = type(
        "TransitionCallbackReturn", (), {"SUCCESS": "s", "FAILURE": "f"}
    )
    lc_mod.State = type("State", (), {})

    class _FakeNode:
        def __init__(self, name):
            self._name = name

        def get_logger(self):
            class L:
                def info(s, *a):
                    pass

                def debug(s, *a):
                    pass

                def warning(s, *a):
                    pass

                def error(s, *a):
                    pass

            return L()

        def create_lifecycle_publisher(self, *a, **kw):
            return MagicMock()

        def create_subscription(self, *a, **kw):
            return MagicMock()

        def create_timer(self, *a, **kw):
            return MagicMock()

        def get_parameter(self, n):
            class P:
                value = None

            return P()

        def declare_parameter(self, *a, **kw):
            pass

        def destroy_node(self):
            pass

    lc_mod.LifecycleNode = _FakeNode

    qos_mod = types.ModuleType("rclpy.qos")
    qos_mod.QoSProfile = type("QoSProfile", (), {"__init__": lambda s, **kw: None})
    qos_mod.ReliabilityPolicy = type("ReliabilityPolicy", (), {"RELIABLE": 1, "BEST_EFFORT": 0})
    qos_mod.HistoryPolicy = type("HistoryPolicy", (), {"KEEP_LAST": 1})
    rclpy_mod.lifecycle = lc_mod
    rclpy_mod.qos = qos_mod

    bm = types.ModuleType("bonbon_msgs")
    bmm = types.ModuleType("bonbon_msgs.msg")

    def _msg(name, **f):
        return type(name, (), {"__init__": lambda s: s.__dict__.update(f)})

    bmm.AudioChunk = _msg("AudioChunk", data=[], sample_rate=16000, header=None, doa_angle_deg=0.0)
    bmm.SpeechCommand = _msg(
        "SpeechCommand",
        header=None,
        text="",
        language="",
        confidence=0.0,
        is_low_confidence=False,
        is_timeout=False,
        is_silence=False,
        wake_word_triggered=False,
        speaker_id="",
        audio_duration_sec=0.0,
        transcription_ms=0.0,
        doa_angle_deg=0.0,
    )
    bmm.SpeechTranscription = _msg(
        "SpeechTranscription",
        header=None,
        text="",
        language="",
        confidence=0.0,
        words=[],
        word_start_times_sec=[],
        word_end_times_sec=[],
        word_confidences=[],
        speaker_id="",
        all_speaker_ids=[],
        audio_duration_sec=0.0,
        transcription_ms=0.0,
        doa_angle_deg=0.0,
        vad_force_cut=False,
    )
    bmm.ModuleHealth = _msg(
        "ModuleHealth",
        module_name="",
        status=0,
        status_text="",
        uptime_sec=0.0,
        last_successful_cycle_sec=0.0,
        cpu_percent=0.0,
        memory_mb=0.0,
        latency_ms=0.0,
        error_count=0,
        warning_count=0,
        processed_count=0,
    )
    bm.msg = bmm

    for k, v in [
        ("rclpy", rclpy_mod),
        ("rclpy.lifecycle", lc_mod),
        ("rclpy.qos", qos_mod),
        ("bonbon_msgs", bm),
        ("bonbon_msgs.msg", bmm),
    ]:
        sys.modules.setdefault(k, v)


_inject_stubs()

# ── Pipeline imports ──────────────────────────────────────────────────────────

from bonbon_speech.audio.audio_buffer import AudioBuffer
from bonbon_speech.audio.audio_preprocessor import AudioPreprocessor, PreprocessorConfig
from bonbon_speech.config.speech_config import SpeechConfig, WakeWordConfig
from bonbon_speech.diarization.mock_diarizer import DiarizationResult, MockDiarizer
from bonbon_speech.stt.mock_stt import MockSTT
from bonbon_speech.vad.mock_vad import MockVAD
from bonbon_speech.wake_word.mock_wake_word import MockWakeWordDetector

# ── Benchmark harness ─────────────────────────────────────────────────────────


class BenchResult:
    __slots__ = ("name", "reps", "samples_ms")

    def __init__(self, name: str, reps: int, samples_ms: list[float]) -> None:
        self.name = name
        self.reps = reps
        self.samples_ms = sorted(samples_ms)

    # ------------------------------------------------------------------
    def mean_ms(self) -> float:
        return mean(self.samples_ms)

    def p50_ms(self) -> float:
        return median(self.samples_ms)

    def min_ms(self) -> float:
        return self.samples_ms[0]

    def max_ms(self) -> float:
        return self.samples_ms[-1]

    def p95_ms(self) -> float:
        return _percentile(self.samples_ms, 95)

    def p99_ms(self) -> float:
        return _percentile(self.samples_ms, 99)

    def to_dict(self) -> dict:
        return {
            "bench": self.name,
            "reps": self.reps,
            "mean_ms": round(self.mean_ms(), 3),
            "p50_ms": round(self.p50_ms(), 3),
            "p95_ms": round(self.p95_ms(), 3),
            "p99_ms": round(self.p99_ms(), 3),
            "min_ms": round(self.min_ms(), 3),
            "max_ms": round(self.max_ms(), 3),
        }


def _percentile(sorted_data: list[float], pct: int) -> float:
    n = len(sorted_data)
    if n == 1:
        return sorted_data[0]
    idx = pct / 100 * (n - 1)
    lo, hi = int(idx), min(int(idx) + 1, n - 1)
    return sorted_data[lo] + (sorted_data[hi] - sorted_data[lo]) * (idx - lo)


def _run_bench(
    name: str,
    fn: Callable[[], None],
    reps: int,
    warmup: int = 3,
) -> BenchResult:
    for _ in range(warmup):
        fn()
    samples_ms: list[float] = []
    for _ in range(reps):
        t0 = time.perf_counter()
        fn()
        samples_ms.append((time.perf_counter() - t0) * 1000.0)
    return BenchResult(name, reps, samples_ms)


def _print_table(results: list[BenchResult]) -> None:
    cols = ["bench", "reps", "mean_ms", "p50_ms", "p95_ms", "p99_ms", "min_ms", "max_ms"]
    rows = [r.to_dict() for r in results]
    widths = {c: max(len(c), max(len(str(row[c])) for row in rows)) for c in cols}
    sep = "  ".join("-" * widths[c] for c in cols)
    header = "  ".join(c.ljust(widths[c]) for c in cols)
    print(f"\n{header}\n{sep}")
    for row in rows:
        print("  ".join(str(row[c]).ljust(widths[c]) for c in cols))
    print()


# ── Fixtures / setup helpers ──────────────────────────────────────────────────


def _chunk(n: int = 512) -> np.ndarray:
    return np.zeros(n, dtype=np.float32)


def _speech_samples(n: int = 16000) -> np.ndarray:
    """Synthetic speech-like signal (sine burst)."""
    t = np.linspace(0, 1, n, dtype=np.float32)
    return (0.3 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)


# ── Individual benchmarks ─────────────────────────────────────────────────────


def bench_preprocessor(reps: int) -> BenchResult:
    """AudioPreprocessor.process() on a 512-sample chunk."""
    preproc = AudioPreprocessor(PreprocessorConfig())
    data = _chunk(512)
    return _run_bench(
        "preprocessor_512samp",
        lambda: preproc.process(data),
        reps,
    )


def bench_preprocessor_large(reps: int) -> BenchResult:
    """AudioPreprocessor.process() on a 16000-sample (1 s) frame."""
    preproc = AudioPreprocessor(PreprocessorConfig())
    data = _speech_samples(16000)
    return _run_bench(
        "preprocessor_16ksamp",
        lambda: preproc.process(data),
        reps,
    )


def bench_audio_buffer_push(reps: int) -> BenchResult:
    """AudioBuffer.push() with 512 samples."""
    buf = AudioBuffer(sample_rate=16000, max_buffer_sec=30.0, prebuffer_sec=0.5)
    data = _chunk(512)
    return _run_bench(
        "audio_buffer_push",
        lambda: buf.push(data),
        reps,
    )


def bench_audio_buffer_drain(reps: int) -> BenchResult:
    """AudioBuffer.drain_all() on a ~1 s buffer."""

    def _setup_and_drain():
        buf = AudioBuffer(sample_rate=16000, max_buffer_sec=30.0, prebuffer_sec=0.5)
        for _ in range(32):  # 32 × 512 = 16 384 samples ≈ 1 s
            buf.push(_chunk(512))
        buf.drain_all()

    return _run_bench("audio_buffer_drain_1s", _setup_and_drain, reps)


def bench_mock_vad_silence(reps: int) -> BenchResult:
    """MockVAD.process_chunk() — silence path (no segment emitted)."""
    vad = MockVAD(sample_rate=16000)
    vad.load()
    data = _chunk(512)
    return _run_bench(
        "mock_vad_silence",
        lambda: vad.process_chunk(data),
        reps,
    )


def bench_mock_vad_emit(reps: int) -> BenchResult:
    """MockVAD.process_chunk() — forced emit path (segment returned)."""
    vad = MockVAD(sample_rate=16000)
    vad.load()
    data = _speech_samples(512)

    def _emit():
        vad.force_next_emit(samples=_speech_samples(8000))
        vad.process_chunk(data)

    return _run_bench("mock_vad_emit", _emit, reps)


def bench_mock_stt(reps: int) -> BenchResult:
    """MockSTT.transcribe() — zero-latency response."""
    cfg = SpeechConfig().stt
    stt = MockSTT(cfg)
    stt.load()
    data = _speech_samples(16000)
    return _run_bench(
        "mock_stt_transcribe",
        lambda: stt.transcribe(data),
        reps,
    )


def bench_mock_stt_with_block(reps: int) -> BenchResult:
    """MockSTT.transcribe() — simulated 20 ms inference latency."""
    cfg = SpeechConfig().stt
    cfg.inference_timeout_sec = 5.0
    stt = MockSTT(cfg, block_sec=0.020)
    stt.load()
    data = _speech_samples(16000)
    return _run_bench(
        "mock_stt_20ms_block",
        lambda: stt.transcribe(data),
        reps,
        warmup=1,
    )


def bench_mock_diarizer(reps: int) -> BenchResult:
    """MockDiarizer.diarize() — zero-latency response."""
    d = MockDiarizer()
    d.load()
    data = _speech_samples(16000)
    return _run_bench(
        "mock_diarizer",
        lambda: d.diarize(data),
        reps,
    )


def bench_mock_wake_word(reps: int) -> BenchResult:
    """MockWakeWordDetector.process_chunk() — no-detection path."""
    cfg = WakeWordConfig(enabled=True, backend="mock", keyword="hey bonbon", threshold=0.5)
    det = MockWakeWordDetector(cfg=cfg, detect_pattern=[False])
    det.load()
    data = _chunk(512)
    return _run_bench(
        "wake_word_no_detect",
        lambda: det.process_chunk(data),
        reps,
    )


def bench_end_to_end_stt_only(reps: int) -> BenchResult:
    """
    Preprocessor → push_buffer → MockVAD emit → MockSTT.

    Represents the hot path from AudioChunk arrival to SpeechCommand
    publication, excluding diarization.
    """
    preproc = AudioPreprocessor(PreprocessorConfig())
    buf = AudioBuffer(16000, 30.0, 0.5)
    vad = MockVAD(sample_rate=16000)
    vad.load()
    cfg = SpeechConfig().stt
    stt = MockSTT(cfg)
    stt.load()
    raw = _speech_samples(512)

    def _pipeline():
        chunk = preproc.process(raw.copy())
        buf.push(chunk)
        vad.force_next_emit(samples=_speech_samples(8000))
        seg = vad.process_chunk(chunk)
        if seg is not None:
            stt.transcribe(seg.samples)

    return _run_bench("e2e_no_diarization", _pipeline, reps)


def bench_end_to_end_with_diarizer(reps: int) -> BenchResult:
    """
    Preprocessor → push_buffer → MockVAD emit → MockSTT + MockDiarizer.
    """
    preproc = AudioPreprocessor(PreprocessorConfig())
    buf = AudioBuffer(16000, 30.0, 0.5)
    vad = MockVAD(sample_rate=16000)
    vad.load()
    cfg = SpeechConfig().stt
    stt = MockSTT(cfg)
    stt.load()
    diarizer = MockDiarizer()
    diarizer.load()
    raw = _speech_samples(512)

    def _pipeline():
        chunk = preproc.process(raw.copy())
        buf.push(chunk)
        vad.force_next_emit(samples=_speech_samples(8000))
        seg = vad.process_chunk(chunk)
        if seg is not None:
            stt.transcribe(seg.samples)
            diarizer.diarize(seg.samples)

    return _run_bench("e2e_with_diarization", _pipeline, reps)


def bench_end_to_end_with_wake_word(reps: int) -> BenchResult:
    """
    Wake-word detection → Preprocessor → MockVAD emit → MockSTT.
    """
    preproc = AudioPreprocessor(PreprocessorConfig())
    buf = AudioBuffer(16000, 30.0, 0.5)
    vad = MockVAD(sample_rate=16000)
    vad.load()
    cfg = SpeechConfig().stt
    stt = MockSTT(cfg)
    stt.load()
    ww_cfg = WakeWordConfig(enabled=True, backend="mock", keyword="hey bonbon", threshold=0.5)
    ww = MockWakeWordDetector(cfg=ww_cfg, detect_pattern=[False])
    ww.load()
    raw = _speech_samples(512)

    def _pipeline():
        chunk = preproc.process(raw.copy())
        ww.process_chunk(chunk)  # no-detect path
        buf.push(chunk)
        vad.force_next_emit(samples=_speech_samples(8000))
        seg = vad.process_chunk(chunk)
        if seg is not None:
            stt.transcribe(seg.samples)

    return _run_bench("e2e_with_wake_word", _pipeline, reps)


def bench_privacy_anonymize(reps: int) -> BenchResult:
    """
    Cost of the privacy anonymisation string-replace inside _process_segment.
    Measured as one STT + diarize + speaker_id replacement.
    """
    cfg = SpeechConfig()
    cfg.privacy.anonymize_speaker = True
    stt = MockSTT(cfg.stt)
    stt.load()
    diarizer = MockDiarizer(
        responses=[
            DiarizationResult(
                dominant_speaker="SPEAKER_01",
                all_speaker_ids=["SPEAKER_00", "SPEAKER_01"],
            )
        ]
    )
    diarizer.load()
    data = _speech_samples(16000)

    def _step():
        result = stt.transcribe(data)
        dr = diarizer.diarize(data)
        speaker_id = dr.dominant_speaker
        if cfg.privacy.anonymize_speaker:
            speaker_id = "SPEAKER_ANON"
        return result, speaker_id

    return _run_bench("privacy_anonymize", _step, reps)


# ── Runner ────────────────────────────────────────────────────────────────────

_ALL_BENCHES = [
    bench_preprocessor,
    bench_preprocessor_large,
    bench_audio_buffer_push,
    bench_audio_buffer_drain,
    bench_mock_vad_silence,
    bench_mock_vad_emit,
    bench_mock_stt,
    bench_mock_stt_with_block,
    bench_mock_diarizer,
    bench_mock_wake_word,
    bench_end_to_end_stt_only,
    bench_end_to_end_with_diarizer,
    bench_end_to_end_with_wake_word,
    bench_privacy_anonymize,
]


def run_all(reps: int = 200) -> list[BenchResult]:
    results = []
    for fn in _ALL_BENCHES:
        r = fn(reps)
        results.append(r)
    return results


# ── pytest integration ────────────────────────────────────────────────────────

import pytest  # noqa: E402 — after stub injection

QUICK_REPS = 50
FULL_REPS = 200


@pytest.mark.parametrize(
    "bench_fn,max_p99_ms",
    [
        (bench_preprocessor, 1.0),
        (bench_preprocessor_large, 5.0),
        (bench_audio_buffer_push, 0.5),
        (bench_audio_buffer_drain, 10.0),
        (bench_mock_vad_silence, 0.5),
        (bench_mock_vad_emit, 1.0),
        (bench_mock_stt, 1.0),
        (bench_mock_stt_with_block, 35.0),  # 20 ms block + overhead
        (bench_mock_diarizer, 1.0),
        (bench_mock_wake_word, 0.5),
        (bench_end_to_end_stt_only, 5.0),
        (bench_end_to_end_with_diarizer, 5.0),
        (bench_end_to_end_with_wake_word, 5.0),
        (bench_privacy_anonymize, 3.0),
    ],
)
def test_bench_latency(bench_fn, max_p99_ms):
    """Each benchmark must stay under its p99 budget (quick mode)."""
    result = bench_fn(QUICK_REPS)
    print(f"\n  {result.name}: p99={result.p99_ms():.3f} ms  (budget={max_p99_ms} ms)")
    assert (
        result.p99_ms() <= max_p99_ms
    ), f"{result.name} p99={result.p99_ms():.3f} ms exceeds budget {max_p99_ms} ms"


# ── CLI entry point ───────────────────────────────────────────────────────────


def _cli() -> None:
    parser = argparse.ArgumentParser(description="bonbon_speech latency benchmarks")
    parser.add_argument(
        "--quick", action="store_true", help="Use reduced reps (50) for faster turnaround"
    )
    parser.add_argument("--json", action="store_true", help="Output results as JSON to stdout")
    args = parser.parse_args()

    reps = 50 if args.quick else 200
    results = run_all(reps)

    if args.json:
        print(json.dumps([r.to_dict() for r in results], indent=2))
    else:
        _print_table(results)


if __name__ == "__main__":
    _cli()
