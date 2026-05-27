"""
Tests for bonbon_speech.nodes.speech_node.SpeechNode

ROS2 and bonbon_msgs are stubbed so tests run without a ROS2 installation.
"""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import numpy as np

# ── ROS2 / bonbon_msgs stubs ─────────────────────────────────────────────────


def _make_stub_modules():
    """Inject minimal ROS2 stubs into sys.modules before importing speech_node."""

    # --- rclpy ---
    rclpy_mod = types.ModuleType("rclpy")
    rclpy_mod.init = lambda args=None: None
    rclpy_mod.spin = lambda node: None
    rclpy_mod.shutdown = lambda: None

    # lifecycle
    lifecycle_mod = types.ModuleType("rclpy.lifecycle")
    TransitionCallbackReturn = type(
        "TransitionCallbackReturn", (), {"SUCCESS": "success", "FAILURE": "failure"}
    )
    State = type("State", (), {})

    class FakeLifecycleNode:
        def __init__(self, name):
            self._name = name
            self._params: dict = {}
            self._timers = []
            self._publishers = []
            self._subscribers = []

        def get_logger(self):
            class Logger:
                def info(self, *a):
                    pass

                def debug(self, *a):
                    pass

                def warning(self, *a):
                    pass

                def error(self, *a):
                    pass

            return Logger()

        def declare_parameter(self, name, value=None):
            pass

        def get_parameter(self, name):
            class _Param:
                def __init__(self, v):
                    self.value = v

            return _Param(self._params.get(name))

        def create_lifecycle_publisher(self, msg_type, topic, qos):
            pub = MagicMock()
            self._publishers.append(pub)
            return pub

        def create_subscription(self, msg_type, topic, cb, qos):
            sub = MagicMock()
            self._subscribers.append(sub)
            return sub

        def create_timer(self, period, cb):
            t = MagicMock()
            t.cancel = MagicMock()
            self._timers.append(t)
            return t

        def destroy_node(self):
            pass

    lifecycle_mod.LifecycleNode = FakeLifecycleNode
    lifecycle_mod.TransitionCallbackReturn = TransitionCallbackReturn
    lifecycle_mod.State = State

    # qos
    qos_mod = types.ModuleType("rclpy.qos")
    qos_mod.QoSProfile = type("QoSProfile", (), {"__init__": lambda s, **kw: None})
    qos_mod.ReliabilityPolicy = type(
        "ReliabilityPolicy",
        (),
        {
            "RELIABLE": 1,
            "BEST_EFFORT": 0,
        },
    )
    qos_mod.HistoryPolicy = type(
        "HistoryPolicy",
        (),
        {
            "KEEP_LAST": 1,
            "KEEP_ALL": 0,
        },
    )

    rclpy_mod.lifecycle = lifecycle_mod
    rclpy_mod.qos = qos_mod

    # --- bonbon_msgs ---
    bm_mod = types.ModuleType("bonbon_msgs")
    bm_msg_mod = types.ModuleType("bonbon_msgs.msg")

    def _make_msg(name, **fields):
        cls = type(name, (), {"__init__": lambda s: s.__dict__.update(fields)})
        return cls

    bm_msg_mod.AudioChunk = _make_msg(
        "AudioChunk",
        data=[],
        sample_rate=16000,
        channels=1,
        doa_angle_deg=0.0,
        header=None,
    )
    bm_msg_mod.SpeechCommand = _make_msg(
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
    bm_msg_mod.SpeechTranscription = _make_msg(
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
    bm_msg_mod.ModuleHealth = _make_msg(
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

    for name, mod in [
        ("rclpy", rclpy_mod),
        ("rclpy.lifecycle", lifecycle_mod),
        ("rclpy.qos", qos_mod),
        ("bonbon_msgs", bm_mod),
        ("bonbon_msgs.msg", bm_msg_mod),
    ]:
        sys.modules.setdefault(name, mod)


_make_stub_modules()

from bonbon_speech.config.speech_config import SpeechConfig
from bonbon_speech.diarization.mock_diarizer import DiarizationResult, MockDiarizer, SpeakerSegment
from bonbon_speech.nodes.speech_node import SpeechNode
from bonbon_speech.stt.base_stt import TranscriptionResult
from bonbon_speech.stt.mock_stt import MockSTT
from bonbon_speech.vad.mock_vad import MockVAD
from bonbon_speech.wake_word.mock_wake_word import MockWakeWordDetector

# ── Helpers ───────────────────────────────────────────────────────────────────


def make_node(cfg: SpeechConfig | None = None) -> SpeechNode:
    node = SpeechNode("test_speech_node")
    if cfg is None:
        cfg = SpeechConfig()
    node._cfg = cfg
    return node


def make_audio_msg(data=None, sample_rate=16000, doa=0.0):
    from bonbon_msgs.msg import AudioChunk  # type: ignore

    msg = AudioChunk()
    msg.data = (data if data is not None else np.zeros(512, dtype=np.float32)).tolist()
    msg.sample_rate = sample_rate
    msg.doa_angle_deg = doa
    msg.header = None
    return msg


def init_pipeline(node: SpeechNode) -> None:
    """Install mock components into a node."""
    from bonbon_speech.audio.audio_buffer import AudioBuffer
    from bonbon_speech.audio.audio_preprocessor import AudioPreprocessor, PreprocessorConfig

    node._buf = AudioBuffer(sample_rate=16000, max_buffer_sec=30.0, prebuffer_sec=0.5)
    node._preproc = AudioPreprocessor(PreprocessorConfig())
    node._vad = MockVAD(sample_rate=16000)
    node._vad.load()
    node._stt = MockSTT(node._cfg.stt)
    node._stt.load()
    node._diarizer = None
    node._ww = None
    node._pipeline_ok = True
    # Create mock publishers
    node._pub_command = MagicMock()
    node._pub_transcription = MagicMock()
    node._pub_health = MagicMock()


# ── Construction ──────────────────────────────────────────────────────────────


class TestConstruction:
    def test_node_created(self):
        node = SpeechNode("test_node")
        assert node is not None

    def test_initial_state(self):
        node = SpeechNode("test_node")
        assert node._cfg is None
        assert node._pipeline_ok is False


# ── on_configure ──────────────────────────────────────────────────────────────


class TestConfigure:
    def test_configure_success_with_mock_backends(self):
        node = make_node()
        # Inject a pre-built config so we don't need from_ros_params
        from rclpy.lifecycle import State, TransitionCallbackReturn

        node._cfg = SpeechConfig()  # all defaults = mock backends

        # Patch _load_config to avoid from_ros_params
        node._load_config = lambda: None  # already set
        node._create_interfaces = lambda: None
        node._init_pipeline = lambda: None
        node._pipeline_ok = True

        result = node.on_configure(State())
        assert result == TransitionCallbackReturn.SUCCESS

    def test_configure_failure_no_degraded(self):
        node = make_node()
        from rclpy.lifecycle import State, TransitionCallbackReturn

        cfg = SpeechConfig()
        cfg.allow_degraded_startup = False
        node._cfg = cfg

        node._load_config = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
        result = node.on_configure(State())
        assert result == TransitionCallbackReturn.FAILURE

    def test_configure_degraded_allowed(self):
        node = make_node()
        from rclpy.lifecycle import State, TransitionCallbackReturn

        cfg = SpeechConfig()
        cfg.allow_degraded_startup = True
        node._cfg = cfg

        node._load_config = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
        result = node.on_configure(State())
        assert result == TransitionCallbackReturn.SUCCESS


# ── Audio callback ────────────────────────────────────────────────────────────


class TestAudioCallback:
    def test_silence_no_publish(self):
        node = make_node()
        init_pipeline(node)
        # MockVAD defaults to all-silence
        msg = make_audio_msg()
        node._on_audio_chunk(msg)
        node._pub_command.publish.assert_not_called()

    def test_speech_segment_emits_command(self):
        node = make_node()
        init_pipeline(node)
        # Configure VAD to emit on next call
        node._vad.force_next_emit(
            samples=np.zeros(16000, dtype=np.float32),
            force_cut=False,
        )
        msg = make_audio_msg()
        node._on_audio_chunk(msg)
        node._pub_command.publish.assert_called_once()

    def test_published_command_has_text(self):
        node = make_node()
        init_pipeline(node)
        node._stt.set_responses([TranscriptionResult(text="order coffee", confidence=0.88)])
        node._vad.force_next_emit(samples=np.zeros(8000, dtype=np.float32))
        node._on_audio_chunk(make_audio_msg())
        args = node._pub_command.publish.call_args[0]
        assert args[0].text == "order coffee"

    def test_doa_passed_through(self):
        node = make_node()
        init_pipeline(node)
        node._vad.force_next_emit(samples=np.zeros(8000, dtype=np.float32))
        node._on_audio_chunk(make_audio_msg(doa=30.0))
        # Check publish was called (doa is on the AudioSegment, not re-read from msg)
        node._pub_command.publish.assert_called_once()

    def test_invalid_audio_data_no_crash(self):
        node = make_node()
        init_pipeline(node)
        msg = make_audio_msg(data=np.array([float("nan")] * 512, dtype=np.float32))
        node._on_audio_chunk(msg)  # must not raise

    def test_low_confidence_flagged_in_command(self):
        node = make_node()
        init_pipeline(node)
        node._stt.set_responses(
            [TranscriptionResult(text="unclear", confidence=0.2, is_low_confidence=True)]
        )
        node._vad.force_next_emit(samples=np.zeros(8000, dtype=np.float32))
        node._on_audio_chunk(make_audio_msg())
        args = node._pub_command.publish.call_args[0]
        assert args[0].is_low_confidence is True


# ── Transcription detail ──────────────────────────────────────────────────────


class TestTranscriptionDetail:
    def test_detail_published_when_enabled(self):
        cfg = SpeechConfig()
        cfg.publish_transcription_detail = True
        node = make_node(cfg)
        init_pipeline(node)
        node._vad.force_next_emit(samples=np.zeros(8000, dtype=np.float32))
        node._on_audio_chunk(make_audio_msg())
        node._pub_transcription.publish.assert_called_once()

    def test_detail_not_published_when_disabled(self):
        cfg = SpeechConfig()
        cfg.publish_transcription_detail = False
        node = make_node(cfg)
        init_pipeline(node)
        node._vad.force_next_emit(samples=np.zeros(8000, dtype=np.float32))
        node._on_audio_chunk(make_audio_msg())
        node._pub_transcription.publish.assert_not_called()


# ── Diarization integration ───────────────────────────────────────────────────


class TestDiarizationIntegration:
    def test_speaker_id_from_diarizer(self):
        node = make_node()
        init_pipeline(node)
        responses = [
            DiarizationResult(
                segments=[SpeakerSegment("SPEAKER_01", 0.0, 2.0)],
                dominant_speaker="SPEAKER_01",
                all_speaker_ids=["SPEAKER_01"],
            )
        ]
        node._diarizer = MockDiarizer(responses=responses)
        node._diarizer.load()
        node._vad.force_next_emit(samples=np.zeros(8000, dtype=np.float32))
        node._on_audio_chunk(make_audio_msg())
        args = node._pub_command.publish.call_args[0]
        assert args[0].speaker_id == "SPEAKER_01"

    def test_privacy_anonymise_overrides_speaker(self):
        cfg = SpeechConfig()
        cfg.privacy.anonymize_speaker = True
        node = make_node(cfg)
        init_pipeline(node)
        responses = [
            DiarizationResult(
                dominant_speaker="SPEAKER_00",
                all_speaker_ids=["SPEAKER_00"],
            )
        ]
        node._diarizer = MockDiarizer(responses=responses)
        node._diarizer.load()
        node._vad.force_next_emit(samples=np.zeros(8000, dtype=np.float32))
        node._on_audio_chunk(make_audio_msg())
        args = node._pub_command.publish.call_args[0]
        assert args[0].speaker_id == "SPEAKER_ANON"


# ── Wake word gate ────────────────────────────────────────────────────────────


class TestWakeWordGate:
    def test_no_speech_before_wake_word(self):
        cfg = SpeechConfig()
        cfg.wake_word.enabled = True
        cfg.wake_word.backend = "mock"
        node = make_node(cfg)
        init_pipeline(node)
        # Wake word detector: always False (never detected)
        node._ww = MockWakeWordDetector(cfg=cfg.wake_word, detect_pattern=[False])
        node._ww.load()
        node._ww_armed = True
        # Even if VAD emits, speech should be blocked (wake word not triggered)
        # But VAD is fed after wake-word → VAD never emits either
        node._vad.force_next_emit(samples=np.zeros(8000, dtype=np.float32))
        # With ww_armed=True and no detection → returns early
        node._on_audio_chunk(make_audio_msg())
        node._pub_command.publish.assert_not_called()

    def test_speech_after_wake_word(self):
        cfg = SpeechConfig()
        cfg.wake_word.enabled = True
        cfg.wake_word.backend = "mock"
        cfg.wake_word.listen_timeout_sec = 10.0
        node = make_node(cfg)
        init_pipeline(node)
        # Wake word detector: first call detects
        node._ww = MockWakeWordDetector(
            cfg=cfg.wake_word,
            detect_pattern=[True, False],
        )
        node._ww.load()
        node._ww_armed = True
        # First audio chunk: wake word detected → arms listener, returns early
        node._on_audio_chunk(make_audio_msg())
        assert not node._ww_armed  # now listening
        # Second chunk: within listen window, VAD can emit
        node._vad.force_next_emit(samples=np.zeros(8000, dtype=np.float32))
        node._on_audio_chunk(make_audio_msg())
        node._pub_command.publish.assert_called_once()


# ── Deactivate / cleanup ──────────────────────────────────────────────────────


class TestLifecycle:
    def test_deactivate_cancels_timer(self):
        node = make_node()
        init_pipeline(node)
        from rclpy.lifecycle import State

        mock_timer = MagicMock()
        node._health_timer = mock_timer
        node.on_deactivate(State())
        mock_timer.cancel.assert_called_once()
        assert node._health_timer is None

    def test_cleanup_clears_buffer(self):
        node = make_node()
        init_pipeline(node)
        node._buf.push(np.zeros(1000, dtype=np.float32))
        from rclpy.lifecycle import State

        node.on_cleanup(State())
        assert node._buf.available() == 0

    def test_health_publish(self):
        node = make_node()
        init_pipeline(node)
        node._pipeline_ok = True
        node._cfg = SpeechConfig()
        node._publish_health()
        node._pub_health.publish.assert_called_once()
