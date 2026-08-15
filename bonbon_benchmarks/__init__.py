"""System-wide efficiency benchmarking framework for BonBon.

Scope, deliberately bounded -- see docs/benchmarks/FINAL_EFFICIENCY_BENCHMARK_REPORT.md
for the full rationale: this package answers "is the small-model + smart-
routing + accelerator + caching + safety-separation architecture actually
faster, lighter, safer, and more stable than before," end to end across
every subsystem (resource usage, ROS2 topics, ASR/TTS/LLM/RAG, vision/
gesture/affective AI, safety-under-load, three-Pi networking, dashboard,
endurance). It is NOT a second edge-ai-runtime-layer benchmark and NOT a
second model-inference benchmark -- those already exist and are reused,
not reimplemented:

  - Task-routing / safety-separation / caching / resource-guard /
    accelerator-selection timing: `scripts/edge_ai/benchmark_edge_ai_stack.py`
    (unchanged, still the source of truth for that layer -- this package's
    Phase 4-6 tests exercise the same real classes for CORRECTNESS
    assertions, a different concern from that script's throughput numbers).
  - ASR/TTS/LLM/vision model-inference latency: `bonbon_ai_model_registry.
    model_benchmark_runner` (this package's `model_benchmark.py` adds
    N-iteration percentile statistics on top of its single-shot results,
    it does not re-invoke models a different way).
  - Percentile/latency-budget math: `bonbon_safety.core.perf_monitor`
    (`percentile()`, `LatencyTracker`, `PerfBudget`, `check_budget()`) and
    its canonical target catalogue `bonbon_safety.core.perf_targets`.
  - CPU/RAM/disk sampling: `bonbon_safety.core.resource_monitor.ResourceMonitor`.

Genuinely new, because nothing covered it: the standardized cross-module
BenchmarkMetric report schema (avg/p50/p90/p95/p99/max + pass/fail +
blocked-reason + recommendation), CPU-temperature sampling (no function
anywhere in the repo reads it), inter-Pi network latency (only clock
offset existed, via bonbon_distributed_network_monitor), safety-latency-
under-simulated-load (no such test existed), and dashboard-endpoint
latency benchmarking.

Pure Python, no rclpy/ROS2 import at module scope -- runs on a workstation
or CI, not only on the robot.
"""

from __future__ import annotations

import sys
from pathlib import Path

# The ROS2 packages this suite reuses (bonbon_safety's perf_monitor/
# resource_monitor, bonbon_edge_ai_runtime's task_router/cache_manager/
# resource_guard, bonbon_ai_model_registry's benchmark_runner) live under
# ros2_ws/src and are only importable once that path is on sys.path --
# same bootstrap pattern as scripts/edge_ai/benchmark_edge_ai_stack.py.
# Done once here so every submodule can `from bonbon_safety... import ...`
# without repeating this block.
_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC = _REPO_ROOT / "ros2_ws" / "src"
for _extra in (
    _SRC / "bonbon_safety",
    _SRC / "bonbon_edge_ai_runtime",
    _SRC / "bonbon_ai_model_registry",
    _SRC / "bonbon_ai_runtime",
    _SRC / "bonbon_llm",
    _SRC / "bonbon_speech_ai",
    _SRC / "bonbon_sarvam_adapter",
    _SRC / "bonbon_distributed_network_monitor",
    _SRC / "bonbon_data_stores",
):
    if str(_extra) not in sys.path:
        sys.path.insert(0, str(_extra))
