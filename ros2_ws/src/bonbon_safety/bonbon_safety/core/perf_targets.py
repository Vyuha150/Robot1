"""Canonical performance-budget catalogue for the BonBon robot.

The measurable latency targets are defined once here as :class:`PerfBudget`
data, so benchmarks, latency tests and runtime budget checks all reference the
same numbers. Tests assert the catalogue covers every required target.

Targets (from the performance requirements)
-------------------------------------------
  behavior decision            ≤ 100 ms
  safety validation            ≤  50 ms   (critical)
  actuation validation         ≤  50 ms   (critical)
  gesture event                ≤ 150 ms
  spatial reasoning update     ≤ 100 ms
  emergency stop reaction      ≤ 300 ms   (critical)
  dashboard status response    ≤ 100 ms
  database simple write        ≤ 100 ms
  RAG query                    ≤ 500 ms
  TTS emergency announcement   ≤ 500 ms   (critical)
"""

from __future__ import annotations

from typing import Dict

from bonbon_safety.core.perf_monitor import PerfBudget

# name → PerfBudget. Names match the LatencyTracker names used in benchmarks.
_TARGETS = [
    PerfBudget("behavior_decision",       100.0, "p95"),
    PerfBudget("safety_validation",        50.0, "p95", critical=True),
    PerfBudget("actuation_validation",     50.0, "p95", critical=True),
    PerfBudget("gesture_event",           150.0, "p95"),
    PerfBudget("spatial_reasoning_update",100.0, "p95"),
    PerfBudget("emergency_stop_reaction", 300.0, "p99", critical=True),
    PerfBudget("dashboard_status",        100.0, "p95"),
    PerfBudget("database_write",          100.0, "p95"),
    PerfBudget("rag_query",               500.0, "p95"),
    PerfBudget("tts_emergency",           500.0, "p99", critical=True),
]


def build_targets() -> Dict[str, PerfBudget]:
    """Return the full {name: PerfBudget} performance-target registry."""
    return {b.name: b for b in _TARGETS}


def critical_targets() -> Dict[str, PerfBudget]:
    """Return only the safety-critical budgets."""
    return {b.name: b for b in _TARGETS if b.critical}
