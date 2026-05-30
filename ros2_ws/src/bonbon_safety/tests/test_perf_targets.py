"""Integrity tests for the performance-target catalogue."""

from __future__ import annotations

from bonbon_safety.core.perf_targets import build_targets, critical_targets

# The 10 required targets and their ceilings (ms).
_REQUIRED = {
    "behavior_decision": 100.0,
    "safety_validation": 50.0,
    "actuation_validation": 50.0,
    "gesture_event": 150.0,
    "spatial_reasoning_update": 100.0,
    "emergency_stop_reaction": 300.0,
    "dashboard_status": 100.0,
    "database_write": 100.0,
    "rag_query": 500.0,
    "tts_emergency": 500.0,
}


class TestTargets:
    def test_all_required_present(self):
        targets = build_targets()
        for name, ceiling in _REQUIRED.items():
            assert name in targets, f"missing target {name}"
            assert targets[name].budget_ms == ceiling

    def test_exactly_ten_targets(self):
        assert len(build_targets()) == 10

    def test_safety_paths_are_critical(self):
        crit = critical_targets()
        for name in ("safety_validation", "actuation_validation",
                     "emergency_stop_reaction", "tts_emergency"):
            assert name in crit, f"{name} should be critical"

    def test_non_safety_paths_not_critical(self):
        targets = build_targets()
        assert targets["dashboard_status"].critical is False
        assert targets["rag_query"].critical is False

    def test_emergency_uses_p99(self):
        # Worst-case tail matters for emergency reaction, not the median.
        assert build_targets()["emergency_stop_reaction"].metric == "p99"
