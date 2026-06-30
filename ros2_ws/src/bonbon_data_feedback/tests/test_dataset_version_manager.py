"""Tests for DatasetVersionManager — named, versioned dataset exports."""

from __future__ import annotations

from bonbon_data_feedback.core.annotation_export_manager import AnnotationExportManager
from bonbon_data_feedback.core.dataset_version_manager import DatasetVersionManager
from bonbon_data_feedback.core.feedback_store import FailureCaseRecord, FeedbackStore


def _manager(tmp_path):
    store = FeedbackStore(tmp_path / "feedback.db")
    export_manager = AnnotationExportManager(store, tmp_path / "exports")
    return DatasetVersionManager(store, export_manager), store


class TestCreateVersion:
    def test_create_version_records_case_count(self, tmp_path):
        manager, store = _manager(tmp_path)
        case_id = store.insert_failure_case(
            FailureCaseRecord(
                case_id="",
                category="gesture",
                signal_name="s",
                expected_label="",
                actual_label="x",
                confidence=0.4,
                person_track_id="",
            )
        )
        store.mark_reviewed(case_id, "wave")
        version_id = manager.create_version("gesture_v1", "gesture")
        versions = manager.list_versions(category="gesture")
        assert len(versions) == 1
        assert versions[0]["version_id"] == version_id
        assert versions[0]["case_count"] == 1

    def test_create_version_defaults_to_reviewed_only(self, tmp_path):
        manager, store = _manager(tmp_path)
        store.insert_failure_case(
            FailureCaseRecord(  # unreviewed
                case_id="",
                category="gesture",
                signal_name="s",
                expected_label="",
                actual_label="x",
                confidence=0.4,
                person_track_id="",
            )
        )
        manager.create_version("gesture_v1", "gesture")
        versions = manager.list_versions(category="gesture")
        assert versions[0]["case_count"] == 0

    def test_list_versions_filters_by_category(self, tmp_path):
        manager, _ = _manager(tmp_path)
        manager.create_version("gesture_v1", "gesture")
        manager.create_version("object_v1", "object")
        assert len(manager.list_versions(category="gesture")) == 1
        assert len(manager.list_versions(category="object")) == 1
        assert len(manager.list_versions()) == 2
