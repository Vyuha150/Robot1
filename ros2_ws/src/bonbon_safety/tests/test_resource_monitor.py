"""Unit tests for bonbon_safety.core.resource_monitor."""

from __future__ import annotations

from bonbon_safety.core.resource_monitor import ResourceMonitor


def _reader(cpu, mem, rss, disk):
    return lambda: (cpu, mem, rss, disk)


class TestSnapshot:
    def test_injected_reader_used(self):
        m = ResourceMonitor(reader=_reader(42.0, 30.0, 256.0, 80.0))
        s = m.sample()
        assert s.cpu_percent == 42.0
        assert s.memory_percent == 30.0
        assert s.memory_mb == 256.0
        assert s.disk_free_percent == 80.0
        assert s.available is True

    def test_read_failure_is_safe(self):
        def boom():
            raise RuntimeError("sensor gone")
        m = ResourceMonitor(reader=boom)
        s = m.sample()
        assert s.available is False
        assert s.cpu_percent == 0.0   # safe fallback, no crash


class TestFlags:
    def test_cpu_overload_flag(self):
        m = ResourceMonitor(reader=_reader(95.0, 20.0, 100.0, 90.0))
        assert m.sample().cpu_overloaded is True

    def test_memory_pressure_flag(self):
        m = ResourceMonitor(reader=_reader(10.0, 90.0, 100.0, 90.0))
        assert m.sample().memory_pressure is True

    def test_disk_low_flag(self):
        m = ResourceMonitor(reader=_reader(10.0, 20.0, 100.0, 5.0))
        assert m.sample().disk_low is True

    def test_nominal_no_flags(self):
        m = ResourceMonitor(reader=_reader(20.0, 30.0, 100.0, 80.0))
        s = m.sample()
        assert not (s.cpu_overloaded or s.memory_pressure or s.disk_low)


class TestLoadShed:
    def test_full_rate_when_idle(self):
        m = ResourceMonitor(reader=_reader(20.0, 30.0, 100.0, 90.0))
        m.sample()
        assert m.recommended_load_shed() == 1.0

    def test_halves_under_cpu_overload(self):
        m = ResourceMonitor(reader=_reader(95.0, 30.0, 100.0, 90.0))
        m.sample()
        assert m.recommended_load_shed() <= 0.5

    def test_reduces_under_memory_pressure(self):
        m = ResourceMonitor(reader=_reader(20.0, 88.0, 100.0, 90.0))
        m.sample()
        assert m.recommended_load_shed() <= 0.5
