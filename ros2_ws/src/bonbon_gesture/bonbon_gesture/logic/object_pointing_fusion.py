"""Fuses a pointing gesture's direction with nearby detected objects to
distinguish "pointing at a specific object" from generic directional
pointing.

See docs/GESTURE_RECOGNITION_FAILURE_ANALYSIS.md's Phase 5 fix scope, item 2
(previously deferred): "pointing_at_object" requires fusing gesture
direction with tracked-object positions, which did not exist anywhere in the
gesture package. Both the pointing direction (elbow->wrist vector) and
detected-object bounding boxes are already expressed in the same 2D camera
pixel space (see PoseLandmarkProcessor.compute_pointing_direction and
DetectedObject.msg's bbox_x/y/w/h) -- this module is pure geometry, no ROS
dependency, so it can be unit-tested without a camera or MediaPipe.

This is a real, testable heuristic, not a validated ground-truth pointing
model: it checks whether an object's bounding-box center falls within an
angular tolerance cone extending from the wrist along the pointing
direction. It deliberately never guesses when no object qualifies -- the
caller falls back to the existing pointing_left/right/forward classification
in that case (honest degraded behavior, not fabricated).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Sequence, Tuple


@dataclass(frozen=True)
class PointableObject:
    """Minimal, ROS-independent view of a detected object usable for
    pointing fusion."""

    track_id: str
    class_name: str
    bbox_x: float
    bbox_y: float
    bbox_w: float
    bbox_h: float

    @property
    def center(self) -> Tuple[float, float]:
        """Bounding-box center in the same pixel space as pose landmarks."""
        return (self.bbox_x + self.bbox_w / 2.0, self.bbox_y + self.bbox_h / 2.0)


class PointingObjectFusion:
    """Finds the detected object (if any) that a pointing gesture is most
    plausibly aimed at.
    """

    def __init__(self, angle_tolerance_deg: float = 25.0) -> None:
        """Initialise the fusion helper.

        Args:
            angle_tolerance_deg: Maximum angle (degrees) between the
                pointing direction and the wrist-to-object vector for an
                object to be considered "pointed at". Smaller is stricter.
        """
        self._angle_tolerance_rad = math.radians(angle_tolerance_deg)

    def find_pointed_object(
        self,
        wrist_px: Tuple[float, float],
        direction_px: Tuple[float, float],
        objects: Sequence[PointableObject],
    ) -> Optional[PointableObject]:
        """Return the object the pointing gesture most plausibly targets.

        Args:
            wrist_px: (x, y) pixel position of the pointing wrist.
            direction_px: (dx, dy) pointing direction in the same pixel
                space (need not be a unit vector; only its direction is
                used). Typically the x/y components of
                ``PoseLandmarkProcessor.compute_pointing_direction``'s
                elbow->wrist vector.
            objects: Candidate detected objects for the current frame.

        Returns:
            The closest-angle object within tolerance and "ahead" of the
            wrist along the pointing direction, or ``None`` if no object
            qualifies -- never a guessed/lowest-confidence fallback.
        """
        dx, dy = direction_px
        dir_len = math.hypot(dx, dy)
        if dir_len < 1e-6:
            return None

        best: Optional[PointableObject] = None
        best_angle: Optional[float] = None

        for obj in objects:
            center_x, center_y = obj.center
            to_obj_x = center_x - wrist_px[0]
            to_obj_y = center_y - wrist_px[1]
            to_obj_len = math.hypot(to_obj_x, to_obj_y)
            if to_obj_len < 1e-6:
                continue

            dot = dx * to_obj_x + dy * to_obj_y
            if dot <= 0.0:
                continue  # object is behind the wrist relative to the pointing direction

            cos_angle = max(-1.0, min(1.0, dot / (dir_len * to_obj_len)))
            angle = math.acos(cos_angle)

            if angle <= self._angle_tolerance_rad and (best_angle is None or angle < best_angle):
                best_angle = angle
                best = obj

        return best
