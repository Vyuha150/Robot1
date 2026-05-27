"""
bonbon_tts.config.tts_config
==============================
Fully typed, nested configuration for the TTS synthesis pipeline.

No model paths or API credentials are hardcoded — all injected via
ROS2 parameters, environment variables, or explicit constructor args.

Sections
--------
* PiperConfig   — Piper TTS model, voice, rate settings
* FillerConfig  — filler audio clips and trigger conditions
* QueueConfig   — utterance queue depth, age limits, deduplication
* SpeakerConfig — HAL speaker driver settings
* TTSConfig     — top-level aggregate with ROS2 factory
"""

from __future__ import annotations

import copy
import logging
from dataclasses import asdict, dataclass, field, fields
from typing import Any

logger = logging.getLogger(__name__)


# ── Piper TTS settings ────────────────────────────────────────────────────────


@dataclass
class PiperConfig:
    """Piper neural TTS backend configuration."""

    # Path to the .onnx voice model file.
    # Download from: https://github.com/rhasspy/piper/releases
    # NOT hardcoded — must be set via ros2 param tts_piper_model_path.
    model_path: str = ""

    # Path to the .onnx.json model config (auto-derived if empty).
    config_path: str = ""

    # Path to the piper executable or "piper" if on PATH.
    executable: str = "piper"

    # True = use subprocess (preferred: isolates memory, allows restart).
    # False = use piper_tts Python API (lower latency, more memory).
    use_subprocess: bool = True

    # Default voice name (used when model_path is empty).
    # Piper will try to download it on first use.
    voice: str = "en_US-lessac-medium"

    # Speaking rate (1.0 = natural; >1.0 = slower; <1.0 = faster).
    length_scale: float = 1.0

    # Phoneme duration noise (higher = more natural variation).
    noise_scale: float = 0.667

    # Phoneme width noise.
    noise_w: float = 0.8

    # Seconds of silence appended after each sentence.
    sentence_silence_sec: float = 0.2

    # Wall-clock deadline for a single synthesis call.
    synthesis_timeout_sec: float = 10.0

    # Use CUDA for inference (requires CUDA-enabled piper build).
    cuda: bool = False

    def validate(self) -> None:
        if self.length_scale <= 0:
            raise ValueError("piper.length_scale must be > 0")
        if self.synthesis_timeout_sec <= 0:
            raise ValueError("piper.synthesis_timeout_sec must be > 0")


# ── Filler audio settings ─────────────────────────────────────────────────────


@dataclass
class FillerConfig:
    """Filler audio clip configuration.

    Filler clips are short pre-recorded phrases (e.g., "one moment",
    "let me think") played while Piper synthesis is in progress, giving
    the user an immediate audio acknowledgement with minimal latency.
    """

    enabled: bool = True

    # Directory containing .wav filler clips.
    # If empty, bonbon_tts will generate minimal built-in clips.
    filler_dir: str = ""

    # Synthesizer queue depth threshold: play a filler when depth >= this.
    trigger_queue_depth: int = 2

    # Latency threshold: start filler if synthesis exceeds this many ms.
    trigger_latency_ms: float = 400.0

    # Minimum gap between two consecutive filler plays (avoids spamming).
    cooldown_sec: float = 3.0

    # Ordered list of clip filenames (relative to filler_dir).
    # The player cycles through them round-robin.
    clips: list[str] = field(
        default_factory=lambda: [
            "one_moment.wav",
            "let_me_think.wav",
            "sure.wav",
            "hmm.wav",
        ]
    )

    def validate(self) -> None:
        if self.cooldown_sec < 0:
            raise ValueError("filler.cooldown_sec must be >= 0")
        if self.trigger_latency_ms < 0:
            raise ValueError("filler.trigger_latency_ms must be >= 0")


# ── Queue settings ────────────────────────────────────────────────────────────


@dataclass
class QueueConfig:
    """Utterance queue parameters."""

    # Maximum utterances held in the queue.
    # When full, the lowest-priority item is dropped.
    max_depth: int = 32

    # Default maximum age before an utterance is silently discarded.
    default_max_age_sec: float = 30.0

    # Longer age limit for emergency announcements.
    emergency_max_age_sec: float = 120.0

    # When True, a new utterance with the same dedup_key replaces any
    # existing queued utterance with the same key.
    dedup_enabled: bool = True

    def validate(self) -> None:
        if self.max_depth < 1:
            raise ValueError("queue.max_depth must be >= 1")


# ── Speaker settings ──────────────────────────────────────────────────────────


@dataclass
class SpeakerConfig:
    """HAL speaker driver settings."""

    # Driver backend: "alsa" | "mock".
    # "mock" is used in tests and CI.
    driver: str = "mock"

    # ALSA device string (e.g., "default", "hw:0,0").
    device: str = "default"

    # Playback volume (0–100 %).
    volume_pct: float = 80.0

    # Expected sample rate of synthesised audio.
    sample_rate: int = 22050

    # Mono audio.
    channels: int = 1

    def validate(self) -> None:
        if not 0.0 <= self.volume_pct <= 100.0:
            raise ValueError("speaker.volume_pct must be in 0–100")
        if self.sample_rate <= 0:
            raise ValueError("speaker.sample_rate must be > 0")
        if self.driver not in ("alsa", "mock"):
            logger.warning("speaker.driver=%r is not a standard value", self.driver)


# ── Top-level config ──────────────────────────────────────────────────────────


@dataclass
class TTSConfig:
    """Complete typed configuration for the BonBon TTS pipeline."""

    piper: PiperConfig = field(default_factory=PiperConfig)
    filler: FillerConfig = field(default_factory=FillerConfig)
    queue: QueueConfig = field(default_factory=QueueConfig)
    speaker: SpeakerConfig = field(default_factory=SpeakerConfig)

    # Health-report publication rate (Hz).
    health_rate_hz: float = 1.0

    # If True, the node transitions to ACTIVE even when Piper is unavailable
    # (mock fallback is used instead).
    allow_degraded_startup: bool = True

    # ── Factories ─────────────────────────────────────────────────────────────

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> TTSConfig:
        d = copy.deepcopy(d)
        cfg = cls()
        cfg.piper = _fill(PiperConfig, d.pop("piper", {}))
        cfg.filler = _fill(FillerConfig, d.pop("filler", {}))
        cfg.queue = _fill(QueueConfig, d.pop("queue", {}))
        cfg.speaker = _fill(SpeakerConfig, d.pop("speaker", {}))
        for k, v in d.items():
            if hasattr(cfg, k):
                setattr(cfg, k, v)
        return cfg

    @classmethod
    def from_yaml(cls, path: str) -> TTSConfig:
        import yaml

        with open(path) as fh:
            raw = yaml.safe_load(fh) or {}
        return cls.from_dict(raw)

    @classmethod
    def from_ros_params(cls, node) -> TTSConfig:
        def _p(name: str, default=None):
            try:
                return node.get_parameter(name).value
            except Exception:
                return default

        cfg = cls()
        # Piper
        cfg.piper.model_path = _p("tts_piper_model_path", "")
        cfg.piper.config_path = _p("tts_piper_config_path", "")
        cfg.piper.executable = _p("tts_piper_executable", "piper")
        cfg.piper.use_subprocess = bool(_p("tts_piper_subprocess", True))
        cfg.piper.voice = _p("tts_piper_voice", "en_US-lessac-medium")
        cfg.piper.length_scale = float(_p("tts_piper_length_scale", 1.0))
        cfg.piper.synthesis_timeout_sec = float(_p("tts_piper_timeout_sec", 10.0))
        cfg.piper.cuda = bool(_p("tts_piper_cuda", False))
        # Filler
        cfg.filler.enabled = bool(_p("tts_filler_enabled", True))
        cfg.filler.filler_dir = _p("tts_filler_dir", "")
        cfg.filler.trigger_queue_depth = int(_p("tts_filler_queue_depth", 2))
        cfg.filler.trigger_latency_ms = float(_p("tts_filler_latency_ms", 400.0))
        cfg.filler.cooldown_sec = float(_p("tts_filler_cooldown_sec", 3.0))
        # Queue
        cfg.queue.max_depth = int(_p("tts_queue_max_depth", 32))
        cfg.queue.default_max_age_sec = float(_p("tts_queue_max_age_sec", 30.0))
        cfg.queue.emergency_max_age_sec = float(_p("tts_queue_emergency_age_sec", 120.0))
        cfg.queue.dedup_enabled = bool(_p("tts_queue_dedup", True))
        # Speaker
        cfg.speaker.driver = _p("tts_speaker_driver", "mock")
        cfg.speaker.device = _p("tts_speaker_device", "default")
        cfg.speaker.volume_pct = float(_p("tts_speaker_volume", 80.0))
        cfg.speaker.sample_rate = int(_p("tts_speaker_sample_rate", 22050))
        # Top-level
        cfg.health_rate_hz = float(_p("tts_health_rate_hz", 1.0))
        cfg.allow_degraded_startup = bool(_p("tts_allow_degraded", True))
        return cfg

    # ── Validation ─────────────────────────────────────────────────────────────

    def validate(self) -> None:
        self.piper.validate()
        self.filler.validate()
        self.queue.validate()
        self.speaker.validate()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def summary(self) -> str:
        backend = "piper" if self.piper.model_path else "mock"
        return (
            f"backend={backend!r} voice={self.piper.voice!r} "
            f"filler={self.filler.enabled} "
            f"queue_depth={self.queue.max_depth} "
            f"speaker={self.speaker.driver!r} "
            f"volume={self.speaker.volume_pct:.0f}%"
        )


# ── Internal helper ───────────────────────────────────────────────────────────


def _fill(cls, d: dict[str, Any]):
    """Populate a dataclass from a dict, ignoring unknown keys."""
    valid = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in d.items() if k in valid})
