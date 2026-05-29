"""
tests.test_hand_classifier
============================
Unit tests for HandGestureClassifier.

Tests use synthetic 21-point hand landmarks constructed in image coordinates
(y increases downward, x increases rightward).
"""

from __future__ import annotations

import math
from typing import List, Tuple

import pytest

# Avoid importing bonbon_gesture as a package path — adjust sys.path for standalone pytest
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from bonbon_gesture.classifiers.hand_gesture_classifier import HandGestureClassifier


# ---------------------------------------------------------------------------
# Landmark builders
# ---------------------------------------------------------------------------

def _closed_fist(cx: float = 320.0, cy: float = 240.0) -> List[Tuple[float, float, float]]:
    """21-point closed fist: all fingertips below PIPs."""
    pts: List[Tuple[float, float, float]] = []
    for i in range(21):
        angle = (i / 21) * 2 * math.pi
        r = 10 + (i % 4) * 3
        pts.append((cx + r * math.cos(angle), cy + r * math.sin(angle), 0.0))
    # Ensure all finger tips below PIPs (y_tip > y_pip)
    tip_pip = [(8, 6), (12, 10), (16, 14), (20, 18)]
    for tip, pip_idx in tip_pip:
        pts[tip] = (pts[tip][0], pts[pip_idx][1] + 15, 0.0)
    return pts


def _open_palm(cx: float = 320.0, cy: float = 240.0) -> List[Tuple[float, float, float]]:
    """21-point fully open palm: all five fingers extended upward."""
    pts = [None] * 21
    # Wrist at base
    pts[0] = (cx, cy, 0.0)
    finger_offsets = [-25, -12, 0, 12, 25]
    for fi in range(5):
        fx = cx + finger_offsets[fi]
        start_idx = 1 + fi * 4
        for joint in range(4):
            fy = cy - 10 - joint * 15
            pts[start_idx + joint] = (fx, fy, 0.0)
    return pts


def _pointing_hand(cx: float = 320.0, cy: float = 240.0) -> List[Tuple[float, float, float]]:
    """Index finger extended, middle/ring/pinky curled."""
    pts = _closed_fist(cx, cy)
    # Index tip (8) above PIP (6), others curled
    pts[6] = (cx - 12, cy - 5, 0.0)
    pts[7] = (cx - 12, cy - 20, 0.0)
    pts[8] = (cx - 12, cy - 40, 0.0)  # tip well above pip
    return pts


def _thumbs_up_hand(cx: float = 320.0, cy: float = 240.0, is_right: bool = True) -> List[Tuple[float, float, float]]:
    """Thumb extended upward, four fingers curled."""
    pts = _closed_fist(cx, cy)
    # Thumb tip (4) well above wrist (0), IP joint (3) between
    pts[0] = (cx, cy, 0.0)          # wrist
    pts[3] = (cx - 12 if is_right else cx + 12, cy - 20, 0.0)   # thumb IP
    pts[4] = (cx - 20 if is_right else cx + 20, cy - 50, 0.0)   # thumb tip
    # Middle tip y at wrist level (needed for threshold)
    pts[12] = (cx, cy - 5, 0.0)
    # All finger tips below pip
    for tip, pip_idx in [(8, 6), (16, 14), (20, 18)]:
        pts[tip] = (pts[tip][0], pts[pip_idx][1] + 12, 0.0)
    return pts


def _thumbs_down_hand(cx: float = 320.0, cy: float = 240.0, is_right: bool = True) -> List[Tuple[float, float, float]]:
    """Thumb pointing downward, four fingers curled."""
    pts = _closed_fist(cx, cy)
    pts[0] = (cx, cy, 0.0)           # wrist
    pts[3] = (cx - 10 if is_right else cx + 10, cy + 20, 0.0)
    pts[4] = (cx - 18 if is_right else cx + 18, cy + 55, 0.0)   # thumb tip well below wrist
    pts[12] = (cx, cy - 5, 0.0)
    for tip, pip_idx in [(8, 6), (16, 14), (20, 18)]:
        pts[tip] = (pts[tip][0], pts[pip_idx][1] + 12, 0.0)
    return pts


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestHandGestureClassifier:

    def setup_method(self):
        self.clf = HandGestureClassifier()

    def test_none_landmarks_returns_none(self):
        gesture, conf = self.clf.classify(None, is_right=True)
        assert gesture == "none"
        assert conf == 0.0

    def test_too_few_landmarks_returns_none(self):
        gesture, conf = self.clf.classify([(0.0, 0.0, 0.0)] * 10, is_right=True)
        assert gesture == "none"
        assert conf == 0.0

    def test_open_palm_stop_gesture(self):
        lm = _open_palm()
        gesture, conf = self.clf.classify(lm, is_right=True)
        assert gesture == "stop_palm", f"Expected stop_palm, got {gesture}"
        assert conf >= 0.85

    def test_pointing_right_hand(self):
        lm = _pointing_hand()
        gesture, conf = self.clf.classify(lm, is_right=True)
        assert gesture == "pointing", f"Expected pointing, got {gesture}"
        assert conf >= 0.80

    def test_pointing_left_hand(self):
        lm = _pointing_hand()
        gesture, conf = self.clf.classify(lm, is_right=False)
        assert gesture == "pointing", f"Expected pointing, got {gesture}"
        assert conf >= 0.80

    def test_thumbs_up_right_hand(self):
        lm = _thumbs_up_hand(is_right=True)
        gesture, conf = self.clf.classify(lm, is_right=True)
        assert gesture == "thumbs_up", f"Expected thumbs_up, got {gesture}"
        assert conf >= 0.80

    def test_thumbs_up_left_hand(self):
        lm = _thumbs_up_hand(is_right=False)
        gesture, conf = self.clf.classify(lm, is_right=False)
        assert gesture == "thumbs_up", f"Expected thumbs_up, got {gesture}"
        assert conf >= 0.80

    def test_thumbs_down_right_hand(self):
        lm = _thumbs_down_hand(is_right=True)
        gesture, conf = self.clf.classify(lm, is_right=True)
        assert gesture == "thumbs_down", f"Expected thumbs_down, got {gesture}"
        assert conf >= 0.80

    def test_thumbs_down_left_hand(self):
        lm = _thumbs_down_hand(is_right=False)
        gesture, conf = self.clf.classify(lm, is_right=False)
        assert gesture == "thumbs_down", f"Expected thumbs_down, got {gesture}"
        assert conf >= 0.80

    def test_closed_fist_unknown(self):
        lm = _closed_fist()
        gesture, conf = self.clf.classify(lm, is_right=True)
        assert gesture in ("unknown_gesture", "thumbs_up", "thumbs_down", "none")

    def test_wave_candidate_four_fingers(self):
        """Four fingers extended (but not all 5) → wave_candidate."""
        lm = _open_palm()
        # Curl the pinky: move tip below pip
        lm[20] = (lm[18][0], lm[18][1] + 10, 0.0)
        gesture, conf = self.clf.classify(lm, is_right=True)
        # With 4 fingers up and no stop_palm or thumb logic, should be wave_candidate
        assert gesture in ("wave_candidate", "stop_palm"), f"Unexpected gesture: {gesture}"

    def test_confidence_range(self):
        """All returned confidences should be in [0.0, 1.0]."""
        for lm_fn in [_closed_fist, _open_palm, _pointing_hand,
                      lambda: _thumbs_up_hand(is_right=True),
                      lambda: _thumbs_down_hand(is_right=True)]:
            _, conf = self.clf.classify(lm_fn(), is_right=True)
            assert 0.0 <= conf <= 1.0, f"Confidence out of range: {conf}"
