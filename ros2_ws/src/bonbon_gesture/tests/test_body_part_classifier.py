"""Tests for classify_body_part — disambiguating hand/arm/head/posture origin."""

from __future__ import annotations

from bonbon_gesture.logic.body_part_classifier import classify_body_part


class TestHeadGestures:
    def test_head_nod_is_head(self):
        assert classify_body_part("head_nod_yes", "none") == "head"

    def test_head_shake_is_head(self):
        assert classify_body_part("head_shake_no", "none") == "head"


class TestPostureGestures:
    def test_fallen_posture_is_posture(self):
        assert classify_body_part("fallen_posture", "none") == "posture"


class TestArmGestures:
    def test_raised_hand_is_arm(self):
        assert classify_body_part("raised_hand", "none") == "arm"

    def test_come_here_is_arm(self):
        assert classify_body_part("come_here", "wave_candidate") == "arm"

    def test_pointing_direction_is_arm(self):
        assert classify_body_part("pointing_left", "pointing") == "arm"


class TestHandPassthrough:
    def test_passthrough_hand_gesture_is_hand(self):
        # Body classifier passed the hand classification straight through.
        assert classify_body_part("thumbs_up", "thumbs_up") == "hand"

    def test_stop_palm_from_body_classifier_is_arm_not_hand(self):
        # stop_palm is in both hand and body vocab, but body's pose-confirmed
        # stop_palm should be reported as the arm/pose signal, not raw hand.
        assert classify_body_part("stop_palm", "stop_palm") == "arm"


class TestNoneAndUnknown:
    def test_no_gesture_is_empty(self):
        assert classify_body_part("none", "none") == ""

    def test_unknown_gesture_is_empty(self):
        assert classify_body_part("unknown_gesture", "unknown_gesture") == ""
