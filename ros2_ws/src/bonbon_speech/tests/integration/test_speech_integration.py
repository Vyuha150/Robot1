"""
Integration tests: full wired speech pipeline without ROS2.

Exercises the real component chain:
  AudioBuffer → AudioPreprocessor → MockVAD → MockSTT → MockDiarizer
  → SpeechNode._process_segment()

No ROS2 stubs needed for the pipeline itself; only SpeechNode is tested
at the call level (not via on_configure / ROS2 pub/sub).
"""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import numpy as np
import pytest

# ── Minimal ROS2 stubs (same as test_speech_node.py) ────────────────────────


def _inject_stubs():
    if "rclpy" in sys.modules:
        return

    rclpy_mod = types.ModuleType("rclpy")
    rclpy_mod.init = lambda args=None: None
    rclpy_mod.spin = lambda node: None
    rclpy_mod.shutdown = lambda: None

    lifecycle_mod = types.ModuleType("rclpy.lifecycle")
    lifecycle_mod.TransitionCallbackReturn = type(
        "TransitionCallbackReturn", (), {"SUCCESS": "s", "FAILURE": "f"}
    )
    lifecycle_mod.State = type("State", (), {})

    class FakeLifecycleNode:
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

        def get_parameter(self, name):
            class _P:
                value = None

            return _P()

        def declare_parameter(self, *a, **kw):
            pass

        def destroy_node(self):
            pass

    lifecycle_mod.LifecycleNode = FakeLifecycleNode

    qos_mod = types.ModuleType("rclpy.qos")
    qos_mod.QoSProfile = type("QoSProfile", (), {"__init__": lambda s, **kw: None})
    qos_mod.ReliabilityPolicy = type("ReliabilityPolicy", (), {"RELIABLE": 1, "BEST_EFFORT": 0})
    qos_mod.HistoryPolicy = type("HistoryPolicy", (), {"KEEP_LAST": 1})
    rclpy_mod.lifecycle = lifecycle_mod
    rclpy_mod.qos = qos_mod

    bm_mod = types.ModuleType("bonbon_msgs")
    bm_msg_mod = types.ModuleType("bonbon_msgs.msg")

    def _msg(name, **fields):
        return type(name, (), {"__init__": lambda s: s.__dict__.update(fields)})

    bm_msg_mod.AudioChunk = _msg(
        "AudioChunk", data=[], sample_rate=16000, header=None, doa_angle_deg=0.0
    )
    bm_msg_mod.SpeechCommand = _msg(
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
    bm_msg_mod.SpeechTranscription = _msg(
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
    bm_msg_mod.ModuleHealth = _msg(
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

    bm_mod.msg = bm_msg_mod
    for k, v in [
        ("rclpy", rclpy_mod),
        ("rclpy.lifecycle", lifecycle_mod),
        ("rclpy.qos", qos_mod),
        ("bonbon_msgs", bm_mod),
        ("bonbon_msgs.msg", bm_msg_mod),
    ]:
        sys.modules.setdefault(k, v)


_inject_stubs()

from bonbon_speech.audio.audio_buffer import AudioBuffer
from bonbon_speech.audio.audio_preprocessor import AudioPreprocessor, PreprocessorConfig
from bonbon_speech.config.speech_config import SpeechConfig
from bonbon_speech.diarization.mock_diarizer import DiarizationResult, MockDiarizer, SpeakerSegment
from bonbon_speech.nodes.speech_node import SpeechNode
from bonbon_speech.stt.base_stt import TranscriptionResult
from bonbon_speech.stt.mock_stt import MockSTT
from bonbon_speech.vad.mock_vad import MockVAD


def wired_node(cfg: SpeechConfig = None) -> SpeechNode:
    """Return a SpeechNode with fully wired mock pipeline."""
    if cfg is None:
        cfg = SpeechConfig()
    node = SpeechNode("integration_test_node")
    node._cfg = cfg
    node._buf = AudioBuffer(16000, 30.0, 0.5)
    node._preproc = AudioPreprocessor(PreprocessorConfig())
    node._vad = MockVAD(sample_rate=16000)
    node._vad.load()
    node._stt = MockSTT(cfg.stt)
    node._stt.load()
    node._diarizer = None
    node._ww = None
    node._pipeline_ok = True
    node._pub_command = MagicMock()
    node._pub_transcription = MagicMock()
    node._pub_health = MagicMock()
    return node


def audio_msg(samples=None):
    from bonbon_msgs.msg import AudioChunk

    msg = AudioChunk()
    msg.data = (samples if samples is not None else np.zeros(512, dtype=np.float32)).tolist()
    msg.header = None
    msg.doa_angle_deg = 0.0
    return msg


# ── Basic pipeline flow ───────────────────────────────────────────────────────


class TestBasicFlow:
    def test_silence_does_not_publish(self):
        node = wired_node()
        for _ in range(10):
            node._on_audio_chunk(audio_msg())
        node._pub_command.publish.assert_not_called()

    def test_speech_segment_publishes_command(self):
        node = wired_node()
        node._stt.set_responses(
            [TranscriptionResult(text="hello bonbon", language="en", confidence=0.9)]
        )
        node._vad.force_next_emit(samples=np.zeros(8000, dtype=np.float32))
        node._on_audio_chunk(audio_msg())
        node._pub_command.publish.assert_called_once()
        msg = node._pub_command.publish.call_args[0][0]
        assert msg.text == "hello bonbon"
        assert msg.confidence == pytest.approx(0.9)

    def test_multiple_utterances_published(self):
        node = wired_node()
        for _i in range(3):
            node._vad.force_next_emit(samples=np.zeros(8000, dtype=np.float32))
            node._on_audio_chunk(audio_msg())
        assert node._pub_command.publish.call_count == 3

    def test_buffer_accumulates_between_speech(self):
        node = wired_node()
        for _ in range(5):
            node._on_audio_chunk(audio_msg(np.zeros(512, dtype=np.float32)))
        assert node._buf.available() > 0


# ── Confidence fallback ───────────────────────────────────────────────────────


class TestConfidenceFallback:
    def test_low_confidence_published_with_flag(self):
        node = wired_node()
        node._stt.set_responses(
            [TranscriptionResult(text="mumble", confidence=0.2, is_low_confidence=True)]
        )
        node._vad.force_next_emit(samples=np.zeros(8000, dtype=np.float32))
        node._on_audio_chunk(audio_msg())
        msg = node._pub_command.publish.call_args[0][0]
        assert msg.is_low_confidence is True

    def test_silence_result_published_as_silence(self):
        node = wired_node()
        node._stt.set_responses([TranscriptionResult(is_silence=True)])
        node._vad.force_next_emit(samples=np.zeros(8000, dtype=np.float32))
        node._on_audio_chunk(audio_msg())
        msg = node._pub_command.publish.call_args[0][0]
        assert msg.is_silence is True


# ── Force-cut propagation ─────────────────────────────────────────────────────


class TestForceCut:
    def test_force_cut_segment_still_transcribed(self):
        node = wired_node()
        node._vad.force_next_emit(samples=np.zeros(8000, dtype=np.float32), force_cut=True)
        node._on_audio_chunk(audio_msg())
        node._pub_command.publish.assert_called_once()


# ── Diarization pipeline ──────────────────────────────────────────────────────


class TestDiarizationPipeline:
    def test_diarizer_called_per_segment(self):
        node = wired_node()
        node._diarizer = MockDiarizer()
        node._diarizer.load()
        for _ in range(3):
            node._vad.force_next_emit(samples=np.zeros(8000, dtype=np.float32))
            node._on_audio_chunk(audio_msg())
        assert node._diarizer.call_count == 3

    def test_dominant_speaker_in_command(self):
        node = wired_node()
        node._diarizer = MockDiarizer(
            responses=[
                DiarizationResult(
                    dominant_speaker="SPEAKER_01",
                    all_speaker_ids=["SPEAKER_01"],
                )
            ]
        )
        node._diarizer.load()
        node._vad.force_next_emit(samples=np.zeros(8000, dtype=np.float32))
        node._on_audio_chunk(audio_msg())
        msg = node._pub_command.publish.call_args[0][0]
        assert msg.speaker_id == "SPEAKER_01"

    def test_diarization_timeout_fallback_speaker(self):
        node = wired_node()
        node._diarizer = MockDiarizer(responses=[DiarizationResult(is_timeout=True)])
        node._diarizer.load()
        node._vad.force_next_emit(samples=np.zeros(8000, dtype=np.float32))
        node._on_audio_chunk(audio_msg())
        msg = node._pub_command.publish.call_args[0][0]
        # Timeout → fallback to SPEAKER_00
        assert msg.speaker_id == "SPEAKER_00"


# ── Privacy mode ─────────────────────────────────────────────────────────────


class TestPrivacyMode:
    def test_anonymize_speaker_replaces_id(self):
        cfg = SpeechConfig()
        cfg.privacy.anonymize_speaker = True
        node = wired_node(cfg)
        node._diarizer = MockDiarizer()
        node._diarizer.load()
        node._vad.force_next_emit(samples=np.zeros(8000, dtype=np.float32))
        node._on_audio_chunk(audio_msg())
        msg = node._pub_command.publish.call_args[0][0]
        assert msg.speaker_id == "SPEAKER_ANON"


# ── Noisy environment ─────────────────────────────────────────────────────────


class TestNoisyEnvironment:
    def test_noisy_silence_no_publish(self):
        """Low-amplitude noise passes through preprocessor but VAD stays silent."""
        node = wired_node()
        rng = np.random.default_rng(99)
        for _ in range(20):
            noisy = (rng.standard_normal(512) * 0.005).astype(np.float32)
            node._on_audio_chunk(audio_msg(noisy))
        node._pub_command.publish.assert_not_called()


# ── STT timeout inside pipeline ───────────────────────────────────────────────


class TestSTTTimeoutInPipeline:
    def test_timeout_result_published(self):
        node = wired_node()
        # Block STT longer than timeout
        cfg = SpeechConfig()
        cfg.stt.inference_timeout_sec = 0.05
        cfg.stt.max_consecutive_timeouts = 10
        node._cfg = cfg
        node._stt = MockSTT(cfg.stt, block_sec=0.3)
        node._stt.load()
        node._vad.force_next_emit(samples=np.zeros(8000, dtype=np.float32))
        node._on_audio_chunk(audio_msg())
        msg = node._pub_command.publish.call_args[0][0]
        assert msg.is_timeout is True

    def test_degraded_after_max_timeouts(self):
        cfg = SpeechConfig()
        cfg.stt.inference_timeout_sec = 0.05
        cfg.stt.max_consecutive_timeouts = 2
        node = wired_node(cfg)
        node._stt = MockSTT(cfg.stt, block_sec=0.3)
        node._stt.load()
        for _ in range(2):
            node._vad.force_next_emit(samples=np.zeros(8000, dtype=np.float32))
            node._on_audio_chunk(audio_msg())
        assert node._stt.is_degraded


# ── Multi-speaker integration ─────────────────────────────────────────────────


class TestMultiSpeakerIntegration:
    def test_two_speakers_alternate(self):
        node = wired_node()
        speakers = ["SPEAKER_00", "SPEAKER_01"]
        responses = [
            DiarizationResult(
                segments=[SpeakerSegment(s, 0.0, 1.0)],
                dominant_speaker=s,
                all_speaker_ids=[s],
            )
            for s in speakers
        ]
        node._diarizer = MockDiarizer(responses=responses)
        node._diarizer.load()

        results = []
        for _ in range(2):
            node._vad.force_next_emit(samples=np.zeros(8000, dtype=np.float32))
            node._on_audio_chunk(audio_msg())
            results.append(node._pub_command.publish.call_args[0][0].speaker_id)

        assert results[0] == "SPEAKER_00"
        assert results[1] == "SPEAKER_01"
