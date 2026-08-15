"""Speech AI benchmarking: VAD, ASR, TTS.

VAD is timed against the real `bonbon_speech.vad.mock_vad.MockVAD` --
labeled honestly as a mock backend, not Silero, since Silero requires a
torch install this environment doesn't have. Timing a mock's real Python
execution is still a real measurement (of the VAD interface's own
overhead), just not representative of Silero's model-inference latency --
that distinction is stated in the returned metric's `recommendation`, not
hidden. ASR/TTS reuse `model_benchmark.benchmark_capability`.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

import bonbon_benchmarks  # noqa: F401
from bonbon_benchmarks.metrics_collector import (
    BenchmarkCategoryReport,
    BenchmarkMetric,
    MetricSampler,
)
from bonbon_benchmarks.model_benchmark import benchmark_capability

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SPEECH_SRC = _REPO_ROOT / "ros2_ws" / "src" / "bonbon_speech"
if str(_SPEECH_SRC) not in sys.path:
    sys.path.insert(0, str(_SPEECH_SRC))


def _silero_available() -> bool:
    try:
        import torch  # noqa: F401
    except ImportError:
        return False
    return True


def benchmark_vad(iterations: int = 200, board: str = "dev_sandbox") -> BenchmarkMetric:
    try:
        from bonbon_speech.vad.mock_vad import MockVAD
    except ImportError as exc:
        return BenchmarkMetric.blocked(
            metric_name="vad_decision_latency", board=board, module="vad", scenario="process_chunk",
            reason=f"bonbon_speech not importable: {exc}",
        )

    vad = MockVAD(sample_rate=16000)
    vad.load()
    vad.set_speech_pattern([True, True, False])
    chunk = np.zeros(512, dtype=np.float32)

    sampler = MetricSampler()
    import time
    for _ in range(iterations):
        started = time.perf_counter()
        vad.process_chunk(chunk)
        sampler.record((time.perf_counter() - started) * 1000.0)

    backend_note = "Silero (torch) unavailable in this environment -- timing MockVAD's own decision overhead only, not real model inference." if not _silero_available() else "MockVAD, not Silero -- swap when a real audio pipeline is available."
    return BenchmarkMetric.from_sampler(
        sampler, metric_name="vad_decision_latency", board=board, module="vad",
        scenario=f"MockVAD.process_chunk() x{iterations}", unit="ms",
        target=100.0, target_stat="p95", recommendation=backend_note,
    )


def benchmark_asr(iterations: int = 3, board: str = "dev_sandbox") -> BenchmarkMetric:
    m = benchmark_capability("asr", iterations=iterations, board=board)
    m.target, m.target_stat = 2000.0, "p95"
    m.evaluate()
    return m


def benchmark_tts_generated(iterations: int = 3, board: str = "dev_sandbox") -> BenchmarkMetric:
    m = benchmark_capability("tts", iterations=iterations, board=board)
    m.recommendation = (m.recommendation + " TTS generated-phrase latency, benchmark-and-report per brief Phase 3 (no fixed target).").strip()
    return m


def benchmark_tts_cached_phrase(board: str = "dev_sandbox") -> BenchmarkMetric:
    """Cached-phrase playback is file I/O + audio-device write, not model
    inference -- distinct concern from benchmark_tts_generated. No audio
    device exists in this environment, so this is honestly BLOCKED here
    rather than timing a no-op."""
    return BenchmarkMetric.blocked(
        metric_name="tts_cached_phrase_latency", board=board, module="tts", scenario="cached WAV playback start",
        reason="no audio output device in this environment",
        recommendation="Measure time-to-first-audio-sample on the real Pi speaker output.",
    )


def run_all(board: str = "dev_sandbox") -> BenchmarkCategoryReport:
    report = BenchmarkCategoryReport(category="speech_ai")
    report.add(benchmark_vad(board=board))
    report.add(benchmark_asr(board=board))
    report.add(benchmark_tts_generated(board=board))
    report.add(benchmark_tts_cached_phrase(board=board))
    return report
