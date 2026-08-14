"""FailureCaseLogger — the entry point other packages use to record a model
failure/uncertainty case.

Every write passes through PrivacySafeDataPolicy first: context is
sanitized (forbidden keys stripped unconditionally), and a raw snapshot
reference is only ever recorded when the policy's debug mode is explicitly
enabled — this module does no raw file I/O itself, it only decides whether
a caller-supplied path reference is ALLOWED to be persisted.
"""

from __future__ import annotations

from bonbon_data_feedback.core.feedback_store import FailureCaseRecord, FeedbackStore
from bonbon_data_feedback.core.privacy_safe_data_policy import PrivacySafeDataPolicy


class FailureCaseLogger:
    def __init__(self, store: FeedbackStore, policy: PrivacySafeDataPolicy) -> None:
        self._store = store
        self._policy = policy

    def log(
        self,
        category: str,
        signal_name: str,
        actual_label: str,
        confidence: float,
        expected_label: str = "",
        person_track_id: str = "",
        context: dict | None = None,
        raw_snapshot_path: str = "",
        site_id: str = "",
        language_code: str = "",
    ) -> str:
        sanitize_result = self._policy.sanitize_context(context or {})

        snapshot_allowed = bool(raw_snapshot_path) and self._policy.is_raw_snapshot_allowed()

        record = FailureCaseRecord(
            case_id="",
            category=category,
            signal_name=signal_name,
            expected_label=expected_label,
            actual_label=actual_label,
            confidence=confidence,
            person_track_id=person_track_id,
            context=sanitize_result.sanitized,
            has_raw_snapshot=snapshot_allowed,
            raw_snapshot_path=raw_snapshot_path if snapshot_allowed else "",
            site_id=site_id,
            language_code=language_code,
        )
        return self._store.insert_failure_case(record)
