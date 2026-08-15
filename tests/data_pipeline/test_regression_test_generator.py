"""Required test 6: a reviewed failure can become a regression test.

Exercises bonbon_field_learning.RegressionTestGenerator (the real
implementation this brief's regression-test requirement reuses) with the
newly-added FailureCategory values, writing to a tmp_path-scoped output
file so this test never touches the real
tests/scenarios/generated_scenarios/regression_scenarios.yaml catalog.
"""

from __future__ import annotations

import pytest

from bonbon_field_learning import (
    AnonymizedEventStore,
    FailureCategory,
    HumanReviewQueue,
)
from bonbon_field_learning.annotation_exporter import AnnotationExporter
from bonbon_field_learning.failure_case_logger import FailureCaseLogger
from bonbon_field_learning.regression_test_generator import RegressionTestGenerator


@pytest.fixture
def store(tmp_path):
    return AnonymizedEventStore(tmp_path / "events.jsonl")


@pytest.fixture
def queue(tmp_path):
    return HumanReviewQueue(tmp_path / "review_queue.jsonl")


@pytest.fixture
def generator(tmp_path):
    return RegressionTestGenerator(out_path=tmp_path / "regression_scenarios.yaml")


class TestRequiredBehavior6ReviewedFailureBecomesRegressionTest:
    def test_approved_example_generates_a_scenario(self, store, queue, generator):
        logger = FailureCaseLogger(store)
        event = logger.log_failure(
            family="rag_grounding", failure_category=FailureCategory.WRONG_RAG_ANSWER,
            reason="answered with cafeteria hours instead of visiting hours",
        )
        queue.enqueue(event.event_id)
        review_item = queue.submit_review(
            event.event_id, reviewer="staff_001", approve=True,
            corrected_expected_outcome={"expected_behavior": "answer with visiting hours from the FAQ table"},
        )

        example = AnnotationExporter(store, queue).approved_examples()[0]
        scenario = generator.generate(example)

        assert scenario.scenario_id.startswith("BB-REG-")
        # Scenario IDs truncate the failure_category to 8 chars (see
        # RegressionTestGenerator.generate); "wrong_rag_answer" -> "WRONG_RA".
        assert "WRONG_RA" in scenario.scenario_id
        assert scenario in generator.all_regression_scenarios()
        assert review_item.status.value == "approved"

    def test_unreviewed_pending_example_cannot_be_generated(self, store, queue, generator):
        from bonbon_field_learning.human_review_queue import ReviewItem

        logger = FailureCaseLogger(store)
        event = logger.log_failure(
            family="navigation", failure_category=FailureCategory.NAVIGATION_FAILURE, reason="x"
        )
        pending_item = ReviewItem(event_id=event.event_id)  # never submitted/approved

        from bonbon_field_learning.annotation_exporter import LabeledExample

        example = LabeledExample(event=event, review=pending_item)
        with pytest.raises(ValueError, match="refusing to generate"):
            generator.generate(example)

    def test_rejected_example_cannot_be_generated(self, store, queue, generator):
        logger = FailureCaseLogger(store)
        event = logger.log_failure(
            family="gesture_understanding", failure_category=FailureCategory.WRONG_GESTURE, reason="x"
        )
        queue.enqueue(event.event_id)
        queue.submit_review(event.event_id, reviewer="staff_001", approve=False)
        example = AnnotationExporter(store, queue).approved_examples()
        assert example == []  # rejected items never reach approved_examples() at all

    def test_generated_scenarios_persist_across_generator_instances(self, store, queue, tmp_path):
        out_path = tmp_path / "persisted_scenarios.yaml"
        logger = FailureCaseLogger(store)
        event = logger.log_failure(
            family="wayfinding", failure_category=FailureCategory.WRONG_SEMANTIC_LOCATION, reason="x"
        )
        queue.enqueue(event.event_id)
        queue.submit_review(event.event_id, reviewer="staff_001", approve=True)
        example = AnnotationExporter(store, queue).approved_examples()[0]

        RegressionTestGenerator(out_path=out_path).generate(example)
        reloaded = RegressionTestGenerator(out_path=out_path).all_regression_scenarios()
        assert len(reloaded) == 1
        assert "WRONG_SE" in reloaded[0].scenario_id
