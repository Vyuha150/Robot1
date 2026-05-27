"""Tests for ModalityBuffer."""

import threading
import time

import pytest
from bonbon_perception_ai.fusion.modality_buffer import ModalityBuffer


class TestConstruction:
    def test_default_is_stale(self):
        buf = ModalityBuffer("test", stale_timeout_sec=1.0)
        assert buf.is_stale()

    def test_invalid_timeout_raises(self):
        with pytest.raises(ValueError):
            ModalityBuffer("bad", stale_timeout_sec=0.0)

    def test_initial_age_is_inf(self):
        buf = ModalityBuffer("test", stale_timeout_sec=1.0)
        assert buf.age_sec() == float("inf")

    def test_initial_peek_is_none(self):
        buf = ModalityBuffer("test", stale_timeout_sec=1.0)
        assert buf.peek() is None


class TestUpdate:
    def test_update_makes_not_stale(self):
        buf = ModalityBuffer("test", stale_timeout_sec=10.0)
        buf.update({"x": 1})
        assert not buf.is_stale()

    def test_get_returns_data(self):
        buf = ModalityBuffer("test", stale_timeout_sec=10.0)
        buf.update([1, 2, 3])
        data, ts = buf.get()
        assert data == [1, 2, 3]
        assert ts > 0

    def test_peek_returns_latest(self):
        buf = ModalityBuffer("test", stale_timeout_sec=10.0)
        buf.update("first")
        buf.update("second")
        assert buf.peek() == "second"

    def test_update_count_increments(self):
        buf = ModalityBuffer("test", stale_timeout_sec=10.0)
        for _ in range(5):
            buf.update(0)
        assert buf.update_count == 5

    def test_age_is_small_after_update(self):
        buf = ModalityBuffer("test", stale_timeout_sec=10.0)
        buf.update(42)
        assert buf.age_sec() < 0.1


class TestStaleness:
    def test_becomes_stale_after_timeout(self):
        buf = ModalityBuffer("fast", stale_timeout_sec=0.05)
        buf.update("data")
        assert not buf.is_stale()
        time.sleep(0.08)
        assert buf.is_stale()

    def test_refreshed_not_stale(self):
        buf = ModalityBuffer("fast", stale_timeout_sec=0.05)
        buf.update("v1")
        time.sleep(0.03)
        buf.update("v2")
        time.sleep(0.03)
        assert not buf.is_stale()


class TestClear:
    def test_clear_makes_stale(self):
        buf = ModalityBuffer("test", stale_timeout_sec=10.0)
        buf.update("x")
        assert not buf.is_stale()
        buf.clear()
        assert buf.is_stale()
        assert buf.peek() is None

    def test_update_count_preserved_after_clear(self):
        buf = ModalityBuffer("test", stale_timeout_sec=10.0)
        buf.update("x")
        buf.clear()
        assert buf.update_count == 1


class TestThreadSafety:
    def test_concurrent_updates(self):
        buf = ModalityBuffer("shared", stale_timeout_sec=10.0)
        errors = []

        def writer(val):
            for _ in range(200):
                try:
                    buf.update(val)
                except Exception as exc:
                    errors.append(exc)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert buf.update_count == 1000

    def test_concurrent_read_write(self):
        buf = ModalityBuffer("shared", stale_timeout_sec=10.0)
        errors = []

        def writer():
            for i in range(500):
                buf.update(i)

        def reader():
            for _ in range(500):
                try:
                    buf.peek()
                except Exception as exc:
                    errors.append(exc)

        threads = [threading.Thread(target=writer)] + [
            threading.Thread(target=reader) for _ in range(3)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
