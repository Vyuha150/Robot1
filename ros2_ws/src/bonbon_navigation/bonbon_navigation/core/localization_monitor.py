"""
bonbon_navigation.core.localization_monitor
============================================
Monitors localization quality from AMCL or RTAB-Map.

Responsibilities
----------------
* Track pose estimate confidence (covariance trace)
* Detect localization loss (too-high covariance or stale pose)
* Trigger global re-localization when confidence drops below threshold
* Provide the latest robot pose to other navigation components
* Report localization health for the /health/navigation topic
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from enum import StrEnum

logger = logging.getLogger(__name__)


# ── Localization quality ──────────────────────────────────────────────────────


class LocalizationQuality(StrEnum):
    UNKNOWN = "UNKNOWN"  # no pose received yet
    GOOD = "GOOD"  # covariance within limits
    DEGRADED = "DEGRADED"  # covariance elevated, but usable
    LOST = "LOST"  # covariance too high or pose stale


@dataclass
class PoseEstimate:
    """The robot's estimated pose in the map frame."""

    x: float = 0.0
    y: float = 0.0
    yaw: float = 0.0  # radians

    # Covariance diagonal elements (xx, yy, yawyaw)
    cov_xx: float = 1.0
    cov_yy: float = 1.0
    cov_yawyaw: float = 1.0

    timestamp: float = 0.0  # time.monotonic()

    @property
    def covariance_trace(self) -> float:
        return self.cov_xx + self.cov_yy + self.cov_yawyaw

    def distance_to(self, x: float, y: float) -> float:
        return math.hypot(self.x - x, self.y - y)


@dataclass
class LocalizationReport:
    """Localization health snapshot for the node to consume."""

    quality: LocalizationQuality
    pose: PoseEstimate | None
    covariance_trace: float
    pose_age_sec: float
    quality_history: list[LocalizationQuality] = field(default_factory=list)
    message: str = ""


# ── Monitor ───────────────────────────────────────────────────────────────────


class LocalizationMonitor:
    """
    Tracks localization quality from incoming pose messages.

    Usage::

        monitor = LocalizationMonitor(
            good_cov_threshold=0.10,
            lost_cov_threshold=1.00,
            pose_stale_sec=2.0,
        )
        monitor.update_pose(x, y, yaw, cov_xx, cov_yy, cov_yawyaw)
        report = monitor.get_report()
    """

    def __init__(
        self,
        good_cov_threshold: float = 0.10,
        lost_cov_threshold: float = 1.00,
        pose_stale_sec: float = 2.0,
        history_len: int = 20,
    ) -> None:
        self._good_thresh = good_cov_threshold
        self._lost_thresh = lost_cov_threshold
        self._stale_sec = pose_stale_sec
        self._history_len = history_len

        self._pose = PoseEstimate()
        self._quality = LocalizationQuality.UNKNOWN
        self._history: list[LocalizationQuality] = []
        self._reloc_count = 0
        self._loss_events = 0
        self._pose_received = False  # True only after update_pose() with covariance
        self._simple_pose_received = False  # True after update_pose_simple()

    # ── Pose ingestion ────────────────────────────────────────────────────────

    def update_pose(
        self,
        x: float,
        y: float,
        yaw: float,
        cov_xx: float = 0.01,
        cov_yy: float = 0.01,
        cov_yawyaw: float = 0.01,
    ) -> None:
        """
        Called when a new PoseWithCovarianceStamped arrives
        (from /amcl_pose or /rtabmap/localization_pose).
        """
        self._pose = PoseEstimate(
            x=x,
            y=y,
            yaw=yaw,
            cov_xx=cov_xx,
            cov_yy=cov_yy,
            cov_yawyaw=cov_yawyaw,
            timestamp=time.monotonic(),
        )
        self._pose_received = True
        self._update_quality()

    def update_pose_simple(self, x: float, y: float, yaw: float) -> None:
        """Update pose without covariance (e.g. from a TF lookup).
        Quality is not evaluated — only the position is stored."""
        self._pose = PoseEstimate(
            x=x,
            y=y,
            yaw=yaw,
            cov_xx=0.05,
            cov_yy=0.05,
            cov_yawyaw=0.05,
            timestamp=time.monotonic(),
        )
        self._simple_pose_received = True
        # Do NOT call _update_quality() — quality remains UNKNOWN until update_pose() called

    # ── Quality assessment ────────────────────────────────────────────────────

    def _update_quality(self) -> None:
        age = time.monotonic() - self._pose.timestamp
        trace = self._pose.covariance_trace

        if age > self._stale_sec or trace > self._lost_thresh:
            q = LocalizationQuality.LOST
        elif trace > self._good_thresh:
            q = LocalizationQuality.DEGRADED
        else:
            q = LocalizationQuality.GOOD

        if q == LocalizationQuality.LOST and self._quality != LocalizationQuality.LOST:
            self._loss_events += 1
            logger.warning("Localization LOST  trace=%.3f  age=%.1fs", trace, age)

        self._quality = q
        self._history.append(q)
        if len(self._history) > self._history_len:
            self._history.pop(0)

    # ── Public API ─────────────────────────────────────────────────────────────

    def get_pose(self) -> PoseEstimate | None:
        """Return last pose, or None if no pose has been received yet."""
        if not (self._pose_received or self._simple_pose_received):
            return None
        return self._pose

    def get_quality(self) -> LocalizationQuality:
        if not self._pose_received:
            return LocalizationQuality.UNKNOWN  # no covariance pose received
        self._update_quality()  # refresh staleness check
        return self._quality

    def is_localized(self) -> bool:
        q = self.get_quality()
        return q in (LocalizationQuality.GOOD, LocalizationQuality.DEGRADED)

    def get_report(self) -> LocalizationReport:
        q = self.get_quality()
        pose = self.get_pose()
        age = (time.monotonic() - self._pose.timestamp) if pose else 0.0
        cov = self._pose.covariance_trace if pose else 0.0
        msg = {
            LocalizationQuality.GOOD: "Localization good",
            LocalizationQuality.DEGRADED: "Localization degraded — high covariance",
            LocalizationQuality.LOST: "Localization LOST — pose unreliable",
            LocalizationQuality.UNKNOWN: "No pose received yet",
        }[q]
        return LocalizationReport(
            quality=q,
            pose=pose,
            covariance_trace=cov,
            pose_age_sec=age,
            quality_history=list(self._history),
            message=msg,
        )

    def record_relocalization(self) -> None:
        """Call when a global relocalization is triggered."""
        self._reloc_count += 1
        logger.info("Global relocalization triggered (count=%d)", self._reloc_count)

    @property
    def relocalization_count(self) -> int:
        return self._reloc_count

    @property
    def loss_event_count(self) -> int:
        return self._loss_events

    def consecutive_lost_count(self) -> int:
        """Number of consecutive LOST samples at the end of history."""
        count = 0
        for q in reversed(self._history):
            if q == LocalizationQuality.LOST:
                count += 1
            else:
                break
        return count
