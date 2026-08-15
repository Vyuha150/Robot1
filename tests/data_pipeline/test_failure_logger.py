"""Required test 5: a field failure creates a review item.

Deliberately exercises bonbon_field_learning.FailureCaseLogger +
HumanReviewQueue rather than a duplicate bonbon_data_pipeline
implementation -- see bonbon_data_pipeline/__init__.py's module docstring
for why. This test also proves the five FailureCategory values added for
this brief (WRONG_ASR_TRANSCRIPT, WRONG_INTENT, WRONG_RAG_ANSWER,
WRONG_SEMANTIC_LOCATION, STAFF_INTERVENTION) work through the same real
pipeline bonbon_operator_api's /data/failure-cases endpoint reads.
"""

from __future__ import annotations

import pytest

from bonbon_field_learning import AnonymizedEventStore, FailureCategory, HumanReviewQueue
from bonbon_field_learning.failure_case_logger import FailureCaseLogger


@pytest.fixture
def store(tmp_path):
    return AnonymizedEventStore(tmp_path / "events.jsonl")


@pytest.fixture
def queue(tmp_path):
    return HumanReviewQueue(tmp_path / "review_queue.jsonl")


@pytest.fixture
def logger(store):
    return FailureCaseLogger(store)


class TestRequiredBehavior5FailureCreatesReviewItem:
    def test_logged_failure_can_be_enqueued_for_review(self, logger, queue):
        event = logger.log_failure(
            family="speech_understanding",
            failure_category=FailureCategory.WRONG_ASR_TRANSCRIPT,
            reason="transcript did not match corrected staff input",
        )

        item = queue.enqueue(event.event_id)
        assert item.event_id == event.event_id
        assert item.status.value == "pending"
        assert item in queue.pending()

    @pytest.mark.parametrize(
        "category",
        [
            FailureCategory.WRONG_ASR_TRANSCRIPT,
            FailureCategory.WRONG_INTENT,
            FailureCategory.WRONG_RAG_ANSWER,
            FailureCategory.WRONG_SEMANTIC_LOCATION,
            FailureCategory.STAFF_INTERVENTION,
        ],
    )
    def test_new_failure_categories_round_trip_through_the_logger_and_store(self, logger, store, category):
        event = logger.log_failure(family="test_family", failure_category=category, reason="x")
        reloaded = store.all_events()[0]
        assert reloaded.event_id == event.event_id
        assert reloaded.failure_category == category

    def test_review_and_annotation_export_share_the_same_event_id(self, logger, store, queue):
        from bonbon_field_learning.annotation_exporter import AnnotationExporter

        event = logger.log_failure(
            family="rag_grounding", failure_category=FailureCategory.WRONG_RAG_ANSWER, reason="x"
        )
        queue.enqueue(event.event_id)
        queue.submit_review(
            event.event_id, reviewer="staff_001", approve=True,
            corrected_expected_outcome={"category": "field_pilot"},
        )

        exporter = AnnotationExporter(store, queue)
        examples = exporter.approved_examples()
        assert len(examples) == 1
        assert examples[0].event.event_id == event.event_id
        assert examples[0].review.status.value == "approved"

    def test_rejected_review_does_not_appear_in_approved_examples(self, logger, store, queue):
        from bonbon_field_learning.annotation_exporter import AnnotationExporter

        event = logger.log_failure(
            family="rag_grounding", failure_category=FailureCategory.STAFF_INTERVENTION, reason="x"
        )
        queue.enqueue(event.event_id)
        queue.submit_review(event.event_id, reviewer="staff_001", approve=False, notes="duplicate report")

        exporter = AnnotationExporter(store, queue)
        assert exporter.approved_examples() == []
