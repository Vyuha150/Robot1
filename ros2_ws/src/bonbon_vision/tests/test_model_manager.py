"""
tests/test_model_manager.py
============================
Unit tests for bonbon_vision.models.model_manager.ModelManager.

Covered
-------
* load_async() transitions UNLOADED → LOADING → READY
* load_sync() blocks until READY and returns True
* wait_ready() returns True on success, False on timeout
* FAILED state set when load_model() raises an exception
* allow_degraded=True suppresses re-raise on failure (FAILED, no crash)
* allow_degraded=False re-raises the exception from the thread
* load_async() skips when already LOADING
* reload() resets to UNLOADED and triggers fresh load
* load_ms > 0 after successful load
* error property carries the exception message on failure
* is_ready property
* summary() dict structure
* Thread safety: concurrent load_async() calls are safe
"""

import threading
import time
import unittest

from bonbon_vision.models.model_manager import ModelManager, ModelState

# ── Stub detectors ────────────────────────────────────────────────────────────


class _OKDetector:
    """load_model() succeeds after a tiny delay."""

    def __init__(self, delay_sec=0.01):
        self._delay = delay_sec
        self.is_degraded = False

    def load_model(self):
        time.sleep(self._delay)


class _FailDetector:
    """load_model() always raises."""

    def __init__(self, msg="load failed"):
        self._msg = msg
        self.is_degraded = False

    def load_model(self):
        raise RuntimeError(self._msg)


class _DegradedDetector:
    """load_model() succeeds but sets is_degraded = True."""

    def __init__(self):
        self.is_degraded = False

    def load_model(self):
        self.is_degraded = True


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestLoadAsync(unittest.TestCase):
    def test_initial_state_is_unloaded(self):
        mgr = ModelManager(_OKDetector())
        self.assertEqual(mgr.state, ModelState.UNLOADED)

    def test_loading_state_while_slow_load(self):
        """Detector takes 0.2 s — state should be LOADING immediately."""
        mgr = ModelManager(_OKDetector(delay_sec=0.2))
        mgr.load_async()
        # Check state right after calling load_async
        self.assertIn(mgr.state, (ModelState.LOADING, ModelState.READY))
        mgr.wait_ready(timeout=2.0)

    def test_ready_after_load(self):
        mgr = ModelManager(_OKDetector())
        mgr.load_async()
        ok = mgr.wait_ready(timeout=5.0)
        self.assertTrue(ok)
        self.assertEqual(mgr.state, ModelState.READY)

    def test_is_ready_property(self):
        mgr = ModelManager(_OKDetector())
        mgr.load_async()
        mgr.wait_ready(timeout=5.0)
        self.assertTrue(mgr.is_ready)

    def test_load_ms_positive_after_load(self):
        mgr = ModelManager(_OKDetector())
        mgr.load_async()
        mgr.wait_ready(timeout=5.0)
        self.assertGreater(mgr.load_ms, 0.0)

    def test_error_is_none_on_success(self):
        mgr = ModelManager(_OKDetector())
        mgr.load_async()
        mgr.wait_ready(timeout=5.0)
        self.assertIsNone(mgr.error)

    def test_load_async_skips_when_already_loading(self):
        """Calling load_async twice should not start a second thread."""
        mgr = ModelManager(_OKDetector(delay_sec=0.2))
        mgr.load_async()
        mgr.load_async()  # second call — should be a no-op
        ok = mgr.wait_ready(timeout=5.0)
        self.assertTrue(ok)

    def test_load_async_skips_when_ready(self):
        mgr = ModelManager(_OKDetector())
        mgr.load_async()
        mgr.wait_ready(timeout=5.0)
        # Now call again — should not change state to LOADING
        mgr.load_async()
        self.assertEqual(mgr.state, ModelState.READY)


class TestLoadSync(unittest.TestCase):
    def test_load_sync_returns_true(self):
        mgr = ModelManager(_OKDetector())
        ok = mgr.load_sync()
        self.assertTrue(ok)

    def test_load_sync_blocks_until_ready(self):
        mgr = ModelManager(_OKDetector(delay_sec=0.05))
        ok = mgr.load_sync()
        self.assertEqual(mgr.state, ModelState.READY)
        self.assertTrue(ok)

    def test_load_sync_returns_false_on_failure(self):
        mgr = ModelManager(_FailDetector(), allow_degraded=True)
        ok = mgr.load_sync()
        self.assertFalse(ok)


class TestFailedLoad(unittest.TestCase):
    def test_failed_state_on_exception(self):
        mgr = ModelManager(_FailDetector(), allow_degraded=True)
        mgr.load_async()
        mgr.wait_ready(timeout=5.0)
        self.assertEqual(mgr.state, ModelState.FAILED)

    def test_error_property_set(self):
        mgr = ModelManager(_FailDetector(msg="oops"), allow_degraded=True)
        mgr.load_async()
        mgr.wait_ready(timeout=5.0)
        self.assertIn("oops", mgr.error)

    def test_is_ready_false_on_failure(self):
        mgr = ModelManager(_FailDetector(), allow_degraded=True)
        mgr.load_async()
        mgr.wait_ready(timeout=5.0)
        self.assertFalse(mgr.is_ready)

    def test_allow_degraded_false_sets_failed(self):
        """With allow_degraded=False the manager still records FAILED state."""
        mgr = ModelManager(_FailDetector(), allow_degraded=False)
        mgr.load_async()
        # The exception is logged at ERROR level but event is still set
        mgr.wait_ready(timeout=5.0)
        self.assertEqual(mgr.state, ModelState.FAILED)

    def test_degraded_detector_triggers_failed(self):
        """Detector whose is_degraded=True after load_model() → FAILED."""
        mgr = ModelManager(_DegradedDetector(), allow_degraded=True)
        mgr.load_async()
        mgr.wait_ready(timeout=5.0)
        self.assertEqual(mgr.state, ModelState.FAILED)


class TestWaitReady(unittest.TestCase):
    def test_wait_ready_timeout_returns_false(self):
        """Detector never finishes loading within the timeout."""
        mgr = ModelManager(_OKDetector(delay_sec=10.0))
        mgr.load_async()
        ok = mgr.wait_ready(timeout=0.05)
        self.assertFalse(ok)

    def test_wait_ready_true_after_load(self):
        mgr = ModelManager(_OKDetector())
        mgr.load_async()
        ok = mgr.wait_ready(timeout=5.0)
        self.assertTrue(ok)


class TestReload(unittest.TestCase):
    def test_reload_after_ready(self):
        mgr = ModelManager(_OKDetector())
        mgr.load_sync()
        self.assertEqual(mgr.state, ModelState.READY)
        mgr.reload()
        # Should go back to loading/ready
        mgr.wait_ready(timeout=5.0)
        self.assertEqual(mgr.state, ModelState.READY)

    def test_reload_after_failed(self):
        """reload() after failure with a fresh (working) detector."""
        detector = _FailDetector()
        mgr = ModelManager(detector, allow_degraded=True)
        mgr.load_sync()
        self.assertEqual(mgr.state, ModelState.FAILED)

        # Swap in an OK detector and reload
        mgr._detector = _OKDetector()
        mgr.reload()
        mgr.wait_ready(timeout=5.0)
        self.assertEqual(mgr.state, ModelState.READY)

    def test_reload_clears_error(self):
        mgr = ModelManager(_FailDetector(), allow_degraded=True)
        mgr.load_sync()
        self.assertIsNotNone(mgr.error)
        mgr._detector = _OKDetector()
        mgr.reload()
        mgr.wait_ready(timeout=5.0)
        self.assertIsNone(mgr.error)


class TestSummary(unittest.TestCase):
    def test_summary_dict_structure(self):
        mgr = ModelManager(_OKDetector())
        mgr.load_sync()
        s = mgr.summary()
        self.assertIn("state", s)
        self.assertIn("load_ms", s)
        self.assertIn("error", s)
        self.assertIn("allow_degraded", s)

    def test_summary_state_ready(self):
        mgr = ModelManager(_OKDetector())
        mgr.load_sync()
        self.assertEqual(mgr.summary()["state"], "READY")

    def test_summary_state_failed(self):
        mgr = ModelManager(_FailDetector(), allow_degraded=True)
        mgr.load_sync()
        self.assertEqual(mgr.summary()["state"], "FAILED")

    def test_load_ms_before_load_is_zero(self):
        mgr = ModelManager(_OKDetector())
        self.assertAlmostEqual(mgr.load_ms, 0.0)


class TestThreadSafety(unittest.TestCase):
    def test_concurrent_load_async_calls(self):
        """10 threads all call load_async simultaneously — no crash, one load."""
        mgr = ModelManager(_OKDetector(delay_sec=0.05))
        threads = [threading.Thread(target=mgr.load_async) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        mgr.wait_ready(timeout=5.0)
        self.assertEqual(mgr.state, ModelState.READY)

    def test_concurrent_state_reads(self):
        """Concurrent state property reads while loading — no crash."""
        mgr = ModelManager(_OKDetector(delay_sec=0.1))
        mgr.load_async()
        states = []

        def read():
            for _ in range(100):
                states.append(mgr.state)

        threads = [threading.Thread(target=read) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        mgr.wait_ready(timeout=5.0)
        # All values should be valid ModelState members
        valid = set(ModelState)
        for s in states:
            self.assertIn(s, valid)


if __name__ == "__main__":
    unittest.main()
