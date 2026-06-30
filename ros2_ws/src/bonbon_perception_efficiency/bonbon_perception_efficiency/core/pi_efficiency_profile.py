"""PiEfficiencyProfile — typed loader for config/pi_efficiency_profile.yaml.

Turns the Pi efficiency profile into queryable policy: the priority order
(who runs first / sheds last), per-module FPS limits, which modules are
safety-critical (never shed), and the shed order under increasing load. Pure
Python so it's testable without ROS2 or a Pi.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ModulePriority:
    rank: int
    module: str
    safety_critical: bool


@dataclass
class PiEfficiencyProfile:
    priority: list[ModulePriority] = field(default_factory=list)
    fps_limits: dict[str, float] = field(default_factory=dict)
    event_gated: dict[str, str] = field(default_factory=dict)
    thresholds: dict[str, float] = field(default_factory=dict)
    queue_limits: dict[str, int] = field(default_factory=dict)
    data_writes: dict[str, bool] = field(default_factory=dict)

    # ── Construction ──────────────────────────────────────────────────────────

    @classmethod
    def from_dict(cls, data: dict) -> PiEfficiencyProfile:
        priority = [
            ModulePriority(
                rank=int(p["rank"]),
                module=str(p["module"]),
                safety_critical=bool(p.get("safety_critical", False)),
            )
            for p in data.get("priority_order", [])
        ]
        priority.sort(key=lambda p: p.rank)
        return cls(
            priority=priority,
            fps_limits={k: float(v) for k, v in data.get("fps_limits", {}).items()},
            event_gated=dict(data.get("event_gated", {})),
            thresholds={k: float(v) for k, v in data.get("thresholds", {}).items()},
            queue_limits={k: int(v) for k, v in data.get("queue_limits", {}).items()},
            data_writes=dict(data.get("data_writes", {})),
        )

    @classmethod
    def load(cls, path: str | Path) -> PiEfficiencyProfile:
        import yaml

        return cls.from_dict(yaml.safe_load(Path(path).read_text(encoding="utf-8")))

    # ── Queries ───────────────────────────────────────────────────────────────

    def is_safety_critical(self, module: str) -> bool:
        for p in self.priority:
            if p.module == module:
                return p.safety_critical
        return False

    def rank_of(self, module: str) -> int | None:
        for p in self.priority:
            if p.module == module:
                return p.rank
        return None

    def fps_limit(self, module: str) -> float | None:
        return self.fps_limits.get(module)

    def is_event_gated(self, module: str) -> bool:
        return module in self.event_gated

    def safety_critical_modules(self) -> list[str]:
        return [p.module for p in self.priority if p.safety_critical]

    def shed_order(self) -> list[str]:
        """Non-safety modules in the order they should be shed under
        increasing load — least important (highest rank) shed FIRST."""
        non_critical = [p for p in self.priority if not p.safety_critical]
        non_critical.sort(key=lambda p: p.rank, reverse=True)
        return [p.module for p in non_critical]

    def modules_to_shed(self, count: int) -> list[str]:
        """The first `count` modules to drop under pressure — never includes
        a safety-critical module, however high `count` goes."""
        order = self.shed_order()
        return order[: max(0, count)]

    def validate(self) -> list[str]:
        """Return a list of problems (empty = valid). Used by tests + the
        dashboard to refuse a profile that could shed safety."""
        problems: list[str] = []
        ranks = [p.rank for p in self.priority]
        if len(ranks) != len(set(ranks)):
            problems.append("duplicate priority ranks")
        required_safety = {"safety_supervisor", "emergency_stop", "hal"}
        present_safety = {p.module for p in self.priority if p.safety_critical}
        missing = required_safety - present_safety
        if missing:
            problems.append(f"safety-critical modules not marked safety_critical: {missing}")
        # No safety-critical module may ever be in the shed order.
        if set(self.shed_order()) & present_safety:
            problems.append("a safety-critical module appears in the shed order")
        return problems
