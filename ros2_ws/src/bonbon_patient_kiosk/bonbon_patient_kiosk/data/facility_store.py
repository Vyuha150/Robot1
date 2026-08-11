"""FacilityLabelStore — staff-placed room/doctor pins on the SLAM map.

Export-only for this pass (see plan decision): staff generate a
`named_locations` YAML block here and paste it into bonbon_navigation's
nav_params.yaml themselves, then relaunch. This store never calls back
into bonbon_navigation.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from bonbon_patient_kiosk.models.facility_models import NamedLocationLabel, NamedLocationLabelUpsert


class FacilityLabelStore:
    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._labels: dict[str, NamedLocationLabel] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            for item in raw:
                label = NamedLocationLabel(**item)
                self._labels[label.label_id] = label
        except Exception:
            # Corrupt/empty file — start clean rather than crashing startup.
            self._labels = {}

    def _save(self) -> None:
        data = [label.model_dump() for label in self._labels.values()]
        self._path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def list(self) -> list[NamedLocationLabel]:
        with self._lock:
            return list(self._labels.values())

    def upsert(self, req: NamedLocationLabelUpsert, label_id: str | None = None) -> NamedLocationLabel:
        with self._lock:
            if label_id and label_id in self._labels:
                label = self._labels[label_id]
                label.name = req.name
                label.display_label = req.display_label
                label.category = req.category
                label.map_x = req.map_x
                label.map_y = req.map_y
                label.map_yaw = req.map_yaw
                label.notes = req.notes
                label.updated_at = time.time()
            else:
                label = NamedLocationLabel(**req.model_dump())
                self._labels[label.label_id] = label
            label.validate_category()
            self._save()
            return label

    def delete(self, label_id: str) -> bool:
        with self._lock:
            existed = self._labels.pop(label_id, None) is not None
            if existed:
                self._save()
            return existed

    def export_yaml(self) -> str:
        """Render a `named_locations` block matching bonbon_navigation's
        nav_params.yaml format: "name:x_val,y_val,yaw_val"."""
        with self._lock:
            lines = ["named_locations:"]
            for label in sorted(self._labels.values(), key=lambda l: l.name):
                lines.append(
                    f'  - "{label.name}:{label.map_x},{label.map_y},{label.map_yaw}"'
                    f"  # {label.category}: {label.display_label}"
                )
            return "\n".join(lines) + "\n"
