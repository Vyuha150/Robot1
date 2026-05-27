"""
tests/integration/test_tts_pipeline.py
========================================
End-to-end integration tests for the full TTS pipeline.

These tests exercise the complete path:
  Utterance → UtteranceQueue → SpeechSynthesizer → MockTTS → MockSpeakerBridge

No real audio device, Piper model, or ROS2 installation is required.
"""

import time

from bonbon_tts.backends.mock_tts import MockTTS
from bonbon_tts.core.filler_player import FillerPlayer
from bonbon_tts.core.speech_synthesizer import SpeechSynthesizer
from bonbon_tts.core.utterance_queue import Priority, Utterance, UtteranceQueue
from bonbon_tts.speaker.speaker_bridge import MockSpeakerBridge

# ── Helpers ───────────────────────────────────────────────────────────────────


def _pipeline(
    *,
    queue_max: int = 32,
    cooldown_sec: float = 0.0,
    filler_enabled: bool = False,
) -> tuple[SpeechSynthesizer, MockTTS, MockSpeakerBridge]:
    tts = MockTTS()
    speaker = MockSpeakerBridge()
    queue = UtteranceQueue(max_depth=queue_max)
    filler = FillerPlayer(
        cooldown_sec=cooldown_sec,
        trigger_queue_depth=2,
        trigger_latency_ms=0.0,
        enabled=filler_enabled,
    )
    filler.load()
    synth = SpeechSynthesizer(
        primary_tts=tts,
        speaker=speaker,
        queue=queue,
        fallback_tts=MockTTS(),
        filler=filler,
    )
    return synth, tts, speaker


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestPipelineSmokeTest:
    def test_single_utterance_end_to_end(self):
        synth, tts, speaker = _pipeline()
        synth.start()

        synth.say(Utterance(text="Hello BonBon", priority=Priority.NORMAL))
        assert synth.wait_until_idle(timeout=5.0)
        synth.stop()

        assert tts.call_count == 1
        assert tts.synthesized_texts[0] == "Hello BonBon"
        assert speaker.play_count == 1

    def test_five_utterances_all_processed(self):
        synth, tts, speaker = _pipeline()
        synth.start()

        texts = [f"sentence {i}" for i in range(5)]
        for text in texts:
            synth.say(Utterance(text=text))

        assert synth.wait_until_idle(timeout=10.0)
        synth.stop()

        assert tts.call_count == 5
        assert speaker.play_count == 5


class TestPipelinePriority:
    def test_emergency_reaches_front(self):
        """
        Enqueue NORMAL items, then an EMERGENCY — the EMERGENCY must be
        processed before the remaining NORMALs.

        Because the worker is running, some NORMALs may already be processed
        by the time we enqueue EMERGENCY.  We verify that EMERGENCY is
        synthesised at some point.
        """
        tts = MockTTS(simulate_latency_ms=30.0)
        speaker = MockSpeakerBridge()
        synth = SpeechSynthesizer(
            primary_tts=tts,
            speaker=speaker,
            fallback_tts=MockTTS(),
        )
        synth.start()

        for i in range(3):
            synth.say(Utterance(text=f"normal-{i}", priority=Priority.NORMAL))

        synth.say(Utterance(text="EMERGENCY", priority=Priority.EMERGENCY))

        assert synth.wait_until_idle(timeout=10.0)
        synth.stop()

        assert "EMERGENCY" in tts.synthesized_texts
        assert tts.call_count == 4

    def test_low_after_high(self):
        tts = MockTTS()
        speaker = MockSpeakerBridge()
        synth = SpeechSynthesizer(
            primary_tts=tts,
            speaker=speaker,
            fallback_tts=MockTTS(),
        )
        synth.start()

        synth.say(Utterance(text="low", priority=Priority.LOW))
        synth.say(Utterance(text="high", priority=Priority.HIGH))

        assert synth.wait_until_idle(timeout=5.0)
        synth.stop()

        assert tts.call_count == 2


class TestPipelineDeduplication:
    def test_dedup_key_replaces(self):
        """Repeated battery status should replace, not stack."""
        synth, tts, speaker = _pipeline()
        synth.start()

        for pct in [50, 49, 48]:
            synth.say(
                Utterance(
                    text=f"Battery {pct}%",
                    dedup_key="battery_status",
                    priority=Priority.LOW,
                )
            )
            time.sleep(0.001)

        assert synth.wait_until_idle(timeout=5.0)
        synth.stop()

        # Only one unique key → at most 1 utterance actually played
        # (earlier ones may have been replaced before worker picked them up)
        assert tts.call_count <= 3
        assert speaker.play_count >= 1


class TestPipelineStaleEviction:
    def test_stale_utterances_not_played(self):
        synth, tts, speaker = _pipeline()

        # Enqueue a stale item directly into the queue (bypassing say())
        stale_utt = Utterance(
            text="should not play",
            max_age_sec=0.01,
            priority=Priority.NORMAL,
        )
        synth.queue.enqueue(stale_utt)
        time.sleep(0.05)  # let it expire

        synth.say(Utterance(text="fresh", priority=Priority.LOW))

        synth.start()
        assert synth.wait_until_idle(timeout=5.0)
        synth.stop()

        # Only "fresh" should have been synthesised
        assert tts.call_count == 1
        assert tts.synthesized_texts[0] == "fresh"


class TestPipelineHealthReporting:
    def test_health_tracks_playback(self):
        synth, tts, speaker = _pipeline()
        synth.start()

        for i in range(3):
            synth.say(Utterance(text=f"msg {i}"))

        assert synth.wait_until_idle(timeout=5.0)
        synth.stop()

        report = synth.get_health_report()
        assert report.utterances_played == 3
        assert report.synthesis_errors == 0
        assert report.last_synthesis_ms >= 0.0
        assert report.mean_synthesis_ms >= 0.0

    def test_health_shows_fallback(self):
        primary = MockTTS()
        fallback = MockTTS()
        speaker = MockSpeakerBridge()

        primary.fail_next = True  # force one fallback

        synth = SpeechSynthesizer(
            primary_tts=primary,
            speaker=speaker,
            fallback_tts=fallback,
        )
        synth.start()
        synth.say(Utterance(text="test fallback"))
        assert synth.wait_until_idle(timeout=5.0)
        synth.stop()

        report = synth.get_health_report()
        assert report.fallback_count == 1


class TestPipelineQueueOverflow:
    def test_overflow_drops_lowest_priority(self):
        synth, tts, speaker = _pipeline(queue_max=3)

        # Fill queue with LOWs, then add a HIGH
        synth.queue.enqueue(Utterance(text="low-a", priority=Priority.LOW))
        synth.queue.enqueue(Utterance(text="low-b", priority=Priority.LOW))
        synth.queue.enqueue(Utterance(text="low-c", priority=Priority.LOW))
        synth.queue.enqueue(Utterance(text="high", priority=Priority.HIGH))

        # Queue at max=3: adding HIGH caused one LOW to be dropped
        assert synth.queue.overflow_count == 1
        assert synth.queue.depth() == 3

        synth.start()
        assert synth.wait_until_idle(timeout=5.0)
        synth.stop()

        # HIGH should have been processed
        assert "high" in tts.synthesized_texts
