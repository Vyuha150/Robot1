"""
test_reconnect_policy.py
========================
Tests for ReconnectPolicy exponential backoff.
"""

from __future__ import annotations

import time

from bonbon_hal.base.reconnect_policy import ReconnectConfig, ReconnectPolicy


def _policy(max_attempts=3, base=1.0, max_d=10.0, factor=2.0, cooldown=0.1) -> ReconnectPolicy:
    cfg = ReconnectConfig(
        max_attempts=max_attempts,
        base_delay_sec=base,
        max_delay_sec=max_d,
        backoff_factor=factor,
        cooldown_sec=cooldown,
    )
    return ReconnectPolicy("test_device", cfg)


class TestReconnectPolicy:
    def test_can_attempt_initially(self):
        p = _policy()
        assert p.should_attempt() is True

    def test_delays_increase_with_backoff(self):
        p = _policy(base=1.0, factor=2.0)
        d0 = p.next_wait_sec()
        p.record_failure()
        d1 = p.next_wait_sec()
        p.record_failure()
        d2 = p.next_wait_sec()
        # With jitter, just check rough ordering
        assert d1 > d0 * 0.5
        assert d2 > d1 * 0.5

    def test_delay_capped_at_max(self):
        p = _policy(base=1.0, max_d=5.0, factor=100.0)
        for _ in range(10):
            p.record_failure()
        # delay must not massively exceed max (jitter can add ±10%)
        assert p.next_wait_sec() <= 5.0 * 1.15

    def test_exhausted_after_max_attempts(self):
        p = _policy(max_attempts=3)
        for _ in range(3):
            p.record_failure()
        assert p.should_attempt() is False
        assert p.exhausted() is True

    def test_success_resets_counter(self):
        p = _policy(max_attempts=3)
        p.record_failure()
        p.record_failure()
        p.record_success()
        assert p.attempt_count == 0
        assert p.should_attempt() is True
        assert not p.exhausted()

    def test_cooldown_allows_retry_after_expiry(self):
        p = _policy(max_attempts=2, cooldown=0.05)
        p.record_failure()
        p.record_failure()
        assert p.should_attempt() is False
        time.sleep(0.1)  # wait for cooldown
        assert p.should_attempt() is True

    def test_unlimited_attempts(self):
        p = ReconnectPolicy("dev", ReconnectConfig(max_attempts=0))
        for _ in range(100):
            p.record_failure()
        assert p.should_attempt() is True

    def test_reset_clears_gave_up(self):
        p = _policy(max_attempts=1)
        p.record_failure()
        assert p.exhausted()
        p.reset()
        assert not p.exhausted()
        assert p.should_attempt()

    def test_jitter_produces_different_values(self):
        p = _policy(base=1.0)
        delays = {p.next_wait_sec() for _ in range(20)}
        # With jitter there should be variation
        assert len(delays) > 1
