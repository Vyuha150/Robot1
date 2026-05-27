from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SimulationEvent:
    time_sec: float
    type: str
    target: str
    params: dict[str, Any] = field(default_factory=dict)
