"""Facility Map Editor models — staff-only, export-only for this pass.

Pins are stored locally by this package and exported as a `named_locations`
YAML block for bonbon_navigation's nav_params.yaml. This package never
calls back into bonbon_navigation to mutate its location registry.
"""

from __future__ import annotations

import time
import uuid

from pydantic import BaseModel, Field

_VALID_CATEGORIES = frozenset({"room", "doctor", "department", "amenity", "restricted"})


class NamedLocationLabel(BaseModel):
    label_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str = Field(min_length=1, max_length=64)  # becomes the named_location key
    display_label: str = Field(min_length=1, max_length=200)
    category: str = Field(default="room")
    map_x: float = 0.0
    map_y: float = 0.0
    map_yaw: float = 0.0
    notes: str = Field(default="", max_length=500)
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)

    def validate_category(self) -> None:
        if self.category not in _VALID_CATEGORIES:
            raise ValueError(f"category must be one of {sorted(_VALID_CATEGORIES)}")


class NamedLocationLabelUpsert(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    display_label: str = Field(min_length=1, max_length=200)
    category: str = Field(default="room")
    map_x: float = 0.0
    map_y: float = 0.0
    map_yaw: float = 0.0
    notes: str = Field(default="", max_length=500)


class FacilityMapExport(BaseModel):
    yaml_text: str
    label_count: int
    generated_at: float = Field(default_factory=time.time)
