"""
tests.test_body_classifier
============================
Unit tests for BodyGestureClassifier.

Tests use synthetic 33-point pose landmarks (MediaPipe format).
Each landmark is (x_px, y_px, z_relative, visibility).
"""

from __future__ import annotations

import sys
import os
from typing import List, Tuple

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from bonbon_gesture.classifiers.body_gesture_classifier import BodyGestureClassifier


# ---------------------------------------------------------------------------
# Landmark builders
# ---------------------------------------------------------------------------

_W, _H = 640, 480
_CX = _W / 2


def _standing_pose() -> List[Tuple[float, float, float, float]]:
    """Baseline 33-point standing pose (arms at sides)."""
    nose_y = _H * 0.12
    shoulder_y = _H * 0.28
    elbow_y = _H * 0.46
    wrist_y = _H * 0.60
    hip_y = _H * 0.58
    knee_y = _H * 0.75
    ankle_y = _H * 0.92
    spread = _W * 0.12

    pose = []
    for i in range(33):
        if i == 0:
            pose.append((_CX, nose_y, 0.0, 0.99))
        elif i == 11:
            pose.append((_CX - spread, shoulder_y, 0.0, 0.99))
        elif i == 12:
            pose.append((_CX + spread, shoulder_y, 0.0, 0.99))
        elif i == 13:
            pose.append((_CX - spread, elbow_y, 0.0, 0.95))
        elif i == 14:
            pose.append((_CX + spread, elbow_y, 0.0, 0.95))
        elif i == 15:
            pose.append((_CX - spread, wrist_y, 0.0, 0.90))
        elif i == 16:
            pose.append((_CX + spread, wrist_y, 0.0, 0.90))
        elif i == 23:
            pose.append((_CX - spread * 0.5, hip_y, 0.0, 0.95))
        elif i == 24:
            pose.append((_CX + spread * 0.5, hip_y, 0.0, 0.95))
        elif i in (25, 27):
            pose.append((_CX - spread * 0.4, knee_y if i == 25 else ankle_y, 0.0, 0.90))
        elif i in (26, 28):
            pose.append((_CX + spread * 0.4, knee_y if i == 26 else ankle_y, 0.0, 0.90))
        else:
            pose.append((_CX, (_H * 0.12 + _H * 0.58) / 2, 0.0, 0.80))
    return pose


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestBodyGestureClassifier:

    def setup_method(self):
        self.clf = BodyGestureClassifier()

    def test_none_pose_returns_none(self):
        gesture, conf = self.clf.classify(None, "none")
        assert gesture == "none"
        assert conf == 0.0

    def test_too_short_pose_returns_none(self):
        gesture, conf = self.clf.classify([(0.0, 0.0, 0.0, 1.0)] * 5, "none")
        assert gesture == "none"
        assert conf == 0.0

    def test_raised_right_hand(self):
        """Right wrist (16) raised well above right shoulder (12) → raised_hand."""
        pose = _standing_pose()
        # Move right wrist 120px above shoulder
        rs_y = pose[12][1]
        pose[16] = (pose[16][0], rs_y - 120, 0.0, 0.95)
        gesture, conf = self.clf.classify(pose, "none")
        assert gesture == "raised_hand", f"Expected raised_hand, got {gesture}"
        assert conf >= 0.85

    def test_raised_left_hand(self):
        """Left wrist (15) raised above left shoulder (11) → raised_hand."""
        pose = _standing_pose()
        ls_y = pose[11][1]
        pose[15] = (pose[15][0], ls_y - 120, 0.0, 0.95)
        gesture, conf = self.clf.classify(pose, "none")
        assert gesture == "raised_hand", f"Expected raised_hand, got {gesture}"
        assert conf >= 0.85

    def test_fallen_posture(self):
        """Nose y close to hip y (< 60px apart) → fallen_posture."""
        pose = _standing_pose()
        hip_y = (pose[23][1] + pose[24][1]) / 2
        # Move nose to be very close to hip level
        pose[0] = (_CX, hip_y - 20, 0.0, 0.99)
        gesture, conf = self.clf.classify(pose, "none")
        assert gesture == "fallen_posture", f"Expected fallen_posture, got {gesture}"
        assert conf >= 0.70

    def test_pointing_right(self):
        """Wrist 16 more than 80px to the right of nose (0) → pointing_right."""
        pose = _standing_pose()
        nose_x = pose[0][0]
        pose[16] = (nose_x + 120, pose[16][1], 0.0, 0.95)
        gesture, conf = self.clf.classify(pose, "pointing")
        assert gesture == "pointing_right", f"Expected pointing_right, got {gesture}"
        assert conf >= 0.80

    def test_pointing_left(self):
        """Wrist 15 more than 80px to the left of nose → pointing_left."""
        pose = _standing_pose()
        nose_x = pose[0][0]
        pose[15] = (nose_x - 120, pose[15][1], 0.0, 0.95)
        gesture, conf = self.clf.classify(pose, "pointing")
        assert gesture == "pointing_left", f"Expected pointing_left, got {gesture}"
        assert conf >= 0.80

    def test_pointing_forward_default(self):
        """Wrist not far left or right of nose → pointing_forward."""
        pose = _standing_pose()
        # Wrist just slightly right of nose — not beyond threshold
        pose[16] = (pose[0][0] + 30, pose[16][1], 0.0, 0.95)
        gesture, conf = self.clf.classify(pose, "pointing")
        assert gesture == "pointing_forward", f"Expected pointing_forward, got {gesture}"

    def test_stop_palm_confirmed(self):
        """Hand-level stop_palm is confirmed by body classifier."""
        pose = _standing_pose()
        gesture, conf = self.clf.classify(pose, "stop_palm")
        assert gesture == "stop_palm"
        assert conf >= 0.90

    def test_wave_candidate_becomes_wave(self):
        """wave_candidate with wrist above elbow → wave."""
        pose = _standing_pose()
        # Right wrist (16) above right elbow (14)
        pose[16] = (pose[16][0], pose[14][1] - 30, 0.0, 0.92)
        gesture, conf = self.clf.classify(pose, "wave_candidate")
        assert gesture == "wave", f"Expected wave, got {gesture}"
        assert conf >= 0.80

    def test_no_fallen_with_low_visibility(self):
        """Fallen heuristic should not fire when nose visibility is low."""
        pose = _standing_pose()
        hip_y = (pose[23][1] + pose[24][1]) / 2
        pose[0] = (_CX, hip_y - 10, 0.0, 0.1)  # low visibility
        gesture, conf = self.clf.classify(pose, "none")
        assert gesture != "fallen_posture"

    def test_confidence_range(self):
        """All returned confidences should be in [0.0, 1.0]."""
        pose = _standing_pose()
        for hand_g in ["none", "stop_palm", "pointing", "thumbs_up", "wave_candidate"]:
            _, conf = self.clf.classify(pose, hand_g)
            assert 0.0 <= conf <= 1.0, f"Confidence out of range for {hand_g}: {conf}"
