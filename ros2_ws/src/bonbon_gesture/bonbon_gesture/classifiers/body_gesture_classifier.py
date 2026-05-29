"""
bonbon_gesture.classifiers.body_gesture_classifier
====================================================
Rules-based body / arm pose classifier operating on the 33-point MediaPipe
Pose landmark set.

MediaPipe Pose landmark indices (used here)
--------------------------------------------
0  = nose
11 = left_shoulder   12 = right_shoulder
13 = left_elbow      14 = right_elbow
15 = left_wrist      16 = right_wrist
23 = left_hip        24 = right_hip

Each landmark is a tuple ``(x_px, y_px, z_relative, visibility)``.
Landmarks with visibility below ``min_visibility_threshold`` should be
treated as absent; this classifier uses 0.5 as its internal default.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

# Minimum landmark visibility score treated as "visible"
_VIS_MIN = 0.5

# Pixel thresholds (independent of resolution — calibrated for 640×480)
# scale factor helper: these constants were tuned for 480-pixel-tall frames.
_RAISED_HAND_MARGIN_PX = 50   # wrist must be this far above shoulder
_POINTING_SIDE_MARGIN_PX = 80  # wrist must be this far left/right of nose
_FALLEN_NOSE_HIP_PX = 60       # max y-distance for "fallen" heuristic
_WRIST_ELBOW_WAVE_PX = 0       # wrist y strictly less than elbow y


class BodyGestureClassifier:
    """Classify body / arm gestures from 33-point pose landmarks.

    This classifier is stateless; a single instance can be reused for every
    person across frames.
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def classify(
        self,
        pose: Optional[List[Tuple[float, float, float, float]]],
        hand_gesture: str,
    ) -> Tuple[str, float]:
        """Map pose landmarks + hand gesture to a body-level gesture.

        Args:
            pose: 33-point pose landmark list, or ``None`` when pose was not
                detected.  Each element: ``(x_px, y_px, z_relative, visibility)``.
            hand_gesture: The gesture string returned by
                :class:`~bonbon_gesture.classifiers.hand_gesture_classifier.HandGestureClassifier`.
                Used to refine ambiguous cases (e.g., confirming a stop-palm or
                choosing the pointing sub-type).

        Returns:
            A ``(gesture_name, confidence)`` tuple.
        """
        if pose is None or len(pose) < 33:
            # No pose available — fall back to hand-only result if meaningful
            if hand_gesture not in ("none", "wave_candidate", "unknown_gesture"):
                return (hand_gesture, 0.50)
            return ("none", 0.0)

        # ── Safety: fallen posture ───────────────────────────────────────────
        # Check first so it is never masked by other rules.
        if self._is_fallen(pose):
            return ("fallen_posture", 0.75)

        # ── Raised hand ─────────────────────────────────────────────────────
        if self._is_hand_raised(pose):
            return ("raised_hand", 0.90)

        # ── Stop palm (confirmed at body level) ─────────────────────────────
        if hand_gesture == "stop_palm":
            return ("stop_palm", 0.92)

        # ── Wave (open hand + wrist at shoulder/above-elbow level) ──────────
        if hand_gesture == "wave_candidate" and self._is_waving(pose):
            return ("wave", 0.85)

        # ── Pointing — choose directional sub-type ─────────────────────────
        if "pointing" in hand_gesture:
            direction = self._classify_pointing_direction(pose)
            return (direction, 0.83)

        # ── Come here ───────────────────────────────────────────────────────
        if self._is_beckoning(pose):
            return ("come_here", 0.78)

        # ── Fall-through: propagate meaningful hand result ───────────────────
        if hand_gesture not in ("none", "wave_candidate", "unknown_gesture"):
            return (hand_gesture, 0.65)

        return ("unknown_gesture", 0.30)

    # ------------------------------------------------------------------
    # Pose analysis helpers
    # ------------------------------------------------------------------

    def _is_hand_raised(self, pose: List[Tuple[float, float, float, float]]) -> bool:
        """Detect whether either wrist is significantly above its shoulder.

        A raised wrist that is also visible and high enough above the shoulder
        line is considered a raised-hand gesture (attention / hailing).

        Args:
            pose: 33-point pose landmark list.

        Returns:
            True when at least one wrist is raised above its shoulder.
        """
        left_wrist_raised = (
            pose[15][3] > _VIS_MIN
            and pose[11][3] > _VIS_MIN
            and pose[15][1] < pose[11][1] - _RAISED_HAND_MARGIN_PX
        )
        right_wrist_raised = (
            pose[16][3] > _VIS_MIN
            and pose[12][3] > _VIS_MIN
            and pose[16][1] < pose[12][1] - _RAISED_HAND_MARGIN_PX
        )
        return left_wrist_raised or right_wrist_raised

    def _is_waving(self, pose: List[Tuple[float, float, float, float]]) -> bool:
        """Check whether a wrist is above elbow level (wave prerequisite).

        A ``wave_candidate`` from the hand classifier is promoted to ``wave``
        when the wrist is at least at elbow height — this distinguishes a
        lowered open palm from an actual wave.

        Args:
            pose: 33-point pose landmark list.

        Returns:
            True when at least one wrist is above its corresponding elbow.
        """
        left_wave = (
            pose[15][3] > _VIS_MIN
            and pose[13][3] > _VIS_MIN
            and pose[15][1] < pose[13][1] - _WRIST_ELBOW_WAVE_PX
        )
        right_wave = (
            pose[16][3] > _VIS_MIN
            and pose[14][3] > _VIS_MIN
            and pose[16][1] < pose[14][1] - _WRIST_ELBOW_WAVE_PX
        )
        return left_wave or right_wave

    def _classify_pointing_direction(
        self, pose: List[Tuple[float, float, float, float]]
    ) -> str:
        """Determine whether the person is pointing left, right, or forward.

        The wrist x-coordinate is compared against the nose x-coordinate.
        A wrist more than ``_POINTING_SIDE_MARGIN_PX`` to the right of the
        nose is "pointing right" and vice versa.

        Args:
            pose: 33-point pose landmark list.

        Returns:
            One of ``'pointing_right'``, ``'pointing_left'``,
            or ``'pointing_forward'``.
        """
        nose_x = pose[0][0]

        right_wrist_visible = pose[16][3] > _VIS_MIN
        left_wrist_visible = pose[15][3] > _VIS_MIN

        if right_wrist_visible and pose[16][0] > nose_x + _POINTING_SIDE_MARGIN_PX:
            return "pointing_right"
        if left_wrist_visible and pose[15][0] < nose_x - _POINTING_SIDE_MARGIN_PX:
            return "pointing_left"
        return "pointing_forward"

    def _is_fallen(self, pose: List[Tuple[float, float, float, float]]) -> bool:
        """Detect a fallen posture by comparing nose and hip y-coordinates.

        When a person has fallen the nose drops close to hip level.  If the
        vertical distance between nose and the average hip position is less
        than the threshold the posture is flagged as fallen.

        Args:
            pose: 33-point pose landmark list.

        Returns:
            True when the fallen-posture heuristic fires.
        """
        if pose[0][3] < _VIS_MIN:
            return False  # nose not visible — cannot determine
        if pose[23][3] < _VIS_MIN and pose[24][3] < _VIS_MIN:
            return False  # no hip data

        nose_y = pose[0][1]
        left_hip_y = pose[23][1] if pose[23][3] > _VIS_MIN else pose[24][1]
        right_hip_y = pose[24][1] if pose[24][3] > _VIS_MIN else pose[23][1]
        hip_y = (left_hip_y + right_hip_y) / 2

        return abs(nose_y - hip_y) < _FALLEN_NOSE_HIP_PX

    def _is_beckoning(self, pose: List[Tuple[float, float, float, float]]) -> bool:
        """Detect a 'come here' beckoning gesture.

        Full beckoning detection requires temporal analysis (finger curl +
        uncurl cycles) which is not available in a single-frame classifier.
        This is a placeholder that always returns False; temporal smoothing
        and higher-level intent mapping handle come_here at the node level.

        Args:
            pose: 33-point pose landmark list.

        Returns:
            Always False in the current implementation.
        """
        return False  # requires multi-frame temporal analysis
