"""BenchmarkRunner — executes registered benchmark cases against
whichever model is actually active for a capability, and records honest
results. A case for a model that isn't installed/available is reported
as BLOCKED, never given a fabricated latency number -- this is the same
"hardware-gated tests must be blocked, not faked" rule applied to
benchmarking rather than testing.

The actual inference call is supplied by the caller (an `invoke`
callable per capability) rather than hardcoded here, because invoking
Ollama/faster-whisper/Piper/mediapipe are all genuinely different
operations this generic package should not need to know how to perform
-- scripts/ai_models/benchmark_all_models.py wires the real invokers.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from bonbon_ai_model_registry.model_health_monitor import ModelHealthMonitor
from bonbon_ai_model_registry.model_registry import ModelEntry, ModelRegistry
from bonbon_ai_model_registry.model_runtime_selector import ModelRuntimeSelector

InvokeFn = Callable[[ModelEntry, "BenchmarkCase"], Any]


@dataclass
class BenchmarkCase:
    case_id: str
    capability: str
    category: str  # e.g. "asr", "tts", "llm", "vision" -- matches Phase 12's categories
    input_data: Any
    language: str | None = None
    timeout_sec: float = 30.0


@dataclass
class BenchmarkResult:
    case_id: str
    model_id: str
    status: str  # "pass" | "fail" | "timeout" | "blocked"
    latency_ms: float | None
    detail: str
    fallback_triggered: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "model_id": self.model_id,
            "status": self.status,
            "latency_ms": self.latency_ms,
            "detail": self.detail,
            "fallback_triggered": self.fallback_triggered,
        }


@dataclass
class BenchmarkReport:
    results: list[BenchmarkResult] = field(default_factory=list)

    def summary(self) -> dict[str, int]:
        counts = {"pass": 0, "fail": 0, "timeout": 0, "blocked": 0}
        for r in self.results:
            counts[r.status] = counts.get(r.status, 0) + 1
        return counts

    def to_dict(self) -> dict[str, Any]:
        return {"summary": self.summary(), "results": [r.to_dict() for r in self.results]}


class BenchmarkRunner:
    def __init__(
        self,
        registry: ModelRegistry,
        selector: ModelRuntimeSelector,
        health_monitor: ModelHealthMonitor | None = None,
    ) -> None:
        self._registry = registry
        self._selector = selector
        self._health = health_monitor

    def run_case(self, case: BenchmarkCase, invoke: InvokeFn) -> BenchmarkResult:
        status = self._selector.select(case.capability)
        decision = status.decision
        if decision.active_model_id is None:
            return BenchmarkResult(case.case_id, decision.requested_model_id, "blocked", None, decision.reason)

        entry = self._registry.get(decision.active_model_id)
        if entry is None:  # pragma: no cover -- registry/selector invariant, defensive only
            return BenchmarkResult(case.case_id, decision.active_model_id, "blocked", None, "active model_id not found in registry")

        started = time.perf_counter()
        try:
            invoke(entry, case)
        except TimeoutError as exc:
            return BenchmarkResult(case.case_id, entry.model_id, "timeout", None, str(exc), decision.fallback_active)
        except Exception as exc:  # noqa: BLE001 -- a benchmark failure must be recorded honestly, not crash the whole run
            if self._health:
                self._health.record_error(entry.model_id, str(exc))
            return BenchmarkResult(case.case_id, entry.model_id, "fail", None, str(exc), decision.fallback_active)

        latency_ms = (time.perf_counter() - started) * 1000.0
        if self._health:
            self._health.record_latency(entry.model_id, latency_ms)
        return BenchmarkResult(case.case_id, entry.model_id, "pass", latency_ms, "ok", decision.fallback_active)

    def run_all(self, cases: list[BenchmarkCase], invokers: dict[str, InvokeFn]) -> BenchmarkReport:
        report = BenchmarkReport()
        for case in cases:
            invoke = invokers.get(case.capability)
            if invoke is None:
                report.results.append(BenchmarkResult(case.case_id, "", "blocked", None, f"no invoker registered for capability {case.capability!r}"))
                continue
            report.results.append(self.run_case(case, invoke))
        return report
