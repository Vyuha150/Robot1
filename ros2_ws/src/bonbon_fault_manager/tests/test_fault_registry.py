"""Tests for bonbon_fault_manager.core.fault_registry."""

from __future__ import annotations

import pytest
from bonbon_fault_manager.core.fault_registry import FaultRegistry
from bonbon_fault_manager.core.fault_taxonomy import FaultLevel


def _clock_seq(*values):
    it = iter(values)
    return lambda: next(it)


class TestUpdateFromHalFault:
    def test_new_fault_creates_record(self):
        reg = FaultRegistry(clock=_clock_seq(1.0))
        rec = reg.update_from_hal_fault("microphone", "USB_DISCONNECTED", "USB gone", severity=2)
        assert rec.component_id == "microphone"
        assert rec.subsystem == "audio"
        assert rec.affected_pi == "pi2"
        assert rec.fault_level == FaultLevel.CRITICAL
        assert rec.occurrence_count == 1
        assert rec.dashboard_visible is True

    def test_repeated_fault_increments_occurrence(self):
        reg = FaultRegistry(clock=_clock_seq(1.0, 2.0, 3.0))
        reg.update_from_hal_fault("lidar", "HEALTH_ERROR", "bad", severity=2)
        reg.update_from_hal_fault("lidar", "HEALTH_ERROR", "bad again", severity=2)
        rec = reg.update_from_hal_fault("lidar", "HEALTH_ERROR", "bad again 2", severity=2)
        assert rec.occurrence_count == 3
        assert rec.last_seen == 3.0

    def test_recovery_resets_level_to_ok_but_keeps_occurrence(self):
        reg = FaultRegistry(clock=_clock_seq(1.0, 2.0))
        reg.update_from_hal_fault("camera", "READ_ERROR", "bad", severity=2)
        rec = reg.update_from_hal_fault(
            "camera", "RECOVERED", "back", severity=0, is_recovered=True
        )
        assert rec.fault_level == FaultLevel.OK
        assert rec.dashboard_visible is False
        assert rec.occurrence_count == 1  # not incremented on recovery

    def test_ok_level_is_not_dashboard_visible(self):
        reg = FaultRegistry(clock=_clock_seq(1.0))
        rec = reg.update_from_hal_fault("camera", "ANY", "back", severity=0, is_recovered=True)
        assert rec.dashboard_visible is False

    def test_custom_component_id_overrides_device_default(self):
        reg = FaultRegistry(clock=_clock_seq(1.0))
        rec = reg.update_from_hal_fault(
            "stepper", "STALLED", "joint 1", severity=2, component_id="stepper_head_pan"
        )
        assert rec.component_id == "stepper_head_pan"
        assert reg.get("stepper_head_pan") is not None
        assert reg.get("stepper") is None


class TestDegradedModuleSync:
    def test_new_degraded_modules_are_tracked(self):
        reg = FaultRegistry(clock=_clock_seq(1.0, 1.0))
        reg.sync_degraded_modules(["perception_ai", "llm_orchestrator"], reason="pi2 link lost")
        assert reg.get("safety:perception_ai").fault_level == FaultLevel.DEGRADED
        assert reg.get("safety:llm_orchestrator").fault_level == FaultLevel.DEGRADED

    def test_module_no_longer_listed_is_cleared(self):
        reg = FaultRegistry(clock=_clock_seq(1.0, 2.0))
        reg.sync_degraded_modules(["perception_ai"])
        reg.sync_degraded_modules([])  # recovered
        assert reg.get("safety:perception_ai") is None

    def test_still_listed_module_is_not_cleared(self):
        reg = FaultRegistry(clock=_clock_seq(1.0, 2.0))
        reg.sync_degraded_modules(["perception_ai"])
        reg.sync_degraded_modules(["perception_ai"])
        rec = reg.get("safety:perception_ai")
        assert rec is not None
        assert rec.occurrence_count == 2


class TestSafetySupervisor:
    def test_normal_state_is_ok(self):
        reg = FaultRegistry(clock=_clock_seq(1.0))
        rec = reg.update_safety_supervisor("NORMAL", "", requires_manual_reset=False)
        assert rec.fault_level == FaultLevel.OK
        assert rec.dashboard_visible is False

    def test_danger_state_is_fault(self):
        reg = FaultRegistry(clock=_clock_seq(1.0))
        rec = reg.update_safety_supervisor(
            "DANGER", "person too close", requires_manual_reset=False
        )
        assert rec.fault_level == FaultLevel.FAULT
        assert "person too close" in rec.message

    def test_safe_stop_is_critical(self):
        reg = FaultRegistry(clock=_clock_seq(1.0))
        rec = reg.update_safety_supervisor("SAFE_STOP", "estop", requires_manual_reset=False)
        assert rec.fault_level == FaultLevel.CRITICAL

    def test_requires_manual_reset_forces_blocked_regardless_of_state(self):
        reg = FaultRegistry(clock=_clock_seq(1.0))
        rec = reg.update_safety_supervisor("NORMAL", "", requires_manual_reset=True)
        assert rec.fault_level == FaultLevel.BLOCKED
        assert "MANUAL reset" in rec.recovery_action

    def test_unknown_state_name_falls_back_to_degraded(self):
        reg = FaultRegistry(clock=_clock_seq(1.0))
        rec = reg.update_safety_supervisor("SOME_NEW_STATE", "", requires_manual_reset=False)
        assert rec.fault_level == FaultLevel.DEGRADED


class TestUpdateFromPiLinkEvent:
    def test_non_pi_link_trigger_is_ignored(self):
        reg = FaultRegistry(clock=_clock_seq(1.0))
        rec = reg.update_from_pi_link_event("some_other_trigger", "irrelevant", "lost")
        assert rec is None
        assert reg.snapshot() == []

    def test_lost_peer_creates_critical_record(self):
        reg = FaultRegistry(clock=_clock_seq(1.0))
        rec = reg.update_from_pi_link_event(
            "pi_link_state_change", "pi3 observed pi2: stale -> lost", "lost"
        )
        assert rec is not None
        assert rec.component_id == "pi_link:pi2"
        assert rec.affected_pi == "pi2"
        assert rec.fault_level == FaultLevel.CRITICAL
        assert rec.dashboard_visible is True

    def test_stale_peer_creates_warning_record(self):
        reg = FaultRegistry(clock=_clock_seq(1.0))
        rec = reg.update_from_pi_link_event(
            "pi_link_state_change", "pi3 observed pi1: online -> stale", "stale"
        )
        assert rec.fault_level == FaultLevel.WARNING

    def test_peer_back_online_removes_the_record(self):
        reg = FaultRegistry(clock=_clock_seq(1.0, 2.0))
        reg.update_from_pi_link_event(
            "pi_link_state_change", "pi3 observed pi2: stale -> lost", "lost"
        )
        rec = reg.update_from_pi_link_event(
            "pi_link_state_change", "pi3 observed pi2: lost -> online", "online"
        )
        assert rec is None
        assert reg.get("pi_link:pi2") is None

    def test_repeated_loss_increments_occurrence(self):
        reg = FaultRegistry(clock=_clock_seq(1.0, 2.0, 3.0))
        reg.update_from_pi_link_event(
            "pi_link_state_change", "pi3 observed pi2: online -> stale", "stale"
        )
        reg.update_from_pi_link_event(
            "pi_link_state_change", "pi3 observed pi2: stale -> lost", "lost"
        )
        rec = reg.update_from_pi_link_event(
            "pi_link_state_change", "pi3 observed pi2: stale -> lost", "lost"
        )
        assert rec.occurrence_count == 3

    def test_unparseable_description_falls_back_honestly_not_a_guess(self):
        reg = FaultRegistry(clock=_clock_seq(1.0))
        rec = reg.update_from_pi_link_event("pi_link_state_change", "garbled text", "lost")
        assert rec.component_id == "pi_link:unknown_peer"
        assert rec.affected_pi == "unknown_peer"

    def test_two_different_peers_tracked_independently(self):
        reg = FaultRegistry(clock=_clock_seq(1.0, 2.0))
        reg.update_from_pi_link_event(
            "pi_link_state_change", "pi3 observed pi1: online -> lost", "lost"
        )
        reg.update_from_pi_link_event(
            "pi_link_state_change", "pi3 observed pi2: online -> lost", "lost"
        )
        ids = {r.component_id for r in reg.snapshot()}
        assert ids == {"pi_link:pi1", "pi_link:pi2"}


class TestSnapshotAndWorstLevel:
    def test_empty_registry_worst_is_ok(self):
        reg = FaultRegistry()
        assert reg.worst_level() == FaultLevel.OK
        assert reg.snapshot() == []

    def test_worst_level_across_components(self):
        reg = FaultRegistry(clock=_clock_seq(1.0, 2.0, 3.0))
        reg.update_from_hal_fault("camera", "READ_ERROR", "x", severity=2)  # DEGRADED
        reg.update_from_hal_fault("estop", "GPIO_INIT_FAILED", "x", severity=2)  # BLOCKED
        reg.update_from_hal_fault("motor", "WRITE_ERROR", "x", severity=2)  # FAULT
        assert reg.worst_level() == FaultLevel.BLOCKED

    def test_snapshot_returns_all_records(self):
        reg = FaultRegistry(clock=_clock_seq(1.0, 2.0))
        reg.update_from_hal_fault("camera", "READ_ERROR", "x", severity=2)
        reg.update_from_hal_fault("motor", "WRITE_ERROR", "x", severity=2)
        ids = {r.component_id for r in reg.snapshot()}
        assert ids == {"camera", "motor"}


if __name__ == "__main__":
    pytest.main([__file__])
