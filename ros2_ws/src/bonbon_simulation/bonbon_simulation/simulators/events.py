from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class SimulationEvent:
    time_sec: float
    type: str
    target: str
    params: Dict[str, Any] = field(default_factory=dict)
