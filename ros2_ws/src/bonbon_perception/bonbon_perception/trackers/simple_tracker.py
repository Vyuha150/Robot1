"""
bonbon_perception.trackers.simple_tracker
==========================================
IoU-based greedy multi-person tracker.

Algorithm per frame
-------------------
1. Build cost matrix: C[i][j] = 1 - IoU(track_i, detection_j)
2. Greedy assignment: pick the (track, detection) pair with minimum cost
   if cost < (1 - iou_threshold), else no match.
3. Matched tracks: call track.update(detection)
4. Unmatched tracks: call track.mark_lost(); delete after max_lost_frames
5. Unmatched detections: create new TENTATIVE Track

Design rationale
----------------
IoU matching is O(T×D) — fast for T, D ≤ 10 persons, which covers the
service-robot scenario.  For large crowds (T+D > 50) consider replacing
with scipy linear_sum_assignment + Kalman filter (SORT algorithm).

The tracker is entirely pure-Python / NumPy — no ROS2 dependency.
"""

from __future__ import annotations

import numpy as np

from ..detectors.person_detector import Detection
from .person_tracker import Track, TrackState


class SimpleTracker:
    """
    Greedy IoU multi-person tracker.

    Parameters
    ----------
    iou_threshold       float  minimum IoU to count as a match (default 0.3)
    max_lost_frames     int    frames after which a LOST track is deleted (default 15)
    max_tracks          int    safety cap on number of simultaneous tracks (default 20)
    """

    def __init__(
        self,
        iou_threshold: float = 0.3,
        max_lost_frames: int = 15,
        max_tracks: int = 20,
    ) -> None:
        self._iou_threshold = iou_threshold
        self._max_lost_frames = max_lost_frames
        self._max_tracks = max_tracks
        self._tracks: dict[str, Track] = {}
        self._next_id: int = 0

    # ── Public interface ──────────────────────────────────────────────────────

    def update(self, detections: list[Detection]) -> list[Track]:
        """
        Associate detections with existing tracks and return the updated
        list of CONFIRMED tracks.

        Args:
            detections: List[Detection] from the current frame.

        Returns:
            List[Track] — only CONFIRMED tracks (state == CONFIRMED).
        """
        active = [t for t in self._tracks.values() if t.is_active]

        if not active and not detections:
            return []

        matched_track_ids, matched_det_indices = self._associate(active, detections)

        # Update matched tracks
        for t_id, d_idx in zip(matched_track_ids, matched_det_indices):
            self._tracks[t_id].update(detections[d_idx])

        # Mark unmatched tracks as lost
        matched_set = set(matched_track_ids)
        for t in active:
            if t.track_id not in matched_set:
                t.mark_lost()

        # Create new tracks for unmatched detections
        matched_det_set = set(matched_det_indices)
        for i, det in enumerate(detections):
            if i not in matched_det_set:
                self._create_track(det)

        # Purge deleted and over-age-lost tracks
        to_delete = [
            tid
            for tid, t in self._tracks.items()
            if t.state == TrackState.DELETED
            or (t.state == TrackState.LOST and t.lost_count > self._max_lost_frames)
        ]
        for tid in to_delete:
            del self._tracks[tid]

        return [t for t in self._tracks.values() if t.should_publish]

    @property
    def active_tracks(self) -> list[Track]:
        return [t for t in self._tracks.values() if t.is_active]

    @property
    def confirmed_tracks(self) -> list[Track]:
        return [t for t in self._tracks.values() if t.should_publish]

    def reset(self) -> None:
        """Clear all tracks (e.g. on node restart)."""
        self._tracks.clear()
        self._next_id = 0

    # ── Association ───────────────────────────────────────────────────────────

    def _associate(
        self,
        tracks: list[Track],
        detections: list[Detection],
    ) -> tuple[list[str], list[int]]:
        """
        Greedy IoU matching.

        Returns:
            matched_track_ids   List[str]  — track IDs that were matched
            matched_det_indices List[int]  — corresponding detection indices
        """
        if not tracks or not detections:
            return [], []

        # Build IoU cost matrix [T × D]
        n_t = len(tracks)
        n_d = len(detections)
        cost = np.ones((n_t, n_d), dtype=np.float32)

        for i, track in enumerate(tracks):
            det_t = Detection(bbox=track.bbox)  # surrogate Detection for IoU
            for j, det in enumerate(detections):
                iou = Detection.iou(det_t, det)
                cost[i, j] = 1.0 - iou

        # Greedy assignment: repeatedly pick the minimum-cost pair
        matched_t: list[str] = []
        matched_d: list[int] = []
        used_t = set()
        used_d = set()

        threshold = 1.0 - self._iou_threshold
        flat = np.argsort(cost.ravel())

        for idx in flat:
            i = idx // n_d
            j = idx % n_d
            if i in used_t or j in used_d:
                continue
            if cost[i, j] > threshold:
                break
            matched_t.append(tracks[i].track_id)
            matched_d.append(j)
            used_t.add(i)
            used_d.add(j)

        return matched_t, matched_d

    # ── Track creation ────────────────────────────────────────────────────────

    def _create_track(self, det: Detection) -> Track | None:
        if len(self._tracks) >= self._max_tracks:
            return None

        track_id = f"person_{self._next_id}"
        self._next_id += 1

        cx, cy = det.centre_px
        track = Track(
            track_id=track_id,
            cx=cx,
            cy=cy,
            bbox=det.bbox,
            distance_m=det.depth_m,
            bearing_deg=det.bearing_deg,
        )
        track.update(det)  # first update sets state machinery
        self._tracks[track_id] = track
        return track
