"""
bonbon_navigation.core.map_manager
====================================
Map loading, saving, and lifecycle management.

Responsibilities
----------------
* Load a pre-built map from a .yaml / .pgm file pair (static SLAM output)
* Publish /map (nav_msgs/OccupancyGrid) for Nav2 and RTAB-Map localization
* Save map snapshots on demand (useful during live SLAM)
* Maintain a location registry: named places → map-frame poses
* Monitor map age and trigger re-localization if map is stale

The map_manager is consumed by the NavigationNode; it does NOT spin its own
thread — it is driven by the node's lifecycle transitions.
"""

from __future__ import annotations

import logging
import math
import os
import time
from dataclasses import dataclass

import numpy as np
import yaml

logger = logging.getLogger(__name__)


# ── Data types ────────────────────────────────────────────────────────────────


@dataclass
class MapInfo:
    """Metadata from a .yaml map descriptor."""

    image_path: str
    resolution: float  # metres per pixel
    origin_x: float  # map origin in world frame (m)
    origin_y: float
    origin_yaw: float  # yaw of map origin (rad)
    negate: int  # 0=white is free, 1=black is free
    occupied_thresh: float  # 0.65
    free_thresh: float  # 0.196
    width: int = 0
    height: int = 0


@dataclass
class NamedPose:
    """A named location in the map frame."""

    name: str
    x: float
    y: float
    yaw: float  # radians
    frame: str = "map"


# ── Map manager ───────────────────────────────────────────────────────────────


class MapManager:
    """
    Loads and serves the occupancy grid map.

    Usage::

        mgr = MapManager(cfg)
        mgr.load("/share/bonbon_navigation/maps/cafe_map.yaml")
        grid = mgr.get_occupancy_grid()   # nav_msgs/OccupancyGrid equivalent dict
        pose = mgr.resolve_location("table_3")
    """

    def __init__(self, named_locations: dict[str, tuple[float, float, float]]) -> None:
        """
        Parameters
        ----------
        named_locations:
            Dict mapping name → (x, y, yaw_deg) in map frame.
        """
        self._named: dict[str, NamedPose] = {}
        for name, (x, y, yaw_deg) in named_locations.items():
            self._named[name] = NamedPose(name=name, x=x, y=y, yaw=math.radians(yaw_deg))

        self._info: MapInfo | None = None
        self._data: np.ndarray | None = None  # row-major, 0=free, 100=occ, -1=unk
        self._loaded: bool = False
        self._load_time: float = 0.0

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def load(self, yaml_path: str) -> bool:
        """
        Load a map from a ROS2 map_saver .yaml descriptor.

        Returns True on success, False on failure (logs the error).
        """
        if not yaml_path or not os.path.isfile(yaml_path):
            logger.warning("Map file not found: %r — operating without static map", yaml_path)
            return False
        try:
            with open(yaml_path) as f:
                meta = yaml.safe_load(f)

            image_file = meta.get("image", "")
            if not os.path.isabs(image_file):
                image_file = os.path.join(os.path.dirname(yaml_path), image_file)

            origin = meta.get("origin", [0.0, 0.0, 0.0])

            self._info = MapInfo(
                image_path=image_file,
                resolution=float(meta.get("resolution", 0.05)),
                origin_x=float(origin[0]),
                origin_y=float(origin[1]),
                origin_yaw=float(origin[2]) if len(origin) > 2 else 0.0,
                negate=int(meta.get("negate", 0)),
                occupied_thresh=float(meta.get("occupied_thresh", 0.65)),
                free_thresh=float(meta.get("free_thresh", 0.196)),
            )

            # Load PGM image
            if os.path.isfile(image_file):
                self._data, self._info.width, self._info.height = self._load_pgm(
                    image_file, self._info
                )
            else:
                logger.warning("Map image not found: %r", image_file)
                # Create empty map
                self._data = np.full((100, 100), -1, dtype=np.int8)
                self._info.width = 100
                self._info.height = 100

            self._loaded = True
            self._load_time = time.monotonic()
            logger.info(
                "Map loaded: %s  resolution=%.3f m/px  size=%dx%d",
                yaml_path,
                self._info.resolution,
                self._info.width,
                self._info.height,
            )
            return True

        except Exception as exc:
            logger.error("Failed to load map from %r: %s", yaml_path, exc)
            return False

    def is_loaded(self) -> bool:
        return self._loaded

    # ── Grid access ───────────────────────────────────────────────────────────

    def get_map_info(self) -> MapInfo | None:
        return self._info

    def get_grid_data(self) -> np.ndarray | None:
        """Return occupancy grid as flat int8 array (row-major, Nav2 convention)."""
        if self._data is None:
            return None
        return self._data.flatten().astype(np.int8)

    def world_to_cell(self, x: float, y: float) -> tuple[int, int]:
        """Convert world (map frame) coordinates to grid cell (col, row)."""
        if self._info is None:
            return (0, 0)
        col = int((x - self._info.origin_x) / self._info.resolution)
        row = int((y - self._info.origin_y) / self._info.resolution)
        return (col, row)

    def cell_to_world(self, col: int, row: int) -> tuple[float, float]:
        """Convert grid cell to world coordinates (centre of cell)."""
        if self._info is None:
            return (0.0, 0.0)
        x = self._info.origin_x + (col + 0.5) * self._info.resolution
        y = self._info.origin_y + (row + 0.5) * self._info.resolution
        return (x, y)

    def is_occupied(self, x: float, y: float, threshold: int = 50) -> bool:
        """Return True if the world-frame cell is occupied."""
        if self._data is None:
            return False
        col, row = self.world_to_cell(x, y)
        h, w = self._data.shape
        if 0 <= row < h and 0 <= col < w:
            return int(self._data[row, col]) >= threshold
        return False  # out of bounds → unknown → not occupied

    # ── Location registry ─────────────────────────────────────────────────────

    def add_location(self, name: str, x: float, y: float, yaw_deg: float) -> None:
        """Register or update a named location."""
        self._named[name] = NamedPose(name=name, x=x, y=y, yaw=math.radians(yaw_deg))
        logger.debug("Named location added: %s → (%.2f, %.2f, %.1f°)", name, x, y, yaw_deg)

    def resolve_location(self, name: str) -> NamedPose | None:
        """Return the NamedPose for a named location, or None if unknown."""
        return self._named.get(name)

    def list_locations(self) -> list[str]:
        return list(self._named.keys())

    def list_chargers(self) -> list[str]:
        return [n for n in self._named if n.startswith("charger")]

    def nearest_charger(
        self,
        current_x: float,
        current_y: float,
    ) -> NamedPose | None:
        """Return the nearest charger by Euclidean distance."""
        chargers = [self._named[n] for n in self.list_chargers()]
        if not chargers:
            return None
        return min(
            chargers,
            key=lambda p: math.hypot(p.x - current_x, p.y - current_y),
        )

    # ── PGM loader ────────────────────────────────────────────────────────────

    @staticmethod
    def _load_pgm(
        path: str,
        info: MapInfo,
    ) -> tuple[np.ndarray, int, int]:
        """
        Load a PGM file and convert to Nav2 occupancy values.

        Returns (grid_array, width, height) where grid_array is int8,
        shape (height, width), values:  0=free, 100=occupied, -1=unknown.
        """
        with open(path, "rb") as f:
            magic = f.readline().strip()
            if magic not in (b"P5", b"P2"):
                raise ValueError(f"Not a valid PGM file: magic={magic!r}")

            # Skip comments
            while True:
                line = f.readline()
                if not line.startswith(b"#"):
                    break
            dims = line.split()
            while len(dims) < 2:
                dims += f.readline().split()
            width, height = int(dims[0]), int(dims[1])

            maxval_line = f.readline().strip()
            maxval = int(maxval_line)

            if magic == b"P5":
                raw = np.frombuffer(f.read(), dtype=np.uint8).reshape(height, width)
            else:  # P2 ASCII
                data = []
                for line in f:
                    data.extend(int(v) for v in line.split())
                raw = np.array(data, dtype=np.uint8).reshape(height, width)

        # Convert PGM grey values to occupancy
        # Standard: white (255) = free, black (0) = occupied, mid = unknown
        if info.negate:
            raw = maxval - raw

        # Free
        free_thresh_val = int(info.free_thresh * maxval)
        occ_thresh_val = int(info.occupied_thresh * maxval)

        grid = np.full((height, width), -1, dtype=np.int8)  # unknown
        grid[raw > occ_thresh_val] = 0  # free
        grid[raw < free_thresh_val] = 100  # occupied

        # Flip vertically: PGM row 0 is top; Nav2 row 0 is bottom
        grid = np.flipud(grid)

        return grid, width, height
