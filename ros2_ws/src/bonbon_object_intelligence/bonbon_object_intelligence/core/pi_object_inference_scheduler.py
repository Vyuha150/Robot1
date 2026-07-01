"""PiObjectInferenceScheduler — Raspberry Pi frame-rate + bounded-queue
policy for object processing, independent of whatever the camera's raw
frame rate is.

Two responsibilities, both required by the Pi efficiency rules this
project has followed since the boot-topology/Hailo work:
  1. Rate limiting: only accept a new frame for processing at most every
     `1 / target_fps` seconds -- extra frames are stale, not queued.
  2. Bounded queue: at most `bounded_queue_size` frames may be pending;
     once full, the OLDEST pending frame is dropped (never grows
     unbounded, never blocks the publisher).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass


@dataclass
class SchedulerConfig:
    target_fps: float = 8.0
    bounded_queue_size: int = 2
    drop_stale_frames: bool = True


@dataclass(frozen=True)
class ScheduleDecision:
    accepted: bool
    dropped_stale: bool
    reason: str


class PiObjectInferenceScheduler:
    def __init__(self, config: SchedulerConfig | None = None) -> None:
        self._cfg = config or SchedulerConfig()
        self._last_processed_ts: float | None = None
        self._queue: deque[float] = deque()
        self._stale_dropped_count = 0

    @property
    def target_fps(self) -> float:
        return self._cfg.target_fps

    @property
    def min_interval_sec(self) -> float:
        return 1.0 / max(self._cfg.target_fps, 0.01)

    @property
    def queue_depth(self) -> int:
        return len(self._queue)

    @property
    def stale_dropped_count(self) -> int:
        return self._stale_dropped_count

    def offer(self, now: float) -> ScheduleDecision:
        """Call once per incoming frame. Returns whether it should be
        admitted for processing. Admitted frames stay in the bounded queue
        (representing "in flight, not yet drained") until `mark_done()` is
        called for them; the queue never grows past `bounded_queue_size` --
        the oldest still-pending frame is dropped to make room, never the
        newest, so processing always tracks the most recent reality."""
        if (
            self._last_processed_ts is not None
            and (now - self._last_processed_ts) < self.min_interval_sec
        ):
            if self._cfg.drop_stale_frames:
                self._stale_dropped_count += 1
                return ScheduleDecision(False, True, "faster than target_fps, frame dropped")
            return ScheduleDecision(False, False, "faster than target_fps, frame ignored")

        while len(self._queue) >= self._cfg.bounded_queue_size:
            self._queue.popleft()
            self._stale_dropped_count += 1

        self._queue.append(now)
        self._last_processed_ts = now
        return ScheduleDecision(True, False, "accepted")

    def mark_done(self, ts: float) -> None:
        """Call once processing for the frame admitted at `ts` completes."""
        try:
            self._queue.remove(ts)
        except ValueError:
            pass
