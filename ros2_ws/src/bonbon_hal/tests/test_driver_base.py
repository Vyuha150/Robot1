"""
test_driver_base.py
===================
Tests for DriverBase, DriverHealth, DriverStatus, and DriverFault.
"""

from __future__ import annotations

import pytest
from bonbon_hal.base.driver_base import DriverBase, DriverFault, DriverHealth, DriverStatus


class _OkDriver(DriverBase):
    def __init__(self, **kw):
        super().__init__("test", **kw)

    def _do_connect(self) -> bool:
        return True

    def _do_disconnect(self) -> None:
        pass


class _FailDriver(DriverBase):
    def __init__(self):
        super().__init__("fail_dev")

    def _do_connect(self) -> bool:
        return False

    def _do_disconnect(self) -> None:
        pass


class _ExceptionDriver(DriverBase):
    def __init__(self):
        super().__init__("exc_dev")

    def _do_connect(self) -> bool:
        raise OSError("device not found")

    def _do_disconnect(self) -> None:
        pass


class TestDriverBase:
    def test_starts_disconnected(self):
        d = _OkDriver()
        assert d.status == DriverStatus.DISCONNECTED
        assert not d.is_connected

    def test_connect_ok(self):
        d = _OkDriver()
        ok = d.connect()
        assert ok is True
        assert d.is_connected
        assert d.status == DriverStatus.CONNECTED

    def test_connect_returns_false(self):
        d = _FailDriver()
        ok = d.connect()
        assert ok is False
        assert not d.is_connected
        assert d.status == DriverStatus.FAULTED

    def test_connect_raises_exception(self):
        d = _ExceptionDriver()
        ok = d.connect()
        assert ok is False
        assert d.status == DriverStatus.FAULTED
        assert "device not found" in (d.health.last_error or "")

    def test_disconnect_after_connect(self):
        d = _OkDriver()
        d.connect()
        d.disconnect()
        assert d.status == DriverStatus.DISCONNECTED
        assert not d.is_connected

    def test_shutdown_prevents_reconnect(self):
        d = _OkDriver()
        d.connect()
        d.shutdown()
        assert d.status == DriverStatus.SHUTDOWN
        with pytest.raises(DriverFault):
            d.connect()

    def test_reconnect_increments_count(self):
        d = _OkDriver()
        d.connect()
        ok = d.reconnect()
        assert ok is True
        assert d.health.reconnect_count == 1

    def test_context_manager(self):
        with _OkDriver() as d:
            assert d.is_connected
        assert d.status == DriverStatus.SHUTDOWN

    def test_fault_callback_fires(self):
        events = []
        d = _FailDriver()
        d.register_fault_callback(lambda dev, code, msg: events.append((dev, code)))
        d.connect()
        assert len(events) == 1
        assert events[0][0] == "fail_dev"

    def test_health_snapshot(self):
        d = _OkDriver()
        d.connect()
        h = d.health
        assert isinstance(h, DriverHealth)
        assert h.is_healthy is True
        assert h.status == DriverStatus.CONNECTED
        assert h.reconnect_count == 0

    def test_consecutive_errors_accumulate(self):
        d = _FailDriver()
        for _ in range(3):
            d.connect()
        assert d.health.consecutive_errors >= 3

    def test_record_success_resets_error_count(self):
        d = _OkDriver()
        d.connect()
        d._record_fault("ERR", "fake error")
        assert d.health.consecutive_errors > 0
        d._record_success()
        assert d.health.consecutive_errors == 0
