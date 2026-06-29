"""Assigns each backend-detected landmark set to the correct person_track_id
when multiple people are in frame simultaneously.

The problem
-----------
``GestureBackendInterface.process_frame()`` returns landmark sets indexed by
the BACKEND's own per-frame ``tracking_id`` (MediaPipe's own internal pose
tracker). This is a *different* ID space from
``bonbon_multi_person_tracker``'s ``person_track_id`` — they must be
reconciled every frame, and a wrong reconciliation in a multi-person scene
means attributing one person's gesture to another (an identity-mixing bug, not
just a quality issue).

Why no real bbox/depth-based matching
--------------------------------------
Neither ``PersonState`` nor (today) ``PersonTrack`` carries a populated
per-frame bounding box or a camera-pixel-space position — only a robot-frame
3D position. Inventing a fictional depth/projection pipeline to bridge that
gap would be the kind of over-engineering this project explicitly avoids. So
this module uses the one honest, already-real signal available on both sides:

  * Camera side:  horizontal pixel centroid of the person's visible pose
                   landmarks, normalised to [0, 1] across the frame width.
  * Robot side:   bearing_deg = atan2(y, x) of the tracked person's
                   ``position_3d`` — the SAME bearing convention already used
                   by ``bonbon_spatial``'s ``SpatialRelation.bearing_deg``.

Assuming the camera faces forward with a known horizontal field of view
(``camera_hfov_deg``, default 60°, matching ``UsbCameraDriver``'s default), a
tracked person's bearing predicts where they should appear horizontally in
the frame. Each landmark set is greedily matched to its nearest-bearing
tracked person within a tolerance; anything left over (count mismatch,
ambiguous double match, no tracked persons at all) is correctly left
unassigned rather than guessed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class LandmarkCandidate:
    """One backend-detected person, for assignment purposes only."""

    tracking_id: int
    centroid_x_norm: float  # 0.0 (left edge) .. 1.0 (right edge) of the frame


@dataclass
class TrackedPersonCandidate:
    """One bonbon_multi_person_tracker PersonTrack, for assignment purposes only."""

    person_track_id: str
    bearing_deg: float  # atan2(y, x) of position_3d, robot base_link frame


def bearing_to_expected_x_norm(bearing_deg: float, camera_hfov_deg: float) -> float:
    """Predict where in the frame (0..1) a person at this bearing should appear.

    bearing_deg=0 (straight ahead) -> 0.5 (frame centre).
    Positive bearing (robot's left, by the project's existing convention,
    matching bonbon_spatial) -> smaller x_norm (left side of the image, for a
    forward-facing camera whose image x increases left-to-right).
    """
    half_fov = max(camera_hfov_deg, 1.0) / 2.0
    frac = max(-1.0, min(1.0, bearing_deg / half_fov))
    return 0.5 - 0.5 * frac


class GesturePersonAssigner:
    """Greedy nearest-bearing assignment, one-to-one, with a rejection tolerance."""

    def __init__(self, camera_hfov_deg: float = 60.0, max_x_norm_delta: float = 0.35) -> None:
        self._hfov = camera_hfov_deg
        self._max_delta = max_x_norm_delta

    def assign(
        self,
        landmark_candidates: list[LandmarkCandidate],
        tracked_persons: list[TrackedPersonCandidate],
    ) -> dict[int, str]:
        """Returns ``{tracking_id: person_track_id}`` for confidently matched
        pairs only. Unmatched tracking_ids are simply absent from the result —
        callers must treat a missing entry as "person_track_id unknown", never
        guess.
        """
        if not landmark_candidates or not tracked_persons:
            return {}

        expected = [
            (tp.person_track_id, bearing_to_expected_x_norm(tp.bearing_deg, self._hfov))
            for tp in tracked_persons
        ]

        # Build all (distance, tracking_id, person_track_id) candidate pairs,
        # then greedily consume the globally-best pairs first so two people
        # standing close in bearing don't both grab the same track.
        pairs: list[tuple[float, int, str]] = []
        for lm in landmark_candidates:
            for person_track_id, exp_x in expected:
                dist = abs(lm.centroid_x_norm - exp_x)
                if dist <= self._max_delta:
                    pairs.append((dist, lm.tracking_id, person_track_id))
        pairs.sort(key=lambda p: p[0])

        result: dict[int, str] = {}
        used_tracks: set[str] = set()
        used_landmarks: set[int] = set()
        for _dist, tracking_id, person_track_id in pairs:
            if tracking_id in used_landmarks or person_track_id in used_tracks:
                continue
            result[tracking_id] = person_track_id
            used_landmarks.add(tracking_id)
            used_tracks.add(person_track_id)

        return result


def pose_centroid_x_norm(
    pose: list[tuple[float, float, float, float]] | None, image_width: int
) -> float | None:
    """Compute the normalised horizontal centroid of visible pose landmarks.

    Returns None when no pose / no visible landmarks / invalid image_width —
    callers must skip assignment for that candidate rather than assume 0.5.
    """
    if not pose or image_width <= 0:
        return None
    visible = [p for p in pose if len(p) >= 4 and p[3] >= 0.3]
    if not visible:
        return None
    mean_x = sum(p[0] for p in visible) / len(visible)
    return max(0.0, min(1.0, mean_x / image_width))


def bearing_deg_from_xy(x: float, y: float) -> float:
    """Same convention as bonbon_spatial.SpatialRelation.bearing_deg."""
    return math.degrees(math.atan2(y, x))
