"""
tests/test_tts_config.py
========================
Unit tests for bonbon_tts.config.tts_config.
"""
import pytest
from bonbon_tts.config.tts_config import (
    PiperConfig,
    FillerConfig,
    QueueConfig,
    SpeakerConfig,
    TTSConfig,
)


class TestPiperConfig:
    def test_defaults(self):
        cfg = PiperConfig()
        assert cfg.model_path == ""
        assert cfg.use_subprocess is True
        assert cfg.voice == "en_US-lessac-medium"
        assert cfg.length_scale == pytest.approx(1.0)
        assert cfg.noise_scale == pytest.approx(0.667)
        assert cfg.noise_w == pytest.approx(0.8)
        assert cfg.synthesis_timeout_sec == pytest.approx(10.0)
        assert cfg.cuda is False

    def test_custom(self):
        cfg = PiperConfig(model_path="/tmp/model.onnx", cuda=True, length_scale=1.2)
        assert cfg.model_path == "/tmp/model.onnx"
        assert cfg.cuda is True
        assert cfg.length_scale == pytest.approx(1.2)


class TestFillerConfig:
    def test_defaults(self):
        cfg = FillerConfig()
        assert cfg.enabled is True
        assert cfg.cooldown_sec == pytest.approx(3.0)
        assert cfg.trigger_queue_depth == 2
        assert cfg.trigger_latency_ms == pytest.approx(400.0)

    def test_disabled(self):
        cfg = FillerConfig(enabled=False)
        assert cfg.enabled is False


class TestQueueConfig:
    def test_defaults(self):
        cfg = QueueConfig()
        assert cfg.max_depth == 32
        assert cfg.dedup_enabled is True
        assert cfg.default_max_age_sec == pytest.approx(30.0)
        assert cfg.emergency_max_age_sec == pytest.approx(120.0)


class TestSpeakerConfig:
    def test_defaults(self):
        cfg = SpeakerConfig()
        assert cfg.driver == "mock"
        assert cfg.volume_pct == pytest.approx(80.0)
        assert cfg.sample_rate == 22050
        assert cfg.channels == 1


class TestTTSConfig:
    def _cfg(self, **kwargs) -> TTSConfig:
        return TTSConfig(
            piper   = PiperConfig(**kwargs.get("piper", {})),
            filler  = FillerConfig(**kwargs.get("filler", {})),
            queue   = QueueConfig(**kwargs.get("queue", {})),
            speaker = SpeakerConfig(**kwargs.get("speaker", {})),
        )

    def test_default_construction(self):
        cfg = self._cfg()
        assert cfg.health_rate_hz == pytest.approx(1.0)
        assert cfg.allow_degraded_startup is True

    def test_from_dict_roundtrip(self):
        cfg = self._cfg()
        d   = cfg.to_dict()
        cfg2 = TTSConfig.from_dict(d)
        assert cfg2.piper.voice == cfg.piper.voice
        assert cfg2.queue.max_depth == cfg.queue.max_depth
        assert cfg2.speaker.volume_pct == pytest.approx(cfg.speaker.volume_pct)

    def test_from_dict_partial(self):
        """from_dict with only some keys should use defaults for the rest."""
        d = {"piper": {"model_path": "/models/my.onnx"}}
        cfg = TTSConfig.from_dict(d)
        assert cfg.piper.model_path == "/models/my.onnx"
        assert cfg.piper.voice == "en_US-lessac-medium"  # default preserved

    def test_validate_ok(self):
        cfg = self._cfg()
        cfg.validate()   # must not raise

    def test_validate_bad_volume(self):
        cfg = self._cfg(speaker={"volume_pct": 150.0})
        with pytest.raises(ValueError, match="volume"):
            cfg.validate()

    def test_validate_bad_max_depth(self):
        cfg = TTSConfig(
            piper   = PiperConfig(),
            filler  = FillerConfig(),
            queue   = QueueConfig(max_depth=0),
            speaker = SpeakerConfig(),
        )
        with pytest.raises(ValueError, match="max_depth"):
            cfg.validate()

    def test_summary_returns_string(self):
        cfg = self._cfg()
        s = cfg.summary()
        assert isinstance(s, str)
        assert "piper" in s.lower() or "mock" in s.lower() or "tts" in s.lower()
