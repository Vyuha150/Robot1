"""
Tests for the wake-word layer:
  - MockWakeWordDetector detection / no-detection
  - Score threshold
  - Wrong wake word (no false trigger)
  - Pattern cycling
  - force_detect / force_no_detect helpers
"""

import numpy as np
import pytest
from bonbon_speech.config.speech_config import WakeWordConfig
from bonbon_speech.wake_word.mock_wake_word import MockWakeWordDetector


def make_cfg(**kwargs) -> WakeWordConfig:
    defaults = dict(enabled=True, backend="mock", keyword="hey bonbon", threshold=0.5)
    defaults.update(kwargs)
    return WakeWordConfig(**defaults)


def make_detector(**kwargs) -> MockWakeWordDetector:
    d = MockWakeWordDetector(cfg=make_cfg(**kwargs))
    d.load()
    return d


def chunk(n: int = 512) -> np.ndarray:
    return np.zeros(n, dtype=np.float32)


# ── Lifecycle ─────────────────────────────────────────────────────────────────


class TestLifecycle:
    def test_load_unload(self):
        d = MockWakeWordDetector(cfg=make_cfg())
        d.load()
        assert d.loaded
        d.unload()
        assert not d.loaded

    def test_reset_resets_index(self):
        d = make_detector()
        d.set_pattern([True, False])
        d.process_chunk(chunk())  # advances index
        d.reset()
        # After reset, next call should use first pattern element
        detected, score = d.process_chunk(chunk())
        assert detected is True


# ── No-detection (wrong/absent wake word) ────────────────────────────────────


class TestNoDetection:
    def test_all_false_pattern_no_detection(self):
        d = MockWakeWordDetector(cfg=make_cfg(), detect_pattern=[False] * 20)
        d.load()
        for _ in range(20):
            detected, score = d.process_chunk(chunk())
            assert detected is False
            assert score == pytest.approx(0.0)
        assert d.detect_count == 0

    def test_wrong_keyword_no_trigger(self):
        """Pattern always false — wrong keyword never triggers."""
        d = make_detector()
        d.set_pattern([False] * 50)
        for _ in range(50):
            detected, _ = d.process_chunk(chunk())
            assert not detected

    def test_call_count_increments_on_no_detect(self):
        d = make_detector()
        d.set_pattern([False] * 5)
        for _ in range(5):
            d.process_chunk(chunk())
        assert d.call_count == 5
        assert d.detect_count == 0


# ── Detection ─────────────────────────────────────────────────────────────────


class TestDetection:
    def test_true_pattern_triggers(self):
        d = MockWakeWordDetector(cfg=make_cfg(), detect_pattern=[True])
        d.load()
        detected, score = d.process_chunk(chunk())
        assert detected is True
        assert score == pytest.approx(0.90)

    def test_detect_count_increments(self):
        d = MockWakeWordDetector(cfg=make_cfg(), detect_pattern=[True])
        d.load()
        d.process_chunk(chunk())
        d.process_chunk(chunk())
        assert d.detect_count == 2

    def test_custom_detect_score(self):
        d = MockWakeWordDetector(cfg=make_cfg(), detect_pattern=[True], detect_score=0.75)
        d.load()
        _, score = d.process_chunk(chunk())
        assert score == pytest.approx(0.75)

    def test_pattern_cycles(self):
        d = MockWakeWordDetector(cfg=make_cfg(), detect_pattern=[True, False])
        d.load()
        detected0, _ = d.process_chunk(chunk())
        detected1, _ = d.process_chunk(chunk())
        detected2, _ = d.process_chunk(chunk())  # cycles back to True
        assert detected0 is True
        assert detected1 is False
        assert detected2 is True


# ── Force helpers ─────────────────────────────────────────────────────────────


class TestForceHelpers:
    def test_force_detect(self):
        d = make_detector()
        d.set_pattern([False] * 100)
        d.force_detect()
        detected, score = d.process_chunk(chunk())
        assert detected is True
        assert score == pytest.approx(0.90)

    def test_force_detect_only_once(self):
        d = make_detector()
        d.set_pattern([False] * 100)
        d.force_detect()
        d.process_chunk(chunk())  # uses the force
        detected, _ = d.process_chunk(chunk())
        assert detected is False

    def test_force_no_detect(self):
        d = make_detector()
        d.set_pattern([True] * 100)
        d.force_no_detect()
        detected, score = d.process_chunk(chunk())
        assert detected is False
        assert score == pytest.approx(0.0)

    def test_force_no_detect_only_once(self):
        d = make_detector()
        d.set_pattern([True] * 100)
        d.force_no_detect()
        d.process_chunk(chunk())  # forced False
        detected, _ = d.process_chunk(chunk())  # back to True
        assert detected is True


# ── Set pattern ───────────────────────────────────────────────────────────────


class TestSetPattern:
    def test_set_pattern_resets_index(self):
        d = make_detector()
        d.set_pattern([True, False])
        d.process_chunk(chunk())
        d.process_chunk(chunk())
        d.set_pattern([False, False])
        detected, _ = d.process_chunk(chunk())
        assert detected is False

    def test_all_true_pattern(self):
        d = make_detector()
        d.set_pattern([True] * 5)
        for _ in range(5):
            detected, _ = d.process_chunk(chunk())
            assert detected is True


# ── make_wake_word_detector factory ──────────────────────────────────────────


class TestFactory:
    def test_mock_backend_created(self):
        from bonbon_speech.wake_word.wake_word_detector import make_wake_word_detector

        cfg = make_cfg(backend="mock")
        det = make_wake_word_detector(cfg)
        assert isinstance(det, MockWakeWordDetector)

    def test_unknown_backend_raises(self):
        from bonbon_speech.wake_word.wake_word_detector import make_wake_word_detector

        cfg = make_cfg(backend="unknown_backend")
        with pytest.raises(ValueError, match="unknown_backend"):
            make_wake_word_detector(cfg)
