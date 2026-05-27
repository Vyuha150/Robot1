"""UserProfileRepository — CRUD for the ``users`` and ``user_preferences`` tables."""

from __future__ import annotations

import json
import uuid
from typing import Any

from bonbon_data_stores.schema.models import PrivacyLevel, UserPreference, UserRecord
from bonbon_data_stores.sqlite.connection import SQLiteConnection
from bonbon_data_stores.sqlite.repositories.base import BaseRepository


class UserProfileRepository(BaseRepository):
    """Manage user profile records and preferences.

    All biometric fields (face_encoding_ref, voice_profile_ref) are reference
    tokens only — raw biometric data is never stored here.
    """

    def __init__(self, conn: SQLiteConnection) -> None:
        super().__init__(conn)

    # ------------------------------------------------------------------
    # UserRecord CRUD
    # ------------------------------------------------------------------

    def save(self, record: UserRecord) -> str:
        """Insert or update a user record.  Returns user_id."""
        self._assert_storable(record.privacy_level)

        sql = """
        INSERT INTO users (
            user_id, display_name, language, preferred_interaction_style,
            accessibility_needs, face_encoding_ref, voice_profile_ref,
            created_at, last_seen_at, interaction_count,
            privacy_level, retention_policy, is_anonymous
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(user_id) DO UPDATE SET
            display_name                = excluded.display_name,
            language                    = excluded.language,
            preferred_interaction_style = excluded.preferred_interaction_style,
            accessibility_needs         = excluded.accessibility_needs,
            face_encoding_ref           = excluded.face_encoding_ref,
            voice_profile_ref           = excluded.voice_profile_ref,
            last_seen_at                = excluded.last_seen_at,
            interaction_count           = excluded.interaction_count,
            privacy_level               = excluded.privacy_level,
            retention_policy            = excluded.retention_policy,
            is_anonymous                = excluded.is_anonymous;
        """
        params = (
            record.user_id,
            record.display_name,
            record.language,
            record.preferred_interaction_style,
            json.dumps(record.accessibility_needs),
            record.face_encoding_ref,
            record.voice_profile_ref,
            record.created_at,
            record.last_seen_at,
            record.interaction_count,
            record.privacy_level.value,
            record.retention_policy.value,
            int(record.is_anonymous),
        )
        self._execute(sql, params)

        # Persist preferences
        for pref in record.preferences:
            self.save_preference(record.user_id, pref)

        return record.user_id

    def get_by_id(self, user_id: str) -> UserRecord | None:
        row = self._fetchone("SELECT * FROM users WHERE user_id = ?;", (user_id,))
        if row is None:
            return None
        return self._row_to_model(row)

    def find_by_name(self, display_name: str) -> list[UserRecord]:
        rows = self._fetchall(
            "SELECT * FROM users WHERE display_name LIKE ? ORDER BY last_seen_at DESC;",
            (f"%{display_name}%",),
        )
        return [self._row_to_model(r) for r in rows]

    def list_all(self, limit: int = 100, offset: int = 0) -> list[UserRecord]:
        rows = self._fetchall(
            "SELECT * FROM users ORDER BY last_seen_at DESC LIMIT ? OFFSET ?;",
            (limit, offset),
        )
        return [self._row_to_model(r) for r in rows]

    def update_last_seen(self, user_id: str) -> None:
        self._execute(
            "UPDATE users SET last_seen_at = ?, interaction_count = interaction_count + 1 WHERE user_id = ?;",
            (self._now(), user_id),
        )

    def delete(self, user_id: str) -> bool:
        """Delete user and cascade-delete all related preferences and interactions."""
        count = self._execute("DELETE FROM users WHERE user_id = ?;", (user_id,))
        return count > 0

    def delete_all(self) -> int:
        """Delete every user record.  Returns number of deleted rows."""
        return self._execute("DELETE FROM users;")

    def count(self) -> int:
        return self._count("users")

    # ------------------------------------------------------------------
    # User preferences
    # ------------------------------------------------------------------

    def save_preference(self, user_id: str, pref: UserPreference) -> str:
        pref_id = str(uuid.uuid4())
        sql = """
        INSERT INTO user_preferences (pref_id, user_id, category, key, value, updated_at)
        VALUES (?,?,?,?,?,?)
        ON CONFLICT(user_id, category, key) DO UPDATE SET
            value      = excluded.value,
            updated_at = excluded.updated_at;
        """
        self._execute(sql, (pref_id, user_id, pref.category, pref.key, pref.value, self._now()))
        return pref_id

    def get_preferences(self, user_id: str) -> list[UserPreference]:
        rows = self._fetchall(
            "SELECT * FROM user_preferences WHERE user_id = ? ORDER BY category, key;",
            (user_id,),
        )
        return [
            UserPreference(key=r["key"], value=r["value"], category=r["category"]) for r in rows
        ]

    def delete_preference(self, user_id: str, category: str, key: str) -> bool:
        count = self._execute(
            "DELETE FROM user_preferences WHERE user_id = ? AND category = ? AND key = ?;",
            (user_id, category, key),
        )
        return count > 0

    # ------------------------------------------------------------------
    # Right-to-be-forgotten (GDPR-style deletion)
    # ------------------------------------------------------------------

    def forget_user(self, user_id: str) -> dict[str, int]:
        """Cascade-delete the user and all directly associated records.

        Returns a dict of table → deleted row count for the audit log.
        """
        results: dict[str, int] = {}
        results["user_preferences"] = self._execute(
            "DELETE FROM user_preferences WHERE user_id = ?;", (user_id,)
        )
        results["interactions"] = self._execute(
            "UPDATE interactions SET user_id = NULL, input_text = NULL, "
            "response_text = NULL, audio_ref = NULL WHERE user_id = ?;",
            (user_id,),
        )
        results["users"] = self._execute("DELETE FROM users WHERE user_id = ?;", (user_id,))
        return results

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _row_to_model(self, row: dict[str, Any]) -> UserRecord:
        prefs = self.get_preferences(row["user_id"])
        return UserRecord(
            user_id=row["user_id"],
            display_name=row["display_name"],
            language=row["language"],
            preferred_interaction_style=row["preferred_interaction_style"],
            accessibility_needs=json.loads(row["accessibility_needs"] or "[]"),
            face_encoding_ref=row.get("face_encoding_ref"),
            voice_profile_ref=row.get("voice_profile_ref"),
            created_at=row["created_at"],
            last_seen_at=row["last_seen_at"],
            interaction_count=row["interaction_count"],
            privacy_level=PrivacyLevel(row["privacy_level"]),
            retention_policy=row["retention_policy"],
            is_anonymous=bool(row["is_anonymous"]),
            preferences=prefs,
        )
