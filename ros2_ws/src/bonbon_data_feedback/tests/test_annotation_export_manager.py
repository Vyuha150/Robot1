"""Tests for AnnotationExportManager — JSONL export of stored failure cases."""

from __future__ import annotations

import json

from bonbon_data_feedback.core.annotation_export_manager import AnnotationExportManager
from bonbon_data_feedback.core.feedback_store import FailureCaseRecord, FeedbackStore


def _store(tmp_path):
    return FeedbackStore(tmp_path / "feedback.db")


class TestExport:
    def test_export_writes_one_line_per_case(self, tmp_path):
        store = _store(tmp_path)
        store.insert_failure_case(
            FailureCaseRecord(
                case_id="",
                category="gesture",
                signal_name="s",
                expected_label="wave",
                actual_label="point",
                confidence=0.4,
                person_track_id="p1",
            )
        )
        store.insert_failure_case(
            FailureCaseRecord(
                case_id="",
                category="gesture",
                signal_name="s",
                expected_label="wave",
                actual_label="point",
                confidence=0.5,
                person_track_id="p1",
            )
        )
        manager = AnnotationExportManager(store, tmp_path / "exports")
        result = manager.export(category="gesture")
        assert result.count == 2
        lines = open(result.path, encoding="utf-8").read().strip().splitlines()
        assert len(lines) == 2
        row = json.loads(lines[0])
        assert row["category"] == "gesture"

    def test_export_filters_by_category(self, tmp_path):
        store = _store(tmp_path)
        store.insert_failure_case(
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
        store.insert_failure_case(
            FailureCaseRecord(
                case_id="",
                category="object",
                signal_name="s",
                expected_label="",
                actual_label="x",
                confidence=0.4,
                person_track_id="",
            )
        )
        manager = AnnotationExportManager(store, tmp_path / "exports")
        result = manager.export(category="object")
        assert result.count == 1

    def test_export_reviewed_only(self, tmp_path):
        store = _store(tmp_path)
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
        store.insert_failure_case(
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
        store.mark_reviewed(case_id, "x")
        manager = AnnotationExportManager(store, tmp_path / "exports")
        result = manager.export(category="gesture", reviewed_only=True)
        assert result.count == 1

    def test_export_never_includes_raw_snapshot_payload_only_path(self, tmp_path):
        store = _store(tmp_path)
        store.insert_failure_case(
            FailureCaseRecord(
                case_id="",
                category="face",
                signal_name="s",
                expected_label="",
                actual_label="x",
                confidence=0.4,
                person_track_id="",
                has_raw_snapshot=True,
                raw_snapshot_path="/debug/face_1.jpg",
            )
        )
        manager = AnnotationExportManager(store, tmp_path / "exports")
        result = manager.export(category="face")
        row = json.loads(open(result.path, encoding="utf-8").readline())
        assert row["raw_snapshot_path"] == "/debug/face_1.jpg"
        assert "raw_snapshot_bytes" not in row
        assert "face_embedding" not in row

    def test_export_creates_export_dir_if_missing(self, tmp_path):
        store = _store(tmp_path)
        manager = AnnotationExportManager(store, tmp_path / "nested" / "exports")
        result = manager.export(category="gesture")
        assert result.count == 0
        import os

        assert os.path.exists(result.path)
