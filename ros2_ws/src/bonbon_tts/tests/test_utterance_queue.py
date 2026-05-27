"""
tests/test_utterance_queue.py
==============================
Unit tests for UtteranceQueue, Utterance, and Priority.
"""

import time

import pytest
from bonbon_tts.core.utterance_queue import Priority, Utterance, UtteranceQueue

# ── Priority ──────────────────────────────────────────────────────────────────


class TestPriority:
    def test_ordering(self):
        assert Priority.EMERGENCY < Priority.HIGH
        assert Priority.HIGH < Priority.NORMAL
        assert Priority.NORMAL < Priority.LOW

    def test_values(self):
        assert Priority.EMERGENCY == 0
        assert Priority.HIGH == 1
        assert Priority.NORMAL == 2
        assert Priority.LOW == 3


# ── Utterance ─────────────────────────────────────────────────────────────────


class TestUtterance:
    def test_defaults(self):
        u = Utterance(text="Hello")
        assert u.priority == Priority.NORMAL
        assert u.source == ""
        assert u.dedup_key == ""
        assert u.interrupt is False
        assert u.max_age_sec == pytest.approx(30.0)
        assert len(u.utterance_id) == 8

    def test_unique_ids(self):
        ids = {Utterance(text=str(i)).utterance_id for i in range(100)}
        assert len(ids) == 100

    def test_not_stale_fresh(self):
        u = Utterance(text="x", max_age_sec=30.0)
        assert not u.is_stale()

    def test_stale_when_expired(self):
        u = Utterance(text="x", max_age_sec=0.01)
        time.sleep(0.05)
        assert u.is_stale()

    def test_never_stale_when_zero(self):
        u = Utterance(text="x", max_age_sec=0.0)
        assert not u.is_stale()

    def test_lt_by_priority(self):
        high = Utterance(text="h", priority=Priority.HIGH)
        normal = Utterance(text="n", priority=Priority.NORMAL)
        assert high < normal

    def test_lt_same_priority_fifo(self):
        u1 = Utterance(text="first")
        time.sleep(0.001)
        u2 = Utterance(text="second")
        assert u1 < u2  # older = higher priority (FIFO)

    def test_eq_by_id(self):
        u = Utterance(text="x")
        assert u == u
        assert u != Utterance(text="x")  # different id

    def test_eq_not_implemented_for_non_utterance(self):
        u = Utterance(text="x")
        # __eq__ returns NotImplemented for non-Utterance types.
        # The == operator itself returns False (Python handles NotImplemented
        # internally), so we call __eq__ directly to verify the sentinel.
        assert Utterance.__eq__(u, "string") is NotImplemented
        assert u != "string"


# ── UtteranceQueue ────────────────────────────────────────────────────────────


class TestUtteranceQueueBasic:
    def test_empty_on_creation(self):
        q = UtteranceQueue()
        assert q.is_empty()
        assert q.depth() == 0

    def test_enqueue_dequeue(self):
        q = UtteranceQueue()
        u = Utterance(text="Hello")
        q.enqueue(u)
        assert q.depth() == 1
        out = q.dequeue()
        assert out is not None
        assert out.text == "Hello"
        assert q.is_empty()

    def test_dequeue_empty_returns_none(self):
        q = UtteranceQueue()
        assert q.dequeue() is None

    def test_priority_ordering(self):
        q = UtteranceQueue()
        q.enqueue(Utterance(text="low", priority=Priority.LOW))
        q.enqueue(Utterance(text="high", priority=Priority.HIGH))
        q.enqueue(Utterance(text="normal", priority=Priority.NORMAL))
        q.enqueue(Utterance(text="emergency", priority=Priority.EMERGENCY))

        texts = [q.dequeue().text for _ in range(4)]
        assert texts == ["emergency", "high", "normal", "low"]

    def test_same_priority_fifo(self):
        q = UtteranceQueue()
        for i in range(5):
            q.enqueue(Utterance(text=str(i), priority=Priority.NORMAL))
            time.sleep(0.001)

        texts = [q.dequeue().text for _ in range(5)]
        assert texts == ["0", "1", "2", "3", "4"]

    def test_emergency_sets_interrupt(self):
        q = UtteranceQueue()
        utt = Utterance(text="alert", priority=Priority.EMERGENCY, interrupt=False)
        flag = q.enqueue(utt)
        assert flag is True  # enqueue returns True for interrupt
        assert utt.interrupt is True

    def test_non_interrupt_returns_false(self):
        q = UtteranceQueue()
        utt = Utterance(text="normal", priority=Priority.NORMAL)
        flag = q.enqueue(utt)
        assert flag is False


class TestUtteranceQueueStaleness:
    def test_stale_item_skipped(self):
        q = UtteranceQueue()
        stale = Utterance(text="stale", max_age_sec=0.01)
        fresh = Utterance(text="fresh", max_age_sec=30.0, priority=Priority.LOW)

        q.enqueue(stale)
        time.sleep(0.05)  # let stale expire
        q.enqueue(fresh)

        out = q.dequeue()
        # stale had NORMAL priority (higher); but it expired → should be dropped
        assert out is not None
        assert out.text == "fresh"

    def test_all_stale_returns_none(self):
        q = UtteranceQueue()
        q.enqueue(Utterance(text="x", max_age_sec=0.01))
        time.sleep(0.05)
        assert q.dequeue() is None


class TestUtteranceQueueDedup:
    def test_dedup_replaces_old(self):
        q = UtteranceQueue()
        q.enqueue(Utterance(text="v1", dedup_key="batt"))
        q.enqueue(Utterance(text="v2", dedup_key="batt"))
        assert q.depth() == 1
        out = q.dequeue()
        assert out.text == "v2"

    def test_dedup_different_keys_kept(self):
        q = UtteranceQueue()
        q.enqueue(Utterance(text="a", dedup_key="x"))
        q.enqueue(Utterance(text="b", dedup_key="y"))
        assert q.depth() == 2

    def test_no_dedup_key_not_replaced(self):
        q = UtteranceQueue()
        q.enqueue(Utterance(text="a"))
        q.enqueue(Utterance(text="b"))
        assert q.depth() == 2

    def test_dedup_disabled(self):
        q = UtteranceQueue(dedup_enabled=False)
        q.enqueue(Utterance(text="v1", dedup_key="batt"))
        q.enqueue(Utterance(text="v2", dedup_key="batt"))
        assert q.depth() == 2


class TestUtteranceQueueOverflow:
    def test_overflow_drops_lowest(self):
        q = UtteranceQueue(max_depth=3)
        q.enqueue(Utterance(text="low", priority=Priority.LOW))
        q.enqueue(Utterance(text="normal", priority=Priority.NORMAL))
        q.enqueue(Utterance(text="high", priority=Priority.HIGH))
        # Queue now full; adding another LOW drops the existing LOW
        q.enqueue(Utterance(text="low2", priority=Priority.LOW))

        assert q.depth() == 3
        assert q.overflow_count >= 1

        texts = [q.dequeue().text for _ in range(3)]
        assert "high" in texts
        assert "normal" in texts
        # The newest LOW (low2) should survive, original LOW dropped
        assert "low" not in texts or "low2" in texts

    def test_overflow_count_increments(self):
        q = UtteranceQueue(max_depth=2)
        for i in range(5):
            q.enqueue(Utterance(text=str(i)))
        assert q.overflow_count == 3


class TestUtteranceQueueBulk:
    def test_clear_returns_count(self):
        q = UtteranceQueue()
        for i in range(5):
            q.enqueue(Utterance(text=str(i)))
        dropped = q.clear()
        assert dropped == 5
        assert q.is_empty()

    def test_clear_below_priority_drops_low(self):
        q = UtteranceQueue()
        q.enqueue(Utterance(text="high", priority=Priority.HIGH))
        q.enqueue(Utterance(text="normal", priority=Priority.NORMAL))
        q.enqueue(Utterance(text="low", priority=Priority.LOW))

        dropped = q.clear_below_priority(Priority.NORMAL)
        assert dropped == 1  # only LOW dropped
        assert q.depth() == 2

    def test_peek_priority_highest(self):
        q = UtteranceQueue()
        q.enqueue(Utterance(text="n", priority=Priority.NORMAL))
        q.enqueue(Utterance(text="h", priority=Priority.HIGH))
        assert q.peek_priority() == Priority.HIGH

    def test_peek_priority_empty(self):
        q = UtteranceQueue()
        assert q.peek_priority() is None


class TestUtteranceQueueThreadSafety:
    def test_concurrent_enqueue_dequeue(self):
        """Smoke-test: concurrent producers and a consumer should not crash."""
        import threading

        q = UtteranceQueue(max_depth=50)
        errors = []
        results = []
        stop = threading.Event()

        def producer(n: int):
            for i in range(n):
                try:
                    q.enqueue(Utterance(text=f"p{i}"))
                except Exception as exc:
                    errors.append(exc)

        def consumer():
            while not stop.is_set() or not q.is_empty():
                utt = q.dequeue()
                if utt:
                    results.append(utt.text)
                time.sleep(0.001)

        threads = [threading.Thread(target=producer, args=(20,)) for _ in range(5)]
        ct = threading.Thread(target=consumer)
        ct.start()
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        stop.set()
        ct.join(timeout=2.0)

        assert not errors
        # All produced (100 total) but overflow may drop some
        assert len(results) <= 100
