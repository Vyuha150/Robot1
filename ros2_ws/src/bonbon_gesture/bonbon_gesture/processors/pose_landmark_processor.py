"""
bonbon_gesture.processors.pose_landmark_processor
===================================================
Utility class for filtering and normalising raw pose landmarks before they are
fed into the gesture classifiers.

Responsibilities:
* Filter out landmarks below the minimum visibility threshold.
* Compute a pointing direction vector (3D) from wrist–elbow alignment.
* Estimate the person's approximate 2D bounding box in image coordinates.
* Provide a helper to convert pixel-space landmarks to a normalised coordinate
  system centred on the hip midpoint (useful for scale-invariant rules).
"""

from __future__ import annotations

import math
from typing import List, Optional, Tuple

from ..config.gesture_config import GestureConfig

# MediaPipe pose indices used across helpers
_IDX_NOSE = 0
_IDX_LEFT_SHOULDER = 11
_IDX_RIGHT_SHOULDER = 12
_IDX_LEFT_ELBOW = 13
_IDX_RIGHT_ELBOW = 14
_IDX_LEFT_WRIST = 15
_IDX_RIGHT_WRIST = 16
_IDX_LEFT_HIP = 23
_IDX_RIGHT_HIP = 24


class PoseLandmarkProcessor:
    """Pre-process raw pose landmarks for classifier consumption.

    Args:
        config: Runtime gesture configuration providing the
            ``min_visibility_threshold`` parameter.
    """

    def __init__(self, config: GestureConfig) -> None:
        self._vis_min = config.min_visibility_threshold

    # ------------------------------------------------------------------
    # Filtering
    # ------------------------------------------------------------------

    def filter_by_visibility(
        self,
        pose: List[Tuple[float, float, float, float]],
    ) -> List[Tuple[float, float, float, float]]:
        """Zero-out landmarks below the minimum visibility threshold.

        Landmarks that do not meet the threshold are replaced by
        ``(0.0, 0.0, 0.0, 0.0)`` so that downstream index arithmetic
        remains valid.

        Args:
            pose: 33-point pose landmark list, each ``(x, y, z, visibility)``.

        Returns:
            A new list of the same length with low-visibility landmarks
            zeroed out.
        """
        return [
            lm if lm[3] >= self._vis_min else (0.0, 0.0, 0.0, 0.0)
            for lm in pose
        ]

    # ------------------------------------------------------------------
    # Spatial helpers
    # ------------------------------------------------------------------

    def compute_pointing_direction(
        self,
        pose: List[Tuple[float, float, float, float]],
        use_right: bool = True,
    ) -> Tuple[float, float, float]:
        """Compute a 3D unit vector for the arm pointing direction.

        The direction is computed from the elbow → wrist vector, giving the
        orientation of the forearm.

        Args:
            pose: 33-point pose landmark list.
            use_right: When True use the right arm; when False use the left arm.

        Returns:
            A normalised ``(dx, dy, dz)`` unit vector, or ``(0.0, 0.0, 0.0)``
            when the relevant landmarks are not visible.
        """
        wrist_idx = _IDX_RIGHT_WRIST if use_right else _IDX_LEFT_WRIST
        elbow_idx = _IDX_RIGHT_ELBOW if use_right else _IDX_LEFT_ELBOW

        wrist = pose[wrist_idx]
        elbow = pose[elbow_idx]

        if wrist[3] < self._vis_min or elbow[3] < self._vis_min:
            return (0.0, 0.0, 0.0)

        dx = wrist[0] - elbow[0]
        dy = wrist[1] - elbow[1]
        dz = wrist[2] - elbow[2]
        length = math.sqrt(dx * dx + dy * dy + dz * dz)
        if length < 1e-6:
            return (0.0, 0.0, 0.0)
        return (dx / length, dy / length, dz / length)

    def compute_bounding_box(
        self,
        pose: List[Tuple[float, float, float, float]],
    ) -> Optional[Tuple[float, float, float, float]]:
        """Estimate the person's bounding box from visible landmarks.

        Args:
            pose: 33-point pose landmark list.

        Returns:
            ``(x_min, y_min, width, height)`` in pixels, or ``None`` if fewer
            than 4 landmarks are visible.
        """
        visible = [lm for lm in pose if lm[3] >= self._vis_min]
        if len(visible) < 4:
            return None

        xs = [lm[0] for lm in visible]
        ys = [lm[1] for lm in visible]
        x_min, x_max = min(xs), max(xs)
        y_min, y_max = min(ys), max(ys)
        return (x_min, y_min, x_max - x_min, y_max - y_min)

    def normalise_to_hip_centre(
        self,
        pose: List[Tuple[float, float, float, float]],
    ) -> List[Tuple[float, float, float, float]]:
        """Translate landmarks so that the hip midpoint is the origin.

        Scale-invariant rules become more robust when landmarks are expressed
        relative to a stable body reference point.

        Args:
            pose: 33-point pose landmark list.

        Returns:
            A new list with the same visibility scores but with (x, y, z)
            translated so that the hip midpoint is (0, 0, 0).  If hip
            landmarks are not visible the original list is returned unchanged.
        """
        left_hip = pose[_IDX_LEFT_HIP]
        right_hip = pose[_IDX_RIGHT_HIP]

        if left_hip[3] < self._vis_min and right_hip[3] < self._vis_min:
            return pose  # cannot normalise — return as-is

        # Use whichever hip is visible; average both if both visible
        if left_hip[3] >= self._vis_min and right_hip[3] >= self._vis_min:
            cx = (left_hip[0] + right_hip[0]) / 2
            cy = (left_hip[1] + right_hip[1]) / 2
            cz = (left_hip[2] + right_hip[2]) / 2
        elif left_hip[3] >= self._vis_min:
            cx, cy, cz = left_hip[0], left_hip[1], left_hip[2]
        else:
            cx, cy, cz = right_hip[0], right_hip[1], right_hip[2]

        return [(lm[0] - cx, lm[1] - cy, lm[2] - cz, lm[3]) for lm in pose]

    def landmark_distance_px(
        self,
        a: Tuple[float, float, float, float],
        b: Tuple[float, float, float, float],
    ) -> float:
        """Euclidean 2D distance between two landmarks.

        Args:
            a: First landmark tuple ``(x, y, z, visibility)``.
            b: Second landmark tuple ``(x, y, z, visibility)``.

        Returns:
            Pixel distance in the XY plane.
        """
        return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2)
