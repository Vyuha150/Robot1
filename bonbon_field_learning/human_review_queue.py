"""Human review queue: a logged failure case sits PENDING until a person
labels the correct expected outcome, then becomes APPROVED (eligible for
regression-test generation + dataset export) or REJECTED (e.g. duplicate,
not actually a bug).
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path


class ReviewStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass
class ReviewItem:
    event_id: str
    status: ReviewStatus = ReviewStatus.PENDING
    reviewer: str | None = None
    corrected_expected_outcome: dict[str, str] = field(default_factory=dict)
    notes: str = ""
    reviewed_at: float | None = None

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> ReviewItem:
        return cls(
            event_id=str(data["event_id"]),
            status=ReviewStatus(data["status"]),
            reviewer=data.get("reviewer"),
            corrected_expected_outcome=dict(data.get("corrected_expected_outcome", {})),
            notes=str(data.get("notes", "")),
            reviewed_at=data.get("reviewed_at"),
        )


class HumanReviewQueue:
    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._items: dict[str, ReviewItem] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        with open(self._path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    item = ReviewItem.from_dict(json.loads(line))
                    self._items[item.event_id] = item

    def _save(self) -> None:
        with open(self._path, "w", encoding="utf-8") as f:
            for item in self._items.values():
                f.write(json.dumps(item.to_dict()) + "\n")

    def enqueue(self, event_id: str) -> ReviewItem:
        if event_id not in self._items:
            self._items[event_id] = ReviewItem(event_id=event_id)
            self._save()
        return self._items[event_id]

    def pending(self) -> list[ReviewItem]:
        return [i for i in self._items.values() if i.status == ReviewStatus.PENDING]

    def approved(self) -> list[ReviewItem]:
        return [i for i in self._items.values() if i.status == ReviewStatus.APPROVED]

    def submit_review(
        self,
        event_id: str,
        reviewer: str,
        approve: bool,
        corrected_expected_outcome: dict[str, str] | None = None,
        notes: str = "",
    ) -> ReviewItem:
        item = self._items.get(event_id) or self.enqueue(event_id)
        item.status = ReviewStatus.APPROVED if approve else ReviewStatus.REJECTED
        item.reviewer = reviewer
        item.corrected_expected_outcome = dict(corrected_expected_outcome or {})
        item.notes = notes
        item.reviewed_at = time.time()
        self._save()
        return item
