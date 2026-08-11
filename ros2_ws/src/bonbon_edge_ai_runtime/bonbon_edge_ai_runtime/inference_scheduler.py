"""bonbon_edge_ai_runtime.inference_scheduler -- Edge AI Runtime brief
Phase 8. Reads config/pi_efficiency_profile.yaml's existing
priority_order/queue_limits as the single source of truth (not a new
parallel ordering) -- see docs/THREE_PI_RUNTIME_AUDIT.md, which confirms
that file's 18-module priority list already matches this brief's
Highest/Medium/Lower priority tiers closely.

Rule 1 ("safety and movement must never wait for AI") is enforced
structurally, not by convention: a safety_critical module's task is
dispatched immediately in submit(), bypassing the queue entirely -- it
never competes for a slot with any other module's request and can never
be dropped for queue-depth reasons.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_PROFILE_PATH = _REPO_ROOT / "config" / "pi_efficiency_profile.yaml"
DEFAULT_QUEUE_SIZE = 8
DEFAULT_TIMEOUT_SEC = 5.0


@dataclass
class ModulePriority:
    rank: int
    safety_critical: bool


@dataclass
class SchedulerConfig:
    priority: dict[str, ModulePriority]
    queue_limits: dict[str, int]

    @classmethod
    def load(cls, path: str | Path = DEFAULT_PROFILE_PATH) -> "SchedulerConfig":
        path = Path(path)
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
        raw = raw or {}
        priority: dict[str, ModulePriority] = {}
        for entry in raw.get("priority_order", []):
            priority[entry["module"]] = ModulePriority(
                rank=int(entry["rank"]), safety_critical=bool(entry.get("safety_critical", False))
            )
        queue_limits = dict(raw.get("queue_limits", {}))
        return cls(priority=priority, queue_limits=queue_limits)

    def rank_for(self, module: str) -> int:
        # Unknown modules sort last and are never assumed safety-critical
        # -- an unrecognized module name must earn its priority by being
        # added to pi_efficiency_profile.yaml, not default to important.
        entry = self.priority.get(module)
        return entry.rank if entry else 999

    def is_safety_critical(self, module: str) -> bool:
        entry = self.priority.get(module)
        return entry.safety_critical if entry else False

    def queue_limit_for(self, module: str) -> int:
        return self.queue_limits.get(module, DEFAULT_QUEUE_SIZE)


@dataclass
class QueuedTask:
    task_id: str
    module: str
    enqueued_at: float
    timeout_sec: float
    payload: object = None


@dataclass
class DispatchResult:
    dispatched: bool  # True = run now (safety-critical bypass); False = queued
    task: QueuedTask
    reason: str


class InferenceScheduler:
    """One bounded FIFO queue per non-safety-critical module. Safety-
    critical modules never touch a queue at all."""

    def __init__(self, config: SchedulerConfig | None = None) -> None:
        self._config = config or SchedulerConfig.load()
        self._queues: dict[str, deque[QueuedTask]] = {}
        self._dropped_count = 0
        self._dropped_by_module: dict[str, int] = {}

    def submit(
        self,
        module: str,
        task_id: str,
        timeout_sec: float = DEFAULT_TIMEOUT_SEC,
        payload: object = None,
    ) -> DispatchResult:
        task = QueuedTask(
            task_id=task_id, module=module, enqueued_at=time.monotonic(), timeout_sec=timeout_sec, payload=payload
        )
        if self._config.is_safety_critical(module):
            return DispatchResult(dispatched=True, task=task, reason="safety-critical -- dispatched immediately, never queued")

        queue = self._queues.setdefault(module, deque())
        limit = self._config.queue_limit_for(module)
        if len(queue) >= limit:
            # Drop the OLDEST non-critical request to make room -- a
            # stale queued request is worth less than a fresh one once
            # the bound is hit (matches this brief's "queue too long:
            # drop old non-critical requests" rule).
            queue.popleft()
            self._dropped_count += 1
            self._dropped_by_module[module] = self._dropped_by_module.get(module, 0) + 1
        queue.append(task)
        return DispatchResult(dispatched=False, task=task, reason=f"queued (depth={len(queue)}/{limit})")

    def next_ready(self, module: str, now: float | None = None) -> QueuedTask | None:
        """Pops and returns the next non-expired task for `module`,
        silently dropping (and counting) any that already timed out
        while waiting in queue -- never dispatches a stale request."""
        now = now if now is not None else time.monotonic()
        queue = self._queues.get(module)
        if not queue:
            return None
        while queue:
            task = queue.popleft()
            if (now - task.enqueued_at) > task.timeout_sec:
                self._dropped_count += 1
                self._dropped_by_module[module] = self._dropped_by_module.get(module, 0) + 1
                continue
            return task
        return None

    def queue_depth(self, module: str) -> int:
        return len(self._queues.get(module, ()))

    def priority_order(self) -> list[str]:
        """Modules sorted by rank -- matches
        config/pi_efficiency_profile.yaml's priority_order exactly, safety-critical first."""
        return sorted(self._config.priority.keys(), key=self._config.rank_for)

    def status(self) -> dict:
        return {
            "priorityOrder": self.priority_order(),
            "queueDepths": {m: len(q) for m, q in self._queues.items()},
            "droppedTotal": self._dropped_count,
            "droppedByModule": dict(self._dropped_by_module),
        }
