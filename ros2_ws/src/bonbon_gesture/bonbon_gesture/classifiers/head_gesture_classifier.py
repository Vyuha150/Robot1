"""
bonbon_gesture.classifiers.head_gesture_classifier
====================================================
Temporal head-gesture classifier (nod = yes, shake = no) using a 6-point
face mesh.

Algorithm
---------
A short sliding history of nose-tip (y, x) coordinates is maintained per
tracking ID.  The classifier fires when:

* **Head nod (yes)**: the y-history shows at least 2 direction reversals
  *and* the total vertical range exceeds ``_NOD_AMPLITUDE_PX`` pixels.
* **Head shake (no)**: the x-history shows at least 2 direction reversals
  *and* the total horizontal range exceeds ``_SHAKE_AMPLITUDE_PX`` pixels.

The amplitude thresholds prevent micro-jitter from triggering spurious events.

Face-mesh index mapping (our simplified 6-point set):
  0 = nose_tip, 1 = left_eye, 2 = right_eye,
  3 = mouth_left, 4 = mouth_right, 5 = chin
"""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Dict, List, Optional, Tuple

from ..config.gesture_config import GestureConfig

# Amplitude thresholds (pixels, calibrated for 640×480)
_NOD_AMPLITUDE_PX = 15.0
_SHAKE_AMPLITUDE_PX = 20.0

# Minimum sign changes required to detect a gesture
_MIN_SIGN_CHANGES = 2


class HeadGestureClassifier:
    """Temporal head-gesture classifier for nod and shake detection.

    Args:
        config: Runtime gesture configuration.  The ``temporal_window``
            field controls the history length.

    Note:
        A separate history is kept per ``tracking_id`` so that multiple
        people can be processed simultaneously without cross-contamination.
    """

    def __init__(self, config: GestureConfig) -> None:
        self._config = config
        history_len = max(6, config.temporal_window * 2)
        self._nose_y_history: Dict[int, deque] = defaultdict(
            lambda: deque(maxlen=history_len)
        )
        self._nose_x_history: Dict[int, deque] = defaultdict(
            lambda: deque(maxlen=history_len)
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(
        self,
        tracking_id: int,
        face_pts: Optional[List[Tuple[float, float, float]]],
    ) -> Tuple[str, float]:
        """Update the nose-position history and check for gestures.

        Args:
            tracking_id: Integer identifier for the person being tracked.
            face_pts: 6-point face mesh, or ``None`` if no face was detected.
                Element 0 must be the nose tip: ``(x_px, y_px, z_relative)``.

        Returns:
            ``(gesture_name, confidence)`` where ``gesture_name`` is one of
            ``'head_nod_yes'``, ``'head_shake_no'``, or ``'none'``.
        """
        if face_pts is None or len(face_pts) < 1:
            return ("none", 0.0)

        nose_x, nose_y = face_pts[0][0], face_pts[0][1]
        self._nose_y_history[tracking_id].append(nose_y)
        self._nose_x_history[tracking_id].append(nose_x)

        # Need at least 6 samples to detect a full oscillation cycle
        if len(self._nose_y_history[tracking_id]) < 6:
            return ("none", 0.0)

        if self._detect_nod(self._nose_y_history[tracking_id]):
            return ("head_nod_yes", 0.82)

        if self._detect_shake(self._nose_x_history[tracking_id]):
            return ("head_shake_no", 0.80)

        return ("none", 0.0)

    def reset(self, tracking_id: int) -> None:
        """Clear the history buffers for a person that has left the scene.

        Args:
            tracking_id: The person's integer tracking identifier.
        """
        self._nose_y_history.pop(tracking_id, None)
        self._nose_x_history.pop(tracking_id, None)

    # ------------------------------------------------------------------
    # Detection helpers
    # ------------------------------------------------------------------

    def _detect_nod(self, history: deque) -> bool:
        """Return True when the y-history shows a nodding pattern.

        A nod is characterised by alternating upward/downward motion with
        a total y-range larger than ``_NOD_AMPLITUDE_PX``.

        Args:
            history: Deque of recent nose y-coordinates (pixels, increasing
                downward).

        Returns:
            True when a nod is detected.
        """
        vals = list(history)
        diffs = [vals[i + 1] - vals[i] for i in range(len(vals) - 1)]
        sign_changes = sum(
            1
            for i in range(len(diffs) - 1)
            if diffs[i] * diffs[i + 1] < -0.5  # strict sign change, filtering zero-diffs
        )
        total_range = max(vals) - min(vals)
        return sign_changes >= _MIN_SIGN_CHANGES and total_range > _NOD_AMPLITUDE_PX

    def _detect_shake(self, history: deque) -> bool:
        """Return True when the x-history shows a shaking pattern.

        A shake is characterised by alternating left/right motion with a
        total x-range larger than ``_SHAKE_AMPLITUDE_PX``.

        Args:
            history: Deque of recent nose x-coordinates (pixels).

        Returns:
            True when a shake is detected.
        """
        vals = list(history)
        diffs = [vals[i + 1] - vals[i] for i in range(len(vals) - 1)]
        sign_changes = sum(
            1
            for i in range(len(diffs) - 1)
            if diffs[i] * diffs[i + 1] < -0.5
        )
        total_range = max(vals) - min(vals)
        return sign_changes >= _MIN_SIGN_CHANGES and total_range > _SHAKE_AMPLITUDE_PX
