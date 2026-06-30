"""Turns a Behavior Oracle FAIL/UNCERTAIN verdict into an anonymized event,
and -- only in explicit debug mode -- a raw snapshot kept in a deliberately
separate store so it can never leak into the default anonymized log.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from bonbon_field_learning.anonymized_event_store import (
    AnonymizedEvent,
    AnonymizedEventStore,
    FailureCategory,
)

if TYPE_CHECKING:
    from bonbon_behavior_validation.behavior_oracle import OracleVerdict


# Maps an oracle check name to the failure_category this event should be
# filed under -- so the dashboard/regression pipeline can group by the
# brief's required failure taxonomy.
_CHECK_TO_CATEGORY: dict[str, FailureCategory] = {
    "responded_to_correct_person": FailureCategory.WRONG_PERSON_IDENTITY,
    "no_identity_mixup": FailureCategory.WRONG_PERSON_IDENTITY,
    "low_confidence_handling": FailureCategory.WRONG_RESPONSE,
    "clarification_when_needed": FailureCategory.WRONG_RESPONSE,
    "dashboard_updated": FailureCategory.DASHBOARD_MISMATCH,
    "event_logged": FailureCategory.DASHBOARD_MISMATCH,
    "degraded_mode_entered": FailureCategory.DEGRADED_MODE_FAILURE,
    "llm_no_direct_action": FailureCategory.UNSAFE_PROPOSAL_BLOCKED,
    "safety_supervisor_decision": FailureCategory.UNSAFE_PROPOSAL_BLOCKED,
    "estop_latency": FailureCategory.UNSAFE_PROPOSAL_BLOCKED,
    "emergency_phrase_escalated": FailureCategory.WRONG_RESPONSE,
    "no_unsafe_movement": FailureCategory.NAVIGATION_FAILURE,
}


def category_for_check(check_name: str) -> FailureCategory:
    return _CHECK_TO_CATEGORY.get(check_name, FailureCategory.WRONG_RESPONSE)


@dataclass(frozen=True)
class DebugSnapshotRecord:
    """A pointer to a raw snapshot file, never the bytes themselves in this
    record -- the bytes live on disk under a debug-only directory the
    anonymized store never reads."""

    event_id: str
    snapshot_path: str
    captured_at: float


class DebugSnapshotStore:
    """Separate, explicit-debug-mode-only store for raw snapshot pointers.
    Never imported by anything that also touches AnonymizedEventStore's
    write path -- the separation is structural, not just a flag check."""

    def __init__(self, directory: Path | str) -> None:
        self._dir = Path(directory)
        self._index_path = self._dir / "index.jsonl"

    def record(self, event_id: str, snapshot_path: Path | str) -> DebugSnapshotRecord:
        self._dir.mkdir(parents=True, exist_ok=True)
        rec = DebugSnapshotRecord(
            event_id=event_id, snapshot_path=str(snapshot_path), captured_at=time.time()
        )
        with open(self._index_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec.__dict__) + "\n")
        return rec


class FailureCaseLogger:
    def __init__(
        self, store: AnonymizedEventStore, debug_store: DebugSnapshotStore | None = None
    ) -> None:
        self._store = store
        self._debug_store = debug_store

    def log_verdict(
        self,
        family: str,
        scenario_id: str,
        verdict: "OracleVerdict",
        debug_mode: bool = False,
        raw_snapshot_path: Path | str | None = None,
    ) -> list[AnonymizedEvent]:
        """Logs one AnonymizedEvent per failed check (a scenario can fail
        more than one check at once). Returns the events written.

        `raw_snapshot_path` is only ever persisted (as a pointer, via the
        separate DebugSnapshotStore) when `debug_mode=True` AND a debug
        store was configured. With debug_mode=False the path is dropped on
        the floor entirely, even if a caller passed one by mistake.
        """
        events: list[AnonymizedEvent] = []
        for check in verdict.failed_checks:
            event = AnonymizedEvent.create(
                family=family,
                failure_category=category_for_check(check.name),
                oracle_reason=f"{check.name}: {check.reason}",
                scenario_id=scenario_id,
                metadata={"failed_check": check.name},
            )
            self._store.append(event)
            events.append(event)

            if debug_mode and raw_snapshot_path is not None and self._debug_store is not None:
                self._debug_store.record(event.event_id, raw_snapshot_path)

        return events

    def log_failure(
        self,
        family: str,
        failure_category: FailureCategory,
        reason: str,
        scenario_id: str | None = None,
    ) -> AnonymizedEvent:
        """Direct logging path for failures not produced by the oracle
        (e.g. an operator-flagged field report)."""
        event = AnonymizedEvent.create(
            family=family,
            failure_category=failure_category,
            oracle_reason=reason,
            scenario_id=scenario_id,
        )
        self._store.append(event)
        return event


def new_event_id() -> str:
    return str(uuid.uuid4())
