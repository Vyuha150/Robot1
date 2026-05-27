"""
bonbon_navigation.core.battery_router
=======================================
Low-battery charger routing for the BonBon navigation module.

Responsibilities
----------------
* Monitor battery state from /bonbon/battery/state (sensor_msgs/BatteryState)
* Classify battery level: OK / LOW / CRITICAL
* Select the nearest available charger when routing is triggered
* Emit a CHARGER navigation goal to the GoalManager
* Prevent resumption of non-charging tasks until battery is adequate
* Log all routing decisions for audit

The router does NOT issue Nav2 commands directly — it enqueues a goal
with goal_type=TYPE_CHARGER and priority=PRIORITY_URGENT.
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass
from enum import StrEnum

from bonbon_navigation.config.nav_config import BatteryRoutingConfig
from bonbon_navigation.core.map_manager import MapManager, NamedPose

logger = logging.getLogger(__name__)


# ── Battery level classification ─────────────────────────────────────────────


class BatteryLevel(StrEnum):
    OK = "OK"  # above low threshold — normal operation
    LOW = "LOW"  # below low_pct — start planning dock route
    CRITICAL = "CRITICAL"  # below critical_pct — abort task, dock now
    CHARGING = "CHARGING"  # on charger, charging


# ── State ─────────────────────────────────────────────────────────────────────


@dataclass
class BatteryState:
    percentage: float = 100.0  # 0–100 %
    voltage_v: float = 0.0
    current_a: float = 0.0
    is_charging: bool = False
    timestamp: float = 0.0


@dataclass
class RoutingDecision:
    should_dock: bool
    level: BatteryLevel
    charger: NamedPose | None
    reason: str
    urgency: str  # "normal" | "urgent"


# ── Router ────────────────────────────────────────────────────────────────────


class BatteryRouter:
    """
    Evaluates battery state and recommends charger routing.

    Usage::

        router = BatteryRouter(cfg, map_manager)
        router.update_battery(percentage=15.0, voltage=22.5,
                              current=-2.0, is_charging=False)
        decision = router.evaluate(current_x=2.0, current_y=3.0)
        if decision.should_dock:
            gm.enqueue(decision.charger.x, decision.charger.y, ...)
    """

    def __init__(
        self,
        cfg: BatteryRoutingConfig,
        map_manager: MapManager,
    ) -> None:
        self._cfg = cfg
        self._map = map_manager
        self._bat = BatteryState()
        self._routing_active = False
        self._last_routed_at: float | None = None
        self._dock_goal_id: str | None = None

    # ── Battery ingestion ──────────────────────────────────────────────────────

    def update_battery(
        self,
        percentage: float,
        voltage_v: float = 0.0,
        current_a: float = 0.0,
        is_charging: bool = False,
    ) -> None:
        self._bat = BatteryState(
            percentage=max(0.0, min(100.0, percentage)),
            voltage_v=voltage_v,
            current_a=current_a,
            is_charging=is_charging,
            timestamp=time.monotonic(),
        )

        if is_charging and percentage >= self._cfg.resume_threshold_pct:
            if self._routing_active:
                logger.info(
                    "Battery %.0f%% ≥ %.0f%% — resuming normal tasks",
                    percentage,
                    self._cfg.resume_threshold_pct,
                )
            self._routing_active = False

    # ── Classification ────────────────────────────────────────────────────────

    def classify(self) -> BatteryLevel:
        if self._bat.is_charging:
            return BatteryLevel.CHARGING
        if self._bat.percentage <= self._cfg.critical_battery_pct:
            return BatteryLevel.CRITICAL
        if self._bat.percentage <= self._cfg.low_battery_pct:
            return BatteryLevel.LOW
        return BatteryLevel.OK

    # ── Routing decision ──────────────────────────────────────────────────────

    def evaluate(
        self,
        current_x: float,
        current_y: float,
    ) -> RoutingDecision:
        """
        Decide whether the robot should navigate to a charger.

        Returns a RoutingDecision with should_dock=True when action needed.
        """
        if not self._cfg.enabled:
            return RoutingDecision(
                should_dock=False,
                level=self.classify(),
                charger=None,
                reason="battery routing disabled",
                urgency="normal",
            )

        level = self.classify()

        if level == BatteryLevel.OK or level == BatteryLevel.CHARGING:
            return RoutingDecision(
                should_dock=False,
                level=level,
                charger=None,
                reason="battery adequate",
                urgency="normal",
            )

        # Find nearest charger
        charger = self._map.nearest_charger(current_x, current_y)
        if charger is None:
            logger.error("Low battery but no chargers registered in map!")
            return RoutingDecision(
                should_dock=False,
                level=level,
                charger=None,
                reason="no charger registered",
                urgency="normal",
            )

        dist = math.hypot(charger.x - current_x, charger.y - current_y)

        if level == BatteryLevel.CRITICAL:
            self._routing_active = True
            reason = (
                f"CRITICAL battery {self._bat.percentage:.0f}% "
                f"≤ {self._cfg.critical_battery_pct:.0f}%"
            )
            urgency = "urgent"
            logger.warning("%s → routing to %s (%.1fm away)", reason, charger.name, dist)
        else:  # LOW
            if not self._routing_active:
                self._routing_active = True
                reason = (
                    f"low battery {self._bat.percentage:.0f}% "
                    f"≤ {self._cfg.low_battery_pct:.0f}%"
                )
                urgency = "normal"
                logger.info("%s → routing to %s (%.1fm away)", reason, charger.name, dist)
            else:
                reason = "ongoing low-battery routing"
                urgency = "normal"

        self._last_routed_at = time.monotonic()

        return RoutingDecision(
            should_dock=True,
            level=level,
            charger=charger,
            reason=reason,
            urgency=urgency,
        )

    # ── Accessors ─────────────────────────────────────────────────────────────

    @property
    def percentage(self) -> float:
        return self._bat.percentage

    @property
    def is_charging(self) -> bool:
        return self._bat.is_charging

    @property
    def routing_active(self) -> bool:
        return self._routing_active

    def get_state(self) -> BatteryState:
        return self._bat
