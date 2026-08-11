"""Retention/purge job — deletes intake records past the configured window.

Runs as a periodic asyncio task from main.py's lifespan, mirroring the
event/status broadcaster tasks in bonbon_operator_api.
"""

from __future__ import annotations

import logging

from bonbon_patient_kiosk.data.store import PatientDataStore

logger = logging.getLogger(__name__)


def run_purge(store: PatientDataStore, retention_days: int) -> int:
    """Delete intake records older than *retention_days*. Returns count purged.
    Never raises — a retention job failing must not take down the API."""
    try:
        purged = store.purge_expired_intake(retention_days)
        if purged:
            logger.info("Retention purge: removed %d intake record(s)", purged)
        return purged
    except Exception as exc:
        logger.error("Retention purge failed: %s", exc)
        return 0
