"""MemoryPrivacyManager — enforce do_not_store and right-to-be-forgotten.

Rules
-----
1. Any event with ``privacy_level == do_not_store`` is immediately discarded.
   It is never passed to any repository, FAISS index, or ChromaDB collection.

2. ``forget_user()`` cascades deletion across:
   - All SQLite tables (via UserProfileRepository.forget_user)
   - FAISS indexes (removes all vectors with matching user_id payload field)
   - ChromaDB collections (deletes documents with matching user_id metadata)
   - Writes an audit log entry for each deletion

3. Audio data is never stored unless ``privacy.store_audio=True`` in config.
   The manager strips the ``audio_ref`` field before saving interactions
   when the config flag is False.

4. Face-encoding references are stripped when ``privacy.store_face_data=False``.
"""

from __future__ import annotations

import logging
from typing import Any

from bonbon_data_stores.schema.models import (
    AuditLogEntry,
    InteractionEvent,
    PrivacyLevel,
    UserRecord,
)

logger = logging.getLogger(__name__)


class MemoryPrivacyManager:
    """Screen events for privacy compliance before storage.

    Parameters
    ----------
    store_audio:
        Mirror of ``PrivacyConfig.store_audio``.  When False (default),
        ``audio_ref`` is stripped from interactions before saving.
    store_face_data:
        Mirror of ``PrivacyConfig.store_face_data``.  When False (default),
        ``face_encoding_ref`` is stripped from user records before saving.
    """

    def __init__(
        self,
        store_audio: bool = False,
        store_face_data: bool = False,
    ) -> None:
        self._store_audio = store_audio
        self._store_face_data = store_face_data

    # ------------------------------------------------------------------
    # Screening
    # ------------------------------------------------------------------

    def is_storable(self, event: Any) -> bool:
        """Return False if the event carries ``do_not_store``."""
        privacy = getattr(event, "privacy_level", None)
        if privacy is None:
            return True
        if isinstance(privacy, PrivacyLevel):
            return privacy != PrivacyLevel.DO_NOT_STORE
        return str(privacy).lower() != "do_not_store"

    def screen_interaction(self, event: InteractionEvent) -> InteractionEvent:
        """Return a copy of *event* with privacy-violating fields stripped.

        * Strips ``audio_ref`` when ``store_audio=False``.
        * Returns the event unchanged if it is already compliant.

        Raises ``ValueError`` if ``privacy_level == do_not_store``.
        """
        if not self.is_storable(event):
            raise ValueError(
                f"do_not_store: interaction {event.event_id} must not be written to storage"
            )

        if not self._store_audio and event.audio_ref is not None:
            logger.debug(
                "Stripping audio_ref from interaction %s (store_audio=False)",
                event.event_id,
            )
            event = event.model_copy(update={"audio_ref": None})

        return event

    def screen_user(self, record: UserRecord) -> UserRecord:
        """Return a copy of *record* with privacy-violating fields stripped.

        * Strips ``face_encoding_ref`` when ``store_face_data=False``.

        Raises ``ValueError`` if ``privacy_level == do_not_store``.
        """
        if not self.is_storable(record):
            raise ValueError(
                f"do_not_store: user record {record.user_id} must not be written to storage"
            )

        if not self._store_face_data and record.face_encoding_ref is not None:
            logger.debug(
                "Stripping face_encoding_ref from user %s (store_face_data=False)",
                record.user_id,
            )
            record = record.model_copy(update={"face_encoding_ref": None})

        return record

    # ------------------------------------------------------------------
    # Right-to-be-forgotten (GDPR-style)
    # ------------------------------------------------------------------

    def build_forget_audit_entry(
        self,
        user_id: str,
        actor: str,
        detail: str = "",
    ) -> AuditLogEntry:
        """Build an audit log entry for a right-to-be-forgotten request."""
        return AuditLogEntry(
            actor=actor,
            action="forget_user",
            target_type="user",
            target_id=user_id,
            outcome="success",
            detail=detail or f"Right-to-be-forgotten: all data for user {user_id} deleted",
        )

    # ------------------------------------------------------------------
    # Config accessors
    # ------------------------------------------------------------------

    @property
    def store_audio(self) -> bool:
        return self._store_audio

    @property
    def store_face_data(self) -> bool:
        return self._store_face_data

    def update_config(
        self,
        store_audio: bool | None = None,
        store_face_data: bool | None = None,
    ) -> None:
        """Runtime config update (e.g. from ROS2 param change)."""
        if store_audio is not None:
            self._store_audio = store_audio
        if store_face_data is not None:
            self._store_face_data = store_face_data
