"""MapMetadataRepository — CRUD for ``map_metadata`` and ``environment_zones``."""

from __future__ import annotations

from typing import Any

from bonbon_data_stores.schema.models import EnvironmentZone, MapMetadata
from bonbon_data_stores.sqlite.connection import SQLiteConnection
from bonbon_data_stores.sqlite.repositories.base import BaseRepository


class MapMetadataRepository(BaseRepository):

    def __init__(self, conn: SQLiteConnection) -> None:
        super().__init__(conn)

    # ------------------------------------------------------------------
    # Map CRUD
    # ------------------------------------------------------------------

    def save(self, meta: MapMetadata) -> str:
        sql = """
        INSERT INTO map_metadata (
            map_id, map_name, file_path, pgm_path, yaml_path,
            resolution_m, origin_x, origin_y, width_cells, height_cells,
            created_at, last_updated_at, is_active
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(map_id) DO UPDATE SET
            map_name        = excluded.map_name,
            file_path       = excluded.file_path,
            pgm_path        = excluded.pgm_path,
            yaml_path       = excluded.yaml_path,
            resolution_m    = excluded.resolution_m,
            origin_x        = excluded.origin_x,
            origin_y        = excluded.origin_y,
            width_cells     = excluded.width_cells,
            height_cells    = excluded.height_cells,
            last_updated_at = excluded.last_updated_at,
            is_active       = excluded.is_active;
        """
        self._execute(
            sql,
            (
                meta.map_id,
                meta.map_name,
                meta.file_path,
                meta.pgm_path,
                meta.yaml_path,
                meta.resolution_m,
                meta.origin_x,
                meta.origin_y,
                meta.width_cells,
                meta.height_cells,
                meta.created_at,
                meta.last_updated_at,
                int(meta.is_active),
            ),
        )
        for zone in meta.zones:
            self.save_zone(zone)
        return meta.map_id

    def get_by_id(self, map_id: str) -> MapMetadata | None:
        row = self._fetchone("SELECT * FROM map_metadata WHERE map_id = ?;", (map_id,))
        return self._row_to_model(row) if row else None

    def get_active(self) -> MapMetadata | None:
        row = self._fetchone("SELECT * FROM map_metadata WHERE is_active = 1 LIMIT 1;")
        return self._row_to_model(row) if row else None

    def set_active(self, map_id: str) -> None:
        self._execute("UPDATE map_metadata SET is_active = 0;")
        self._execute("UPDATE map_metadata SET is_active = 1 WHERE map_id = ?;", (map_id,))

    def list_all(self) -> list[MapMetadata]:
        rows = self._fetchall("SELECT * FROM map_metadata ORDER BY last_updated_at DESC;")
        return [self._row_to_model(r) for r in rows]

    def delete(self, map_id: str) -> bool:
        return self._execute("DELETE FROM map_metadata WHERE map_id = ?;", (map_id,)) > 0

    def count(self) -> int:
        return self._count("map_metadata")

    # ------------------------------------------------------------------
    # Zone CRUD
    # ------------------------------------------------------------------

    def save_zone(self, zone: EnvironmentZone) -> str:
        sql = """
        INSERT INTO environment_zones
            (zone_id, map_id, zone_name, zone_type, polygon_json, description)
        VALUES (?,?,?,?,?,?)
        ON CONFLICT(zone_id) DO UPDATE SET
            zone_name    = excluded.zone_name,
            zone_type    = excluded.zone_type,
            polygon_json = excluded.polygon_json,
            description  = excluded.description;
        """
        self._execute(
            sql,
            (
                zone.zone_id,
                zone.map_id,
                zone.zone_name,
                zone.zone_type,
                zone.polygon_json,
                zone.description,
            ),
        )
        return zone.zone_id

    def get_zones(self, map_id: str) -> list[EnvironmentZone]:
        rows = self._fetchall(
            "SELECT * FROM environment_zones WHERE map_id = ? ORDER BY zone_name;",
            (map_id,),
        )
        return [EnvironmentZone(**r) for r in rows]

    def delete_zone(self, zone_id: str) -> bool:
        return self._execute("DELETE FROM environment_zones WHERE zone_id = ?;", (zone_id,)) > 0

    # ------------------------------------------------------------------

    def _row_to_model(self, row: dict[str, Any]) -> MapMetadata:
        zones = self.get_zones(row["map_id"])
        return MapMetadata(
            map_id=row["map_id"],
            map_name=row["map_name"],
            file_path=row["file_path"],
            pgm_path=row["pgm_path"],
            yaml_path=row["yaml_path"],
            resolution_m=row["resolution_m"],
            origin_x=row["origin_x"],
            origin_y=row["origin_y"],
            width_cells=row["width_cells"],
            height_cells=row["height_cells"],
            created_at=row["created_at"],
            last_updated_at=row["last_updated_at"],
            is_active=bool(row["is_active"]),
            zones=zones,
        )
