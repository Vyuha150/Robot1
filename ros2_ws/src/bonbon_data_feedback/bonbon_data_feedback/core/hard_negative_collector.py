"""HardNegativeCollector — the specific, valuable subset of failure cases
where a model was CONFIDENT but WRONG (as opposed to an honest low-confidence
miss, which is a normal failure case but not a hard negative). These are the
cases most worth prioritising for retraining.
"""

from __future__ import annotations

from bonbon_data_feedback.core.feedback_store import FailureCaseRecord, FeedbackStore
from bonbon_data_feedback.core.privacy_safe_data_policy import PrivacySafeDataPolicy


class HardNegativeCollector:
    def __init__(
        self,
        store: FeedbackStore,
        policy: PrivacySafeDataPolicy,
        confidence_threshold: float = 0.7,
    ) -> None:
        self._store = store
        self._policy = policy
        self._threshold = confidence_threshold

    def is_hard_negative(self, confidence: float, was_correct: bool) -> bool:
        return (not was_correct) and confidence >= self._threshold

    def collect(
        self,
        category: str,
        signal_name: str,
        actual_label: str,
        confidence: float,
        was_correct: bool,
        expected_label: str = "",
        person_track_id: str = "",
        context: dict | None = None,
        site_id: str = "",
        language_code: str = "",
    ) -> str | None:
        """Returns the case_id if this met the hard-negative bar, else None
        (a non-hard-negative failure should go through FailureCaseLogger
        instead — this collector only persists the confident-but-wrong
        subset, to keep the hard-negative query cheap and precise)."""
        if not self.is_hard_negative(confidence, was_correct):
            return None

        sanitize_result = self._policy.sanitize_context(context or {})
        record = FailureCaseRecord(
            case_id="",
            category=category,
            signal_name=signal_name,
            expected_label=expected_label,
            actual_label=actual_label,
            confidence=confidence,
            person_track_id=person_track_id,
            context=sanitize_result.sanitized,
            is_hard_negative=True,
            site_id=site_id,
            language_code=language_code,
        )
        return self._store.insert_failure_case(record)
