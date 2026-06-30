"""Exports human-approved review items + their anonymized event into a
labeled-examples JSONL file consumable by model training/fine-tuning and
by `regression_test_generator.py`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from bonbon_field_learning.anonymized_event_store import AnonymizedEvent, AnonymizedEventStore
from bonbon_field_learning.human_review_queue import HumanReviewQueue, ReviewItem


@dataclass(frozen=True)
class LabeledExample:
    event: AnonymizedEvent
    review: ReviewItem

    def to_dict(self) -> dict[str, object]:
        return {"event": self.event.to_dict(), "review": self.review.to_dict()}


class AnnotationExporter:
    def __init__(self, store: AnonymizedEventStore, queue: HumanReviewQueue) -> None:
        self._store = store
        self._queue = queue

    def approved_examples(self) -> list[LabeledExample]:
        events_by_id = {e.event_id: e for e in self._store.all_events()}
        examples = []
        for item in self._queue.approved():
            event = events_by_id.get(item.event_id)
            if event is not None:
                examples.append(LabeledExample(event=event, review=item))
        return examples

    def export(self, out_path: Path | str) -> int:
        """Writes approved_examples() to `out_path` as JSONL. Returns the
        count written."""
        examples = self.approved_examples()
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            for ex in examples:
                f.write(json.dumps(ex.to_dict()) + "\n")
        return len(examples)
