"""
tests/test_tts_health.py
=========================
Unit tests for TTSHealthTracker and TTSHealthReport.
"""
import time

import pytest

from bonbon_tts.core.tts_health import TTSHealthReport, TTSHealthTracker


class TestTTSHealthReport:
    def _report(self, **kwargs) -> TTSHealthReport:
        defaults = dict(
            synthesizer_ok    = True,
            speaker_ok        = True,
            backend           = "piper",
            queue_depth       = 0,
            queue_overflows   = 0,
            last_synthesis_ms = 100.0,
            mean_synthesis_ms = 110.0,
            p95_synthesis_ms  = 180.0,
            synthesis_errors  = 0,
            fallback_count    = 0,
            utterances_played = 5,
            total_audio_sec   = 12.0,
            uptime_sec        = 60.0,
            timestamp         = time.monotonic(),
        )
        defaults.update(kwargs)
        return TTSHealthReport(**defaults)

    def test_healthy_when_all_ok(self):
        r = self._report()
        assert r.is_healthy is True

    def test_unhealthy_when_synth_down(self):
        r = self._report(synthesizer_ok=False)
        assert r.is_healthy is False

    def test_unhealthy_when_speaker_down(self):
        r = self._report(speaker_ok=False)
        assert r.is_healthy is False

    def test_summary_contains_backend(self):
        r = self._report(backend="mock")
        s = r.summary()
        assert "mock" in s

    def test_summary_contains_status(self):
        r = self._report()
        assert "OK" in r.summary()

    def test_summary_down_status(self):
        r = self._report(synthesizer_ok=False)
        assert "DOWN" in r.summary() or "DEGRADED" in r.summary()


class TestTTSHealthTracker:
    def test_initial_state(self):
        t = TTSHealthTracker()
        r = t.get_report(queue_depth=0, backend="mock",
                         synth_ok=True, speaker_ok=True)
        assert r.synthesis_errors  == 0
        assert r.utterances_played == 0
        assert r.mean_synthesis_ms == pytest.approx(0.0)
        assert r.uptime_sec >= 0.0

    def test_record_synthesis_success(self):
        t = TTSHealthTracker()
        t.record_synthesis(ms=120.0, success=True)
        r = t.get_report(0, "piper", True, True)
        assert r.last_synthesis_ms == pytest.approx(120.0)
        assert r.mean_synthesis_ms == pytest.approx(120.0)
        assert r.synthesis_errors  == 0

    def test_record_synthesis_failure(self):
        t = TTSHealthTracker()
        t.record_synthesis(ms=0.0, success=False)
        r = t.get_report(0, "mock", True, True)
        assert r.synthesis_errors == 1

    def test_record_fallback(self):
        t = TTSHealthTracker()
        t.record_synthesis(ms=50.0, success=True, fallback=True)
        r = t.get_report(0, "mock", True, True)
        assert r.fallback_count == 1

    def test_record_play(self):
        t = TTSHealthTracker()
        t.record_play(duration_sec=2.5)
        t.record_play(duration_sec=1.0)
        r = t.get_report(0, "piper", True, True)
        assert r.utterances_played == 2
        assert r.total_audio_sec == pytest.approx(3.5)

    def test_mean_latency_multiple_calls(self):
        t = TTSHealthTracker()
        for ms in [100.0, 200.0, 300.0]:
            t.record_synthesis(ms=ms, success=True)
        r = t.get_report(0, "piper", True, True)
        assert r.mean_synthesis_ms == pytest.approx(200.0)

    def test_p95_latency(self):
        t = TTSHealthTracker()
        # 20 samples: 19 × 100ms, 1 × 900ms
        for _ in range(19):
            t.record_synthesis(ms=100.0, success=True)
        t.record_synthesis(ms=900.0, success=True)
        r = t.get_report(0, "piper", True, True)
        # p95 should be around 900ms (top 5%)
        assert r.p95_synthesis_ms > 100.0

    def test_window_size_limit(self):
        t = TTSHealthTracker(window_size=5)
        for ms in range(10):
            t.record_synthesis(ms=float(ms * 10), success=True)
        r = t.get_report(0, "piper", True, True)
        # Only last 5 samples kept (50, 60, 70, 80, 90 ms)
        assert r.mean_synthesis_ms == pytest.approx(70.0)

    def test_queue_overflow(self):
        t = TTSHealthTracker()
        t.record_queue_overflow()
        t.record_queue_overflow()
        r = t.get_report(queue_depth=0, backend="mock",
                         synth_ok=True, speaker_ok=True)
        assert r.queue_overflows == 2

    def test_queue_depth_in_report(self):
        t = TTSHealthTracker()
        r = t.get_report(queue_depth=7, backend="piper",
                         synth_ok=True, speaker_ok=True)
        assert r.queue_depth == 7

    def test_reset_clears_state(self):
        t = TTSHealthTracker()
        t.record_synthesis(ms=100.0, success=True)
        t.record_play(duration_sec=2.0)
        t.reset()
        r = t.get_report(0, "mock", True, True)
        assert r.utterances_played == 0
        assert r.mean_synthesis_ms == pytest.approx(0.0)
        assert r.synthesis_errors  == 0

    def test_uptime_increases(self):
        t = TTSHealthTracker()
        r1 = t.get_report(0, "mock", True, True)
        time.sleep(0.05)
        r2 = t.get_report(0, "mock", True, True)
        assert r2.uptime_sec > r1.uptime_sec

    def test_backend_and_flags_pass_through(self):
        t = TTSHealthTracker()
        r = t.get_report(queue_depth=3, backend="piper",
                         synth_ok=False, speaker_ok=True)
        assert r.backend        == "piper"
        assert r.synthesizer_ok is False
        assert r.speaker_ok     is True
        assert r.queue_depth    == 3
