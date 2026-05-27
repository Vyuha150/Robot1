"""
Tests for bonbon_speech.audio.audio_buffer.AudioBuffer
"""

import threading

import numpy as np
import pytest
from bonbon_speech.audio.audio_buffer import AudioBuffer

# ── Fixtures ──────────────────────────────────────────────────────────────────


def make_buf(**kwargs) -> AudioBuffer:
    defaults = dict(sample_rate=16000, max_buffer_sec=1.0, prebuffer_sec=0.1)
    defaults.update(kwargs)
    return AudioBuffer(**defaults)


def ramp(n: int, start: float = 0.0) -> np.ndarray:
    return np.arange(start, start + n, dtype=np.float32)


# ── Construction ──────────────────────────────────────────────────────────────


class TestConstruction:
    def test_default_values(self):
        buf = make_buf()
        assert buf.sample_rate == 16000
        assert buf.max_samples == 16000  # 1.0 sec * 16000
        assert buf.prebuffer_samples == 1600  # 0.1 sec * 16000

    def test_custom_values(self):
        buf = AudioBuffer(sample_rate=8000, max_buffer_sec=2.0, prebuffer_sec=0.25)
        assert buf.sample_rate == 8000
        assert buf.max_samples == 16000
        assert buf.prebuffer_samples == 2000

    def test_initially_empty(self):
        buf = make_buf()
        assert buf.available() == 0
        assert buf.duration_sec() == pytest.approx(0.0)


# ── Push ──────────────────────────────────────────────────────────────────────


class TestPush:
    def test_basic_push(self):
        buf = make_buf()
        buf.push(ramp(512))
        assert buf.available() == 512

    def test_multiple_pushes_accumulate(self):
        buf = make_buf()
        buf.push(ramp(256))
        buf.push(ramp(256))
        assert buf.available() == 512

    def test_push_2d_flattened(self):
        buf = make_buf()
        samples = np.zeros((1, 512), dtype=np.float32)
        buf.push(samples)
        assert buf.available() == 512

    def test_eviction_at_max(self):
        buf = make_buf(max_buffer_sec=0.032)  # 512 samples at 16kHz
        buf.push(ramp(256))
        buf.push(ramp(256))  # now at cap
        buf.push(ramp(256))  # should evict oldest 256
        # Cap is enforced by deque maxlen
        assert buf.available() <= buf.max_samples

    def test_duration_sec(self):
        buf = make_buf()
        buf.push(np.zeros(1600, dtype=np.float32))
        assert buf.duration_sec() == pytest.approx(0.1)


# ── Peek ──────────────────────────────────────────────────────────────────────


class TestPeek:
    def test_peek_all(self):
        buf = make_buf()
        data = ramp(100)
        buf.push(data)
        out = buf.peek()
        np.testing.assert_array_almost_equal(out, data)

    def test_peek_n_samples(self):
        buf = make_buf()
        buf.push(ramp(512))
        out = buf.peek(100)
        assert out.shape == (100,)

    def test_peek_does_not_consume(self):
        buf = make_buf()
        buf.push(ramp(100))
        buf.peek(50)
        assert buf.available() == 100

    def test_peek_empty_returns_empty_array(self):
        buf = make_buf()
        out = buf.peek()
        assert out.size == 0

    def test_peek_more_than_available(self):
        buf = make_buf()
        buf.push(ramp(50))
        out = buf.peek(200)
        assert out.shape == (50,)


# ── Drain ─────────────────────────────────────────────────────────────────────


class TestDrain:
    def test_drain_exact(self):
        buf = make_buf()
        data = ramp(512)
        buf.push(data)
        out = buf.drain_segment(512)
        assert out.shape == (512,)
        assert buf.available() == 0
        np.testing.assert_array_almost_equal(out, data)

    def test_drain_partial(self):
        buf = make_buf()
        buf.push(ramp(512))
        out = buf.drain_segment(100)
        assert out.shape == (100,)
        assert buf.available() == 412

    def test_drain_more_than_available(self):
        buf = make_buf()
        buf.push(ramp(50))
        out = buf.drain_segment(200)
        assert out.shape == (50,)
        assert buf.available() == 0

    def test_drain_all(self):
        buf = make_buf()
        buf.push(ramp(300))
        out = buf.drain_all()
        assert out.shape == (300,)
        assert buf.available() == 0

    def test_drain_all_empty(self):
        buf = make_buf()
        out = buf.drain_all()
        assert out.size == 0


# ── Prebuffer ─────────────────────────────────────────────────────────────────


class TestPrebuffer:
    def test_prebuffer_snapshot_length(self):
        buf = make_buf(prebuffer_sec=0.1)  # 1600 samples at 16kHz
        buf.push(ramp(4000))
        snap = buf.prebuffer_snapshot()
        assert snap.shape == (1600,)

    def test_prebuffer_snapshot_content_is_tail(self):
        buf = make_buf(prebuffer_sec=0.1)
        all_data = ramp(4000)
        buf.push(all_data)
        snap = buf.prebuffer_snapshot()
        np.testing.assert_array_almost_equal(snap, all_data[-1600:])

    def test_prebuffer_does_not_consume(self):
        buf = make_buf(prebuffer_sec=0.1)
        buf.push(ramp(4000))
        buf.prebuffer_snapshot()
        assert buf.available() == 4000

    def test_prebuffer_smaller_than_buffer(self):
        buf = make_buf(prebuffer_sec=0.1)
        buf.push(ramp(100))  # less than prebuffer_samples
        snap = buf.prebuffer_snapshot()
        assert snap.shape == (100,)


# ── Clear ─────────────────────────────────────────────────────────────────────


class TestClear:
    def test_clear_empties_buffer(self):
        buf = make_buf()
        buf.push(ramp(512))
        buf.clear()
        assert buf.available() == 0

    def test_clear_then_push(self):
        buf = make_buf()
        buf.push(ramp(512))
        buf.clear()
        buf.push(ramp(100))
        assert buf.available() == 100


# ── Thread safety ─────────────────────────────────────────────────────────────


class TestThreadSafety:
    def test_concurrent_push_and_drain(self):
        buf = make_buf(max_buffer_sec=2.0)
        errors = []

        def producer():
            for _ in range(50):
                try:
                    buf.push(ramp(512))
                except Exception as e:
                    errors.append(e)

        def consumer():
            for _ in range(50):
                try:
                    buf.drain_segment(256)
                except Exception as e:
                    errors.append(e)

        threads = [
            threading.Thread(target=producer),
            threading.Thread(target=consumer),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Thread errors: {errors}"

    def test_concurrent_pushes(self):
        buf = make_buf(max_buffer_sec=5.0)
        n_threads = 4
        errors = []

        def push_worker():
            try:
                for _ in range(25):
                    buf.push(np.zeros(512, dtype=np.float32))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=push_worker) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        # 4 threads * 25 pushes * 512 = 51200 samples, capped at max_samples
        assert buf.available() <= buf.max_samples
