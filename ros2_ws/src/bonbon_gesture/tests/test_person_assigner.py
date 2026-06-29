"""Tests for GesturePersonAssigner — multi-person gesture-to-identity assignment.

Verifies the explicit project rule that gestures must never be attributed to
the wrong person when multiple people are in frame.
"""

from __future__ import annotations

from bonbon_gesture.logic.person_assigner import (
    GesturePersonAssigner,
    LandmarkCandidate,
    TrackedPersonCandidate,
    bearing_deg_from_xy,
    bearing_to_expected_x_norm,
    pose_centroid_x_norm,
)


class TestBearingToExpectedXNorm:
    def test_zero_bearing_is_frame_centre(self):
        assert abs(bearing_to_expected_x_norm(0.0, 60.0) - 0.5) < 1e-6

    def test_positive_bearing_left_of_centre(self):
        x = bearing_to_expected_x_norm(15.0, 60.0)
        assert x < 0.5

    def test_negative_bearing_right_of_centre(self):
        x = bearing_to_expected_x_norm(-15.0, 60.0)
        assert x > 0.5

    def test_clamped_within_0_and_1(self):
        assert 0.0 <= bearing_to_expected_x_norm(1000.0, 60.0) <= 1.0
        assert 0.0 <= bearing_to_expected_x_norm(-1000.0, 60.0) <= 1.0


class TestPoseCentroidXNorm:
    def test_computes_mean_of_visible_landmarks(self):
        pose = [(100.0, 0, 0, 0.9), (300.0, 0, 0, 0.9)]
        assert abs(pose_centroid_x_norm(pose, image_width=400) - 0.5) < 1e-6

    def test_ignores_low_visibility_landmarks(self):
        pose = [(100.0, 0, 0, 0.9), (900.0, 0, 0, 0.05)]  # second is occluded
        result = pose_centroid_x_norm(pose, image_width=400)
        assert abs(result - 0.25) < 1e-6

    def test_none_when_no_pose(self):
        assert pose_centroid_x_norm(None, image_width=400) is None

    def test_none_when_nothing_visible(self):
        pose = [(100.0, 0, 0, 0.1)]
        assert pose_centroid_x_norm(pose, image_width=400) is None

    def test_none_when_invalid_width(self):
        assert pose_centroid_x_norm([(1, 1, 1, 1)], image_width=0) is None


class TestBearingDegFromXY:
    def test_straight_ahead_is_zero(self):
        assert abs(bearing_deg_from_xy(1.0, 0.0)) < 1e-6


class TestGesturePersonAssignerSinglePerson:
    def test_single_person_single_track_assigns(self):
        a = GesturePersonAssigner(camera_hfov_deg=60.0)
        lm = [LandmarkCandidate(tracking_id=0, centroid_x_norm=0.5)]
        tp = [TrackedPersonCandidate(person_track_id="ptrk_1", bearing_deg=0.0)]
        result = a.assign(lm, tp)
        assert result == {0: "ptrk_1"}

    def test_empty_inputs_return_empty(self):
        a = GesturePersonAssigner()
        assert a.assign([], []) == {}
        assert a.assign([LandmarkCandidate(0, 0.5)], []) == {}
        assert a.assign([], [TrackedPersonCandidate("p", 0.0)]) == {}


class TestGesturePersonAssignerMultiPerson:
    def test_two_people_left_and_right_assigned_correctly(self):
        a = GesturePersonAssigner(camera_hfov_deg=60.0)
        # Person A is to the robot's left (positive bearing -> left side of frame)
        # Person B is to the robot's right (negative bearing -> right side of frame)
        lm = [
            LandmarkCandidate(tracking_id=0, centroid_x_norm=0.15),  # left side
            LandmarkCandidate(tracking_id=1, centroid_x_norm=0.85),  # right side
        ]
        tp = [
            TrackedPersonCandidate(person_track_id="left_person", bearing_deg=20.0),
            TrackedPersonCandidate(person_track_id="right_person", bearing_deg=-20.0),
        ]
        result = a.assign(lm, tp)
        assert result[0] == "left_person"
        assert result[1] == "right_person"

    def test_never_double_assigns_one_track_to_two_landmark_sets(self):
        a = GesturePersonAssigner(camera_hfov_deg=60.0, max_x_norm_delta=0.5)
        lm = [
            LandmarkCandidate(tracking_id=0, centroid_x_norm=0.48),
            LandmarkCandidate(tracking_id=1, centroid_x_norm=0.52),
        ]
        tp = [TrackedPersonCandidate(person_track_id="only_one", bearing_deg=0.0)]
        result = a.assign(lm, tp)
        # At most one landmark set may claim this track — never both.
        assert len(result) <= 1
        assigned_tracks = list(result.values())
        assert len(assigned_tracks) == len(set(assigned_tracks))

    def test_count_mismatch_leaves_extra_landmark_unassigned(self):
        """Three people detected by the backend, only two known tracks —
        the third must be left unassigned, never guessed."""
        a = GesturePersonAssigner(camera_hfov_deg=90.0, max_x_norm_delta=0.2)
        lm = [
            LandmarkCandidate(tracking_id=0, centroid_x_norm=0.1),
            LandmarkCandidate(tracking_id=1, centroid_x_norm=0.5),
            LandmarkCandidate(tracking_id=2, centroid_x_norm=0.9),
        ]
        tp = [
            TrackedPersonCandidate(person_track_id="p_left", bearing_deg=36.0),
            TrackedPersonCandidate(person_track_id="p_right", bearing_deg=-36.0),
        ]
        result = a.assign(lm, tp)
        assert len(result) == 2
        assert 1 not in result  # the middle/extra one is correctly unassigned

    def test_out_of_tolerance_match_is_rejected_not_guessed(self):
        a = GesturePersonAssigner(camera_hfov_deg=60.0, max_x_norm_delta=0.05)
        lm = [LandmarkCandidate(tracking_id=0, centroid_x_norm=0.5)]
        # Tracked person predicted way off to one side — too far to trust.
        tp = [TrackedPersonCandidate(person_track_id="far_off", bearing_deg=30.0)]
        result = a.assign(lm, tp)
        assert result == {}

    def test_close_bearings_still_resolve_distinctly(self):
        """Two people close together in bearing but still distinguishable —
        each landmark set must go to its nearest match, not be merged."""
        a = GesturePersonAssigner(camera_hfov_deg=60.0, max_x_norm_delta=0.5)
        lm = [
            LandmarkCandidate(tracking_id=0, centroid_x_norm=0.45),
            LandmarkCandidate(tracking_id=1, centroid_x_norm=0.55),
        ]
        tp = [
            TrackedPersonCandidate(person_track_id="a", bearing_deg=6.0),
            TrackedPersonCandidate(person_track_id="b", bearing_deg=-6.0),
        ]
        result = a.assign(lm, tp)
        assert len(result) == 2
        assert result[0] != result[1]
