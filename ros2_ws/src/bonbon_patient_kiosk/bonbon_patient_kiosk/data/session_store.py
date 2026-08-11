"""SessionStore — in-memory-only patient session state.

This is the core PHI safety control described in the plan: an in-progress
intake form lives ONLY here (never written to disk) until the patient
explicitly confirms + submits. Idle sessions are purged so the next patient
at the kiosk never sees a prior patient's half-finished form.
"""

from __future__ import annotations

import threading
import time

from bonbon_patient_kiosk.models.patient_models import IntakeForm
from bonbon_patient_kiosk.models.session_models import SessionInfo


class SessionStore:
    def __init__(self, idle_timeout_sec: float = 90.0, max_session_age_sec: float = 1800.0) -> None:
        self._idle_timeout = idle_timeout_sec
        self._max_age = max_session_age_sec
        self._lock = threading.Lock()
        self._sessions: dict[str, SessionInfo] = {}
        self._drafts: dict[str, IntakeForm] = {}

    # ------------------------------------------------------------------
    def create(self, info: SessionInfo) -> SessionInfo:
        with self._lock:
            self._sessions[info.session_id] = info
        return info

    def get(self, session_id: str) -> SessionInfo | None:
        """Look up a session. Any successful lookup counts as activity
        (sliding expiration) — every endpoint that validates a session_id
        via this method implicitly keeps it alive, not just /heartbeat."""
        with self._lock:
            self._purge_locked()
            session = self._sessions.get(session_id)
            if session is not None:
                session.last_activity_at = time.time()
            return session

    def touch(self, session_id: str) -> SessionInfo | None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            session.last_activity_at = time.time()
            return session

    def set_consent(self, session_id: str, given: bool) -> SessionInfo | None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            session.consent_given = given
            return session

    def set_privacy_mode(self, session_id: str, active: bool) -> SessionInfo | None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            session.privacy_mode_active = active
            return session

    def save_draft(self, form: IntakeForm) -> None:
        with self._lock:
            self._drafts[form.session_id] = form

    def get_draft(self, session_id: str) -> IntakeForm | None:
        with self._lock:
            return self._drafts.get(session_id)

    def end(self, session_id: str) -> None:
        """Explicit wipe — called on submit, "start over", or idle purge."""
        with self._lock:
            self._sessions.pop(session_id, None)
            self._drafts.pop(session_id, None)

    def purge_idle(self) -> list[str]:
        """Wipe sessions past idle/max-age limits. Returns purged session ids."""
        with self._lock:
            return self._purge_locked()

    def _purge_locked(self) -> list[str]:
        now = time.time()
        expired = [
            sid
            for sid, s in self._sessions.items()
            if (now - s.last_activity_at > self._idle_timeout)
            or (now - s.created_at > self._max_age)
        ]
        for sid in expired:
            self._sessions.pop(sid, None)
            self._drafts.pop(sid, None)
        return expired
