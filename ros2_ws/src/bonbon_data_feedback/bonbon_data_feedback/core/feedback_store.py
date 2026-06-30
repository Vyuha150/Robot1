"""FeedbackStore — thin repository over bonbon_data_feedback's own database.

Reuses bonbon_data_stores.sqlite.connection.SQLiteConnection and
.migrations.SchemaMigrator directly (the generic, reusable connection and
migration machinery) rather than writing a second ad-hoc SQLite layer — the
ONLY new things here are this package's own schema (sql_schema.MIGRATIONS)
and its own database file, justified by retention/privacy rules that
deliberately differ from bonbon_data_stores' operational data (see
PrivacySafeDataPolicy).
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from bonbon_data_stores.sqlite.connection import SQLiteConnection
from bonbon_data_stores.sqlite.migrations import SchemaMigrator

from bonbon_data_feedback.schema.sql_schema import MIGRATIONS


@dataclass
class FailureCaseRecord:
    case_id: str
    category: str
    signal_name: str
    expected_label: str
    actual_label: str
    confidence: float
    person_track_id: str
    context: dict = field(default_factory=dict)
    is_hard_negative: bool = False
    has_raw_snapshot: bool = False
    raw_snapshot_path: str = ""
    created_at: float = 0.0
    reviewed: bool = False
    review_label: str = ""
    reviewed_at: float | None = None


class FeedbackStore:
    def __init__(self, db_path: str | Path) -> None:
        self._conn = SQLiteConnection(Path(db_path))
        SchemaMigrator(self._conn, migrations=MIGRATIONS).migrate()

    def close(self) -> None:
        self._conn.close()

    # ── Failure cases ────────────────────────────────────────────────────────

    def insert_failure_case(self, record: FailureCaseRecord) -> str:
        case_id = record.case_id or str(uuid.uuid4())
        created_at = record.created_at or time.time()
        self._conn.execute(
            """
            INSERT INTO failure_cases (
                case_id, category, signal_name, expected_label, actual_label,
                confidence, person_track_id, context_json, is_hard_negative,
                has_raw_snapshot, raw_snapshot_path, created_at, reviewed,
                review_label, reviewed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                case_id,
                record.category,
                record.signal_name,
                record.expected_label,
                record.actual_label,
                record.confidence,
                record.person_track_id,
                json.dumps(record.context),
                int(record.is_hard_negative),
                int(record.has_raw_snapshot),
                record.raw_snapshot_path,
                created_at,
                int(record.reviewed),
                record.review_label,
                record.reviewed_at,
            ),
        )
        self._conn.commit()
        return case_id

    def insert_failure_cases_batch(self, records: list[FailureCaseRecord]) -> list[str]:
        """Batched insert — the audit found NO repository anywhere in this
        project supports batch writes; this is built batched from the start."""
        ids = []
        rows = []
        for r in records:
            case_id = r.case_id or str(uuid.uuid4())
            ids.append(case_id)
            rows.append(
                (
                    case_id,
                    r.category,
                    r.signal_name,
                    r.expected_label,
                    r.actual_label,
                    r.confidence,
                    r.person_track_id,
                    json.dumps(r.context),
                    int(r.is_hard_negative),
                    int(r.has_raw_snapshot),
                    r.raw_snapshot_path,
                    r.created_at or time.time(),
                    int(r.reviewed),
                    r.review_label,
                    r.reviewed_at,
                )
            )
        self._conn.executemany(
            """
            INSERT INTO failure_cases (
                case_id, category, signal_name, expected_label, actual_label,
                confidence, person_track_id, context_json, is_hard_negative,
                has_raw_snapshot, raw_snapshot_path, created_at, reviewed,
                review_label, reviewed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        self._conn.commit()
        return ids

    def get_failure_case(self, case_id: str) -> FailureCaseRecord | None:
        row = self._conn.execute(
            "SELECT * FROM failure_cases WHERE case_id = ?", (case_id,)
        ).fetchone()
        return self._row_to_record(row) if row else None

    def query_failure_cases(
        self,
        category: str | None = None,
        is_hard_negative: bool | None = None,
        reviewed: bool | None = None,
        limit: int = 100,
    ) -> list[FailureCaseRecord]:
        clauses = []
        params: list = []
        if category is not None:
            clauses.append("category = ?")
            params.append(category)
        if is_hard_negative is not None:
            clauses.append("is_hard_negative = ?")
            params.append(int(is_hard_negative))
        if reviewed is not None:
            clauses.append("reviewed = ?")
            params.append(int(reviewed))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._conn.execute(
            f"SELECT * FROM failure_cases {where} ORDER BY created_at DESC LIMIT ?",
            (*params, limit),
        ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def mark_reviewed(self, case_id: str, review_label: str) -> bool:
        cur = self._conn.execute(
            "UPDATE failure_cases SET reviewed = 1, review_label = ?, reviewed_at = ? WHERE case_id = ?",
            (review_label, time.time(), case_id),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def delete_expired(self, category: str, cutoff_ts: float) -> int:
        cur = self._conn.execute(
            "DELETE FROM failure_cases WHERE category = ? AND created_at < ?",
            (category, cutoff_ts),
        )
        self._conn.commit()
        return cur.rowcount

    def count_failure_cases(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) FROM failure_cases").fetchone()
        return int(row[0]) if row else 0

    # ── Dataset versions ─────────────────────────────────────────────────────

    def insert_dataset_version(
        self, name: str, category: str, case_count: int, export_path: str, notes: str = ""
    ) -> str:
        version_id = str(uuid.uuid4())
        self._conn.execute(
            "INSERT INTO dataset_versions (version_id, name, category, case_count, created_at, export_path, notes)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (version_id, name, category, case_count, time.time(), export_path, notes),
        )
        self._conn.commit()
        return version_id

    def list_dataset_versions(self, category: str | None = None) -> list[dict]:
        if category is not None:
            rows = self._conn.execute(
                "SELECT * FROM dataset_versions WHERE category = ? ORDER BY created_at DESC",
                (category,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM dataset_versions ORDER BY created_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Model evaluations ────────────────────────────────────────────────────

    def insert_model_evaluation(
        self,
        model_name: str,
        model_version: str,
        category: str,
        sample_count: int,
        accuracy: float | None,
        notes: str = "",
    ) -> str:
        eval_id = str(uuid.uuid4())
        self._conn.execute(
            "INSERT INTO model_evaluations (eval_id, model_name, model_version, category, "
            "sample_count, accuracy, notes, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                eval_id,
                model_name,
                model_version,
                category,
                sample_count,
                accuracy,
                notes,
                time.time(),
            ),
        )
        self._conn.commit()
        return eval_id

    def list_model_evaluations(self, model_name: str | None = None) -> list[dict]:
        if model_name is not None:
            rows = self._conn.execute(
                "SELECT * FROM model_evaluations WHERE model_name = ? ORDER BY created_at DESC",
                (model_name,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM model_evaluations ORDER BY created_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Internal helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _row_to_record(row) -> FailureCaseRecord:
        d = dict(row)
        return FailureCaseRecord(
            case_id=d["case_id"],
            category=d["category"],
            signal_name=d["signal_name"],
            expected_label=d["expected_label"],
            actual_label=d["actual_label"],
            confidence=d["confidence"],
            person_track_id=d["person_track_id"],
            context=json.loads(d["context_json"]) if d["context_json"] else {},
            is_hard_negative=bool(d["is_hard_negative"]),
            has_raw_snapshot=bool(d["has_raw_snapshot"]),
            raw_snapshot_path=d["raw_snapshot_path"],
            created_at=d["created_at"],
            reviewed=bool(d["reviewed"]),
            review_label=d["review_label"],
            reviewed_at=d["reviewed_at"],
        )
