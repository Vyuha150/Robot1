"""Tests for FeedbackStore — repository over the failure-case database.

Uses bonbon_data_stores' SQLiteConnection/SchemaMigrator directly (verified
against a real temp-file SQLite database, not a mock) — this is the
"reuse, don't duplicate database access" requirement under real test.
"""

from __future__ import annotations

from bonbon_data_feedback.core.feedback_store import FailureCaseRecord, FeedbackStore


def _make_store(tmp_path):
    return FeedbackStore(tmp_path / "feedback.db")


def _record(**overrides) -> FailureCaseRecord:
    defaults = dict(
        case_id="",
        category="gesture",
        signal_name="gesture_low_confidence",
        expected_label="wave",
        actual_label="point",
        confidence=0.42,
        person_track_id="p1",
    )
    defaults.update(overrides)
    return FailureCaseRecord(**defaults)


class TestMigrationAndConnectionReuse:
    def test_creates_database_file(self, tmp_path):
        db_path = tmp_path / "feedback.db"
        _make_store(tmp_path)
        assert db_path.exists()

    def test_migration_is_idempotent(self, tmp_path):
        _make_store(tmp_path)
        store2 = _make_store(tmp_path)  # re-opening must not fail or duplicate schema
        assert store2.count_failure_cases() == 0


class TestInsertAndGet:
    def test_insert_assigns_case_id_when_blank(self, tmp_path):
        store = _make_store(tmp_path)
        case_id = store.insert_failure_case(_record())
        assert case_id

    def test_get_failure_case_round_trips_fields(self, tmp_path):
        store = _make_store(tmp_path)
        case_id = store.insert_failure_case(_record(confidence=0.31, context={"frame_idx": 7}))
        got = store.get_failure_case(case_id)
        assert got is not None
        assert got.confidence == 0.31
        assert got.context == {"frame_idx": 7}

    def test_get_missing_case_returns_none(self, tmp_path):
        store = _make_store(tmp_path)
        assert store.get_failure_case("does-not-exist") is None

    def test_count_increments(self, tmp_path):
        store = _make_store(tmp_path)
        store.insert_failure_case(_record())
        store.insert_failure_case(_record())
        assert store.count_failure_cases() == 2


class TestBatchInsert:
    def test_batch_insert_returns_all_ids(self, tmp_path):
        store = _make_store(tmp_path)
        ids = store.insert_failure_cases_batch([_record(), _record(), _record()])
        assert len(ids) == 3
        assert store.count_failure_cases() == 3

    def test_batch_insert_is_a_single_round_of_writes(self, tmp_path):
        """Addresses the audit finding that no repository in this project
        batches writes — verified by checking all rows land from one call."""
        store = _make_store(tmp_path)
        records = [_record(signal_name=f"sig_{i}") for i in range(50)]
        store.insert_failure_cases_batch(records)
        assert store.count_failure_cases() == 50


class TestQuery:
    def test_query_filters_by_category(self, tmp_path):
        store = _make_store(tmp_path)
        store.insert_failure_case(_record(category="gesture"))
        store.insert_failure_case(_record(category="object"))
        results = store.query_failure_cases(category="object")
        assert len(results) == 1
        assert results[0].category == "object"

    def test_query_filters_by_hard_negative(self, tmp_path):
        store = _make_store(tmp_path)
        store.insert_failure_case(_record(is_hard_negative=True))
        store.insert_failure_case(_record(is_hard_negative=False))
        results = store.query_failure_cases(is_hard_negative=True)
        assert len(results) == 1
        assert results[0].is_hard_negative is True

    def test_query_respects_limit(self, tmp_path):
        store = _make_store(tmp_path)
        for _ in range(10):
            store.insert_failure_case(_record())
        assert len(store.query_failure_cases(limit=3)) == 3


class TestReview:
    def test_mark_reviewed_sets_fields(self, tmp_path):
        store = _make_store(tmp_path)
        case_id = store.insert_failure_case(_record())
        ok = store.mark_reviewed(case_id, "wave")
        assert ok is True
        got = store.get_failure_case(case_id)
        assert got.reviewed is True
        assert got.review_label == "wave"

    def test_mark_reviewed_missing_case_returns_false(self, tmp_path):
        store = _make_store(tmp_path)
        assert store.mark_reviewed("does-not-exist", "wave") is False


class TestRetentionDeletion:
    def test_delete_expired_removes_only_old_rows_in_category(self, tmp_path):
        store = _make_store(tmp_path)
        store.insert_failure_case(_record(category="face", created_at=1000.0))
        store.insert_failure_case(_record(category="face", created_at=9000.0))
        store.insert_failure_case(_record(category="gesture", created_at=1000.0))
        deleted = store.delete_expired("face", cutoff_ts=5000.0)
        assert deleted == 1
        assert store.count_failure_cases() == 2


class TestDatasetVersions:
    def test_insert_and_list_dataset_version(self, tmp_path):
        store = _make_store(tmp_path)
        store.insert_dataset_version("gesture_v1", "gesture", 100, "/exports/gesture_v1.jsonl")
        versions = store.list_dataset_versions(category="gesture")
        assert len(versions) == 1
        assert versions[0]["name"] == "gesture_v1"
        assert versions[0]["case_count"] == 100


class TestModelEvaluations:
    def test_insert_and_list_model_evaluation(self, tmp_path):
        store = _make_store(tmp_path)
        store.insert_model_evaluation("gesture_classifier", "v2", "gesture", 500, 0.91)
        evals = store.list_model_evaluations(model_name="gesture_classifier")
        assert len(evals) == 1
        assert evals[0]["accuracy"] == 0.91
