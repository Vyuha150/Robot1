"""
bonbon_speech.config.speech_config
=====================================
Fully typed, nested configuration for the speech recognition pipeline.

No model path is hardcoded — all paths injected via ROS2 parameters.
Factories: from_ros_params(node)  from_dict(d)  from_yaml(path)
"""

from __future__ import annotations

import copy
import logging
from dataclasses import asdict, dataclass, field, fields
from typing import Any

logger = logging.getLogger(__name__)


# ── Sub-configs ───────────────────────────────────────────────────────────────


@dataclass
class AudioConfig:
    """HAL microphone + audio format settings."""

    sample_rate: int = 16000  # Hz — must match VAD requirement
    channels: int = 1  # mono
    chunk_size_samples: int = 512  # samples per ROS2 AudioChunk frame
    # Maximum audio kept in the rolling buffer (privacy + memory cap)
    max_buffer_sec: float = 30.0
    # Seconds of audio kept before speech onset (capture the beginning)
    prebuffer_sec: float = 0.5

    def validate(self) -> None:
        if self.sample_rate not in (8000, 16000):
            raise ValueError(
                f"audio.sample_rate must be 8000 or 16000 (Silero VAD requirement), "
                f"got {self.sample_rate}"
            )
        if self.chunk_size_samples not in (256, 512, 768, 1024, 1536):
            raise ValueError(
                f"audio.chunk_size_samples must be one of Silero's supported sizes "
                f"(256,512,768,1024,1536), got {self.chunk_size_samples}"
            )


@dataclass
class VADConfig:
    """Silero Voice Activity Detection settings."""

    backend: str = "silero"  # "silero" | "mock"
    # Model file for Silero VAD (downloaded from torch.hub if empty)
    model_path: str = ""
    speech_start_threshold: float = 0.50  # prob above → SPEECH
    speech_end_threshold: float = 0.35  # prob below → silence
    # Min consecutive SPEECH frames before segment is emitted
    min_speech_frames: int = 8  # ~256 ms at 16kHz/512
    # Silence frames to confirm speech end (hysteresis)
    silence_frames_to_end: int = 5  # ~160 ms
    # Hard clip: speech longer than this is force-cut and emitted
    max_speech_sec: float = 15.0
    # Silence pad appended after speech ends (includes trailing phoneme)
    speech_pad_ms: float = 300.0

    def validate(self) -> None:
        if not 0.0 < self.speech_start_threshold <= 1.0:
            raise ValueError("vad.speech_start_threshold must be in (0, 1]")
        if not 0.0 < self.speech_end_threshold <= 1.0:
            raise ValueError("vad.speech_end_threshold must be in (0, 1]")
        if self.speech_end_threshold >= self.speech_start_threshold:
            raise ValueError(
                "vad.speech_end_threshold must be < speech_start_threshold "
                "(hysteresis requires lower end threshold)"
            )


@dataclass
class STTConfig:
    """Whisper speech-to-text settings."""

    backend: str = "mock"  # "whisper" | "faster_whisper" | "mock"
    model_size: str = "base"  # "tiny"|"base"|"small"|"medium"|"large"
    # Absolute path to model directory (downloaded to default cache if "")
    model_dir: str = ""
    device: str = ""  # "" = auto | "cpu" | "cuda"
    language: str = ""  # "" = auto-detect | "en" | "zh" …
    task: str = "transcribe"  # "transcribe" | "translate"
    # Confidence gate: commands below this threshold are flagged is_low_confidence
    confidence_threshold: float = 0.50
    # Per-transcription wall-clock deadline
    inference_timeout_sec: float = 15.0
    max_consecutive_timeouts: int = 3
    # Beam search parameters
    beam_size: int = 5
    best_of: int = 5
    temperature: float = 0.0
    # Word timestamps (slower but richer output)
    word_timestamps: bool = False
    # Suppress common non-speech tokens (breathing, music)
    suppress_tokens: str = "-1"

    def validate(self) -> None:
        if self.backend == "whisper" and not self.model_size:
            raise ValueError("stt.model_size must be set when backend='whisper'")
        valid_sizes = {
            "tiny",
            "base",
            "small",
            "medium",
            "large",
            "tiny.en",
            "base.en",
            "small.en",
            "medium.en",
        }
        if self.model_size and self.model_size not in valid_sizes:
            logger.warning("stt.model_size=%r is not a standard Whisper size", self.model_size)


@dataclass
class DiarizationConfig:
    """pyannote.audio speaker diarization settings."""

    enabled: bool = False  # disabled by default (requires HF token)
    backend: str = "mock"  # "pyannote" | "mock"
    # HuggingFace access token — NOT hardcoded, inject via ROS2 param
    hf_token: str = ""
    # Local pipeline path (optional — avoids HF download)
    pipeline_path: str = ""
    min_speakers: int = 1
    max_speakers: int = 5
    inference_timeout_sec: float = 10.0

    def validate(self) -> None:
        if self.enabled and self.backend == "pyannote" and not self.hf_token:
            logger.warning(
                "diarization.hf_token is empty — pyannote will likely fail. "
                "Set diarization_hf_token ROS2 parameter."
            )


@dataclass
class WakeWordConfig:
    """Wake-word detection pipeline settings."""

    enabled: bool = False  # disabled → always listening
    backend: str = "mock"  # "openwakeword" | "porcupine" | "mock"
    # Keyword phrase — NOT hardcoded
    keyword: str = "hey bonbon"
    # Path to custom wake word model (backend-specific)
    model_path: str = ""
    # Confidence threshold for wake word accept
    threshold: float = 0.50
    # After wake word: how long to wait for speech before re-arming
    listen_timeout_sec: float = 8.0
    # Porcupine access key (if using porcupine backend)
    access_key: str = ""

    def validate(self) -> None:
        if self.enabled and not self.keyword:
            raise ValueError("wake_word.keyword must be set when wake_word.enabled=true")


@dataclass
class PrivacyConfig:
    """Privacy controls for the speech pipeline."""

    # Never write raw audio to disk
    store_audio: bool = False
    # Suppress speaker_id in published SpeechCommand messages
    anonymize_speaker: bool = False
    # Suppress recognised speaker name (keep SPEAKER_00 style IDs only)
    suppress_speaker_name: bool = False
    # Maximum seconds of audio stored in memory (enforced by AudioBuffer)
    max_audio_retention_sec: float = 30.0


@dataclass
class SpeechConfig:
    """Complete typed configuration for the bonbon speech pipeline."""

    audio: AudioConfig = field(default_factory=AudioConfig)
    vad: VADConfig = field(default_factory=VADConfig)
    stt: STTConfig = field(default_factory=STTConfig)
    diarization: DiarizationConfig = field(default_factory=DiarizationConfig)
    wake_word: WakeWordConfig = field(default_factory=WakeWordConfig)
    privacy: PrivacyConfig = field(default_factory=PrivacyConfig)

    # Node-level
    health_rate_hz: float = 1.0
    allow_degraded_startup: bool = True
    # Publish raw transcription detail (SpeechTranscription msg)
    publish_transcription_detail: bool = True

    # ── Factories ─────────────────────────────────────────────────────────────

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SpeechConfig:
        d = copy.deepcopy(d)
        cfg = cls()
        cfg.audio = _fill(AudioConfig, d.pop("audio", {}))
        cfg.vad = _fill(VADConfig, d.pop("vad", {}))
        cfg.stt = _fill(STTConfig, d.pop("stt", {}))
        cfg.diarization = _fill(DiarizationConfig, d.pop("diarization", {}))
        cfg.wake_word = _fill(WakeWordConfig, d.pop("wake_word", {}))
        cfg.privacy = _fill(PrivacyConfig, d.pop("privacy", {}))
        for k, v in d.items():
            if hasattr(cfg, k):
                setattr(cfg, k, v)
        return cfg

    @classmethod
    def from_yaml(cls, path: str) -> SpeechConfig:
        import yaml

        with open(path) as fh:
            raw = yaml.safe_load(fh) or {}
        return cls.from_dict(raw)

    @classmethod
    def from_ros_params(cls, node) -> SpeechConfig:
        def _p(name, default=None):
            try:
                return node.get_parameter(name).value
            except Exception:
                return default

        cfg = cls()
        # Audio
        cfg.audio.sample_rate = int(_p("audio_sample_rate", 16000))
        cfg.audio.channels = int(_p("audio_channels", 1))
        cfg.audio.chunk_size_samples = int(_p("audio_chunk_samples", 512))
        cfg.audio.max_buffer_sec = _p("audio_max_buffer_sec", 30.0)
        cfg.audio.prebuffer_sec = _p("audio_prebuffer_sec", 0.5)
        # VAD
        cfg.vad.backend = _p("vad_backend", "silero")
        cfg.vad.model_path = _p("vad_model_path", "")
        cfg.vad.speech_start_threshold = _p("vad_start_threshold", 0.50)
        cfg.vad.speech_end_threshold = _p("vad_end_threshold", 0.35)
        cfg.vad.min_speech_frames = int(_p("vad_min_speech_frames", 8))
        cfg.vad.silence_frames_to_end = int(_p("vad_silence_frames", 5))
        cfg.vad.max_speech_sec = _p("vad_max_speech_sec", 15.0)
        cfg.vad.speech_pad_ms = _p("vad_speech_pad_ms", 300.0)
        # STT
        cfg.stt.backend = _p("stt_backend", "mock")
        cfg.stt.model_size = _p("stt_model_size", "base")
        cfg.stt.model_dir = _p("stt_model_dir", "")
        cfg.stt.device = _p("stt_device", "")
        cfg.stt.language = _p("stt_language", "")
        cfg.stt.task = _p("stt_task", "transcribe")
        cfg.stt.confidence_threshold = _p("stt_confidence_threshold", 0.50)
        cfg.stt.inference_timeout_sec = _p("stt_timeout_sec", 15.0)
        cfg.stt.max_consecutive_timeouts = int(_p("stt_max_timeouts", 3))
        cfg.stt.word_timestamps = bool(_p("stt_word_timestamps", False))
        # Diarization
        cfg.diarization.enabled = bool(_p("diarization_enabled", False))
        cfg.diarization.backend = _p("diarization_backend", "mock")
        cfg.diarization.hf_token = _p("diarization_hf_token", "")
        cfg.diarization.pipeline_path = _p("diarization_pipeline_path", "")
        cfg.diarization.min_speakers = int(_p("diarization_min_speakers", 1))
        cfg.diarization.max_speakers = int(_p("diarization_max_speakers", 5))
        cfg.diarization.inference_timeout_sec = _p("diarization_timeout_sec", 10.0)
        # Wake word
        cfg.wake_word.enabled = bool(_p("wake_word_enabled", False))
        cfg.wake_word.backend = _p("wake_word_backend", "mock")
        cfg.wake_word.keyword = _p("wake_word_keyword", "hey bonbon")
        cfg.wake_word.model_path = _p("wake_word_model_path", "")
        cfg.wake_word.threshold = _p("wake_word_threshold", 0.50)
        cfg.wake_word.listen_timeout_sec = _p("wake_word_listen_timeout", 8.0)
        cfg.wake_word.access_key = _p("wake_word_access_key", "")
        # Privacy
        cfg.privacy.store_audio = bool(_p("privacy_store_audio", False))
        cfg.privacy.anonymize_speaker = bool(_p("privacy_anonymize_speaker", False))
        # Top-level
        cfg.health_rate_hz = _p("health_rate_hz", 1.0)
        cfg.allow_degraded_startup = bool(_p("allow_degraded", True))
        cfg.publish_transcription_detail = bool(_p("publish_detail", True))
        return cfg

    # ── Validation ─────────────────────────────────────────────────────────────

    def validate(self) -> None:
        self.audio.validate()
        self.vad.validate()
        self.stt.validate()
        self.diarization.validate()
        self.wake_word.validate()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def summary(self) -> str:
        return (
            f"vad={self.vad.backend!r} "
            f"stt={self.stt.backend!r} model={self.stt.model_size!r} "
            f"lang={self.stt.language!r} "
            f"diarize={self.diarization.enabled} "
            f"wake_word={self.wake_word.enabled} keyword={self.wake_word.keyword!r} "
            f"privacy_anon={self.privacy.anonymize_speaker}"
        )


def _fill(cls, d: dict[str, Any]):
    valid = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in d.items() if k in valid})
