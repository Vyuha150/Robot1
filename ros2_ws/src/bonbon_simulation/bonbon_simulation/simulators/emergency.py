from __future__ import annotations


class EmergencyEventInjector:
    def __init__(self, reaction_ms: float = 120.0) -> None:
        self.reaction_ms = float(reaction_ms)
        self.triggered_at_sec: float | None = None
        self.stopped_at_sec: float | None = None

    def trigger(self, now_sec: float) -> None:
        self.triggered_at_sec = now_sec
        self.stopped_at_sec = now_sec + self.reaction_ms / 1000.0

    @property
    def active(self) -> bool:
        return self.triggered_at_sec is not None

    @property
    def reaction_time_ms(self) -> float | None:
        if self.triggered_at_sec is None or self.stopped_at_sec is None:
            return None
        return (self.stopped_at_sec - self.triggered_at_sec) * 1000.0
