"""bonbon_fault_manager.core.fault_registry
==============================================
In-memory, live registry of per-component fault state. Pure Python, no
ROS2 dependency -- the node wrapper (nodes/fault_manager_node.py) is a
thin adapter that feeds HalFault/SafetyState callbacks into this class
and publishes its snapshot() as bonbon_msgs/ComponentFaultArray.

Four update paths, matching the four real signal sources:
  - update_from_hal_fault()   : one HalFault event from any HAL node
  - sync_degraded_modules()   : SafetyState.degraded_modules reconciliation
  - update_safety_supervisor(): SafetyState's own state/reason/manual-reset
  - update_from_pi_link_event(): bonbon_distributed_safety's peer-Pi
    link-state SafetyEvent -- distributed_safety_node already detects a
    fully-offline peer Pi (real, tested HeartbeatMonitor), but until this
    path existed that detection was only visible on the raw
    /bonbon/system/failure_events topic, never in this unified dashboard
    registry alongside every other fault.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Callable, Iterable

from .component_rules import classify, component_info
from .fault_taxonomy import FaultLevel, is_actionable, worst

_PI_LINK_TRIGGER = "pi_link_state_change"
# Parses the one peer-Pi identifier out of distributed_safety_node's own
# free-text description ("{self_id} observed {peer_id}: {old} -> {new}",
# see nodes/distributed_safety_node.py's _cb_evaluate) -- SafetyEvent.msg
# itself has no dedicated peer-id field, and adding one would be a wider,
# shared-message-type change out of scope for this specific gap. Falls
# back to "unknown_peer" rather than guessing if the format ever changes.
_PEER_ID_RE = re.compile(r"observed (pi\d+):")

_PI_LINK_STATE_LEVEL: dict[str, FaultLevel] = {
    "online": FaultLevel.OK,
    "stale": FaultLevel.WARNING,
    "lost": FaultLevel.CRITICAL,
}

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

    # ── bonbon_distributed_safety's peer-Pi link-state SafetyEvent ──────

    def update_from_pi_link_event(
        self, trigger_name: str, description: str, new_state_name: str
    ) -> FaultRecord | None:
        """One SafetyEvent from /bonbon/system/failure_events. Returns
        None for any SafetyEvent that isn't a pi_link_state_change (this
        registry only tracks the one event type it's built for; other
        SafetyEvent triggers are out of this path's scope)."""
        if trigger_name != _PI_LINK_TRIGGER:
            return None

        match = _PEER_ID_RE.search(description)
        peer_id = match.group(1) if match else "unknown_peer"
        cid = f"pi_link:{peer_id}"
        level = _PI_LINK_STATE_LEVEL.get(new_state_name, FaultLevel.WARNING)

        if level == FaultLevel.OK:
            # Peer is back online -- remove rather than leave a stale OK
            # record sitting in the registry, matching
            # sync_degraded_modules()'s own "no longer present = recovered
            # = removed" convention.
            self._records.pop(cid, None)
            return None

        prev = self._records.get(cid)
        occurrence = (prev.occurrence_count if prev else 0) + 1
        record = FaultRecord(
            component_id=cid,
            subsystem="distributed",
            affected_pi=peer_id,
            fault_level=level,
            error_code=f"PI_LINK_{new_state_name.upper()}",
            message=description,
            recovery_action=(
                "Check network connectivity, chrony time sync, and whether "
                f"{peer_id}'s bonbon_distributed_safety container/process is running."
            ),
            dashboard_visible=is_actionable(level),
            last_seen=self._clock(),
            occurrence_count=occurrence,
        )
        self._records[cid] = record
        return record

    # ── Queries ──────────────────────────────────────────────────────────

    def get(self, component_id: str) -> FaultRecord | None:
        return self._records.get(component_id)

    def snapshot(self) -> list[FaultRecord]:
        return list(self._records.values())

    def worst_level(self) -> FaultLevel:
        return worst(r.fault_level for r in self._records.values())
