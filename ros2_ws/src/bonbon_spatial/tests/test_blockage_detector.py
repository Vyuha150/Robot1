"""Unit tests for bonbon_spatial.core.blockage_detector."""

from __future__ import annotations

from dataclasses import dataclass

from bonbon_spatial.core.blockage_detector import BlockageDetector


@dataclass
class _E:
    entity_id: str
    x: float
    y: float


class _FakeClock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


class TestCorridorOccupancy:
    def test_clear_corridor_not_blocked(self):
        det = BlockageDetector()
        state = det.update([_E("a", 5.0, 0.0)])  # beyond corridor length
        assert state.is_blocked is False
        assert state.blocking_entity_ids == []

    def test_lateral_entity_not_in_corridor(self):
        det = BlockageDetector(corridor_half_width_m=0.5)
        state = det.update([_E("a", 1.0, 2.0)])  # too far to the side
        assert state.is_blocked is False

    def test_entity_behind_not_in_corridor(self):
        det = BlockageDetector()
        state = det.update([_E("a", -1.0, 0.0)])  # behind robot
        assert state.is_blocked is False


class TestPersistence:
    def test_transient_crossing_not_blockage(self):
        clock = _FakeClock()
        det = BlockageDetector(persistence_sec=1.5, clock=clock)
        # Person briefly in corridor, then gone.
        det.update([_E("a", 1.0, 0.0)])
        clock.advance(0.5)
        state = det.update([])  # person left
        assert state.is_blocked is False

    def test_sustained_occupancy_triggers_blockage(self):
        clock = _FakeClock()
        det = BlockageDetector(persistence_sec=1.5, clock=clock)
        det.update([_E("a", 1.0, 0.0)])           # t=0 occupied
        clock.advance(1.0)
        s1 = det.update([_E("a", 1.0, 0.0)])      # t=1.0, < threshold
        assert s1.is_blocked is False
        clock.advance(1.0)
        s2 = det.update([_E("a", 1.0, 0.0)])      # t=2.0, > threshold
        assert s2.is_blocked is True
        assert "a" in s2.blocking_entity_ids
        assert s2.occupied_duration_sec >= 1.5

    def test_clearing_resets_timer(self):
        clock = _FakeClock()
        det = BlockageDetector(persistence_sec=1.0, clock=clock)
        det.update([_E("a", 1.0, 0.0)])
        clock.advance(2.0)
        assert det.update([_E("a", 1.0, 0.0)]).is_blocked is True
        # Corridor clears, then re-occupies — timer must restart.
        det.update([])
        clock.advance(0.5)
        assert det.update([_E("a", 1.0, 0.0)]).is_blocked is False

    def test_reset_clears_state(self):
        clock = _FakeClock()
        det = BlockageDetector(persistence_sec=1.0, clock=clock)
        det.update([_E("a", 1.0, 0.0)])
        clock.advance(2.0)
        det.reset()
        # After reset the persistence timer restarts from now.
        assert det.update([_E("a", 1.0, 0.0)]).is_blocked is False
