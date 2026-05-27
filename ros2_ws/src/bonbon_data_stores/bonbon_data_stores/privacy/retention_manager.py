"""RetentionPolicyManager — automatic purge of expired records.

Supported policies and their lifetimes
---------------------------------------
ephemeral               — purged on session close (0-day TTL)
session_only            — purged on session close
7_days                  — 7 days from record timestamp
30_days                 — 30 days from record timestamp
1_year                  — 365 days from record timestamp
permanent_until_deleted — never automatically purged
"""

from __future__ import annotations

import logging
import time

from bonbon_data_stores.schema.models import RetentionPolicy
from bonbon_data_stores.sqlite.repositories.interaction_repo import InteractionHistoryRepository
from bonbon_data_stores.sqlite.repositories.navigation_event_repo import NavigationEventRepository
from bonbon_data_stores.sqlite.repositories.robot_state_repo import RobotStateRepository
from bonbon_data_stores.sqlite.repositories.safety_event_repo import SafetyEventRepository

logger = logging.getLogger(__name__)

# Retention policy → lifetime in seconds (None = never expire automatically)
_POLICY_TTL_SEC: dict[str, int | None] = {
    RetentionPolicy.EPHEMERAL.value: 0,
    RetentionPolicy.SESSION_ONLY.value: 0,
    RetentionPolicy.SEVEN_DAYS.value: 7 * 86400,
    RetentionPolicy.THIRTY_DAYS.value: 30 * 86400,
    RetentionPolicy.ONE_YEAR.value: 365 * 86400,
    RetentionPolicy.PERMANENT_UNTIL_DELETED.value: None,
}


class RetentionPolicyManager:
    """Sweep expired records from all repositories.

    Parameters
    ----------
    interaction_repo, robot_state_repo, navigation_repo, safety_repo:
        Repository instances to sweep.
    custom_ttl_overrides:
        Optional dict to override default TTLs (seconds).
    """

    def __init__(
        self,
        interaction_repo: InteractionHistoryRepository,
        robot_state_repo: RobotStateRepository,
        navigation_repo: NavigationEventRepository,
        safety_repo: SafetyEventRepository,
        custom_ttl_overrides: dict[str, int] | None = None,
    ) -> None:
        self._repos = {
            "interactions": interaction_repo,
            "robot_states": robot_state_repo,
            "navigation_events": navigation_repo,
            "safety_events": safety_repo,
        }
        self._ttl: dict[str, int | None] = {**_POLICY_TTL_SEC}
        if custom_ttl_overrides:
            self._ttl.update(custom_ttl_overrides)

        self._last_sweep: float = 0.0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def sweep(self) -> dict[str, int]:
        """Delete all records whose retention period has elapsed.

        Returns a dict of ``table → deleted_row_count`` for logging.
        """
        now = time.time()
        totals: dict[str, int] = {}

        for policy, ttl_sec in self._ttl.items():
            if ttl_sec is None or ttl_sec == 0:
                # 0 = ephemeral/session_only — handled separately at session close
                # None = permanent
                continue

            cutoff_ts = now - ttl_sec

            for table, repo in self._repos.items():
                try:
                    deleted = repo.purge_by_retention(policy, cutoff_ts)
                    if deleted:
                        totals[table] = totals.get(table, 0) + deleted
                        logger.info(
                            "Retention sweep: removed %d %s rows (policy=%s, cutoff=%s)",
                            deleted,
                            table,
                            policy,
                            time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(cutoff_ts)),
                        )
                except AttributeError:
                    # Not all repos implement purge_by_retention; skip silently
                    pass
                except Exception as exc:
                    logger.error("Retention sweep error for %s/%s: %s", table, policy, exc)

        self._last_sweep = now
        return totals

    def purge_session_data(self, session_id: str) -> dict[str, int]:
        """Purge ephemeral / session_only data tied to *session_id*.

        Called when a session ends.
        """
        results: dict[str, int] = {}
        for policy in (RetentionPolicy.EPHEMERAL.value, RetentionPolicy.SESSION_ONLY.value):
            for table, repo in self._repos.items():
                try:
                    sql = f"DELETE FROM {table} WHERE session_id = ? " f"AND retention_policy = ?;"
                    cur = repo._conn.get().execute(sql, (session_id, policy))
                    repo._conn.get().commit()
                    n = cur.rowcount
                    if n:
                        results[table] = results.get(table, 0) + n
                except Exception as exc:
                    logger.error("Failed to purge session data from %s: %s", table, exc)
        return results

    @property
    def last_sweep_ts(self) -> float:
        return self._last_sweep

    def ttl_for_policy(self, policy: str) -> int | None:
        """Return configured TTL in seconds (None = never expires)."""
        return self._ttl.get(policy)
