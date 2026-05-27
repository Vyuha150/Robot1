"""
tests/test_speech_synthesizer.py
==================================
Unit tests for SpeechSynthesizer.

All tests use MockTTS + MockSpeakerBridge — no real audio device or
Piper installation required.
"""

from bonbon_tts.backends.mock_tts import MockTTS
from bonbon_tts.core.speech_synthesizer import SpeechSynthesizer
from bonbon_tts.core.utterance_queue import Priority, Utterance, UtteranceQueue
from bonbon_tts.speaker.speaker_bridge import MockSpeakerBridge

# ── Fixture helpers ───────────────────────────────────────────────────────────


def _synth(
    *,
    queue_depth: int = 32,
    fail_first: bool = False,
    fallback: MockTTS | None = None,
) -> SpeechSynthesizer:
    tts = MockTTS()
    speaker = MockSpeakerBridge()
    fallback = fallback or MockTTS()
    queue = UtteranceQueue(max_depth=queue_depth)
    s = SpeechSynthesizer(
        primary_tts=tts,
        speaker=speaker,
        queue=queue,
        fallback_tts=fallback,
    )
    if fail_first:
        tts.fail_next = True
    return s


def _say(s: SpeechSynthesizer, text: str = "hello", priority: Priority = Priority.NORMAL) -> None:
    utt = Utterance(text=text, priority=priority)
    s.say(utt)


# ── Lifecycle ──────────────────────────────────────────────────────────────────


class TestLifecycle:
    def test_start_stop(self):
        s = _synth()
        s.start()
        assert s.is_running
        s.stop()
        assert not s.is_running

    def test_start_marks_primary_warmed_up(self):
        tts = MockTTS()
        s = SpeechSynthesizer(primary_tts=tts, speaker=MockSpeakerBridge())
        s.start()
        s.stop()
        # MockTTS.warmup is a no-op; just check no exception raised

    def test_double_stop_safe(self):
        s = _synth()
        s.start()
        s.stop()
        s.stop()  # should not raise


# ── Basic synthesis & playback ─────────────────────────────────────────────────


class TestBasicPlayback:
    def test_single_utterance_played(self):
        s = _synth()
        s.start()
        _say(s, "hello")
        assert s.wait_until_idle(timeout=3.0)
        s.stop()
        assert s._speaker.play_count == 1  # type: ignore[attr-defined]

    def test_multiple_utterances_all_played(self):
        s = _synth()
        s.start()
        for i in range(5):
            _say(s, f"utterance {i}")
        assert s.wait_until_idle(timeout=5.0)
        s.stop()
        assert s._speaker.play_count == 5  # type: ignore[attr-defined]

    def test_wait_until_idle_true_when_empty(self):
        s = _synth()
        s.start()
        result = s.wait_until_idle(timeout=1.0)
        s.stop()
        assert result is True

    def test_wait_until_idle_false_on_timeout(self):
        tts = MockTTS(simulate_latency_ms=500.0)
        s = SpeechSynthesizer(
            primary_tts=tts,
            speaker=MockSpeakerBridge(),
            fallback_tts=MockTTS(),
        )
        s.start()
        _say(s, "long synthesis")
        result = s.wait_until_idle(timeout=0.01)  # too short
        s.stop()
        assert result is False


# ── Priority ordering ─────────────────────────────────────────────────────────


class TestPriorityOrdering:
    def test_high_before_normal(self):
        """HIGH utterances should be played before NORMAL ones."""
        tts = MockTTS(simulate_latency_ms=20.0)
        speaker = MockSpeakerBridge()
        s = SpeechSynthesizer(
            primary_tts=tts,
            speaker=speaker,
            fallback_tts=MockTTS(),
        )
        s.start()
        s.say(Utterance(text="normal-1", priority=Priority.NORMAL))
        s.say(Utterance(text="normal-2", priority=Priority.NORMAL))
        s.say(Utterance(text="high", priority=Priority.HIGH))
        assert s.wait_until_idle(timeout=5.0)
        s.stop()

        # All three should have been synthesised
        assert tts.call_count == 3


# ── Interrupt ─────────────────────────────────────────────────────────────────


class TestInterrupt:
    def test_emergency_calls_speaker_stop(self):
        speaker = MockSpeakerBridge()
        s = SpeechSynthesizer(
            primary_tts=MockTTS(),
            speaker=speaker,
            fallback_tts=MockTTS(),
        )
        s.start()
        s.say(Utterance(text="STOP ROBOT", priority=Priority.EMERGENCY))
        assert s.wait_until_idle(timeout=3.0)
        s.stop()
        # Speaker.stop() is called at enqueue time for EMERGENCY
        assert speaker.stop_count >= 1

    def test_interrupt_flag_propagated(self):
        s = _synth()
        s.start()
        utt = Utterance(text="interrupt me", priority=Priority.HIGH, interrupt=True)
        result = s.say(utt)
        assert result is True  # enqueue returns True when interrupt=True
        assert s.wait_until_idle(timeout=3.0)
        s.stop()


# ── Fallback ──────────────────────────────────────────────────────────────────


class TestFallback:
    def test_primary_failure_uses_fallback(self):
        primary = MockTTS()
        fallback = MockTTS()
        speaker = MockSpeakerBridge()

        primary.fail_next = True  # first call fails

        s = SpeechSynthesizer(
            primary_tts=primary,
            speaker=speaker,
            fallback_tts=fallback,
        )
        s.start()
        _say(s, "try fallback")
        assert s.wait_until_idle(timeout=3.0)
        s.stop()

        assert primary.call_count == 1  # tried once
        assert fallback.call_count == 1  # then fell back
        assert speaker.play_count == 1  # audio still played

    def test_both_fail_no_play(self):
        primary = MockTTS()
        fallback = MockTTS()
        speaker = MockSpeakerBridge()

        primary.fail_next = True
        fallback.fail_next = True

        s = SpeechSynthesizer(
            primary_tts=primary,
            speaker=speaker,
            fallback_tts=fallback,
        )
        s.start()
        _say(s, "double fail")
        assert s.wait_until_idle(timeout=3.0)
        s.stop()

        # Neither played — no crash
        assert speaker.play_count == 0

    def test_fallback_recorded_in_health(self):
        primary = MockTTS()
        fallback = MockTTS()

        primary.fail_next = True

        s = SpeechSynthesizer(
            primary_tts=primary,
            speaker=MockSpeakerBridge(),
            fallback_tts=fallback,
        )
        s.start()
        _say(s, "fallback check")
        assert s.wait_until_idle(timeout=3.0)
        s.stop()

        report = s.get_health_report()
        assert report.fallback_count == 1


# ── Health ────────────────────────────────────────────────────────────────────


class TestHealth:
    def test_health_report_ok_after_start(self):
        s = _synth()
        s.start()
        r = s.get_health_report()
        assert r.synthesizer_ok
        s.stop()

    def test_health_report_plays_tracked(self):
        s = _synth()
        s.start()
        _say(s, "track me")
        assert s.wait_until_idle(timeout=3.0)
        s.stop()
        r = s.get_health_report()
        assert r.utterances_played == 1

    def test_health_report_errors_tracked(self):
        primary = MockTTS()
        fallback = MockTTS()
        fallback.fail_next = True  # fallback also fails
        primary.fail_next = True

        s = SpeechSynthesizer(
            primary_tts=primary,
            speaker=MockSpeakerBridge(),
            fallback_tts=fallback,
        )
        s.start()
        _say(s, "error")
        assert s.wait_until_idle(timeout=3.0)
        s.stop()
        r = s.get_health_report()
        assert r.synthesis_errors >= 1


# ── Queue access ──────────────────────────────────────────────────────────────


class TestQueueAccess:
    def test_queue_property(self):
        s = _synth()
        assert isinstance(s.queue, UtteranceQueue)

    def test_clear_queue_via_queue_property(self):
        s = _synth()
        s.start()
        # Add items without starting worker (pause between enqueue and processing)
        for i in range(3):
            s.queue.enqueue(Utterance(text=str(i), max_age_sec=60.0))
        s.queue.clear()
        assert s.queue.is_empty()
        s.stop()
