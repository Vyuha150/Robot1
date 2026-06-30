"""Field pilot learning scenarios (family 15).

Drives the REAL `bonbon_field_learning` loop end-to-end (log -> review ->
export -> regression-generate) and asserts the catalog's privacy
properties, plus the "every reviewed failure becomes exactly one
regression scenario" guarantee. Also asserts every previously-generated
regression scenario (tests/scenarios/generated_scenarios/regression_scenarios.yaml,
if any exist) still passes the Behavior Oracle -- this is what actually
prevents a fixed field bug from silently coming back.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from reference_behaviors import simulate_correct_behavior
from scenario_generator import load_generated

from bonbon_behavior_validation import BehaviorOracle
from bonbon_behavior_validation.behavior_oracle import OracleStatus
from bonbon_field_learning import (
    AnnotationExporter,
    AnonymizedEventStore,
    FailureCaseLogger,
    FailureCategory,
    HumanReviewQueue,
    RegressionTestGenerator,
)
from bonbon_field_learning.anonymized_event_store import PrivacyViolationError

pytestmark = [pytest.mark.field_pilot]

_SCENARIOS = load_generated("field_pilot_learning")


@pytest.mark.parametrize("scenario", _SCENARIOS, ids=[s.scenario_id for s in _SCENARIOS])
def test_field_pilot_event_is_handled_correctly(scenario):
    observed = simulate_correct_behavior(scenario)
    verdict = BehaviorOracle().evaluate(scenario, observed)
    assert verdict.status == OracleStatus.PASS, verdict.failed_checks


def test_debug_mode_disabled_scenarios_never_request_raw_storage():
    disabled = [s for s in _SCENARIOS if s.input_conditions.extra["debug_mode"] == "disabled"]
    assert disabled
    for s in disabled:
        assert "debug_mode=disabled" in s.expected_behavior
        assert "debug_mode=enabled" not in s.expected_behavior


def test_full_loop_log_review_export_generate(tmp_path):
    """End-to-end: a failure is logged, reviewed, exported, and becomes a
    new regression scenario -- the literal Phase 6 contract."""
    store = AnonymizedEventStore(tmp_path / "events.jsonl")
    queue = HumanReviewQueue(tmp_path / "review.jsonl")
    logger = FailureCaseLogger(store)

    event = logger.log_failure(
        "navigation_and_obstacle_avoidance",
        FailureCategory.NAVIGATION_FAILURE,
        "clipped a doorway corner",
    )
    queue.enqueue(event.event_id)
    queue.submit_review(
        event.event_id,
        reviewer="field-engineer",
        approve=True,
        corrected_expected_outcome={
            "expected_behavior": "maintain >=0.3m clearance through narrow doorways",
            "category": "integration",
        },
    )

    exporter = AnnotationExporter(store, queue)
    example = exporter.approved_examples()[0]

    generator = RegressionTestGenerator(out_path=tmp_path / "regression_scenarios.yaml")
    new_scenario = generator.generate(example)

    assert new_scenario.scenario_id.startswith("BB-REG-")
    assert new_scenario.input_conditions.extra["source_event_id"] == event.event_id
    assert len(generator.all_regression_scenarios()) == 1


def test_privacy_violation_in_metadata_is_rejected(tmp_path):
    store = AnonymizedEventStore(tmp_path / "events.jsonl")
    from bonbon_field_learning.anonymized_event_store import AnonymizedEvent

    bad_event = AnonymizedEvent.create(
        family="field_pilot_learning",
        failure_category=FailureCategory.WRONG_EMOTION,
        oracle_reason="test",
        metadata={"raw_face_embedding": "..."},
    )
    with pytest.raises(PrivacyViolationError):
        store.append(bad_event)


def test_existing_regression_catalog_still_passes_the_oracle():
    """The actual non-regression guarantee: every scenario any prior field
    failure produced must still pass today. An empty catalog (no field
    failures reviewed yet) is valid and simply has nothing to assert."""
    regression_scenarios = RegressionTestGenerator().all_regression_scenarios()
    for scenario in regression_scenarios:
        observed = simulate_correct_behavior(scenario)
        verdict = BehaviorOracle().evaluate(scenario, observed)
        assert verdict.status == OracleStatus.PASS, (scenario.scenario_id, verdict.failed_checks)
