"""bonbon_fault_manager.core.fault_registry
==============================================
In-memory, live registry of per-component fault state. Pure Python, no
ROS2 dependency -- the node wrapper (nodes/fault_manager_node.py) is a
thin adapter that feeds HalFault/SafetyState callbacks into this class
and publishes its snapshot() as bonbon_msgs/ComponentFaultArray.

Three update paths, matching the three real signal sources:
  - update_from_hal_fault()   : one HalFault event from any HAL node
  - sync_degraded_modules()   : SafetyState.degraded_modules reconciliation
  - update_safety_supervisor(): SafetyState's own state/reason/manual-reset
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Iterable

from .component_rules import classify, component_info
from .fault_taxonomy import FaultLevel, is_actionable, worst

_SAFETY_PREFIX = "safety:"

# bonbon_msgs/SafetyState.msg's state_name strings -> FaultLevel, used only
# when requires_manual_reset is False (that flag always forces BLOCKED,
# since a manual reset requirement is definitionally not self-recovering).
_SAFETY_STATE_LEVEL: dict[str, FaultLevel] = {
    "INITIALIZING": FaultLevel.OK,
    "NORMAL": FaultLevel.OK,
    "CAUTION": FaultLevel.WARNING,
    "DANGER": FaultLevel.FAULT,
    "DOCKING": FaultLevel.OK,
    "DEGRADED": FaultLevel.DEGRADED,
    "FAULT": FaultLevel.FAULT,
    "SAFE_STOP": FaultLevel.CRITICAL,
}


@dataclass
class FaultRecord:
    component_id: str
    subsystem: str
    affected_pi: str
    fault_level: FaultLevel
    error_code: str
    message: str
    recovery_action: str
    dashboard_visible: bool
    last_seen: float
    occurrence_count: int


class FaultRegistry:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._records: dict[str, FaultRecord] = {}

    # ── HalFault path ────────────────────────────────────────────────────

    def update_from_hal_fault(
        self,
        device: str,
        error_code: str,
        message: str,
        severity: int = 2,
        is_recovered: bool = False,
        component_id: str | None = None,
    ) -> FaultRecord:
        cid = component_id or device
        level, action = classify(device, error_code, severity, is_recovered)
        info = component_info(device)
        prev = self._records.get(cid)
        occurrence = (prev.occurrence_count if prev else 0) + (0 if is_recovered else 1)
        record = FaultRecord(
            component_id=cid,
            subsystem=info.subsystem,
            affected_pi=info.affected_pi,
            fault_level=level,
            error_code=error_code,
            message=message,
            recovery_action=action,
            dashboard_visible=is_actionable(level),
            last_seen=self._clock(),
            occurrence_count=occurrence,
        )
        self._records[cid] = record
        return record

    # ── SafetyState.degraded_modules reconciliation ─────────────────────

    def sync_degraded_modules(self, current_modules: Iterable[str], reason: str = "") -> None:
        """Called on every SafetyState message with the CURRENT full list.
        Modules no longer present are treated as recovered and removed."""
        current = set(current_modules)
        tracked_names = {
            cid[len(_SAFETY_PREFIX) :] for cid in self._records if cid.startswith(_SAFETY_PREFIX)
        }
        for name in current:
            self._update_degraded_module(name, reason)
        for name in tracked_names - current:
            self._records.pop(f"{_SAFETY_PREFIX}{name}", None)

    def _update_degraded_module(self, module_name: str, reason: str) -> FaultRecord:
        cid = f"{_SAFETY_PREFIX}{module_name}"
        prev = self._records.get(cid)
        occurrence = (prev.occurrence_count if prev else 0) + 1
        record = FaultRecord(
            component_id=cid,
            subsystem="safety-reported",
            affected_pi="unknown",
            fault_level=FaultLevel.DEGRADED,
            error_code="DEGRADED_MODULE",
            message=f"{module_name} reported degraded by safety supervisor"
            + (f": {reason}" if reason else ""),
            recovery_action=(
                "See /bonbon/safety/state reason field -- module-specific "
                "investigation required to clear this degradation."
            ),
            dashboard_visible=True,
            last_seen=self._clock(),
            occurrence_count=occurrence,
        )
        self._records[cid] = record
        return record

    # ── SafetyState's own state/reason/manual-reset ─────────────────────

    def update_safety_supervisor(
        self, state_name: str, reason: str, requires_manual_reset: bool
    ) -> FaultRecord:
        if requires_manual_reset:
            level = FaultLevel.BLOCKED
            action = (
                "Safety supervisor requires a MANUAL reset before "
                "actuation/navigation can resume -- operator action required."
            )
        else:
            level = _SAFETY_STATE_LEVEL.get(state_name, FaultLevel.DEGRADED)
            action = (
                "No action needed."
                if level == FaultLevel.OK
                else f"Safety state {state_name}: {reason or 'see safety supervisor logs'}."
            )
        prev = self._records.get("safety_supervisor")
        occurrence = (prev.occurrence_count if prev else 0) + (0 if level == FaultLevel.OK else 1)
        record = FaultRecord(
            component_id="safety_supervisor",
            subsystem="safety",
            affected_pi="pi3",
            fault_level=level,
            error_code=state_name,
            message=reason or state_name,
            recovery_action=action,
            dashboard_visible=is_actionable(level),
            last_seen=self._clock(),
            occurrence_count=occurrence,
        )
        self._records["safety_supervisor"] = record
        return record

    # ── Queries ──────────────────────────────────────────────────────────

    def get(self, component_id: str) -> FaultRecord | None:
        return self._records.get(component_id)

    def snapshot(self) -> list[FaultRecord]:
        return list(self._records.values())

    def worst_level(self) -> FaultLevel:
        return worst(r.fault_level for r in self._records.values())
