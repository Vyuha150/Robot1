"""
bonbon_gesture.logic.temporal_smoother
========================================
Majority-vote temporal smoother for gesture detections.

Rationale
---------
Per-frame gesture classification is inherently noisy.  A single bad frame
can produce a spurious label.  The smoother aggregates the last N detections
(the *temporal window*) and only fires an event when the same gesture wins a
majority vote — and only once per cooldown period.

Safety-relevant gestures (stop_palm, raised_hand, fallen_posture) bypass the
cooldown so they always produce an event when they first appear.

Fired events vs. held events
------------------------------
The smoother also tracks whether a gesture is *just_started*, *is_held*, or
*just_ended* by comparing the current winner to the previous winning gesture.
"""

from __future__ import annotations

import time
from collections import Counter, defaultdict, deque
from typing import Dict, Optional, Tuple

from ..config.gesture_config import GestureConfig

# Gestures for which cooldown is skipped
_SAFETY_GESTURES = frozenset({"stop_palm", "raised_hand", "fallen_posture"})

# Minimum vote count required to fire (also needs majority)
_MIN_VOTES = 2


class GestureTemporalSmoother:
    """Majority-vote smoother and cooldown manager for gesture events.

    Args:
        config: Runtime gesture configuration.
    """

    def __init__(self, config: GestureConfig) -> None:
        self._config = config
        self._windows: Dict[int, deque] = defaultdict(
            lambda: deque(maxlen=config.temporal_window)
        )
        # Tracks last fire time per "tracking_id:gesture" key
        self._last_fired: Dict[str, float] = {}
        # Tracks the previous winning gesture per person
        self._prev_gesture: Dict[int, str] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(
        self,
        tracking_id: int,
        gesture: str,
        confidence: float,
    ) -> Optional[Tuple[str, float, bool, bool, bool]]:
        """Submit a new gesture observation and decide whether to fire an event.

        Args:
            tracking_id: Integer ID of the person being tracked.
            gesture: Gesture name string (e.g. ``'raised_hand'``).
            confidence: Classifier confidence score for this observation.

        Returns:
            A 5-tuple ``(gesture, avg_confidence, just_started, is_held,
            just_ended)`` when an event should be published, or ``None``
            when the window has not converged, the vote is too weak, or the
            cooldown has not elapsed.
        """
        self._windows[tracking_id].append((gesture, confidence))

        votes = Counter(g for g, _ in self._windows[tracking_id])
        if not votes:
            return None

        top_gesture, count = votes.most_common(1)[0]

        # Require majority and minimum absolute vote count
        window_size = len(self._windows[tracking_id])
        if top_gesture == "none" or count < max(_MIN_VOTES, window_size // 2):
            self._update_prev(tracking_id, "none")
            return None

        avg_conf = (
            sum(c for g, c in self._windows[tracking_id] if g == top_gesture) / count
        )

        # ── Cooldown check ───────────────────────────────────────────────────
        is_safety = top_gesture in _SAFETY_GESTURES
        fire_key = f"{tracking_id}:{top_gesture}"
        now = time.monotonic()

        if (
            not is_safety
            and now - self._last_fired.get(fire_key, 0.0) < self._config.gesture_cooldown_sec
        ):
            # Within cooldown — update held state silently
            self._update_prev(tracking_id, top_gesture)
            return None

        self._last_fired[fire_key] = now

        # ── Temporal context flags ───────────────────────────────────────────
        prev = self._prev_gesture.get(tracking_id, "none")
        just_started = prev != top_gesture
        just_ended = False  # just_ended is determined on the *next* call
        is_held = not just_started

        self._update_prev(tracking_id, top_gesture)
        return (top_gesture, avg_conf, just_started, is_held, just_ended)

    def notify_person_lost(self, tracking_id: int) -> Optional[Tuple[str, float, bool, bool, bool]]:
        """Notify the smoother that a person has left the scene.

        If the person was holding a gesture, a just_ended event is returned
        so that the node can publish a final trailing event.

        Args:
            tracking_id: The lost person's integer tracking ID.

        Returns:
            A 5-tuple with ``just_ended=True`` if the person held a gesture,
            otherwise ``None``.
        """
        prev = self._prev_gesture.pop(tracking_id, "none")
        self._windows.pop(tracking_id, None)

        if prev and prev != "none":
            return (prev, 0.0, False, False, True)
        return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _update_prev(self, tracking_id: int, gesture: str) -> None:
        self._prev_gesture[tracking_id] = gesture
