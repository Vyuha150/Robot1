"""Tracks dataset version bumps (new labeled examples merged in) so the
dashboard and model_evaluation_tracker can tie a model evaluation back to
exactly which dataset version produced it.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class DatasetVersionEntry:
    version: str
    reason: str
    new_examples_count: int
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> DatasetVersionEntry:
        return cls(
            version=str(data["version"]),
            reason=str(data["reason"]),
            new_examples_count=int(data["new_examples_count"]),
            timestamp=float(data["timestamp"]),
        )


class DatasetVersionManager:
    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def _history(self) -> list[DatasetVersionEntry]:
        if not self._path.exists():
            return []
        with open(self._path, encoding="utf-8") as f:
            data = json.load(f)
        return [DatasetVersionEntry.from_dict(d) for d in data.get("history", [])]

    def _write(self, history: list[DatasetVersionEntry]) -> None:
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump({"history": [h.to_dict() for h in history]}, f, indent=2)

    def current_version(self) -> str:
        history = self._history()
        return history[-1].version if history else "0.0.0"

    def bump(self, reason: str, new_examples_count: int) -> DatasetVersionEntry:
        history = self._history()
        major, minor, patch = (int(x) for x in self.current_version().split("."))
        # Field data is additive, not a breaking schema change -> minor bump.
        next_version = f"{major}.{minor + 1}.{patch}"
        entry = DatasetVersionEntry(
            version=next_version, reason=reason, new_examples_count=new_examples_count
        )
        history.append(entry)
        self._write(history)
        return entry

    def history(self) -> list[DatasetVersionEntry]:
        return self._history()
