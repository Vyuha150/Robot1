"""DatasetVersionManager — ties a named, versioned dataset export to its
underlying failure-case query, so a training run can reference a stable,
reproducible "gesture_dataset_v3" rather than an ad-hoc unlabeled file.
"""

from __future__ import annotations

from bonbon_data_feedback.core.annotation_export_manager import AnnotationExportManager
from bonbon_data_feedback.core.feedback_store import FeedbackStore


class DatasetVersionManager:
    def __init__(self, store: FeedbackStore, export_manager: AnnotationExportManager) -> None:
        self._store = store
        self._export_manager = export_manager

    def create_version(
        self,
        name: str,
        category: str,
        reviewed_only: bool = True,
        notes: str = "",
    ) -> str:
        """Exports the current matching cases and records that export as a
        named, immutable version. reviewed_only defaults True — an
        unreviewed failure case is a candidate, not yet a labeled example."""
        result = self._export_manager.export(category=category, reviewed_only=reviewed_only)
        return self._store.insert_dataset_version(
            name=name,
            category=category,
            case_count=result.count,
            export_path=result.path,
            notes=notes,
        )

    def list_versions(self, category: str | None = None) -> list[dict]:
        return self._store.list_dataset_versions(category=category)
