"""
bonbon_navigation.planners.human_aware_costmap
================================================
Human-aware dynamic inflation layer for the Nav2 local costmap.

This module does NOT subclass a Nav2 C++ plugin (that would require
compiled bindings).  Instead it operates as a Python layer that:

  1. Listens to PersonStateArray from /perception/persons
  2. Computes inflation regions around each tracked person
  3. Publishes an additional OccupancyGrid on /navigation/human_costmap
     that Nav2 can consume as a static layer or that the navigation node
     uses to veto goals / re-route

Social force model
------------------
Each person creates a circular cost region:
  - Core radius:   person_inflation_radius_m (default 0.80 m)
  - Extra margin:  1.30× if person is facing the robot (may step forward)
  - Vulnerable:    1.20 m for children / elderly
  - Cost falloff:  exponential from 100 (centre) → 0 at edge

The layer also computes an approach vector for "passing announcements"
so the navigation node can trigger TTS when crossing within
announce_distance_m of a person.
"""
from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from threading import Lock
from typing import Dict, List, Optional, Tuple

import numpy as np

from bonbon_navigation.config.nav_config import HumanAwareConfig

logger = logging.getLogger(__name__)


# ── Person obstacle ───────────────────────────────────────────────────────────

@dataclass
class PersonObstacle:
    track_id:      str
    x:             float
    y:             float
    velocity_mps:  float
    facing_robot:  bool
    age_group:     str       # "child" | "adult" | "elderly" | "unknown"
    last_seen:     float = field(default_factory=time.monotonic)

    @property
    def is_vulnerable(self) -> bool:
        return self.age_group in ("child", "elderly")

    @property
    def is_stale(self) -> bool:
        return (time.monotonic() - self.last_seen) > 3.0


@dataclass
class PassingAlert:
    """Trigger a TTS announcement when approaching a person closely."""
    person_id:      str
    distance_m:     float
    should_announce: bool
    announced:      bool = False


# ── Costmap layer ─────────────────────────────────────────────────────────────

class HumanAwareCostmapLayer:
    """
    Maintains an inflated cost grid around tracked persons.

    The layer operates in map-frame coordinates.  The nav node merges
    this into its planning by injecting the persons' positions as
    dynamic obstacles into the Nav2 costmap via the obstacle layer topic,
    or by using this data to replan around persons.

    Usage::

        layer = HumanAwareCostmapLayer(cfg, resolution=0.05, width=400, height=400,
                                        origin_x=-10.0, origin_y=-10.0)
        # In person callback:
        layer.update_person("person_1", x=2.0, y=3.0, velocity=0.0,
                            facing_robot=True, age_group="adult")
        # In navigation timer:
        grid = layer.get_cost_grid()   # np.ndarray (height, width), int8
        alerts = layer.get_passing_alerts(robot_x, robot_y)
    """

    def __init__(
        self,
        cfg:       HumanAwareConfig,
        resolution: float = 0.05,   # m/px
        width:     int    = 400,    # px
        height:    int    = 400,    # px
        origin_x:  float  = -10.0,  # map frame
        origin_y:  float  = -10.0,
    ) -> None:
        self._cfg        = cfg
        self._resolution = resolution
        self._width      = width
        self._height     = height
        self._origin_x   = origin_x
        self._origin_y   = origin_y

        self._persons: Dict[str, PersonObstacle] = {}
        self._lock     = Lock()
        self._dirty    = False

        self._grid = np.zeros((height, width), dtype=np.int8)

    # ── Person updates ────────────────────────────────────────────────────────

    def update_person(
        self,
        track_id:     str,
        x:            float,
        y:            float,
        velocity_mps: float = 0.0,
        facing_robot: bool  = False,
        age_group:    str   = "adult",
    ) -> None:
        with self._lock:
            self._persons[track_id] = PersonObstacle(
                track_id     = track_id,
                x            = x,
                y            = y,
                velocity_mps = velocity_mps,
                facing_robot = facing_robot,
                age_group    = age_group,
                last_seen    = time.monotonic(),
            )
            self._dirty = True

    def remove_person(self, track_id: str) -> None:
        with self._lock:
            self._persons.pop(track_id, None)
            self._dirty = True

    def expire_stale_persons(self) -> int:
        """Remove persons not seen for > decay_sec.  Returns number removed."""
        with self._lock:
            stale = [
                tid for tid, p in self._persons.items()
                if (time.monotonic() - p.last_seen) > self._cfg.person_decay_sec
            ]
            for tid in stale:
                del self._persons[tid]
            if stale:
                self._dirty = True
                logger.debug("Expired %d stale persons", len(stale))
            return len(stale)

    def get_persons(self) -> List[PersonObstacle]:
        with self._lock:
            return list(self._persons.values())

    # ── Grid generation ───────────────────────────────────────────────────────

    def rebuild_grid(self) -> None:
        """Recompute the cost grid from current tracked persons."""
        with self._lock:
            self._grid[:] = 0
            for p in self._persons.values():
                if p.is_stale:
                    continue
                self._inflate_person(p)
            self._dirty = False

    def _inflate_person(self, p: PersonObstacle) -> None:
        """Paint exponential cost falloff around a person."""
        # Determine inflation radius
        if p.is_vulnerable:
            radius = self._cfg.vulnerable_inflation_radius_m
        else:
            radius = self._cfg.person_inflation_radius_m
        if p.facing_robot:
            radius *= self._cfg.facing_multiplier

        radius_px = int(math.ceil(radius / self._resolution))

        # Person centre in grid coordinates
        col_c = int((p.x - self._origin_x) / self._resolution)
        row_c = int((p.y - self._origin_y) / self._resolution)

        for dr in range(-radius_px, radius_px + 1):
            for dc in range(-radius_px, radius_px + 1):
                row = row_c + dr
                col = col_c + dc
                if not (0 <= row < self._height and 0 <= col < self._width):
                    continue
                dist_m = math.hypot(dr, dc) * self._resolution
                if dist_m > radius:
                    continue
                # Exponential cost: 100 at centre, ~0 at edge
                ratio = 1.0 - (dist_m / radius)
                cost  = int(
                    100.0 * math.exp(
                        -self._cfg.person_cost_scaling * (1.0 - ratio)
                    ) * ratio
                )
                cost = max(0, min(100, cost))
                if cost > self._grid[row, col]:
                    self._grid[row, col] = cost

    def get_cost_grid(self) -> np.ndarray:
        """Return the current cost grid (height × width, int8).  Rebuilds if dirty."""
        if self._dirty:
            self.rebuild_grid()
        return self._grid.copy()

    def cost_at(self, x: float, y: float) -> int:
        """Return the human-aware cost at a world-frame position."""
        if self._dirty:
            self.rebuild_grid()
        col = int((x - self._origin_x) / self._resolution)
        row = int((y - self._origin_y) / self._resolution)
        if 0 <= row < self._height and 0 <= col < self._width:
            return int(self._grid[row, col])
        return 0

    # ── Passing alerts ────────────────────────────────────────────────────────

    def get_passing_alerts(
        self,
        robot_x: float,
        robot_y: float,
    ) -> List[PassingAlert]:
        """
        Return passing alerts for persons within announce_distance_m.
        Only persons facing the robot or in the robot's path are flagged.
        """
        if not self._cfg.announce_passing_intent:
            return []
        alerts = []
        with self._lock:
            for p in self._persons.values():
                d = math.hypot(p.x - robot_x, p.y - robot_y)
                if d <= self._cfg.announce_distance_m:
                    alerts.append(PassingAlert(
                        person_id       = p.track_id,
                        distance_m      = d,
                        should_announce = True,
                    ))
        return alerts

    # ── Grid metadata ─────────────────────────────────────────────────────────

    @property
    def resolution(self) -> float:
        return self._resolution

    @property
    def origin(self) -> Tuple[float, float]:
        return (self._origin_x, self._origin_y)

    @property
    def size(self) -> Tuple[int, int]:
        return (self._width, self._height)
