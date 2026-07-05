"""Pure-Python stepper math -- no GPIO, fully unit-testable.

Two independent pieces, deliberately separated from the GPIO-driving
NEMA17ClosedLoopDriver so the logic that actually matters for correctness
and safety (radians<->step conversion, position tracking, stall
debouncing) can be tested without hardware:

  StepConverter    -- radians <-> motor steps, honestly bounded by the
                       driver's configured steps_per_rev * microstepping.
  StallFaultTracker -- turns a raw, possibly-noisy ALM (alarm) GPIO
                       reading into a debounced is_stalled/lost_sync
                       state machine. A single glitched read must not
                       declare a stall (false alarm -> unnecessary
                       motion-stop); N consecutive alarm reads must not
                       be silently ignored either (a real stall must be
                       caught promptly). lost_sync is LATCHED -- it stays
                       true after a confirmed stall until clear_stall()
                       is called, mirroring how a real closed-loop
                       stepper driver's fault output behaves (it doesn't
                       self-clear the instant the mechanical jam is gone).
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class StepConverterConfig:
    steps_per_rev: int = 200  # standard NEMA17 full-step count (1.8 deg/step)
    microstepping: int = 8  # driver microstep setting (must match physical DIP/config)

    def __post_init__(self) -> None:
        if self.steps_per_rev <= 0:
            raise ValueError("steps_per_rev must be > 0")
        if self.microstepping <= 0:
            raise ValueError("microstepping must be > 0")

    @property
    def steps_per_radian(self) -> float:
        return (self.steps_per_rev * self.microstepping) / (2.0 * math.pi)


class StepConverter:
    def __init__(self, config: StepConverterConfig | None = None) -> None:
        self._cfg = config or StepConverterConfig()

    @property
    def config(self) -> StepConverterConfig:
        return self._cfg

    def radians_to_steps(self, radians: float) -> int:
        return round(radians * self._cfg.steps_per_radian)

    def steps_to_radians(self, steps: int) -> float:
        return steps / self._cfg.steps_per_radian

    def step_delta(self, current_rad: float, target_rad: float) -> int:
        """Signed step count to move from current to target -- computed
        in step-space (rounds each side independently) so repeated small
        moves don't accumulate rounding error beyond +/-1 step."""
        return self.radians_to_steps(target_rad) - self.radians_to_steps(current_rad)


@dataclass(frozen=True)
class StallFaultConfig:
    confirm_after_n_polls: int = 3  # consecutive alarm-asserted polls to confirm a stall
    clear_after_n_polls: int = 3  # consecutive alarm-clear polls before allowing clear_stall()

    def __post_init__(self) -> None:
        if self.confirm_after_n_polls < 1:
            raise ValueError("confirm_after_n_polls must be >= 1")
        if self.clear_after_n_polls < 1:
            raise ValueError("clear_after_n_polls must be >= 1")


class StallFaultTracker:
    """One instance per stepper. Feed it raw ALM pin reads via poll();
    read is_stalled/lost_sync for the debounced state."""

    def __init__(self, config: StallFaultConfig | None = None) -> None:
        self._cfg = config or StallFaultConfig()
        self._consecutive_alarm = 0
        self._consecutive_clear = 0
        self._lost_sync = False

    def poll(self, alarm_asserted: bool) -> None:
        if alarm_asserted:
            self._consecutive_alarm += 1
            self._consecutive_clear = 0
            if self._consecutive_alarm >= self._cfg.confirm_after_n_polls:
                self._lost_sync = True
        else:
            self._consecutive_clear += 1
            self._consecutive_alarm = 0

    @property
    def is_stalled(self) -> bool:
        """True only while the alarm signal is CURRENTLY confirmed
        asserted -- distinct from lost_sync, which stays true after
        the alarm clears until clear_stall() is explicitly called."""
        return self._consecutive_alarm >= self._cfg.confirm_after_n_polls

    @property
    def lost_sync(self) -> bool:
        return self._lost_sync

    @property
    def can_clear(self) -> bool:
        """True once the alarm has read clear for enough consecutive
        polls that acknowledging the fault is physically meaningful --
        clear_stall() calling code should check this rather than allow
        clearing a fault whose underlying condition is still present."""
        return self._consecutive_clear >= self._cfg.clear_after_n_polls

    def clear_stall(self) -> bool:
        """Attempt to clear a latched stall. Returns True if cleared,
        False if the alarm hasn't been clear for long enough yet (the
        latch is NOT force-cleared -- calling this while still stalled
        must not silently pretend the fault is gone)."""
        if not self.can_clear:
            return False
        self._lost_sync = False
        return True
