"""PatientDataStore — encrypted-at-rest local store for submitted records.

Every row's JSON payload is AES-256-GCM encrypted with PHICipher before it
touches disk. Only *submitted* (consented) data lands here — draft/unsubmitted
intake forms stay in SessionStore's in-memory dict and are never persisted.
"""

from __future__ import annotations

import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

from bonbon_patient_kiosk.data.crypto import PHICipher

_SCHEMA = """
CREATE TABLE IF NOT EXISTS intake_records (
    intake_id   TEXT PRIMARY KEY,
    session_id  TEXT NOT NULL,
    payload     TEXT NOT NULL,
    submitted_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS appointments (
    appointment_id TEXT PRIMARY KEY,
    payload        TEXT NOT NULL,
    created_at     REAL NOT NULL,
    status         TEXT NOT NULL DEFAULT 'confirmed'
);
CREATE TABLE IF NOT EXISTS queue_tokens (
    token_id    TEXT PRIMARY KEY,
    payload     TEXT NOT NULL,
    created_at  REAL NOT NULL,
    status      TEXT NOT NULL DEFAULT 'waiting'
);
CREATE TABLE IF NOT EXISTS feedback (
    feedback_id TEXT PRIMARY KEY,
    payload     TEXT NOT NULL,
    submitted_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_intake_submitted ON intake_records(submitted_at);
"""


class PatientDataStore:
    def __init__(self, db_path: Path, cipher: PHICipher) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._cipher = cipher
        with self._conn() as conn:
            conn.executescript(_SCHEMA)
            conn.commit()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        return conn

    # ------------------------------------------------------------------
    # Intake
    # ------------------------------------------------------------------

    def save_intake(self, intake_id: str, session_id: str, payload: dict[str, Any]) -> None:
        blob = self._cipher.encrypt(payload)
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO intake_records (intake_id, session_id, payload, submitted_at) "
                "VALUES (?,?,?,?);",
                (intake_id, session_id, blob, time.time()),
            )
            conn.commit()

    def get_intake(self, intake_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM intake_records WHERE intake_id = ?;", (intake_id,)
            ).fetchone()
        if not row:
            return None
        data = self._cipher.decrypt(row["payload"])
        data["_submitted_at"] = row["submitted_at"]
        return data

    def purge_expired_intake(self, retention_days: int) -> int:
        cutoff = time.time() - retention_days * 86400
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM intake_records WHERE submitted_at < ?;", (cutoff,))
            conn.commit()
        return cur.rowcount

    # ------------------------------------------------------------------
    # Appointments
    # ------------------------------------------------------------------

    def save_appointment(self, appointment_id: str, payload: dict[str, Any]) -> None:
        blob = self._cipher.encrypt(payload)
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO appointments (appointment_id, payload, created_at, status) "
                "VALUES (?,?,?,?);",
                (appointment_id, blob, time.time(), payload.get("status", "confirmed")),
            )
            conn.commit()

    def update_appointment(self, appointment_id: str, payload: dict[str, Any]) -> bool:
        blob = self._cipher.encrypt(payload)
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE appointments SET payload = ?, status = ? WHERE appointment_id = ?;",
                (blob, payload.get("status", "confirmed"), appointment_id),
            )
            conn.commit()
        return cur.rowcount > 0

    def get_appointment(self, appointment_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM appointments WHERE appointment_id = ?;", (appointment_id,)
            ).fetchone()
        return self._cipher.decrypt(row["payload"]) if row else None

    # ------------------------------------------------------------------
    # Queue tokens
    # ------------------------------------------------------------------

    def save_token(self, token_id: str, payload: dict[str, Any]) -> None:
        blob = self._cipher.encrypt(payload)
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO queue_tokens (token_id, payload, created_at, status) "
                "VALUES (?,?,?,?);",
                (token_id, blob, time.time(), payload.get("status", "waiting")),
            )
            conn.commit()

    def update_token(self, token_id: str, payload: dict[str, Any]) -> bool:
        blob = self._cipher.encrypt(payload)
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE queue_tokens SET payload = ?, status = ? WHERE token_id = ?;",
                (blob, payload.get("status", "waiting"), token_id),
            )
            conn.commit()
        return cur.rowcount > 0

    def get_token(self, token_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM queue_tokens WHERE token_id = ?;", (token_id,)
            ).fetchone()
        return self._cipher.decrypt(row["payload"]) if row else None

    def list_waiting_tokens(self, department_id: str) -> list[dict[str, Any]]:
        return [t for t in self.list_all_waiting_tokens() if t.get("department_id") == department_id]

    def list_all_waiting_tokens(self) -> list[dict[str, Any]]:
        """All waiting tokens across every department, oldest first —
        used by the staff dashboard's queue overview."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM queue_tokens WHERE status = 'waiting' ORDER BY created_at ASC;"
            ).fetchall()
        return [self._cipher.decrypt(r["payload"]) for r in rows]

    # ------------------------------------------------------------------
    # Feedback
    # ------------------------------------------------------------------

    def save_feedback(self, payload: dict[str, Any]) -> str:
        feedback_id = payload.get("feedback_id") or str(uuid.uuid4())
        blob = self._cipher.encrypt(payload)
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO feedback (feedback_id, payload, submitted_at) VALUES (?,?,?);",
                (feedback_id, blob, time.time()),
            )
            conn.commit()
        return feedback_id

    # ------------------------------------------------------------------
    # Staff dashboard aggregate reads
    # ------------------------------------------------------------------

    def list_appointments(self, status: str | None = None) -> list[dict[str, Any]]:
        """All appointments, newest first, optionally filtered by status —
        used by the staff dashboard's "today's appointments" section."""
        with self._conn() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM appointments WHERE status = ? ORDER BY created_at DESC;",
                    (status,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM appointments ORDER BY created_at DESC;"
                ).fetchall()
        return [self._cipher.decrypt(r["payload"]) for r in rows]

    def list_recent_feedback(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM feedback ORDER BY submitted_at DESC LIMIT ?;", (limit,)
            ).fetchall()
        return [self._cipher.decrypt(r["payload"]) for r in rows]

    def feedback_summary(self) -> dict[str, Any]:
        # Ratings live inside the encrypted payload, not a plain column, so
        # the average must be computed over decrypted rows, not in SQL.
        feedback = self.list_recent_feedback(limit=100_000)
        count = len(feedback)
        average = sum(f.get("rating", 0) for f in feedback) / count if count else 0.0
        return {"average_rating": round(average, 2), "count": count}
