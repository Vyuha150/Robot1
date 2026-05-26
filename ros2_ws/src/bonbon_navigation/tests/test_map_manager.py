"""
Tests for bonbon_navigation.core.map_manager
"""
import math
import os
import tempfile
from pathlib import Path

import pytest

from bonbon_navigation.core.map_manager import MapInfo, MapManager, NamedPose


# ── Helpers ───────────────────────────────────────────────────────────────────

def _write_pgm_p5(path: str, width: int, height: int, maxval: int = 255) -> None:
    """Write a minimal P5 (binary) PGM file — all free space (255)."""
    with open(path, "wb") as f:
        header = f"P5\n{width} {height}\n{maxval}\n".encode()
        f.write(header)
        f.write(bytes([255] * (width * height)))


def _write_pgm_with_obstacle(path: str, width: int = 20, height: int = 20,
                              obstacle_col: int = 10, obstacle_row: int = 10) -> None:
    """P5 PGM with one occupied pixel (value=0 → occupied after negate)."""
    data = [255] * (width * height)
    data[obstacle_row * width + obstacle_col] = 0
    with open(path, "wb") as f:
        f.write(f"P5\n{width} {height}\n255\n".encode())
        f.write(bytes(data))


def _write_yaml(yaml_path: str, pgm_path: str,
                resolution: float = 0.05,
                origin: tuple = (0.0, 0.0, 0.0)) -> None:
    ox, oy, oyaw = origin
    content = (
        f"image: {pgm_path}\n"
        f"resolution: {resolution}\n"
        f"origin: [{ox}, {oy}, {oyaw}]\n"
        "negate: 0\n"
        "occupied_thresh: 0.65\n"
        "free_thresh: 0.25\n"
    )
    with open(yaml_path, "w") as f:
        f.write(content)


# ── MapManager constructor ────────────────────────────────────────────────────

class TestMapManagerConstruct:
    def test_empty_locations(self):
        mm = MapManager({})
        assert mm.list_locations() == []

    def test_pre_populated_locations(self):
        mm = MapManager({"entrance": (0.0, 0.0, 0.0), "counter": (3.5, 1.0, 0.0)})
        assert "entrance" in mm.list_locations()
        assert "counter" in mm.list_locations()

    def test_pre_populated_yaw_converted_to_radians(self):
        mm = MapManager({"loc": (1.0, 2.0, 90.0)})  # 90 degrees
        pose = mm.resolve_location("loc")
        assert pose.yaw == pytest.approx(math.pi / 2, abs=1e-6)


# ── MapManager load ───────────────────────────────────────────────────────────

class TestMapLoad:
    def test_load_valid_map(self, tmp_path):
        pgm = str(tmp_path / "test.pgm")
        yaml = str(tmp_path / "test.yaml")
        _write_pgm_p5(pgm, width=40, height=40)
        _write_yaml(yaml, pgm, resolution=0.05, origin=(-1.0, -1.0, 0.0))

        mm = MapManager({})
        result = mm.load(yaml)
        assert result is True
        info = mm.get_map_info()
        assert info is not None
        assert info.width == 40
        assert info.height == 40
        assert info.resolution == pytest.approx(0.05)

    def test_load_sets_origin(self, tmp_path):
        pgm = str(tmp_path / "test.pgm")
        yaml = str(tmp_path / "test.yaml")
        _write_pgm_p5(pgm, 10, 10)
        _write_yaml(yaml, pgm, origin=(-0.5, -0.5, 0.0))

        mm = MapManager({})
        mm.load(yaml)
        info = mm.get_map_info()
        assert info.origin_x == pytest.approx(-0.5)
        assert info.origin_y == pytest.approx(-0.5)

    def test_load_nonexistent_returns_false(self):
        mm = MapManager({})
        result = mm.load("/nonexistent/path/map.yaml")
        assert result is False


# ── Coordinate transforms ─────────────────────────────────────────────────────

class TestCoordinateTransforms:
    def _load_map(self, tmp_path, origin=(0.0, 0.0)):
        pgm = str(tmp_path / "t.pgm")
        yaml = str(tmp_path / "t.yaml")
        _write_pgm_p5(pgm, 40, 40)
        _write_yaml(yaml, pgm, resolution=0.05, origin=(origin[0], origin[1], 0.0))
        mm = MapManager({})
        mm.load(yaml)
        return mm

    def test_world_to_cell_at_origin(self, tmp_path):
        mm = self._load_map(tmp_path, origin=(0.0, 0.0))
        col, row = mm.world_to_cell(0.0, 0.0)
        assert col == 0
        assert row == 0

    def test_world_to_cell_with_offset(self, tmp_path):
        mm = self._load_map(tmp_path, origin=(-1.0, -1.0))
        # (0.0, 0.0) world → (0.0-(-1.0))/0.05 = 20 cells from origin
        col, row = mm.world_to_cell(0.0, 0.0)
        assert col == 20
        assert row == 20

    def test_cell_to_world_roundtrip(self, tmp_path):
        mm = self._load_map(tmp_path, origin=(-1.0, -1.0))
        x, y = mm.cell_to_world(10, 15)
        col, row = mm.world_to_cell(x, y)
        assert col == 10
        assert row == 15


# ── Occupancy ─────────────────────────────────────────────────────────────────

class TestOccupancy:
    def test_free_cell_not_occupied(self, tmp_path):
        pgm = str(tmp_path / "t.pgm")
        yaml = str(tmp_path / "t.yaml")
        _write_pgm_p5(pgm, 20, 20, maxval=255)
        _write_yaml(yaml, pgm, resolution=0.05, origin=(0.0, 0.0, 0.0))
        mm = MapManager({})
        mm.load(yaml)
        assert mm.is_occupied(0.25, 0.25) is False

    def test_out_of_bounds_not_occupied(self, tmp_path):
        pgm = str(tmp_path / "t.pgm")
        yaml = str(tmp_path / "t.yaml")
        _write_pgm_p5(pgm, 10, 10)
        _write_yaml(yaml, pgm, resolution=0.05, origin=(0.0, 0.0, 0.0))
        mm = MapManager({})
        mm.load(yaml)
        assert mm.is_occupied(999.0, 999.0) is False

    def test_no_map_loaded_not_occupied(self):
        mm = MapManager({})
        assert mm.is_occupied(0.0, 0.0) is False


# ── Named locations ───────────────────────────────────────────────────────────

class TestNamedLocations:
    def test_add_and_resolve_location(self):
        mm = MapManager({})
        mm.add_location("counter", 3.5, 1.0, 0.0)   # yaw_deg=0
        pose = mm.resolve_location("counter")
        assert pose is not None
        assert pose.x == pytest.approx(3.5)
        assert pose.y == pytest.approx(1.0)

    def test_yaw_stored_in_radians(self):
        mm = MapManager({})
        mm.add_location("table_1", 5.0, 2.0, 180.0)   # yaw_deg=180 → π rad
        pose = mm.resolve_location("table_1")
        assert pose.yaw == pytest.approx(math.pi, abs=1e-6)

    def test_resolve_nonexistent_returns_none(self):
        mm = MapManager({})
        assert mm.resolve_location("does_not_exist") is None

    def test_multiple_locations(self):
        mm = MapManager({})
        for i in range(5):
            mm.add_location(f"table_{i}", float(i), 0.0, 0.0)
        for i in range(5):
            assert mm.resolve_location(f"table_{i}") is not None

    def test_list_locations(self):
        mm = MapManager({"a": (0, 0, 0), "b": (1, 1, 0)})
        locs = mm.list_locations()
        assert "a" in locs
        assert "b" in locs


# ── Charger registry ──────────────────────────────────────────────────────────

class TestChargerRegistry:
    def test_list_chargers_by_prefix(self):
        """list_chargers() returns all locations whose name starts with 'charger'."""
        mm = MapManager({})
        mm.add_location("charger_a", 1.0, 1.0, 0.0)
        mm.add_location("charger_b", 1.0, 8.0, 0.0)
        mm.add_location("table_1",   5.0, 2.0, 0.0)
        chargers = mm.list_chargers()
        assert "charger_a" in chargers
        assert "charger_b" in chargers
        assert "table_1" not in chargers

    def test_nearest_charger_returns_closest(self):
        mm = MapManager({})
        mm.add_location("charger_a", 1.0, 1.0, 0.0)
        mm.add_location("charger_b", 1.0, 8.0, 0.0)
        # Robot at (1.0, 2.0) → charger_a is 1.0 m away, charger_b is 6.0 m
        pose = mm.nearest_charger(current_x=1.0, current_y=2.0)
        assert pose is not None
        assert pose.name == "charger_a"
        assert math.hypot(pose.x - 1.0, pose.y - 2.0) == pytest.approx(1.0)

    def test_nearest_charger_no_chargers_returns_none(self):
        mm = MapManager({})
        result = mm.nearest_charger(current_x=0.0, current_y=0.0)
        assert result is None
