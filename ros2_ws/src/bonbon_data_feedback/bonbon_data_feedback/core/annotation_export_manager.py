"""AnnotationExportManager — exports stored failure cases to a JSONL file for
human annotation review or model retraining.

Exports only ever contain what is already in the database — since
FailureCaseLogger/HardNegativeCollector already strip forbidden context
keys and gate raw_snapshot_path behind explicit debug mode, the export
inherits that same privacy guarantee for free; no separate redaction pass
is needed here.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

from bonbon_data_feedback.core.feedback_store import FeedbackStore


@dataclass
class ExportResult:
    path: str
    count: int


class AnnotationExportManager:
    def __init__(self, store: FeedbackStore, export_dir: str | Path) -> None:
        self._store = store
        self._export_dir = Path(export_dir)
        self._export_dir.mkdir(parents=True, exist_ok=True)

    def export(
        self,
        category: str | None = None,
        reviewed_only: bool = False,
        is_hard_negative: bool | None = None,
        limit: int = 1000,
        filename: str | None = None,
    ) -> ExportResult:
        cases = self._store.query_failure_cases(
            category=category,
            is_hard_negative=is_hard_negative,
            reviewed=True if reviewed_only else None,
            limit=limit,
        )

        name = filename or f"export_{category or 'all'}_{int(time.time())}.jsonl"
        out_path = self._export_dir / name

        with out_path.open("w", encoding="utf-8") as f:
            for case in cases:
                row = {
                    "case_id": case.case_id,
                    "category": case.category,
                    "signal_name": case.signal_name,
                    "expected_label": case.expected_label,
                    "actual_label": case.actual_label,
                    "confidence": case.confidence,
                    "context": case.context,
                    "is_hard_negative": case.is_hard_negative,
                    "raw_snapshot_path": case.raw_snapshot_path,
                    "review_label": case.review_label,
                    "created_at": case.created_at,
                }
                f.write(json.dumps(row) + "\n")

        return ExportResult(path=str(out_path), count=len(cases))
