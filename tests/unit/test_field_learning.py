"""Unit tests for bonbon_field_learning: the privacy contract, the human
review -> regression test pipeline, and the deployment-blocking gate.
"""

from __future__ import annotations

import pytest
from scenario_generator import load_generated

from bonbon_behavior_validation import BehaviorOracle, ObservedOutcome
from bonbon_field_learning import (
    AnnotationExporter,
    AnonymizedEventStore,
    DatasetVersionManager,
    FailureCaseLogger,
    FailureCategory,
    HumanReviewQueue,
    ModelEvaluationTracker,
    RegressionTestGenerator,
)
from bonbon_field_learning.annotation_exporter import LabeledExample
from bonbon_field_learning.anonymized_event_store import AnonymizedEvent, PrivacyViolationError
from bonbon_field_learning.failure_case_logger import DebugSnapshotStore
from bonbon_field_learning.model_evaluation_tracker import EvaluationRun


@pytest.fixture
def store(tmp_path):
    return AnonymizedEventStore(tmp_path / "events.jsonl")


@pytest.fixture
def queue(tmp_path):
    return HumanReviewQueue(tmp_path / "review_queue.jsonl")


class TestPrivacyContract:
    def test_no_raw_media_fields_exist_on_the_event_type(self):
        fields = AnonymizedEvent.__dataclass_fields__.keys()
        for banned in ("raw_face", "raw_audio", "face_image", "audio_waveform"):
            assert banned not in fields

    def test_smuggled_metadata_key_is_rejected(self, store):
        event = AnonymizedEvent.create(
            family="gesture_understanding",
            failure_category=FailureCategory.WRONG_GESTURE,
            oracle_reason="test",
            metadata={"raw_face_image": "base64data"},
        )
        with pytest.raises(PrivacyViolationError):
            store.append(event)

    def test_normal_metadata_is_accepted(self, store):
        event = AnonymizedEvent.create(
            family="gesture_understanding",
            failure_category=FailureCategory.WRONG_GESTURE,
            oracle_reason="test",
            metadata={"failed_check": "no_unsafe_movement"},
        )
        store.append(event)
        assert len(store.all_events()) == 1

    def test_debug_snapshot_never_reaches_the_default_store(self, store, tmp_path):
        debug_store = DebugSnapshotStore(tmp_path / "debug_snapshots")
        logger = FailureCaseLogger(store, debug_store)

        scenarios = load_generated("gesture_understanding")
        scenario = next(s for s in scenarios if s.input_conditions.gesture == "stop_palm")
        observed = ObservedOutcome(safety_decision="approved", estop_triggered=False)
        verdict = BehaviorOracle().evaluate(scenario, observed)

        logger.log_verdict(
            "gesture_understanding",
            scenario.scenario_id,
            verdict,
            debug_mode=True,
            raw_snapshot_path=tmp_path / "frame_001.jpg",
        )

        # The anonymized event store has events, but none of them carry the
        # raw snapshot path -- it only lives in the separate debug index.
        for event in store.all_events():
            assert "frame_001.jpg" not in str(event.to_dict())
        debug_index = (tmp_path / "debug_snapshots" / "index.jsonl").read_text()
        assert "frame_001.jpg" in debug_index

    def test_debug_mode_off_drops_the_snapshot_path_entirely(self, store, tmp_path):
        debug_store = DebugSnapshotStore(tmp_path / "debug_snapshots")
        logger = FailureCaseLogger(store, debug_store)
        scenarios = load_generated("gesture_understanding")
        scenario = next(s for s in scenarios if s.input_conditions.gesture == "stop_palm")
        observed = ObservedOutcome(safety_decision="approved", estop_triggered=False)
        verdict = BehaviorOracle().evaluate(scenario, observed)

        logger.log_verdict(
            "gesture_understanding",
            scenario.scenario_id,
            verdict,
            debug_mode=False,
            raw_snapshot_path=tmp_path / "frame_002.jpg",
        )
        assert not (tmp_path / "debug_snapshots" / "index.jsonl").exists()


class TestFailureCaseLogger:
    def test_log_verdict_writes_one_event_per_failed_check(self, store):
        logger = FailureCaseLogger(store)
        scenarios = load_generated("gesture_understanding")
        scenario = next(s for s in scenarios if s.input_conditions.gesture == "stop_palm")
        # Wrong response: no halt, no logging, no dashboard update.
        observed = ObservedOutcome(safety_decision="approved", estop_triggered=False)
        verdict = BehaviorOracle().evaluate(scenario, observed)

        events = logger.log_verdict("gesture_understanding", scenario.scenario_id, verdict)
        assert len(events) == len(verdict.failed_checks)
        assert len(store.all_events()) == len(verdict.failed_checks)

    def test_passing_verdict_logs_nothing(self, store):
        logger = FailureCaseLogger(store)
        scenarios = load_generated("dashboard_and_operator_control")
        scenario = scenarios[0]
        observed = ObservedOutcome(dashboard_updated=True, event_logged=True)
        verdict = BehaviorOracle().evaluate(scenario, observed)
        events = logger.log_verdict("dashboard_and_operator_control", scenario.scenario_id, verdict)
        assert events == []


class TestHumanReviewQueue:
    def test_enqueue_then_approve_round_trips(self, queue):
        queue.enqueue("evt-1")
        assert len(queue.pending()) == 1
        queue.submit_review(
            "evt-1", reviewer="alice", approve=True, corrected_expected_outcome={"x": "y"}
        )
        assert queue.pending() == []
        assert len(queue.approved()) == 1

    def test_rejected_review_does_not_count_as_approved(self, queue):
        queue.enqueue("evt-2")
        queue.submit_review("evt-2", reviewer="bob", approve=False, notes="duplicate")
        assert queue.approved() == []

    def test_state_persists_across_instances(self, tmp_path):
        path = tmp_path / "queue.jsonl"
        q1 = HumanReviewQueue(path)
        q1.enqueue("evt-3")
        q1.submit_review("evt-3", reviewer="carol", approve=True)

        q2 = HumanReviewQueue(path)
        assert len(q2.approved()) == 1


class TestAnnotationExporterAndRegressionGeneration:
    def _approved_example(self, store, queue):
        logger = FailureCaseLogger(store)
        event = logger.log_failure(
            "gesture_understanding", FailureCategory.WRONG_GESTURE, "stop_palm ignored"
        )
        queue.enqueue(event.event_id)
        queue.submit_review(
            event.event_id,
            reviewer="alice",
            approve=True,
            corrected_expected_outcome={"expected_behavior": "halt immediately on stop_palm"},
        )
        exporter = AnnotationExporter(store, queue)
        return exporter.approved_examples()[0]

    def test_export_writes_only_approved_examples(self, store, queue, tmp_path):
        logger = FailureCaseLogger(store)
        approved_event = logger.log_failure(
            "gesture_understanding", FailureCategory.WRONG_GESTURE, "approved case"
        )
        rejected_event = logger.log_failure(
            "gesture_understanding", FailureCategory.WRONG_GESTURE, "rejected case"
        )
        queue.enqueue(approved_event.event_id)
        queue.submit_review(approved_event.event_id, reviewer="alice", approve=True)
        queue.enqueue(rejected_event.event_id)
        queue.submit_review(rejected_event.event_id, reviewer="alice", approve=False)

        exporter = AnnotationExporter(store, queue)
        count = exporter.export(tmp_path / "labeled.jsonl")
        assert count == 1
        contents = (tmp_path / "labeled.jsonl").read_text()
        assert "approved case" in contents
        assert "rejected case" not in contents

    def test_regression_generator_refuses_unapproved_examples(self, store, queue, tmp_path):
        logger = FailureCaseLogger(store)
        event = logger.log_failure("gesture_understanding", FailureCategory.WRONG_GESTURE, "x")
        queue.enqueue(event.event_id)
        queue.submit_review(event.event_id, reviewer="alice", approve=False)
        exporter = AnnotationExporter(store, queue)
        rejected = LabeledExample(event=event, review=queue._items[event.event_id])

        generator = RegressionTestGenerator(out_path=tmp_path / "unused.yaml")
        with pytest.raises(ValueError):
            generator.generate(rejected)
        assert exporter.approved_examples() == []

    def test_regression_generator_appends_a_new_scenario(self, store, queue, tmp_path):
        example = self._approved_example(store, queue)
        out_path = tmp_path / "regression_scenarios.yaml"
        generator = RegressionTestGenerator(out_path=out_path)
        scenario = generator.generate(example)
        assert scenario.scenario_id.startswith("BB-REG-")
        assert scenario.expected_behavior == "halt immediately on stop_palm"
        assert len(generator.all_regression_scenarios()) == 1

        # A second approved case appends, it does not overwrite.
        store2 = AnonymizedEventStore(store._path.parent / "events2.jsonl")
        queue2 = HumanReviewQueue(queue._path.parent / "queue2.jsonl")
        example2 = self._approved_example(store2, queue2)
        generator.generate(example2)
        assert len(generator.all_regression_scenarios()) == 2


class TestDatasetVersionManager:
    def test_starts_at_zero_and_bumps_minor(self, tmp_path):
        mgr = DatasetVersionManager(tmp_path / "dataset_version.json")
        assert mgr.current_version() == "0.0.0"
        entry = mgr.bump("first field batch", new_examples_count=12)
        assert entry.version == "0.1.0"
        assert mgr.current_version() == "0.1.0"
        mgr.bump("second batch", new_examples_count=5)
        assert mgr.current_version() == "0.2.0"
        assert len(mgr.history()) == 2


class TestModelEvaluationTracker:
    def test_first_evaluation_is_always_allowed(self, tmp_path):
        tracker = ModelEvaluationTracker(tmp_path / "model_eval.json")
        candidate = EvaluationRun(
            model_version="v1",
            dataset_version="0.1.0",
            regression_pass_rate=0.8,
            total_regression_scenarios=10,
        )
        allowed, reason = tracker.deployment_allowed(candidate)
        assert allowed is True

    def test_regression_worsening_blocks_deployment(self, tmp_path):
        tracker = ModelEvaluationTracker(tmp_path / "model_eval.json")
        tracker.record(
            EvaluationRun(
                model_version="v1",
                dataset_version="0.1.0",
                regression_pass_rate=0.9,
                total_regression_scenarios=10,
            )
        )
        candidate = EvaluationRun(
            model_version="v2",
            dataset_version="0.2.0",
            regression_pass_rate=0.7,
            total_regression_scenarios=12,
        )
        allowed, reason = tracker.deployment_allowed(candidate)
        assert allowed is False
        assert "BLOCKED" in reason

    def test_equal_or_improved_pass_rate_is_allowed(self, tmp_path):
        tracker = ModelEvaluationTracker(tmp_path / "model_eval.json")
        tracker.record(
            EvaluationRun(
                model_version="v1",
                dataset_version="0.1.0",
                regression_pass_rate=0.9,
                total_regression_scenarios=10,
            )
        )
        candidate = EvaluationRun(
            model_version="v2",
            dataset_version="0.2.0",
            regression_pass_rate=0.95,
            total_regression_scenarios=10,
        )
        allowed, _ = tracker.deployment_allowed(candidate)
        assert allowed is True

    def test_recording_does_not_happen_implicitly(self, tmp_path):
        tracker = ModelEvaluationTracker(tmp_path / "model_eval.json")
        candidate = EvaluationRun(
            model_version="v1",
            dataset_version="0.1.0",
            regression_pass_rate=0.5,
            total_regression_scenarios=4,
        )
        tracker.deployment_allowed(candidate)
        assert tracker.latest() is None
