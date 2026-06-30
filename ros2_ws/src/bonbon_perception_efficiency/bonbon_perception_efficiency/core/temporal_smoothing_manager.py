"""TemporalSmoothingManager — a generic, label-agnostic temporal-stability
tracker for signals that don't already have one.

bonbon_gesture already has GestureTemporalSmoother (majority-vote + cooldown,
gesture-specific, well-tested). This is NOT a replacement — it's the same
"don't react to a one-frame flicker" principle, generalised to any labeled
signal keyed by an arbitrary id, for signals that currently have no
smoothing at all (e.g. is HumanState.emotional_state flapping frame to
frame? is text_intent stable across consecutive utterances?). Reuse this for
new signals rather than writing a fifth bespoke majority-vote window.
"""

from __future__ import annotations

from collections import Counter, defaultdict, deque
from dataclasses import dataclass


@dataclass
class StabilityResult:
    stable_label: str
    is_stable: bool
    agreement_fraction: float


class TemporalSmoothingManager:
    def __init__(self, window: int = 5, min_agreement: float = 0.6) -> None:
        self._window = window
        self._min_agreement = min_agreement
        self._buffers: dict[str, deque] = defaultdict(lambda: deque(maxlen=window))

    def update(self, key: str, label: str) -> StabilityResult:
        buf = self._buffers[key]
        buf.append(label)
        votes = Counter(buf)
        top_label, count = votes.most_common(1)[0]
        fraction = count / len(buf)
        return StabilityResult(
            stable_label=top_label,
            is_stable=fraction >= self._min_agreement,
            agreement_fraction=fraction,
        )

    def forget(self, key: str) -> None:
        self._buffers.pop(key, None)

    @property
    def tracked_key_count(self) -> int:
        return len(self._buffers)
