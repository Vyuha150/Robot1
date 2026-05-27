"""
tests/test_frame_throttler.py
==============================
Unit tests for bonbon_vision.preprocessing.frame_throttler.FrameThrottler.

Covers
------
* First call always accepted (burst=1 means one free token)
* Rapid successive calls are throttled (only ~target_hz accepted per second)
* set_rate() changes the processing rate at runtime
* drop_rate property reflects correct fraction
* stats dict returns correct counts
* reset_stats() zeros counters
* Thread-safety: concurrent should_process calls from N threads
* Invalid target_hz raises ValueError
* Burst > 1 allows initial burst of N consecutive accepts
"""

import threading
import unittest

from bonbon_vision.preprocessing.frame_throttler import FrameThrottler


class TestFirstCall(unittest.TestCase):
    def test_first_call_accepted(self):
        """Token bucket starts full; first call must always succeed."""
        t = FrameThrottler(target_hz=10.0)
        self.assertTrue(t.should_process())

    def test_second_immediate_call_dropped(self):
        """No time passes → no refill → second call dropped."""
        t = FrameThrottler(target_hz=10.0)
        t.should_process()  # consume the initial token
        result = t.should_process()
        self.assertFalse(result)


class TestThrottling(unittest.TestCase):
    def test_only_target_rate_accepted_over_one_second(self):
        """
        Simulate 100 calls in ~1 s with time.monotonic manipulation.
        We monkey-patch time.monotonic inside the throttler instance so we
        can control elapsed time deterministically.
        """
        import bonbon_vision.preprocessing.frame_throttler as _mod

        ticks = [0.0]

        def fake_monotonic():
            return ticks[0]

        original = _mod.time.monotonic
        _mod.time.monotonic = fake_monotonic
        try:
            t = FrameThrottler(target_hz=10.0)
            processed = 0
            for i in range(100):
                ticks[0] = i * 0.01  # advance 10 ms per call (= 100 Hz offer rate)
                if t.should_process():
                    processed += 1

            # Should be approximately 10 processed in 1 s (plus initial burst of 1)
            self.assertGreaterEqual(processed, 9)
            self.assertLessEqual(processed, 12)
        finally:
            _mod.time.monotonic = original

    def test_drop_rate_close_to_expected(self):
        """Offer at 30 Hz target 10 Hz → ~67% drop rate."""
        import bonbon_vision.preprocessing.frame_throttler as _mod

        ticks = [0.0]

        def fake_monotonic():
            return ticks[0]

        original = _mod.time.monotonic
        _mod.time.monotonic = fake_monotonic
        try:
            t = FrameThrottler(target_hz=10.0)
            for i in range(300):
                ticks[0] = i * (1.0 / 30.0)  # 30 Hz offer rate
                t.should_process()

            # drop rate should be ~67%
            self.assertGreater(t.drop_rate, 0.60)
            self.assertLess(t.drop_rate, 0.75)
        finally:
            _mod.time.monotonic = original


class TestSetRate(unittest.TestCase):
    def test_set_rate_changes_interval(self):
        t = FrameThrottler(target_hz=10.0)
        t.set_rate(20.0)
        self.assertAlmostEqual(t._interval, 0.05, places=4)

    def test_set_rate_zero_raises(self):
        t = FrameThrottler(target_hz=10.0)
        with self.assertRaises(ValueError):
            t.set_rate(0.0)

    def test_set_rate_negative_raises(self):
        t = FrameThrottler(target_hz=10.0)
        with self.assertRaises(ValueError):
            t.set_rate(-5.0)

    def test_init_zero_hz_raises(self):
        with self.assertRaises(ValueError):
            FrameThrottler(target_hz=0.0)


class TestStats(unittest.TestCase):
    def test_stats_after_two_calls(self):
        t = FrameThrottler(target_hz=10.0)
        t.should_process()  # True
        t.should_process()  # False
        s = t.stats
        self.assertEqual(s["offered"], 2)
        self.assertEqual(s["processed"], 1)
        self.assertEqual(s["dropped"], 1)

    def test_drop_rate_zero_initially(self):
        t = FrameThrottler(target_hz=10.0)
        self.assertAlmostEqual(t.drop_rate, 0.0)

    def test_drop_rate_after_all_drops(self):
        t = FrameThrottler(target_hz=1.0)
        t.should_process()  # consume token
        for _ in range(9):
            t.should_process()  # all dropped
        self.assertAlmostEqual(t.drop_rate, 9.0 / 10.0, delta=0.01)

    def test_reset_stats(self):
        t = FrameThrottler(target_hz=10.0)
        for _ in range(5):
            t.should_process()
        t.reset_stats()
        s = t.stats
        self.assertEqual(s["offered"], 0)
        self.assertEqual(s["processed"], 0)
        self.assertEqual(s["dropped"], 0)


class TestBurst(unittest.TestCase):
    def test_burst_allows_initial_multiple_accepts(self):
        """burst=3 should allow 3 consecutive accepts without time passing."""
        t = FrameThrottler(target_hz=10.0, burst=3)
        results = [t.should_process() for _ in range(5)]
        # First 3 should be True
        self.assertEqual(results[:3], [True, True, True])
        # 4th and 5th should be False
        self.assertFalse(results[3])
        self.assertFalse(results[4])

    def test_burst_defaults_to_one(self):
        t = FrameThrottler(target_hz=10.0)
        t.should_process()  # uses the 1 token
        self.assertFalse(t.should_process())


class TestThreadSafety(unittest.TestCase):
    def test_concurrent_should_process_no_race(self):
        """
        50 threads each call should_process once; processed + dropped must
        equal 50 and the bucket must never have more tokens than the burst.
        """
        t = FrameThrottler(target_hz=1000.0)  # very high rate to reduce drops
        results = []
        lock = threading.Lock()

        def worker():
            r = t.should_process()
            with lock:
                results.append(r)

        threads = [threading.Thread(target=worker) for _ in range(50)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()

        self.assertEqual(len(results), 50)
        s = t.stats
        self.assertEqual(s["offered"], 50)
        self.assertEqual(s["processed"] + s["dropped"], 50)

    def test_tokens_never_exceed_burst(self):
        """Internal token count must never exceed burst capacity."""
        import bonbon_vision.preprocessing.frame_throttler as _mod

        tick = [0.0]
        original = _mod.time.monotonic

        def fake_mono():
            return tick[0]

        _mod.time.monotonic = fake_mono
        try:
            t = FrameThrottler(target_hz=5.0, burst=2)
            tick[0] = 100.0  # large time jump
            t.should_process()  # triggers refill, then consumes 1 token
            with t._lock:
                self.assertLessEqual(t._tokens, float(t._burst))
        finally:
            _mod.time.monotonic = original


if __name__ == "__main__":
    unittest.main()
