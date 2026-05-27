"""Tests for StaleDetector."""

import time

from bonbon_perception_ai.fusion.modality_buffer import ModalityBuffer
from bonbon_perception_ai.fusion.stale_detector import (
    UNCERTAINTY_HIGH,
    UNCERTAINTY_LOW,
    UNCERTAINTY_MEDIUM,
    StaleDetector,
)


def _fresh_buf(name="m", timeout=10.0, value="data"):
    b = ModalityBuffer(name, timeout)
    b.update(value)
    return b


def _stale_buf(name="m", timeout=0.001):
    b = ModalityBuffer(name, timeout)
    b.update("data")
    time.sleep(0.005)
    return b


class TestUncertaintyLevels:
    def test_all_fresh_low(self):
        bufs = {f"m{i}": _fresh_buf(f"m{i}") for i in range(5)}
        stale, unc = StaleDetector().assess(bufs)
        assert stale == []
        assert unc == UNCERTAINTY_LOW

    def test_one_stale_medium(self):
        bufs = {f"m{i}": _fresh_buf(f"m{i}") for i in range(4)}
        bufs["stale_one"] = _stale_buf("stale_one")
        stale, unc = StaleDetector().assess(bufs)
        assert "stale_one" in stale
        assert unc == UNCERTAINTY_MEDIUM

    def test_two_stale_medium(self):
        bufs = {f"fresh{i}": _fresh_buf(f"fresh{i}") for i in range(3)}
        bufs["s1"] = _stale_buf("s1")
        bufs["s2"] = _stale_buf("s2")
        stale, unc = StaleDetector().assess(bufs)
        assert len(stale) == 2
        assert unc == UNCERTAINTY_MEDIUM

    def test_three_stale_high(self):
        bufs = {"s1": _stale_buf("s1"), "s2": _stale_buf("s2"), "s3": _stale_buf("s3")}
        stale, unc = StaleDetector().assess(bufs)
        assert len(stale) == 3
        assert unc == UNCERTAINTY_HIGH

    def test_all_never_written_high(self):
        bufs = {f"m{i}": ModalityBuffer(f"m{i}", 10.0) for i in range(5)}
        stale, unc = StaleDetector().assess(bufs)
        assert len(stale) == 5
        assert unc == UNCERTAINTY_HIGH


class TestDetailReport:
    def test_ages_reported(self):
        buf = _fresh_buf("x")
        ages = StaleDetector().detail_report({"x": buf})
        assert "x" in ages
        assert ages["x"] < 0.1

    def test_never_written_age_is_inf(self):
        buf = ModalityBuffer("y", 10.0)
        ages = StaleDetector().detail_report({"y": buf})
        assert ages["y"] == float("inf")
