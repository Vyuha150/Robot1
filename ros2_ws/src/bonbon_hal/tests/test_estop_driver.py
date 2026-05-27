"""
test_estop_driver.py
====================
Tests for MockEstopDriver: press/release, relay control, callbacks, recovery.
"""

from __future__ import annotations

import pytest
from bonbon_hal.base.driver_base import DriverFault
from bonbon_hal.drivers.estop import EstopState, MockEstopDriver


@pytest.fixture
def drv() -> MockEstopDriver:
    d = MockEstopDriver()
    d.connect()
    return d


class TestMockEstopNormal:
    def test_connect_ok(self, drv):
        assert drv.is_connected

    def test_initial_state_not_pressed(self, drv):
        s = drv.read_state()
        assert s.pressed is False
        assert s.relay_asserted is False

    def test_press_changes_state(self, drv):
        drv.press()
        s = drv.read_state()
        assert s.pressed is True

    def test_release_clears_state(self, drv):
        drv.press()
        drv.release()
        s = drv.read_state()
        assert s.pressed is False

    def test_assert_relay(self, drv):
        drv.assert_relay()
        s = drv.read_state()
        assert s.relay_asserted is True

    def test_deassert_relay(self, drv):
        drv.assert_relay()
        drv.deassert_relay()
        s = drv.read_state()
        assert s.relay_asserted is False


class TestEstopCallbacks:
    def test_press_fires_callback(self, drv):
        events = []
        drv.register_press_callback(lambda p: events.append(p))
        drv.press()
        assert events == [True]

    def test_release_fires_callback(self, drv):
        events = []
        drv.press()
        drv.register_press_callback(lambda p: events.append(p))
        drv.release()
        assert events == [False]

    def test_double_press_fires_once(self, drv):
        events = []
        drv.register_press_callback(lambda p: events.append(p))
        drv.press()
        drv.press()  # already pressed — should not fire again
        assert len(events) == 1

    def test_double_release_fires_once(self, drv):
        events = []
        drv.press()
        drv.register_press_callback(lambda p: events.append(p))
        drv.release()
        drv.release()  # already released
        assert len(events) == 1


class TestEstopFaults:
    def test_read_without_connect_raises(self):
        drv = MockEstopDriver()
        with pytest.raises(DriverFault) as exc:
            drv.read_state()
        assert exc.value.error_code == "NOT_CONNECTED"

    def test_start_pressed(self):
        drv = MockEstopDriver(start_pressed=True)
        drv.connect()
        s = drv.read_state()
        assert s.pressed is True

    def test_start_disconnected(self):
        drv = MockEstopDriver(start_disconnected=True)
        ok = drv.connect()
        assert ok is False

    def test_relay_assert_fails_when_not_connected(self):
        drv = MockEstopDriver()
        with pytest.raises(DriverFault):
            drv.assert_relay()

    def test_relay_deassert_fails_when_not_connected(self):
        drv = MockEstopDriver()
        with pytest.raises(DriverFault):
            drv.deassert_relay()


class TestEstopRecovery:
    def test_reconnect_after_disconnect(self):
        drv = MockEstopDriver()
        drv.connect()
        drv.disconnect()
        ok = drv.reconnect()
        assert ok
        s = drv.read_state()
        assert isinstance(s, EstopState)

    def test_relay_state_preserved_across_read(self, drv):
        drv.assert_relay()
        s1 = drv.read_state()
        s2 = drv.read_state()
        assert s1.relay_asserted is True
        assert s2.relay_asserted is True

    def test_full_press_relay_release_sequence(self, drv):
        # Press button → assert relay
        drv.press()
        drv.assert_relay()
        s = drv.read_state()
        assert s.pressed and s.relay_asserted

        # Operator physically releases button
        drv.release()
        # System de-asserts relay after reset
        drv.deassert_relay()
        s = drv.read_state()
        assert not s.pressed and not s.relay_asserted
